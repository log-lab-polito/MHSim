"""Refactored Forklift and ForkliftFleet for 3D movement simulation.

Forklifts are now independent agents with their own movement profiles.
ForkliftFleet manages a collection of independent Forklift instances.
"""

from __future__ import annotations

import simpy
import math
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Generator, Callable, Sequence
from enum import Enum

from .movement import (
    Position3D,
    MovementProfile,
    clamp01,
    distance_to_speed,
    time_to_cover_distance,
)
from .routing import Route, RouteMotionSegment, RouteStep, Router
from .pallet import Pallet
from .traffic import LineGuidedTraffic, PathTrafficController

POSITION_TOLERANCE_M = 0.01
# AnyLogic plans each movement to rest 2 * ARRIVAL_TOLERANCE_M beyond its target and reports
# the destination reached after D + ARRIVAL_TOLERANCE_M of travel
# (docs/forklift_rules/R1_arrival_tolerance.md). Measured on the Model 1 probe, not fitted.
ARRIVAL_TOLERANCE_M = 1.0e-4


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
    # AnyLogic rack transfer (docs/forklift_rules/R5_rack_handling_and_slots.md): at a
    # bay's path exit the transporter drives `rack_approach_m` into the aisle and back
    # and reaches `rack_reach_m` across it at `rack_handling_speed`, while the pallet
    # moves between the cargo height (store) or the floor (retrieve) and the shelf.
    cargo_height: float = 0.0
    rack_approach_m: float = 0.0
    rack_reach_m: float = 0.0
    rack_handling_speed: float = 0.0
    # Direction from the path exit into the rack (radians). During the transfer the
    # transporter stands `rack_approach_m` that way, which is where its own vision looks
    # from (R8); None keeps it at the path exit.
    rack_approach_heading_rad: Optional[float] = None

    def height_for_level(self, shelf_level: int) -> float:
        """Height of a shelf level above the floor.

        Args:
            shelf_level: Zero-based level index. Ground level and any
                negative value give zero height.

        Returns:
            Height in metres.
        """
        if shelf_level <= 0:
            return 0.0
        return shelf_level * self.shelf_height

    def lift_cycle_time(self, shelf_level: int) -> float:
        """Time to raise the forks to a level and lower them again.

        Args:
            shelf_level: Zero-based level index.

        Returns:
            Combined raise and lower time in seconds. A speed of zero
            contributes nothing rather than raising, so an unconfigured
            profile yields zero instead of dividing by zero.
        """
        height = self.height_for_level(shelf_level)
        up = height / self.elevation_speed if self.elevation_speed > 0 else 0.0
        down = height / self.lowering_speed if self.lowering_speed > 0 else 0.0
        return up + down

    def rack_transfer_time(self, shelf_level: int, storing: bool) -> float:
        """Time at a bay's path exit to store a pallet in, or retrieve it from, a level (R5).

        Args:
            shelf_level: Zero-based level index.
            storing: `True` for a store (pallet raised from the cargo height to the
                shelf), `False` for a retrieve (pallet lowered from the shelf to the
                floor).

        Returns:
            Handling plus vertical transfer time in seconds.
        """
        handling = (
            (2.0 * self.rack_approach_m + self.rack_reach_m) / self.rack_handling_speed
            if self.rack_handling_speed > 0
            else 0.0
        )
        height = self.height_for_level(shelf_level)
        if storing:
            speed = self.elevation_speed
            change = abs(height - self.cargo_height)
        else:
            speed = self.lowering_speed
            change = height
        return handling + (change / speed if speed > 0 else 0.0)


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


