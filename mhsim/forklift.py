"""
Refactored Forklift and ForkliftFleet for 3D movement simulation.

Forklifts are now independent agents with their own movement profiles.
ForkliftFleet manages a collection of independent Forklift instances.
"""

from __future__ import annotations

import simpy
import math
from dataclasses import dataclass, field
from typing import Optional, Generator, Callable
from enum import Enum

from .movement import Position3D, MovementProfile
from .routing import Route, RouteMotionSegment, RouteStep, Router
from .pallet import Pallet
from .traffic import PathTrafficController


class ForkliftStatus(Enum):
    """Forklift operational status."""
    IDLE = "idle"
    MOVING = "moving"
    LOADING = "loading"
    UNLOADING = "unloading"
    CHARGING = "charging"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class LiftProfile:
    """Lift timing and geometry for shelf-level operations."""
    shelf_height: float
    elevation_speed: float
    lowering_speed: float

    def height_for_level(self, shelf_level: int) -> float:
        if shelf_level <= 0:
            return 0.0
        return shelf_level * self.shelf_height

    def lift_cycle_time(self, shelf_level: int) -> float:
        height = self.height_for_level(shelf_level)
        up = height / self.elevation_speed if self.elevation_speed > 0 else 0.0
        down = height / self.lowering_speed if self.lowering_speed > 0 else 0.0
        return up + down


@dataclass(frozen=True)
class ForkliftMovementOverrides:
    """Per-move routing settings that override a forklift's defaults."""

    routed_motion_mode: Optional[str] = None
    turn_radius: Optional[float] = None
    line_guided_update_timestep_s: Optional[float] = None


@dataclass(frozen=True)
class ChargingStation:
    """Simple charger location for transporter battery operations."""
    id: str
    position: Position3D


@dataclass(frozen=True)
class ForkliftAssignment:
    """A specific transporter assignment returned by ForkliftFleet.seize()."""
    request: object
    forklift: Forklift


@dataclass
class Forklift:
    """Independent forklift agent with movement simulation."""

    # Identity
    id: str
    env: simpy.Environment

    # Movement profile
    movement_profile: MovementProfile
    lift_profile: Optional[LiftProfile] = None

    # State
    position: Position3D = field(default_factory=lambda: Position3D(0, 0, 0))
    status: ForkliftStatus = ForkliftStatus.IDLE
    current_load: Optional[Pallet] = None
    router: Optional[Router] = None
    traffic_controller: Optional[PathTrafficController] = None
    stats: Optional[object] = None
    turn_radius: float = 0.5
    routed_motion_mode: str = "analytical"
    line_guided_update_timestep_s: float = 0.5
    route_calc_delay_s: float = 0.0
    resume_delay_s: float = 0.0
    home_position: Optional[Position3D] = None
    charging_station: Optional[ChargingStation] = None

    # TODO check if we'll ever use it or not.
    # Battery settings (disabled by default when discharge_per_meter == 0).
    battery_soc: float = 1.0
    discharge_per_meter: float = 0.0
    charge_rate_per_second: float = 0.0
    charge_when_below: float = 0.20
    charge_until: float = 0.95

    # Set by ForkliftFleet assignment lifecycle.
    is_reserved: bool = False
    _traffic_wait_reason: Optional[str] = field(default=None, init=False, repr=False)
    _traffic_wait_started_at: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Initialize forklift process."""
        if self.home_position is None:
            self.home_position = self.position
        # TODO introduce clamp01 somewhere...
        self.battery_soc = min(max(self.battery_soc, 0.0), 1.0)
        self.charge_when_below = min(max(self.charge_when_below, 0.0), 1.0)
        self.charge_until = min(max(self.charge_until, 0.0), 1.0)
        if not self.router:
            # TODO remove the fallback and make Router mandatory.
            # Create a simple router if none provided
            from .spatial import WarehouseLayout, RectangularNode, Storage
            default_layout = WarehouseLayout(
                inbound_area=RectangularNode(
                    "inbound", Position3D(0, 0, 0), 10, 10, 2),
                outbound_area=RectangularNode(
                    "outbound", Position3D(20, 0, 0), 10, 10, 2),
                forklifts_home=RectangularNode(
                    "home", Position3D(10, 10, 0), 5, 5, 2),
                storage=Storage(),
            )
            self.router = Router(default_layout)

    def _consume_battery(self, horizontal_distance_m: float) -> None:
        """Apply travel energy usage to battery SOC."""
        if self.discharge_per_meter <= 0 or horizontal_distance_m <= 0:
            return
        self.battery_soc = max(0.0, self.battery_soc - horizontal_distance_m * self.discharge_per_meter)

    def needs_charging(self) -> bool:
        """Whether the transporter should go to a charging station."""
        if self.charging_station is None:
            return False
        if self.discharge_per_meter <= 0:
            return False
        if self.charge_rate_per_second <= 0:
            return False
        return self.battery_soc <= self.charge_when_below

    def charge_if_needed(self, update_interval: float = 0.1) -> Generator:
        """Move to charger and charge battery when below threshold."""
        if not self.needs_charging():
            yield self.env.timeout(0)
            return

        target_station = self.charging_station
        if target_station is None:
            yield self.env.timeout(0)
            return

        if self.position.distance_xy(target_station.position) > 0.01:
            yield from self.move_to(target_station.position, update_interval=update_interval)

        self.status = ForkliftStatus.CHARGING
        target_soc = max(self.battery_soc, self.charge_until)
        if target_soc > self.battery_soc:
            charge_time = (target_soc - self.battery_soc) / self.charge_rate_per_second
            yield self.env.timeout(charge_time)
            self.battery_soc = target_soc
        self.status = ForkliftStatus.IDLE

    def _move_direct_to(self, target: Position3D, update_interval: float = 0.05) -> Generator:
        """Move directly to target using acceleration profile (no routing)."""
        # Check if we're already at target (in 3D, not just XY)
        # TODO 0.01 should be a private constant.
        if self.position.distance_to(target) < 0.01:
            yield self.env.timeout(0)
            return

        self.status = ForkliftStatus.MOVING
        start_pos = self.position
        height_change = target.z - start_pos.z

        from .movement import AcceleratingInterpolator
        start_xy = Position3D(start_pos.x, start_pos.y, 0)
        target_xy = Position3D(target.x, target.y, 0)
        horizontal_distance = start_xy.distance_xy(target_xy)
        interpolator = AcceleratingInterpolator(
            start_xy, target_xy, self.movement_profile.horizontal)
        horizontal_time = interpolator.travel_time

        vertical_speed = 0.0
        if height_change != 0:
            if self.lift_profile:
                vertical_speed = (
                    self.lift_profile.elevation_speed
                    if height_change > 0
                    else self.lift_profile.lowering_speed
                )
            else:
                vertical_speed = self.movement_profile.elevation.speed
        vertical_time = abs(height_change) / \
            vertical_speed if vertical_speed > 0 else 0.0

        total_time = max(horizontal_time, vertical_time)
        if total_time <= 0:
            self.position = target
            self._consume_battery(horizontal_distance)
            if self.status == ForkliftStatus.MOVING:
                self.status = ForkliftStatus.IDLE
            yield self.env.timeout(0)
            return

        elapsed = 0.0
        while elapsed < total_time:
            dt = min(update_interval, total_time - elapsed)
            yield self.env.timeout(dt)
            elapsed += dt

            if horizontal_time > 0:
                xy_pos = interpolator.update(dt)
            else:
                xy_pos = target_xy

            if vertical_time > 0:
                z_progress = min(elapsed / vertical_time, 1.0)
                z = start_pos.z + height_change * z_progress
            else:
                z = target.z

            self.position = Position3D(xy_pos.x, xy_pos.y, z)

        self.position = target
        self._consume_battery(horizontal_distance)
        if self.status == ForkliftStatus.MOVING:
            self.status = ForkliftStatus.IDLE

    def _start_traffic_wait(self, reason: Optional[str]) -> None:
        """Start or switch an active traffic wait reason."""
        if reason is None:
            return
        if self._traffic_wait_reason == reason:
            return
        self._finish_traffic_wait()
        self._traffic_wait_reason = reason
        self._traffic_wait_started_at = self.env.now

    def _finish_traffic_wait(self) -> bool:
        """Finish the active traffic wait and record metrics."""
        if self._traffic_wait_reason is None or self._traffic_wait_started_at is None:
            return False
        recorder = getattr(self.stats, "record_traffic_wait", None)
        if callable(recorder):
            recorder(
                self._traffic_wait_reason,
                max(0.0, self.env.now - self._traffic_wait_started_at),
            )
        self._traffic_wait_reason = None
        self._traffic_wait_started_at = None
        return True

    def _resume_after_traffic_wait(self) -> Generator:
        """Apply resume delay once after a traffic-induced stop."""
        if self._finish_traffic_wait() and self.resume_delay_s > 0:
            yield self.env.timeout(self.resume_delay_s)

    @staticmethod
    def _route_position(step: RouteStep, progress_m: float) -> Position3D:
        """Interpolate a position along a routed path step."""
        return Router.position_along_step(step, progress_m)

    @staticmethod
    def _motion_segment_position(
        segment: RouteMotionSegment,
        progress_m: float,
    ) -> Position3D:
        """Interpolate a position along a routed motion segment."""
        return segment.position_at(progress_m)

    @staticmethod
    def _route_has_corner(steps: list[RouteStep]) -> bool:
        """Whether a route changes horizontal direction between path steps."""
        for index in range(len(steps) - 1):
            incoming = steps[index]
            outgoing = steps[index + 1]
            in_dx = incoming.end.x - incoming.start.x
            in_dy = incoming.end.y - incoming.start.y
            out_dx = outgoing.end.x - outgoing.start.x
            out_dy = outgoing.end.y - outgoing.start.y
            in_len = math.hypot(in_dx, in_dy)
            out_len = math.hypot(out_dx, out_dy)
            if in_len <= 1e-9 or out_len <= 1e-9:
                continue
            in_unit = (in_dx / in_len, in_dy / in_len)
            out_unit = (out_dx / out_len, out_dy / out_len)
            cross = in_unit[0] * out_unit[1] - in_unit[1] * out_unit[0]
            dot = in_unit[0] * out_unit[0] + in_unit[1] * out_unit[1]
            if abs(cross) > 1e-9 and dot < 1.0 - 1e-9:
                return True
        return False

    def _has_path_network(self) -> bool:
        """Whether horizontal travel is constrained to designed paths."""
        return bool(self.router and getattr(self.router.layout, "paths", None))

    def _compute_horizontal_motion(
        self,
        current_speed: float,
        dt: float,
        route_remaining_m: float,
        available_distance_m: float,
    ) -> tuple[float, float, float]:
        """Compute horizontal motion for the current tick.

        Returns:
            Tuple of (distance_m, end_speed_mps, elapsed_time_s).

        The routed mover advances in discrete updates for visualization and
        traffic checks, but the elapsed simulation time for a tick should match
        the distance actually traveled in that tick. Otherwise the final
        partial movement on each routed segment incurs a full fixed-step delay,
        which systematically slows SimPy relative to AnyLogic.
        """
        effective_distance = min(max(0.0, route_remaining_m), max(0.0, available_distance_m))
        if effective_distance <= 1e-9:
            return 0.0, 0.0, 0.0

        horizontal = self.movement_profile.horizontal
        max_speed = max(0.0, horizontal.max_speed)
        acceleration = max(0.0, horizontal.acceleration)
        deceleration = max(0.0, horizontal.deceleration)
        if max_speed <= 0 or dt <= 0:
            return 0.0, 0.0, 0.0

        def next_speed_for_interval(interval_s: float) -> float:
            stop_speed_limit = (
                math.sqrt(max(0.0, 2.0 * deceleration * effective_distance))
                if deceleration > 0
                else max_speed
            )
            accelerated_speed = (
                current_speed + acceleration * interval_s
                if acceleration > 0
                else current_speed
            )
            decelerated_speed = (
                max(0.0, current_speed - deceleration * interval_s)
                if deceleration > 0
                else current_speed
            )
            target_upper = min(max_speed, accelerated_speed, stop_speed_limit)
            return decelerated_speed if target_upper < decelerated_speed else target_upper

        elapsed_time = dt
        next_speed = next_speed_for_interval(elapsed_time)
        distance = 0.5 * (current_speed + next_speed) * elapsed_time

        # Refine the interval so the final partial move only consumes the time
        # needed to cover that remaining distance, rather than a full update
        # step. This removes the fixed-step drift that showed up in the
        # simplified transporter validation model.
        if distance > effective_distance + 1e-9:
            for _ in range(4):
                avg_speed = current_speed + next_speed
                if avg_speed <= 1e-9:
                    elapsed_time = 0.0
                    next_speed = 0.0
                    distance = 0.0
                    break

                elapsed_time = min(
                    elapsed_time,
                    max(0.0, 2.0 * effective_distance / avg_speed),
                )
                next_speed = next_speed_for_interval(elapsed_time)
                distance = 0.5 * (current_speed + next_speed) * elapsed_time
                if abs(distance - effective_distance) <= 1e-6:
                    break

            distance = min(distance, effective_distance)
            if distance >= effective_distance - 1e-6:
                distance = effective_distance

            if distance <= 1e-9 and effective_distance <= max(1e-6, current_speed * dt * 0.25):
                next_speed = 0.0

        return distance, next_speed, elapsed_time

    @staticmethod
    def _distance_to_speed(  # TODO check duplicated logic with HorizontalMovement
        current_speed: float,
        acceleration: float,
        target_speed: float,
    ) -> float:
        """Distance needed to reach target speed under constant acceleration."""
        if current_speed == target_speed:
            return 0.0
        if acceleration == 0.0:
            return math.inf
        if math.copysign(1.0, target_speed - current_speed) != math.copysign(
            1.0,
            acceleration,
        ):
            return math.copysign(math.inf, target_speed - current_speed)
        return (current_speed + (target_speed - current_speed) / 2.0) * (
            (target_speed - current_speed) / acceleration
        )

    @staticmethod
    def _time_to_cover_distance(  # TODO check duplicated logic with HorizontalMovement
        current_speed: float,
        acceleration: float,
        distance_m: float,
    ) -> float:
        """Solve time for distance under constant acceleration."""
        if distance_m <= 0.0:
            return 0.0
        if acceleration == 0.0:
            return math.inf if current_speed <= 0.0 else distance_m / current_speed
        discriminant = current_speed * current_speed + 2.0 * acceleration * distance_m
        if discriminant < 0.0:
            return math.inf
        root = math.sqrt(discriminant)
        candidates = [
            (root - current_speed) / acceleration,
            (-root - current_speed) / acceleration,
        ]
        nonnegative = [value for value in candidates if value >= -1e-12]
        return max(0.0, min(nonnegative)) if nonnegative else math.inf

    def _compute_line_guided_horizontal_motion(  # TODO check duplicated logic with HorizontalMovement
        self,
        current_speed: float,
        dt: float,
        route_remaining_m: float,
        available_distance_m: float,
        profile_acceleration: float,
        profile_speed_limit: float,
    ) -> tuple[float, float, float]:
        """Advance one AnyLogic line-guided controller slice.

        AnyLogic stores a speed profile as ``(t0, v0, a, vmax)`` and keeps
        that profile until the controller updates it. Unlike the analytical
        route solve, the final slice may reach the target with residual speed.
        """
        effective_distance = min(
            max(0.0, route_remaining_m),
            max(0.0, available_distance_m),
        )
        if effective_distance <= 1e-9 or dt <= 0.0:
            return 0.0, max(0.0, current_speed), 0.0

        speed_limit = max(0.0, profile_speed_limit)
        acceleration = profile_acceleration
        elapsed_time = dt

        if acceleration == 0.0:
            next_speed = max(0.0, current_speed)
            distance = next_speed * elapsed_time
        else:
            time_to_limit = (speed_limit - current_speed) / acceleration
            if time_to_limit < 0.0:
                time_to_limit = 0.0
            if elapsed_time >= time_to_limit:
                distance = (
                    current_speed * time_to_limit
                    + 0.5 * acceleration * time_to_limit * time_to_limit
                    + speed_limit * (elapsed_time - time_to_limit)
                )
                next_speed = speed_limit
            else:
                distance = (
                    current_speed * elapsed_time
                    + 0.5 * acceleration * elapsed_time * elapsed_time
                )
                next_speed = current_speed + acceleration * elapsed_time

        if distance > effective_distance + 1e-9:
            if acceleration == 0.0:
                elapsed_time = self._time_to_cover_distance(
                    current_speed,
                    0.0,
                    effective_distance,
                )
                next_speed = current_speed
            else:
                time_to_limit = (speed_limit - current_speed) / acceleration
                if time_to_limit < 0.0:
                    time_to_limit = 0.0
                distance_to_limit = (
                    current_speed * time_to_limit
                    + 0.5 * acceleration * time_to_limit * time_to_limit
                )
                if effective_distance <= distance_to_limit + 1e-9:
                    elapsed_time = self._time_to_cover_distance(
                        current_speed,
                        acceleration,
                        effective_distance,
                    )
                    next_speed = max(0.0, current_speed + acceleration * elapsed_time)
                else:
                    elapsed_time = time_to_limit + (
                        (effective_distance - distance_to_limit) / speed_limit
                        if speed_limit > 0.0
                        else 0.0
                    )
                    next_speed = speed_limit
            distance = effective_distance

        return max(0.0, distance), max(0.0, next_speed), max(0.0, elapsed_time)

    @staticmethod
    def _line_guided_route_boundary_distances(route: Route) -> list[float]:
        """Controller-update distances for AnyLogic route movement boundaries."""
        if not route.steps or route.total_distance <= 1e-9:
            return []

        boundaries: list[float] = []
        cumulative_raw_distance = 0.0
        boundary_epsilon_m = 1.0e-4
        for step in route.steps[:-1]:
            cumulative_raw_distance += step.length
            boundary_distance = cumulative_raw_distance + boundary_epsilon_m
            if boundary_epsilon_m < boundary_distance < route.total_distance - 1e-9:
                boundaries.append(boundary_distance)
        return boundaries

    @staticmethod
    def _next_controller_update_time(now: float, update_timestep: float) -> float:
        """Return the next global controller tick after ``now``."""
        if update_timestep <= 0.0:
            return now
        return (math.floor(now / update_timestep) + 1.0) * update_timestep

    def _move_along_route(  # TODO this is the most important function for a deep review
        self,
        route: Route,
        update_interval: float = 0.05,
        movement_overrides: Optional[ForkliftMovementOverrides] = None,
    ) -> Generator:
        """Move along routed path steps with shared traffic control."""
        if len(route.waypoints) < 2:
            yield self.env.timeout(0)
            return

        if not route.steps:
            yield from self._move_direct_to(route.waypoints[-1], update_interval=update_interval)
            return

        motion_segments = list(route.motion_segments)
        if not motion_segments:
            for step_index, step in enumerate(route.steps):
                motion_segments.append(
                    RouteMotionSegment(
                        kind="straight",
                        start=step.start,
                        end=step.end,
                        length=step.length,
                        step_index=step_index,
                        start_progress_m=0.0,
                        end_progress_m=step.length,
                    )
                )

        self.status = ForkliftStatus.MOVING
        start_pos = self.position
        target = route.waypoints[-1]
        height_change = target.z - start_pos.z
        total_distance = route.total_distance
        routed_motion_mode = (
            self.routed_motion_mode
            if movement_overrides is None
            or movement_overrides.routed_motion_mode is None
            else movement_overrides.routed_motion_mode
        )
        line_guided_update_timestep_s = (
            self.line_guided_update_timestep_s
            if movement_overrides is None
            or movement_overrides.line_guided_update_timestep_s is None
            else movement_overrides.line_guided_update_timestep_s
        )

        has_corner = self._route_has_corner(route.steps)
        use_line_guided_controller = (
            routed_motion_mode == "anylogic_line_guided" and has_corner
        )
        use_analytical_topup = not use_line_guided_controller

        # AnyLogic's line-guided controller rebuilds motion profiles on a 0.5 s
        # controller cadence. On cornered paths this delays final deceleration
        # and can arrive with residual velocity. Straight paths match the
        # closed-form triangular/trapezoidal profile, so keep the analytical
        # top-up there and only use the controller cadence for cornered routes.
        if total_distance > 1e-9 and use_analytical_topup:
            analytical_horizontal_time = self.movement_profile.horizontal.travel_time(
                total_distance
            )
        else:
            analytical_horizontal_time = 0.0
        motion_time_elapsed = 0.0

        vertical_speed = 0.0
        if height_change != 0:
            if self.lift_profile:
                vertical_speed = (
                    self.lift_profile.elevation_speed
                    if height_change > 0
                    else self.lift_profile.lowering_speed
                )
            else:
                vertical_speed = self.movement_profile.elevation.speed
        vertical_total_distance = abs(height_change)
        if total_distance <= 0 and vertical_total_distance <= 0:
            self.position = target
            self._consume_battery(total_distance)
            if self.status == ForkliftStatus.MOVING:
                self.status = ForkliftStatus.IDLE
            yield self.env.timeout(0)
            return

        traffic = self.traffic_controller
        current_speed = 0.0
        line_guided_acceleration = 0.0
        line_guided_speed_limit = 0.0
        next_line_guided_update_at = self.env.now
        line_guided_boundary_distances = (
            self._line_guided_route_boundary_distances(route)
            if use_line_guided_controller
            else []
        )
        next_line_guided_boundary_index = 0
        current_segment_index = 0
        active_segment: Optional[RouteMotionSegment] = None
        segment_progress = 0.0
        occupied_node_id: Optional[str] = None
        occupied_node_release_step_index: Optional[int] = None
        occupied_node_release_progress: Optional[float] = None
        horizontal_distance = 0.0
        vertical_distance = 0.0
        current_z = start_pos.z
        current_xy = Position3D(start_pos.x, start_pos.y, 0)

        def recompute_line_guided_profile() -> None:
            nonlocal line_guided_acceleration, line_guided_speed_limit

            horizontal = self.movement_profile.horizontal
            max_speed = max(0.0, horizontal.max_speed)
            acceleration = max(0.0, horizontal.acceleration)
            deceleration = max(0.0, horizontal.deceleration)
            route_remaining = max(0.0, total_distance - horizontal_distance)
            stopping_distance = (
                self._distance_to_speed(current_speed, -deceleration, 0.0)
                if deceleration > 0.0
                else math.inf
            )
            line_guided_speed_limit = (
                0.0 if stopping_distance > route_remaining else max_speed
            )
            if current_speed > line_guided_speed_limit:
                line_guided_acceleration = -deceleration
            elif current_speed < line_guided_speed_limit:
                line_guided_acceleration = acceleration
            else:
                line_guided_acceleration = 0.0

        while horizontal_distance < total_distance - 1e-9 or vertical_distance < vertical_total_distance - 1e-9:
            dt = max(update_interval, 1e-3)
            if use_line_guided_controller:
                update_timestep = max(1e-9, line_guided_update_timestep_s)
                current_controller_time = self.env.now
                if current_controller_time >= next_line_guided_update_at - 1e-9:
                    recompute_line_guided_profile()
                    next_line_guided_update_at = self._next_controller_update_time(
                        current_controller_time,
                        update_timestep,
                    )
                dt = min(dt, max(1e-9, next_line_guided_update_at - current_controller_time))

            if active_segment is None and current_segment_index < len(motion_segments):
                next_segment = motion_segments[current_segment_index]
                wait_reason = None
                if next_segment.kind == "straight" and next_segment.step_index is not None:
                    next_step = route.steps[next_segment.step_index]
                    following_step = (
                        route.steps[next_segment.step_index + 1]
                        if next_segment.step_index + 1 < len(route.steps)
                        else None
                    )
                    if traffic is not None:
                        wait_reason = traffic.try_enter_edge(self.id, next_step, following_step)
                if wait_reason is not None:
                    if occupied_node_id is not None and traffic is not None:
                        traffic.leave_node(self.id, occupied_node_id)
                        occupied_node_id = None
                        occupied_node_release_step_index = None
                        occupied_node_release_progress = None
                    self._start_traffic_wait(wait_reason)
                    current_speed = 0.0
                    yield self.env.timeout(dt)
                else:
                    yield from self._resume_after_traffic_wait()
                    active_segment = next_segment
                    segment_progress = 0.0
                    if (
                        occupied_node_id is not None
                        and traffic is not None
                        and next_segment.kind == "straight"
                    ):
                        clearance_distance = min(
                            next_segment.length,
                            max(0.0, traffic.min_distance_to_obstacle_m),
                        )
                        if clearance_distance <= 1e-9:
                            traffic.leave_node(self.id, occupied_node_id)
                            occupied_node_id = None
                            occupied_node_release_step_index = None
                            occupied_node_release_progress = None
                        else:
                            occupied_node_release_step_index = next_segment.step_index
                            occupied_node_release_progress = (
                                next_segment.start_progress_m + clearance_distance
                            )
                # No simulation time passes when we simply activate the next
                # routed segment, so vertical movement must not advance here.
                if wait_reason is not None and vertical_total_distance > 0:
                    delta_z = min(vertical_speed * dt, vertical_total_distance - vertical_distance)
                    vertical_distance += delta_z
                    direction = 1.0 if height_change >= 0 else -1.0
                    current_z = start_pos.z + direction * vertical_distance
                self.position = Position3D(current_xy.x, current_xy.y, current_z)
                continue

            route_remaining = max(0.0, total_distance - horizontal_distance)
            if route_remaining <= 1e-9:
                current_xy = Position3D(target.x, target.y, 0)
                current_speed = 0.0
                yield self.env.timeout(dt)
            else:
                available_distance = route_remaining
                wait_reason = None
                if (
                    traffic is not None
                    and active_segment is not None
                    and active_segment.kind == "straight"
                    and active_segment.step_index is not None
                ):
                    active_step = route.steps[active_segment.step_index]
                    requested_distance = route_remaining
                    allowance = traffic.available_distance(
                        self.id,
                        active_step,
                        active_segment.start_progress_m + segment_progress,
                        requested_distance,
                    )
                    available_distance = allowance.allowed_distance_m
                    wait_reason = allowance.wait_reason

                if use_line_guided_controller:
                    while (
                        next_line_guided_boundary_index < len(line_guided_boundary_distances)
                        and line_guided_boundary_distances[next_line_guided_boundary_index]
                        <= horizontal_distance + 1e-9
                    ):
                        next_line_guided_boundary_index += 1
                    if next_line_guided_boundary_index < len(line_guided_boundary_distances):
                        # AnyLogic schedules a route-boundary controller update
                        # just after the current RouteData movement ends. Keep
                        # the shared controller clock intact, but stop this
                        # slice exactly at that boundary so the immediate
                        # profile rebuild sees the same remaining route.
                        distance_to_boundary = (
                            line_guided_boundary_distances[next_line_guided_boundary_index]
                            - horizontal_distance
                        )
                        if distance_to_boundary > 1e-9:
                            available_distance = min(available_distance, distance_to_boundary)
                    move_distance, next_speed, move_time = self._compute_line_guided_horizontal_motion(
                        current_speed=current_speed,
                        dt=dt,
                        route_remaining_m=route_remaining,
                        available_distance_m=available_distance,
                        profile_acceleration=line_guided_acceleration,
                        profile_speed_limit=line_guided_speed_limit,
                    )
                else:
                    move_distance, next_speed, move_time = self._compute_horizontal_motion(
                        current_speed=current_speed,
                        dt=dt,
                        route_remaining_m=route_remaining,
                        available_distance_m=available_distance,
                    )

                if move_distance <= 1e-9 and wait_reason is not None:
                    self._start_traffic_wait(wait_reason)
                    current_speed = 0.0
                    yield self.env.timeout(dt)
                else:
                    yield from self._resume_after_traffic_wait()
                    if move_time <= 1e-9 and move_distance > 1e-9:
                        move_time = dt
                    yield self.env.timeout(move_time)
                    motion_time_elapsed += move_time
                    dt = move_time
                    current_speed = next_speed
                    remaining_move = move_distance
                    blocked_reason: Optional[str] = None

                    while remaining_move > 1e-9 and horizontal_distance < total_distance - 1e-9:
                        if active_segment is None:
                            if current_segment_index >= len(motion_segments):
                                break
                            next_segment = motion_segments[current_segment_index]
                            if next_segment.kind == "straight" and next_segment.step_index is not None:
                                next_step = route.steps[next_segment.step_index]
                                following_step = (
                                    route.steps[next_segment.step_index + 1]
                                    if next_segment.step_index + 1 < len(route.steps)
                                    else None
                                )
                                if traffic is not None:
                                    blocked_reason = traffic.try_enter_edge(
                                        self.id,
                                        next_step,
                                        following_step,
                                    )
                                    if blocked_reason is not None:
                                        if occupied_node_id is not None:
                                            traffic.leave_node(self.id, occupied_node_id)
                                            occupied_node_id = None
                                            occupied_node_release_step_index = None
                                            occupied_node_release_progress = None
                                        break
                            active_segment = next_segment
                            segment_progress = 0.0
                            if (
                                occupied_node_id is not None
                                and traffic is not None
                                and next_segment.kind == "straight"
                            ):
                                clearance_distance = min(
                                    next_segment.length,
                                    max(0.0, traffic.min_distance_to_obstacle_m),
                                )
                                if clearance_distance <= 1e-9:
                                    traffic.leave_node(self.id, occupied_node_id)
                                    occupied_node_id = None
                                    occupied_node_release_step_index = None
                                    occupied_node_release_progress = None
                                else:
                                    occupied_node_release_step_index = next_segment.step_index
                                    occupied_node_release_progress = (
                                        next_segment.start_progress_m + clearance_distance
                                    )

                        step_allowance = remaining_move
                        if (
                            traffic is not None
                            and active_segment is not None
                            and active_segment.kind == "straight"
                            and active_segment.step_index is not None
                        ):
                            active_step = route.steps[active_segment.step_index]
                            allowance = traffic.available_distance(
                                self.id,
                                active_step,
                                active_segment.start_progress_m + segment_progress,
                                remaining_move,
                            )
                            step_allowance = allowance.allowed_distance_m
                            if step_allowance <= 1e-9:
                                blocked_reason = allowance.wait_reason
                                break

                        if active_segment is None:
                            break
                        step_remaining = max(0.0, active_segment.length - segment_progress)
                        travel = min(remaining_move, step_allowance, step_remaining)
                        if travel <= 1e-9:
                            break

                        segment_progress += travel
                        horizontal_distance += travel
                        remaining_move -= travel
                        current_xy = self._motion_segment_position(active_segment, segment_progress)
                        if (
                            traffic is not None
                            and active_segment.kind == "straight"
                            and active_segment.step_index is not None
                        ):
                            active_step = route.steps[active_segment.step_index]
                            raw_progress = active_segment.start_progress_m + segment_progress
                            traffic.update_progress(self.id, active_step, raw_progress)
                            if (
                                occupied_node_id is not None
                                and occupied_node_release_step_index == active_segment.step_index
                                and occupied_node_release_progress is not None
                                and raw_progress >= occupied_node_release_progress - 1e-9
                            ):
                                traffic.leave_node(self.id, occupied_node_id)
                                occupied_node_id = None
                                occupied_node_release_step_index = None
                                occupied_node_release_progress = None

                        if segment_progress >= active_segment.length - 1e-9:
                            if active_segment.kind == "straight":
                                if traffic is not None and active_segment.step_index is not None:
                                    active_step = route.steps[active_segment.step_index]
                                    if occupied_node_id is not None:
                                        traffic.leave_node(self.id, occupied_node_id)
                                        occupied_node_id = None
                                        occupied_node_release_step_index = None
                                        occupied_node_release_progress = None
                                    blocked_reason = traffic.enter_node(self.id, active_step.end_node_id)
                                    if blocked_reason is not None:
                                        backed_off_progress = max(0.0, active_segment.length - 1e-6)
                                        rollback = max(0.0, segment_progress - backed_off_progress)
                                        horizontal_distance -= rollback
                                        remaining_move += rollback
                                        segment_progress = backed_off_progress
                                        traffic.update_progress(
                                            self.id,
                                            active_step,
                                            active_segment.start_progress_m + segment_progress,
                                        )
                                        current_xy = self._motion_segment_position(active_segment, segment_progress)
                                        break
                                    traffic.leave_edge(self.id, active_step)
                                    occupied_node_id = active_step.end_node_id
                                    occupied_node_release_step_index = None
                                    occupied_node_release_progress = None

                                if blocked_reason is None:
                                    current_segment_index += 1
                                    active_segment = None
                                    segment_progress = 0.0

                                    if (
                                        current_segment_index >= len(motion_segments)
                                        and occupied_node_id is not None
                                        and traffic is not None
                                    ):
                                        traffic.leave_node(self.id, occupied_node_id)
                                        occupied_node_id = None
                                        occupied_node_release_step_index = None
                                        occupied_node_release_progress = None
                            else:
                                current_segment_index += 1
                                active_segment = None
                                segment_progress = 0.0

                    if blocked_reason is not None:
                        self._start_traffic_wait(blocked_reason)
                        current_speed = 0.0

                    if use_line_guided_controller:
                        crossed_route_boundary = False
                        while (
                            next_line_guided_boundary_index < len(line_guided_boundary_distances)
                            and horizontal_distance
                            >= line_guided_boundary_distances[next_line_guided_boundary_index] - 1e-9
                        ):
                            next_line_guided_boundary_index += 1
                            crossed_route_boundary = True
                        if crossed_route_boundary:
                            recompute_line_guided_profile()

            if vertical_total_distance > 0:
                delta_z = min(vertical_speed * dt, vertical_total_distance - vertical_distance)
                vertical_distance += delta_z
                direction = 1.0 if height_change >= 0 else -1.0
                current_z = start_pos.z + direction * vertical_distance
            else:
                current_z = target.z

            self.position = Position3D(current_xy.x, current_xy.y, current_z)

        if use_analytical_topup:
            # Keep position at the last interpolated location during the
            # top-up; otherwise cyclic traces would show arrival before the
            # movement event actually finishes.
            kinematic_remainder = analytical_horizontal_time - motion_time_elapsed
            if kinematic_remainder > 1e-9:
                yield self.env.timeout(kinematic_remainder)

        self.position = Position3D(target.x, target.y, target.z)

        self._finish_traffic_wait()
        if traffic is not None:
            traffic.release_forklift(self.id)
        self._consume_battery(total_distance)
        if self.status == ForkliftStatus.MOVING:
            self.status = ForkliftStatus.IDLE

    def move_to(
        self,
        target: Position3D,
        preferred_path_id: Optional[str] = None,
        update_interval: float = 0.05,
        movement_overrides: Optional[ForkliftMovementOverrides] = None,
    ) -> Generator:
        """Move to a target while keeping horizontal travel on designed paths.

        When a path network is available, all horizontal movement is routed
        over that network. Only pure vertical moves bypass path routing.
        """
        # Avoid any routing/resume delays if we're already at the target.
        if self.position.distance_to(target) < 0.01:
            yield self.env.timeout(0)
            return

        # Check if this is a pure vertical movement
        xy_distance = self.position.distance_xy(target)
        is_vertical_only = xy_distance < 0.01

        if self._has_path_network() and not is_vertical_only:
            if self.route_calc_delay_s > 0:
                yield self.env.timeout(self.route_calc_delay_s)
            path_id = preferred_path_id or self.router.nearest_path_id(
                self.position) or self.router.nearest_path_id(target)
            turn_radius = (
                self.turn_radius
                if movement_overrides is None
                or movement_overrides.turn_radius is None
                else movement_overrides.turn_radius
            )
            route = self.router.route_between_nodes(
                self.position,
                target,
                path_id,
                turn_radius=turn_radius,
            )
            if not route.steps and route.total_distance > 1e-9:
                raise RuntimeError(
                    "Horizontal forklift movement must follow designed paths, but no routed path was found."
                )
            yield from self._move_along_route(
                route,
                update_interval,
                movement_overrides=movement_overrides,
            )
            return

        # Fallback is only for pure vertical movement or cases without a path network.
        yield from self._move_direct_to(target, update_interval)

    def estimate_travel_time(self, start: Position3D, end: Position3D) -> float:
        if self._has_path_network():
            route = self.router.route_between_nodes(
                start,
                end,
                turn_radius=self.turn_radius,
            )
            if not route.steps and route.total_distance > 1e-9:
                raise RuntimeError(
                    "Horizontal forklift movement must follow designed paths, but no routed path was found."
                )
            xy_distance = route.total_distance
        else:
            xy_distance = start.distance_xy(end)
        horizontal_time = self.movement_profile.horizontal.travel_time(xy_distance)

        height_change = end.z - start.z
        if height_change == 0:
            return horizontal_time
        if self.lift_profile:
            vertical_speed = (
                self.lift_profile.elevation_speed
                if height_change > 0
                else self.lift_profile.lowering_speed
            )
        else:
            vertical_speed = self.movement_profile.elevation.speed
        vertical_time = abs(height_change) / vertical_speed if vertical_speed > 0 else 0.0
        return max(horizontal_time, vertical_time)

    def lift_cycle_time(self, shelf_level: int) -> float:
        if not self.lift_profile:
            return 0.0
        return self.lift_profile.lift_cycle_time(shelf_level)

    def perform_lift(
        self,
        target_pos: Optional[Position3D],
        shelf_level: int,
        update_interval: float = 0.1,
        dwell_time_s: float = 0.0,
        dwell_status: Optional[ForkliftStatus] = None,
        on_dwell_start: Optional[Callable[[float], None]] = None,
        on_dwell_end: Optional[Callable[[float], None]] = None,
        movement_overrides: Optional[ForkliftMovementOverrides] = None,
    ) -> Generator:
        """Move to position, lift to shelf level, dwell, then return to ground."""
        if target_pos is None:
            if dwell_status is not None:
                self.status = dwell_status
            if on_dwell_start is not None:
                on_dwell_start(self.env.now)
            if dwell_time_s > 0:
                yield self.env.timeout(dwell_time_s)
            else:
                yield self.env.timeout(0)
            if on_dwell_end is not None:
                on_dwell_end(self.env.now)
            if dwell_status is not None and self.status == dwell_status:
                self.status = ForkliftStatus.IDLE
            return

        if self.position != target_pos:
            yield from self.move_to(
                target_pos,
                update_interval=update_interval,
                movement_overrides=movement_overrides,
            )

        if self.lift_profile and shelf_level > 0:
            shelf_height_m = self.lift_profile.height_for_level(shelf_level)
            elevated_pos = target_pos._replace(z=shelf_height_m)
            yield from self.move_to(
                elevated_pos,
                update_interval=update_interval,
                movement_overrides=movement_overrides,
            )

        should_notify_dwell = on_dwell_start is not None or on_dwell_end is not None
        if dwell_time_s > 0 or should_notify_dwell:
            if dwell_status is not None:
                self.status = dwell_status
            if on_dwell_start is not None:
                on_dwell_start(self.env.now)
            if dwell_time_s > 0:
                yield self.env.timeout(dwell_time_s)
            if on_dwell_end is not None:
                on_dwell_end(self.env.now)
            if dwell_status is not None and self.status == dwell_status:
                self.status = ForkliftStatus.IDLE

        if self.lift_profile and shelf_level > 0:
            ground_pos = target_pos._replace(z=0)
            yield from self.move_to(
                ground_pos,
                update_interval=update_interval,
                movement_overrides=movement_overrides,
            )

    def elevate(self, height_change: float) -> Generator:
        """Move load up/down by height_change meters."""
        travel_time = self.movement_profile.vertical_travel_time(height_change)

        yield self.env.timeout(travel_time)

    def is_available(self) -> bool:
        """Check if forklift is available for next task."""
        return (
            self.status == ForkliftStatus.IDLE
            and self.current_load is None
            and not self.is_reserved
        )


@dataclass
class ForkliftFleet:
    """Independent fleet manager for multiple forklifts."""

    env: simpy.Environment
    forklifts: list[Forklift] = field(default_factory=list)
    name: str = "fleet"

    # Resource for managing forklift allocation
    _resource: Optional[simpy.PriorityResource] = None
    _available_forklifts: list[Forklift] = field(default_factory=list)
    _active_assignments: dict[str, object] = field(default_factory=dict)
    _busy_since_by_forklift: dict[str, float] = field(default_factory=dict)
    _returning_home_since_by_forklift: dict[str, float] = field(default_factory=dict)
    _completed_busy_time_s: float = 0.0
    _completed_return_home_time_s: float = 0.0
    traffic_controller: Optional[PathTrafficController] = None
    stats: Optional[object] = None

    def __init__(
        self,
        env: simpy.Environment,
        count: int = 0,
        name: str = "fleet",
        home_position: Optional[Position3D] = None,
        charging_station: Optional[ChargingStation] = None,
        min_distance_to_obstacle_m: float = 1.0,
        avoid_collisions: bool = False,
        stats: Optional[object] = None,
        traffic_debug_enabled: bool = False,
        **kwargs
    ):
        """Initialize ForkliftFleet."""
        self.env = env
        self.forklifts = []
        self._available_forklifts = []
        self._active_assignments = {}
        self._busy_since_by_forklift = {}
        self._returning_home_since_by_forklift = {}
        self._completed_busy_time_s = 0.0
        self._completed_return_home_time_s = 0.0
        self.name = name
        self._resource = simpy.PriorityResource(
            self.env, capacity=max(1, count))
        self.busy_store = 0
        self.busy_retrieve = 0
        # Track pending requests (waiting in queue) per operation
        self.pending_store = 0
        self.pending_retrieve = 0
        self.home_position: Optional[Position3D] = home_position
        self.charging_station: Optional[ChargingStation] = charging_station
        self.return_home_policy: str = "stay"
        self.stats = stats
        self.traffic_controller = (
            PathTrafficController(
                min_distance_to_obstacle_m=min_distance_to_obstacle_m,
                avoid_collisions=avoid_collisions,
                debug_enabled=traffic_debug_enabled,
            )
            if avoid_collisions
            else None
        )

    # __post_init__ is no longer needed since we use __init__ directly

    def _rebuild_resource(self) -> None:
        self._resource = simpy.PriorityResource(
            self.env, capacity=max(1, len(self.forklifts))
        )

    def set_home_position(self, position: Optional[Position3D]) -> None:
        self.home_position = position
        for fl in self.forklifts:
            fl.home_position = position

    def set_charging_station(self, station: Optional[ChargingStation]) -> None:
        self.charging_station = station
        for fl in self.forklifts:
            fl.charging_station = station

    def add_forklift(self, forklift: Forklift) -> None:
        """Add a forklift to the fleet."""
        if self.resource.users or self.resource.queue:
            raise RuntimeError("Cannot add forklifts while seize requests are active")
        self.forklifts.append(forklift)
        self._available_forklifts.append(forklift)
        if forklift.home_position is None:
            forklift.home_position = self.home_position
        if forklift.charging_station is None:
            forklift.charging_station = self.charging_station
        if forklift.traffic_controller is None:
            forklift.traffic_controller = self.traffic_controller
        if forklift.stats is None:
            forklift.stats = self.stats
        # Preserve PriorityResource so request(priority=...) works.
        self._rebuild_resource()

    def _select_available_forklift(
        self,
        near_position: Optional[Position3D] = None,
    ) -> Optional[Forklift]:
        if not self._available_forklifts:
            return None
        if near_position is None:
            return self._available_forklifts.pop(0)

        best_idx = 0
        # TODO we should introduce sqr_distance_xy and sqr_distance for faster comparison operations.
        best_cost = self._available_forklifts[0].position.distance_xy(near_position)
        for i in range(1, len(self._available_forklifts)):
            cost = self._available_forklifts[i].position.distance_xy(near_position)
            if cost < best_cost:
                best_cost = cost
                best_idx = i
        return self._available_forklifts.pop(best_idx)

    def seize(
        self,
        priority: int = 1,
        near_position: Optional[Position3D] = None,
    ) -> Generator[object, object, ForkliftAssignment]:
        """Seize a specific transporter from the fleet with queue priority."""
        if not self.forklifts:
            raise RuntimeError(f"{self.name} has no forklifts configured")

        req = self.resource.request(priority=priority)
        yield req

        forklift = self._select_available_forklift(near_position=near_position)
        while forklift is None:
            # Defensive fallback if resource and pool get out-of-sync.
            yield self.env.timeout(0)
            forklift = self._select_available_forklift(near_position=near_position)

        forklift.is_reserved = True
        self._active_assignments[forklift.id] = req
        self._busy_since_by_forklift[forklift.id] = self.env.now
        return ForkliftAssignment(request=req, forklift=forklift)

    def release(self, assignment: Optional[ForkliftAssignment]) -> None:
        """Release a previously seized transporter."""
        if assignment is None:
            return
        forklift = assignment.forklift
        if self._active_assignments.pop(forklift.id, None) is None:
            return
        busy_started_at = self._busy_since_by_forklift.pop(forklift.id, None)
        if busy_started_at is not None:
            self._completed_busy_time_s += max(0.0, self.env.now - busy_started_at)
        forklift.is_reserved = False
        if self.traffic_controller is not None:
            self.traffic_controller.release_forklift(forklift.id)
        forklift._finish_traffic_wait()
        if forklift.status != ForkliftStatus.MAINTENANCE:
            forklift.status = ForkliftStatus.IDLE
        self._available_forklifts.append(forklift)
        self.resource.release(assignment.request)

    def get_available_forklift(self) -> Optional[Forklift]:
        """Get first currently-available forklift without reserving it."""
        for fl in self._available_forklifts:
            if fl.is_available():
                return fl
        return None

    @property
    def waiting_requests_count(self) -> int:
        """Number of queued seize requests still waiting for a transporter."""
        return len(self.resource.queue)

    def resolve_home_position(self, forklift: Forklift) -> Optional[Position3D]:
        return self.home_position if self.home_position is not None else forklift.home_position

    def run_post_task_policy(
        self,
        forklift: Forklift,
    ) -> Generator:  # TODO check this function once more.
        """Apply AnyLogic-style transporter wrap-up behavior after a task.

        AnyLogic's ``ReleaseTransporter`` sends the material item downstream as
        soon as unloading finishes, then drives the transporter home as a
        ResourcePool wrap-up task. That wrap-up task still has
        ``USAGE_BUSY`` by default, so MHSim keeps the assignment busy until
        this generator finishes while exposing return-home time separately for
        parity diagnostics.
        """
        return_policy = self.return_home_policy
        home_pos = self.resolve_home_position(forklift)
        if home_pos is not None and return_policy != "stay":
            should_return = return_policy == "always"
            if return_policy == "idle":
                should_return = self.waiting_requests_count == 0
            if should_return and forklift.position.distance_xy(home_pos) > 0.01:
                self._returning_home_since_by_forklift[forklift.id] = self.env.now
                try:
                    yield from forklift.move_to(home_pos)
                finally:
                    return_started_at = self._returning_home_since_by_forklift.pop(
                        forklift.id,
                        None,
                    )
                    if return_started_at is not None:
                        self._completed_return_home_time_s += max(
                            0.0,
                            self.env.now - return_started_at,
                        )

        if forklift.needs_charging():
            yield from forklift.charge_if_needed()

    def count_total(self) -> int:
        """Get total number of forklifts."""
        return len(self.forklifts)

    @property
    def busy_time_s(self) -> float:
        total = self._completed_busy_time_s
        for busy_started_at in self._busy_since_by_forklift.values():
            total += max(0.0, self.env.now - busy_started_at)
        return total

    @property
    def return_home_time_s(self) -> float:
        total = self._completed_return_home_time_s
        for return_started_at in self._returning_home_since_by_forklift.values():
            total += max(0.0, self.env.now - return_started_at)
        return total

    @property
    def utilization(self) -> float:
        forklift_count = self.count_total()
        if forklift_count <= 0 or self.env.now <= 0:
            return 0.0
        return self.busy_time_s / (forklift_count * self.env.now)

    # Legacy compatibility methods
    @property
    def resource(self) -> simpy.Resource:
        """Get underlying resource (for backwards compatibility)."""
        return self._resource


# TODO why not turn into an explicit Factory Method implementation?
def create_forklift_fleet(
    env: simpy.Environment,
    count: int,
    movement_profile: MovementProfile,
    lift_profile: Optional[LiftProfile] = None,
    router: Optional[Router] = None,
    home_position: Position3D = None,
    charging_station: Optional[ChargingStation] = None,
    turn_radius: float = 0.5,
    routed_motion_mode: str = "analytical",
    line_guided_update_timestep_s: float = 0.5,
    route_calc_delay_s: float = 0.0,
    resume_delay_s: float = 0.0,
    discharge_per_meter: float = 0.0,
    charge_rate_per_second: float = 0.0,
    charge_when_below: float = 0.20,
    charge_until: float = 0.95,
    initial_battery_soc: float = 1.0,
    name_prefix: str = "forklift",
    min_distance_to_obstacle_m: float = 1.0,
    avoid_collisions: bool = False,
    stats: Optional[object] = None,
    traffic_debug_enabled: bool = False,
) -> ForkliftFleet:
    """
    Factory function to create a fleet of identical forklifts.

    Args:
        env: SimPy environment
        count: Number of forklifts in fleet
        movement_profile: Movement profile for all forklifts
        lift_profile: Lift profile for shelf operations (optional)
        router: Router instance (shared across fleet)
        home_position: Starting position for all forklifts
        charging_station: Optional charging station assigned to each forklift
        name_prefix: Prefix for forklift IDs

    Returns:
        ForkliftFleet with initialized forklifts
    """
    if home_position is None:
        home_position = Position3D(0, 0, 0)

    fleet = ForkliftFleet(
        env,
        count=count,
        name=f"{name_prefix}_fleet",
        home_position=home_position,
        charging_station=charging_station,
        min_distance_to_obstacle_m=min_distance_to_obstacle_m,
        avoid_collisions=avoid_collisions,
        stats=stats,
        traffic_debug_enabled=traffic_debug_enabled,
    )

    for i in range(count):
        fl = Forklift(
            id=f"{name_prefix}_{i}",
            env=env,
            movement_profile=movement_profile,
            lift_profile=lift_profile,
            position=home_position,
            router=router,
            traffic_controller=fleet.traffic_controller,
            stats=stats,
            turn_radius=turn_radius,
            routed_motion_mode=routed_motion_mode,
            line_guided_update_timestep_s=line_guided_update_timestep_s,
            route_calc_delay_s=route_calc_delay_s,
            resume_delay_s=resume_delay_s,
            home_position=home_position,
            charging_station=charging_station,
            battery_soc=initial_battery_soc,
            discharge_per_meter=discharge_per_meter,
            charge_rate_per_second=charge_rate_per_second,
            charge_when_below=charge_when_below,
            charge_until=charge_until,
        )
        fleet.add_forklift(fl)

    return fleet