@dataclass(frozen=True)
class _CarriedMotion:
    """Motion state left by a movement that a re-dispatch interrupted (R3)."""

    step: RouteStep
    speed: float
    heading: tuple[float, float]
    captured_at: float
    in_node: bool = False


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
    # R8: AnyLogic-style vision interaction shared by the fleet (None: no interaction).
    vision_traffic: Optional[LineGuidedTraffic] = None
    stats: Optional[object] = None
    turn_radius: float = 0.5
    routed_motion_mode: str = "analytical"
    line_guided_update_timestep_s: float = 0.5
    route_calc_delay_s: float = 0.0
    resume_delay_s: float = 0.0
    home_position: Optional[Position3D] = None
    charging_station: Optional[ChargingStation] = None

    # Battery settings are explicit optional core behavior: disabled unless
    # discharge and charge rates are both configured by a case study.
    battery_soc: float = 1.0
    discharge_per_meter: float = 0.0
    charge_rate_per_second: float = 0.0
    charge_when_below: float = 0.20
    charge_until: float = 0.95

    # Set by ForkliftFleet assignment lifecycle.
    is_reserved: bool = False
    _traffic_wait_reason: Optional[str] = field(default=None, init=False, repr=False)
    _traffic_wait_started_at: Optional[float] = field(default=None, init=False, repr=False)
    # R3: the wrap-up trip home that a seize may take over, and the motion state it leaves.
    wrap_up_process: Optional[simpy.Process] = field(default=None, init=False, repr=False)
    _carried_motion: Optional[_CarriedMotion] = field(default=None, init=False, repr=False)
    # Where the forklift actually rests after a routed movement: ARRIVAL_TOLERANCE_M past
    # its target along the final heading (R1). Dispatch measures distance from here (R9).
    rest_position: Optional[Position3D] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize forklift process."""
        if self.home_position is None:
            self.home_position = self.position
        self.battery_soc = clamp01(self.battery_soc)
        self.charge_when_below = clamp01(self.charge_when_below)
        self.charge_until = clamp01(self.charge_until)
        if self.router is None:
            raise ValueError("Forklift requires an explicit Router")

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
        if self.position.distance_to(target) < POSITION_TOLERANCE_M:
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
        braking_distance_m: Optional[float] = None,
    ) -> tuple[float, float, float]:
        """Compute horizontal motion for the current tick.

        ``braking_distance_m`` is the distance the speed profile must come to rest
        within; it defaults to the distance that may be covered, and is longer when
        the movement is planned past its target (R1).

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

        braking_distance = (
            effective_distance
            if braking_distance_m is None
            else max(effective_distance, braking_distance_m)
        )

        def next_speed_for_interval(interval_s: float) -> float:
            stop_speed_limit = (
                math.sqrt(max(0.0, 2.0 * deceleration * braking_distance))
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

    def _compute_line_guided_horizontal_motion(
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
                elapsed_time = time_to_cover_distance(
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
                    elapsed_time = time_to_cover_distance(
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
        """Return the next global controller tick after ``now``.

        A ``now`` within 1e-9 s of a tick counts as that tick, so floating-point drift
        cannot schedule the same tick twice.
        """
        if update_timestep <= 0.0:
            return now
        return (math.floor((now + 1.0e-9) / update_timestep) + 1.0) * update_timestep

    @staticmethod
    def _overshoot_position(target: Position3D, motion_segments: list) -> Position3D:
        """``target`` moved ARRIVAL_TOLERANCE_M along the heading of the last motion segment."""
        if not motion_segments:
            return target
        last = motion_segments[-1]
        if last.kind == "arc" and last.center is not None and last.radius > 0:
            angle = last.start_angle_rad + last.sweep_angle_rad
            heading = angle + math.copysign(math.pi / 2.0, last.sweep_angle_rad)
        else:
            dx, dy = last.end.x - last.start.x, last.end.y - last.start.y
            if math.hypot(dx, dy) <= 1e-12:
                return target
            heading = math.atan2(dy, dx)
        return Position3D(
            target.x + ARRIVAL_TOLERANCE_M * math.cos(heading),
            target.y + ARRIVAL_TOLERANCE_M * math.sin(heading),
            target.z,
        )

    def _move_along_route(
        self,
        route: Route,
        update_interval: float = 0.05,
        movement_overrides: Optional[ForkliftMovementOverrides] = None,
        initial_speed: float = 0.0,
    ) -> Generator:
        """Move along routed path steps with shared traffic control.

        ``initial_speed`` is the speed carried over from an interrupted movement (R3).
        A ``simpy.Interrupt`` stops the movement where the forklift is and records its
        position, speed and current path step for the next movement.
        """
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
        # R1: plan the profile to rest 2 * eps past the target; arrival after D + eps.
        if total_distance > 1e-9:
            arrival_distance = total_distance + ARRIVAL_TOLERANCE_M
            plan_distance = total_distance + 2.0 * ARRIVAL_TOLERANCE_M
        else:
            arrival_distance = plan_distance = total_distance
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
        # R7 (docs/forklift_rules/R7_line_guided_straight_routes.md): AnyLogic's
        # line-guided controller decides braking on its 0.5 s cadence on cornered
        # routes and on straight routes whose profile reaches the speed limit; a
        # straight route that never cruises follows the closed-form profile.
        # The nominal distance decides, so R1's 2e-4 m overshoot cannot tip a leg
        # that just reaches the speed limit.
        _, cruise_speed, _, cruise_time, _ = self.movement_profile.horizontal._profile_from_speed(
            total_distance, initial_speed
        )
        cruises = total_distance > 1e-9 and cruise_time * cruise_speed > 1e-6
        use_line_guided_controller = (
            routed_motion_mode == "anylogic_line_guided" and (has_corner or cruises)
        )
        # R8: with interaction every movement runs on the controller, so that other
        # transporters can stop or slow it on its updates.
        vision = self.vision_traffic if routed_motion_mode == "anylogic_line_guided" else None
        if vision is not None:
            use_line_guided_controller = True
        use_analytical_topup = not use_line_guided_controller

        # Reviewed invariants for parity-sensitive routed motion:
        # - straight routes keep the analytical top-up used by Model 1/2/5
        # - AnyLogic line-guided mode only applies to real cornered routes
        # - route-boundary updates share the same global controller cadence
        # - traffic waits clamp only the current movement slice
        # - final position, traffic release, and battery distance accounting run
        #   once after the route completes.
        #
        # AnyLogic's line-guided controller rebuilds motion profiles on a 0.5 s
        # controller cadence. On cornered paths this delays final deceleration
        # and can arrive with residual velocity. Straight paths match the
        # closed-form triangular/trapezoidal profile, so keep the analytical
        # top-up there and only use the controller cadence for cornered routes.
        if total_distance > 1e-9 and use_analytical_topup:
            analytical_horizontal_time = self.movement_profile.horizontal.arrival_time(
                arrival_distance,
                plan_distance - arrival_distance,
                initial_speed,
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
        current_speed = max(0.0, initial_speed)
        move_started_at = self.env.now
        slice_state: Optional[tuple[float, ...]] = None
        first_controller_update = True
        self.rest_position = None
        if vision is not None:
            vision.begin_move(
                self, motion_segments, arrival_distance, plan_distance, self.env.now, current_speed
            )
        line_guided_acceleration = 0.0
        line_guided_speed_limit = 0.0
        next_line_guided_update_at = self.env.now
        if not use_line_guided_controller:
            line_guided_boundary_distances = []
        elif getattr(self.router, "junctions", None):
            # AnyLogic updates where a path starts or ends (R8).
            line_guided_boundary_distances = self.router.path_boundaries(route)
        else:
            line_guided_boundary_distances = self._line_guided_route_boundary_distances(route)
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

        def recompute_line_guided_profile(tick: bool = False) -> None:
            nonlocal line_guided_acceleration, line_guided_speed_limit, current_speed

            if vision is not None:
                vision.report(self, self.env.now, horizontal_distance, current_speed)
                current_speed, line_guided_acceleration, line_guided_speed_limit = vision.decide(
                    self, self.env.now, tick
                )
                return

            horizontal = self.movement_profile.horizontal
            max_speed = max(0.0, horizontal.max_speed)
            acceleration = max(0.0, horizontal.acceleration)
            deceleration = max(0.0, horizontal.deceleration)
            stopping_distance = (
                distance_to_speed(current_speed, -deceleration, 0.0)
                if deceleration > 0.0
                else math.inf
            )
            # Brake once the stopping distance reaches the distance left to the arrival
            # point (D + ε); the profile then comes to rest just past it (R1, R8).
            to_arrival = max(0.0, arrival_distance - horizontal_distance)
            line_guided_speed_limit = (
                0.0
                if current_speed > 0.0 and stopping_distance >= to_arrival - 1e-12
                else max_speed
            )
            if current_speed > line_guided_speed_limit:
                line_guided_acceleration = -deceleration
            elif current_speed < line_guided_speed_limit:
                line_guided_acceleration = acceleration
            else:
                line_guided_acceleration = 0.0

        try:
            while horizontal_distance < arrival_distance - 1e-9 or vertical_distance < vertical_total_distance - 1e-9:
                dt = max(update_interval, 1e-3)
                if use_line_guided_controller:
                    update_timestep = max(1e-9, line_guided_update_timestep_s)
                    current_controller_time = self.env.now
                    if current_controller_time >= next_line_guided_update_at - 1e-9:
                        recompute_line_guided_profile(tick=not first_controller_update)
                        first_controller_update = False
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

                route_remaining = max(0.0, arrival_distance - horizontal_distance)
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
                            braking_distance_m=(
                                plan_distance - horizontal_distance
                                if available_distance >= route_remaining - 1e-9
                                else None
                            ),
                        )

                    if move_distance <= 1e-9 and wait_reason is not None:
                        self._start_traffic_wait(wait_reason)
                        current_speed = 0.0
                        yield self.env.timeout(dt)
                    else:
                        yield from self._resume_after_traffic_wait()
                        if move_time <= 1e-9 and move_distance > 1e-9:
                            move_time = dt
                        slice_state = (
                            self.env.now,
                            current_speed,
                            horizontal_distance,
                            line_guided_acceleration,
                            line_guided_speed_limit,
                            route_remaining,
                            available_distance,
                        )
                        yield self.env.timeout(move_time)
                        slice_state = None
                        motion_time_elapsed += move_time
                        dt = move_time
                        current_speed = next_speed
                        remaining_move = move_distance
                        blocked_reason: Optional[str] = None

                        while remaining_move > 1e-9 and horizontal_distance < arrival_distance - 1e-9:
                            if active_segment is None:
                                if current_segment_index >= len(motion_segments):
                                    # R1: the last eps of travel lies past the geometric target;
                                    # the reported position stays at the target.
                                    overshoot = min(remaining_move, arrival_distance - horizontal_distance)
                                    horizontal_distance += overshoot
                                    remaining_move -= overshoot
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
                                recompute_line_guided_profile(tick=False)

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
        except simpy.Interrupt:
            # R3: a seize took this forklift over mid-trip. Record where it is and how
            # fast it moves, so the next movement continues from that state.
            now = self.env.now
            if use_analytical_topup:
                travelled, speed = self.movement_profile.horizontal.state_at(
                    plan_distance, now - move_started_at, initial_speed
                )
            elif slice_state is not None:
                (
                    slice_started_at,
                    slice_speed,
                    slice_distance,
                    slice_acceleration,
                    slice_speed_limit,
                    slice_remaining,
                    slice_available,
                ) = slice_state
                partial, speed, _ = self._compute_line_guided_horizontal_motion(
                    current_speed=slice_speed,
                    dt=now - slice_started_at,
                    route_remaining_m=slice_remaining,
                    available_distance_m=slice_available,
                    profile_acceleration=slice_acceleration,
                    profile_speed_limit=slice_speed_limit,
                )
                travelled = slice_distance + partial
            else:
                travelled, speed = horizontal_distance, current_speed
            travelled = max(0.0, min(travelled, total_distance))
            if vision is not None:
                vision.interrupt(self, now, travelled, speed)
            self._capture_interrupted_motion(route, motion_segments, travelled, speed, current_z)
            self._finish_traffic_wait()
            if traffic is not None:
                traffic.release_forklift(self.id)
            self._consume_battery(travelled)
            raise

        self.position = Position3D(target.x, target.y, target.z)
        self.rest_position = self._overshoot_position(target, motion_segments)
        if vision is not None:
            vision.arrive(self, self.env.now, processing=self.is_reserved)

        self._finish_traffic_wait()
        if traffic is not None:
            traffic.release_forklift(self.id)
        self._consume_battery(total_distance)
        if self.status == ForkliftStatus.MOVING:
            self.status = ForkliftStatus.IDLE

    def _capture_interrupted_motion(
        self,
        route: Route,
        motion_segments: list[RouteMotionSegment],
        travelled_m: float,
        speed: float,
        z: float,
    ) -> None:
        """Place the forklift where an interrupted movement left it and keep its state (R3)."""
        progress = 0.0
        step_index = 0
        position = route.waypoints[-1]
        heading = (0.0, 0.0)
        in_node = False
        for segment in motion_segments:
            if segment.kind == "straight" and segment.step_index is not None:
                step_index = segment.step_index
            if travelled_m <= progress + segment.length + 1e-12:
                # Turn arcs and node connectors lie inside a node, not on a path.
                in_node = not (segment.kind == "straight" and segment.step_index is not None)
                position = segment.position_at(travelled_m - progress)
                dx = segment.end.x - segment.start.x
                dy = segment.end.y - segment.start.y
                norm = math.hypot(dx, dy)
                if norm > 1e-12:
                    heading = (dx / norm, dy / norm)
                break
            progress += segment.length
        self.position = Position3D(position.x, position.y, z)
        self._carried_motion = _CarriedMotion(
            step=route.steps[step_index],
            speed=max(0.0, speed),
            heading=heading,
            captured_at=self.env.now,
            in_node=in_node,
        )

    def _continuation_route(
        self,
        carried: _CarriedMotion,
        target: Position3D,
        turn_radius: float,
    ) -> Route:
        """Route for a forklift taken over while moving (R3).

        AnyLogic neither stops nor reverses a moving transporter in the middle of a path.
        A direct route that starts in the current direction of travel is used as it is;
        otherwise the forklift first runs on to the end of its current path step, turns
        there, and the route continues from that node. Inside a node (a path the router
        lists as a node crossing) the forklift turns at once, keeping its speed; inside a
        node with a radius it heads straight for the point where its next path leaves it.
        """
        position = Position3D(self.position.x, self.position.y, 0)
        if carried.in_node and getattr(self.router, "junctions", None):
            # Straight to where the next path leaves the node.
            exit_route = self.router.node_exit_route(position, target, turn_radius=turn_radius)
            if exit_route is not None:
                return exit_route
        direct = self.router.route_between_nodes(
            position, target, carried.step.path_id, turn_radius=turn_radius
        )
        if carried.in_node or carried.step.path_id in getattr(self.router, "node_crossing_paths", ()):
            return direct
        if direct.motion_segments:
            first = direct.motion_segments[0]
            dx = first.end.x - first.start.x
            dy = first.end.y - first.start.y
            if dx * carried.heading[0] + dy * carried.heading[1] > 0.0:
                return direct
        node = carried.step.end
        u_turn = self._path_end_u_turn(carried, position, target, turn_radius)
        if u_turn is not None:
            return u_turn
        lead = position.distance_xy(node)
        rest = self.router.route_between_nodes(
            node, target, carried.step.path_id, turn_radius=turn_radius
        )
        if lead <= 1e-9:
            return rest
        rest_segments = list(rest.motion_segments) or [
            RouteMotionSegment(
                kind="straight",
                start=step.start,
                end=step.end,
                length=step.length,
                step_index=index,
                start_progress_m=0.0,
                end_progress_m=step.length,
            )
            for index, step in enumerate(rest.steps)
        ]
        lead_step = replace(carried.step, start=position, length=lead)
        lead_segment = RouteMotionSegment(
            kind="straight",
            start=position,
            end=node,
            length=lead,
            step_index=0,
            start_progress_m=0.0,
            end_progress_m=lead,
        )
        shifted = [
            replace(segment, step_index=segment.step_index + 1)
            if segment.step_index is not None
            else segment
            for segment in rest_segments
        ]
        return Route(
            waypoints=[position] + list(rest.waypoints),
            total_distance=lead + rest.total_distance,
            steps=[lead_step] + list(rest.steps),
            raw_distance=lead + rest.raw_distance,
            motion_segments=[lead_segment] + shifted,
        )

    def _path_end_u_turn(
        self,
        carried: _CarriedMotion,
        position: Position3D,
        target: Position3D,
        turn_radius: float,
    ) -> Optional[Route]:
        """Turn back where the current path meets a node with a radius (R3).

        When the new route leaves that node along the same path, AnyLogic turns the
        transporter round on the node's edge instead of driving into the node.
        """
        junctions = getattr(self.router, "junctions", None)
        if not junctions:
            return None
        step = carried.step
        offset = self.router._path_end_offset(step.end, step.start)
        if not offset or step.length <= offset + 1e-9:
            return None
        rest = self.router.route_between_nodes(step.end, target, turn_radius=turn_radius)
        if not rest.steps or rest.steps[0].end.distance_xy(step.start) > 1e-6:
            return None
        ux, uy = (step.end.x - step.start.x) / step.length, (step.end.y - step.start.y) / step.length
        path_end = Position3D(step.end.x - ux * offset, step.end.y - uy * offset, 0)
        lead = position.distance_xy(path_end)
        back = self.router.node_exit_route(path_end, target, turn_radius=turn_radius)
        if back is None:
            return None
        back_segments = [segment for segment in back.motion_segments if segment.length > 1e-12]
        lead_step = replace(step, start=position, end=path_end, length=lead)
        lead_segment = RouteMotionSegment(
            kind="straight",
            start=position,
            end=path_end,
            length=lead,
            step_index=0,
            start_progress_m=0.0,
            end_progress_m=lead,
        )
        shifted = [
            replace(segment, step_index=segment.step_index + 1)
            if segment.step_index is not None
            else segment
            for segment in back_segments
        ]
        return Route(
            waypoints=[position] + list(back.waypoints[1:]),
            total_distance=lead + back.total_distance,
            steps=[lead_step] + list(back.steps),
            raw_distance=lead + back.raw_distance,
            motion_segments=[lead_segment] + shifted,
        )

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
        carried, self._carried_motion = self._carried_motion, None
        if (
            carried is not None
            and carried.captured_at == self.env.now
            and carried.speed > 1e-9
            and self._has_path_network()
        ):
            turn_radius = (
                self.turn_radius
                if movement_overrides is None or movement_overrides.turn_radius is None
                else movement_overrides.turn_radius
            )
            yield from self._move_along_route(
                self._continuation_route(carried, target, turn_radius),
                update_interval,
                movement_overrides=movement_overrides,
                initial_speed=carried.speed,
            )
            return

        # Avoid any routing/resume delays if we're already at the target.
        if self.position.distance_to(target) < POSITION_TOLERANCE_M:
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
        """Predict travel time between two points without moving.

        Used for slot-selection cost functions, so candidate slots can be
        ranked before a forklift is dispatched.

        Args:
            start: Origin.
            end: Destination.

        Returns:
            Estimated time in seconds. Horizontal and vertical motion overlap,
            so the result is the larger of the two rather than their sum.
            Horizontal distance follows the routed path where a path network
            exists, and straight-line XY distance otherwise.

        Raises:
            RuntimeError: If a path network exists but no route connects the
                two points, since silently travelling off-path would break
                parity.
        """
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
        """Time to raise and lower the forks for a shelf level.

        Args:
            shelf_level: Zero-based level index.

        Returns:
            Cycle time in seconds, or `0.0` for a forklift with no lift
            profile configured.
        """
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
            if self.vision_traffic is not None:
                self.vision_traffic.set_processing(self)
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

    def rack_transfer(
        self,
        target_pos: Optional[Position3D],
        shelf_level: int,
        storing: bool,
        dwell_status: Optional[ForkliftStatus] = None,
        on_dwell_start: Optional[Callable[[float], None]] = None,
        on_dwell_end: Optional[Callable[[float], None]] = None,
        movement_overrides: Optional[ForkliftMovementOverrides] = None,
        bay: Optional[simpy.Resource] = None,
    ) -> Generator:
        """Drive to a bay's path exit, then store or retrieve a pallet there (R5).

        With ``bay`` given, the forklift first waits at the path exit until no other
        forklift is in that bay's rack (`StorageSlotManager.bay_access`).

        The rack transfer itself takes `LiftProfile.rack_transfer_time`. AnyLogic moves
        the forklift into the rack for it, out of the other transporters' sight (R8); MHSim
        keeps it at the path exit and hides it from their vision.
        """
        if target_pos is not None and self.position != target_pos:
            yield from self.move_to(target_pos, movement_overrides=movement_overrides)
        request = None
        if bay is not None:
            # Waiting at the path exit: seen by the others, not updated (R8).
            if self.vision_traffic is not None:
                self.vision_traffic.set_processing(self)
            request = bay.request()
            yield request
        try:
            if self.vision_traffic is not None:
                pose = None
                heading = self.lift_profile.rack_approach_heading_rad if self.lift_profile else None
                if heading is not None:
                    reach = self.lift_profile.rack_approach_m
                    pose = (
                        self.position.x + reach * math.cos(heading),
                        self.position.y + reach * math.sin(heading),
                        heading,
                    )
                self.vision_traffic.set_processing(self, visible=False, pose=pose)
            if dwell_status is not None:
                self.status = dwell_status
            if on_dwell_start is not None:
                on_dwell_start(self.env.now)
            duration = (
                self.lift_profile.rack_transfer_time(shelf_level, storing)
                if self.lift_profile
                else 0.0
            )
            yield self.env.timeout(duration)
            if on_dwell_end is not None:
                on_dwell_end(self.env.now)
            if dwell_status is not None and self.status == dwell_status:
                self.status = ForkliftStatus.IDLE
        finally:
            if request is not None:
                bay.release(request)

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
        line_guided_traffic: bool = False,
        **kwargs: Any,
    ) -> None:
        """Create a fleet and its shared seize resource and traffic controller.

        Args:
            env: SimPy environment.
            count: Initial capacity of the seize resource. Forklifts are added
                separately with `add_forklift`.
            name: Fleet name, used in log lines.
            home_position: Shared home position pushed to every member.
            charging_station: Shared charging station pushed to every member.
            min_distance_to_obstacle_m: Minimum following gap in metres.
            avoid_collisions: Enable node and edge reservation.
            stats: Statistics object receiving traffic-wait records.
            traffic_debug_enabled: Record every traffic decision for debugging.
            line_guided_traffic: Let forklifts see, slow down for, stop for and
                pass each other the way AnyLogic's line-guided transporters do
                (docs/forklift_rules/R8_line_guided_traffic.md).
            **kwargs: Accepted and ignored, so callers may forward a shared
                configuration mapping that carries extra keys.
        """
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
        self.vision_traffic: Optional[LineGuidedTraffic] = (
            LineGuidedTraffic(min_distance_to_obstacle_m=min_distance_to_obstacle_m)
            if line_guided_traffic
            else None
        )

    # __post_init__ is no longer needed since we use __init__ directly

    def _rebuild_resource(self) -> None:
        self._resource = simpy.PriorityResource(
            self.env, capacity=max(1, len(self.forklifts))
        )

    def set_home_position(self, position: Optional[Position3D]) -> None:
        """Set the fleet home point and push it to every member.

        Args:
            position: Shared home position, or `None` to clear it. Overwrites
                any per-forklift home already set.
        """
        self.home_position = position
        for fl in self.forklifts:
            fl.home_position = position

    def set_charging_station(self, station: Optional[ChargingStation]) -> None:
        """Set the fleet charging station and push it to every member.

        Args:
            station: Shared charging station, or `None` to clear it.
        """
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
        if self.vision_traffic is not None:
            forklift.vision_traffic = self.vision_traffic
            self.vision_traffic.register(forklift)
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

        # R9: the free forklift nearest to the request in a straight line, measured from
        # where it actually is (on its way home, or resting past its last target); ties go
        # to the earliest-created forklift.
        def cost(forklift: Forklift) -> tuple[float, int]:
            where = None
            if self.vision_traffic is not None:
                where = self.vision_traffic.position_of(forklift, self.env.now)
            if where is None:
                where = forklift.rest_position or forklift.position
            return where.sqr_distance_xy(near_position), self.forklifts.index(forklift)

        best_idx = 0
        best_cost = cost(self._available_forklifts[0])
        for i in range(1, len(self._available_forklifts)):
            cost_i = cost(self._available_forklifts[i])
            if cost_i < best_cost:
                best_cost = cost_i
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
        # The reference experiments run simultaneous events last-scheduled first, so a
        # forklift released at this same instant (its release was scheduled after the
        # event that raised this request) is free before the dispatch decision (R9).
        yield self.env.timeout(0)

        forklift = self._select_available_forklift(near_position=near_position)
        while forklift is None:
            # Defensive fallback if resource and pool get out-of-sync.
            yield self.env.timeout(0)
            forklift = self._select_available_forklift(near_position=near_position)

        forklift.is_reserved = True
        self._active_assignments[forklift.id] = req
        if self.vision_traffic is not None and getattr(forklift, "_fresh_vision_on_seize", False):
            # R8: released after a delivery and seized again in place.
            self.vision_traffic.clear_vision(forklift)
        forklift._fresh_vision_on_seize = False
        # A forklift taken over on its way home stays in the busy period that its
        # wrap-up started (R2, R3).
        self._busy_since_by_forklift.setdefault(forklift.id, self.env.now)
        wrap_up = forklift.wrap_up_process
        if wrap_up is not None and wrap_up.is_alive:
            wrap_up.interrupt("redispatch")
            yield wrap_up
        return ForkliftAssignment(request=req, forklift=forklift)

    def release(
        self,
        assignment: Optional[ForkliftAssignment],
        wrap_up: bool = False,
    ) -> None:
        """Release a previously seized transporter.

        The material item is free as soon as this returns (R2). With ``wrap_up`` the
        fleet's return-home policy may send the forklift home as a wrap-up task: it stays
        busy for utilisation until it arrives, but the next seize request takes it over
        mid-trip (R3).

        Args:
            assignment: Assignment returned by `seize`. `None` is ignored.
            wrap_up: Apply the fleet's return-home policy after the release.
        """
        if assignment is None:
            return
        forklift = assignment.forklift
        if self._active_assignments.pop(forklift.id, None) is None:
            return
        go_home = wrap_up and self._should_return_home(forklift)
        if not go_home:
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
        if self.vision_traffic is not None:
            self.vision_traffic.set_idle(forklift)
        forklift._fresh_vision_on_seize = not go_home
        if go_home:
            forklift.wrap_up_process = self.env.process(self._wrap_up(forklift))
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
        """Decide where a forklift should return to after a task.

        Args:
            forklift: The forklift about to return home.

        Returns:
            The fleet home position when one is set, otherwise the forklift's
            own, or `None` if neither is configured. The fleet setting wins,
            so a fleet-wide home overrides per-unit values.
        """
        return self.home_position if self.home_position is not None else forklift.home_position

    def _should_return_home(self, forklift: Forklift) -> bool:
        """Whether the return-home policy sends ``forklift`` home after a release (R2)."""
        home_pos = self.resolve_home_position(forklift)
        if home_pos is None or self.return_home_policy == "stay":
            return False
        if self.return_home_policy == "idle" and self.waiting_requests_count > 0:
            return False
        return forklift.position.distance_xy(home_pos) > POSITION_TOLERANCE_M

    def _wrap_up(self, forklift: Forklift) -> Generator:
        """Drive a released forklift home as an AnyLogic-style wrap-up task (R2, R3).

        AnyLogic's ``ReleaseTransporter`` lets the material item go at release and sends
        the transporter home as a ResourcePool wrap-up task whose usage state is busy by
        default. A new seize request terminates the wrap-up and takes the forklift over
        where it is; `seize` interrupts this process for that.
        """
        home_pos = self.resolve_home_position(forklift)
        self._returning_home_since_by_forklift[forklift.id] = self.env.now
        arrived = False
        try:
            yield from forklift.move_to(home_pos)
            arrived = True
        except simpy.Interrupt:
            pass
        finally:
            return_started_at = self._returning_home_since_by_forklift.pop(forklift.id, None)
            if return_started_at is not None:
                self._completed_return_home_time_s += max(0.0, self.env.now - return_started_at)
            forklift.wrap_up_process = None
        if arrived and forklift.id not in self._active_assignments:
            busy_started_at = self._busy_since_by_forklift.pop(forklift.id, None)
            if busy_started_at is not None:
                self._completed_busy_time_s += max(0.0, self.env.now - busy_started_at)
            if forklift.needs_charging():
                yield from forklift.charge_if_needed()

    def count_total(self) -> int:
        """Get total number of forklifts."""
        return len(self.forklifts)

    @property
    def busy_time_s(self) -> float:
        """Total seconds the fleet has spent busy, across all forklifts.

        Busy runs from a seize to the release, or to the end of the wrap-up trip home
        that follows it (R2). Includes time accrued by tasks still in progress, so the
        value is meaningful mid-run and not only at the end.
        """
        total = self._completed_busy_time_s
        for busy_started_at in self._busy_since_by_forklift.values():
            total += max(0.0, self.env.now - busy_started_at)
        return total

    @property
    def return_home_time_s(self) -> float:
        """Total seconds the fleet has spent on wrap-up trips home.

        A diagnostic: these seconds are also part of `busy_time_s`, as in AnyLogic,
        whose wrap-up usage state is busy. Includes trips still under way.
        """
        total = self._completed_return_home_time_s
        for return_started_at in self._returning_home_since_by_forklift.values():
            total += max(0.0, self.env.now - return_started_at)
        return total

    @property
    def utilization(self) -> float:
        """Fraction of available fleet time spent busy, in `[0, 1]`.

        Computed as busy time over fleet size times elapsed simulation time.
        Returns `0.0` before the run starts or for an empty fleet.

        Parity:
            Wrap-up trips home are included, matching AnyLogic, whose
            ResourcePool wrap-up usage state is busy by default.
        """
        forklift_count = self.count_total()
        if forklift_count <= 0 or self.env.now <= 0:
            return 0.0
        return self.busy_time_s / (forklift_count * self.env.now)

    # Legacy compatibility methods
    @property
    def resource(self) -> simpy.Resource:
        """Get underlying resource (for backwards compatibility)."""
        return self._resource


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
    line_guided_traffic: bool = False,
    home_positions: Optional[Sequence[Position3D]] = None,
) -> ForkliftFleet:
    """Factory function to create a fleet of identical forklifts.

    Args:
        env: SimPy environment.
        count: Number of forklifts in the fleet.
        movement_profile: Movement profile applied to every forklift.
        lift_profile: Lift profile for shelf operations.
        router: Router shared across the fleet. It may have an empty path
            network, but it must be provided.
        home_position: Starting position for all forklifts. Defaults to the
            origin.
        charging_station: Charging station assigned to each forklift.
        turn_radius: Turn radius in metres used when routing.
        routed_motion_mode: Either `analytical`, which solves each leg
            in closed form, or the line-guided mode, which steps position
            forward on a fixed timestep.
        line_guided_update_timestep_s: Position update interval in seconds for
            the line-guided mode. Ignored by the analytical mode.
        route_calc_delay_s: Delay in seconds charged before a route is
            followed, modelling route computation.
        resume_delay_s: Delay in seconds before resuming after a traffic stop.
        discharge_per_meter: Battery state of charge consumed per metre
            travelled. Zero disables battery modelling entirely.
        charge_rate_per_second: State of charge recovered per second while
            charging.
        charge_when_below: State of charge at or below which a forklift seeks
            the charging station.
        charge_until: State of charge at which charging stops.
        initial_battery_soc: State of charge each forklift starts with, in
            `[0, 1]`.
        name_prefix: Prefix for generated forklift identifiers.
        min_distance_to_obstacle_m: Minimum following gap in metres enforced
            by the traffic controller.
        avoid_collisions: Enable node and edge reservation, so forklifts wait
            rather than passing through each other.
        stats: Statistics object receiving traffic-wait records.
        traffic_debug_enabled: Record every traffic allow and block decision.
        line_guided_traffic: AnyLogic-style vision interaction between the
            forklifts (docs/forklift_rules/R8_line_guided_traffic.md).
        home_positions: One home per forklift, in creation order, where each
            starts and returns to, as AnyLogic spreads transporters over an
            area home node. Overrides `home_position`.

    Returns:
        A fleet of `count` identically configured forklifts, all sharing
        one router and traffic controller.

    Raises:
        ValueError: If no `router` is given.
    """
    if home_position is None:
        home_position = Position3D(0, 0, 0)
    if router is None:
        raise ValueError("create_forklift_fleet requires an explicit Router")
    if home_positions is not None and len(home_positions) < count:
        raise ValueError(f"home_positions has {len(home_positions)} entries for {count} forklifts")

    fleet = ForkliftFleet(
        env,
        count=count,
        name=f"{name_prefix}_fleet",
        # Per-forklift homes must not be overridden by a fleet-wide one.
        home_position=None if home_positions is not None else home_position,
        charging_station=charging_station,
        min_distance_to_obstacle_m=min_distance_to_obstacle_m,
        avoid_collisions=avoid_collisions,
        stats=stats,
        traffic_debug_enabled=traffic_debug_enabled,
        line_guided_traffic=line_guided_traffic,
    )

    for i in range(count):
        fl = Forklift(
            id=f"{name_prefix}_{i}",
            env=env,
            movement_profile=movement_profile,
            lift_profile=lift_profile,
            position=home_positions[i] if home_positions is not None else home_position,
            router=router,
            traffic_controller=fleet.traffic_controller,
            stats=stats,
            turn_radius=turn_radius,
            routed_motion_mode=routed_motion_mode,
            line_guided_update_timestep_s=line_guided_update_timestep_s,
            route_calc_delay_s=route_calc_delay_s,
            resume_delay_s=resume_delay_s,
            home_position=home_positions[i] if home_positions is not None else home_position,
            charging_station=charging_station,
            battery_soc=initial_battery_soc,
            discharge_per_meter=discharge_per_meter,
            charge_rate_per_second=charge_rate_per_second,
            charge_when_below=charge_when_below,
            charge_until=charge_until,
        )
        fleet.add_forklift(fl)

    return fleet
