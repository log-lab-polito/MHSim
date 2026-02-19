"""
Refactored Forklift and ForkliftFleet for 3D movement simulation.

Forklifts are now independent agents with their own movement profiles.
ForkliftFleet manages a collection of independent Forklift instances.
"""

from __future__ import annotations

import simpy
import math
from dataclasses import dataclass, field
from typing import Optional, Generator
from enum import Enum

from .movement import Position3D, MovementProfile
from .routing import Router
from .pallet import Pallet


class ForklifStatus(Enum):
    """Forklift operational status."""
    IDLE = "idle"
    MOVING = "moving"
    LOADING = "loading"
    UNLOADING = "unloading"
    CHARGING = "charging"
    MAINTENANCE = "maintenance"


# Keep a correctly-spelled alias for API clarity while preserving compatibility.
ForkliftStatus = ForklifStatus


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
    status: ForklifStatus = ForklifStatus.IDLE
    current_load: Optional[Pallet] = None
    router: Optional[Router] = None
    turn_radius: float = 1.0
    route_calc_delay_s: float = 0.0
    resume_delay_s: float = 0.0
    home_position: Optional[Position3D] = None
    charging_station: Optional[ChargingStation] = None

    # Battery settings (disabled by default when discharge_per_meter == 0).
    battery_soc: float = 1.0
    discharge_per_meter: float = 0.0
    charge_rate_per_second: float = 0.0
    charge_when_below: float = 0.20
    charge_until: float = 0.95

    # Set by ForkliftFleet assignment lifecycle.
    is_reserved: bool = False

    def __post_init__(self):
        """Initialize forklift process."""
        if self.home_position is None:
            self.home_position = self.position
        self.battery_soc = min(max(self.battery_soc, 0.0), 1.0)
        self.charge_when_below = min(max(self.charge_when_below, 0.0), 1.0)
        self.charge_until = min(max(self.charge_until, 0.0), 1.0)
        if not self.router:
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

        self.status = ForklifStatus.CHARGING
        target_soc = max(self.battery_soc, self.charge_until)
        if target_soc > self.battery_soc:
            charge_time = (target_soc - self.battery_soc) / self.charge_rate_per_second
            yield self.env.timeout(charge_time)
            self.battery_soc = target_soc
        self.status = ForklifStatus.IDLE

    def _move_direct_to(self, target: Position3D, update_interval: float = 0.05) -> Generator:
        """Move directly to target using acceleration profile (no routing)."""
        # Check if we're already at target (in 3D, not just XY)
        if self.position.distance_to(target) < 0.01:
            yield self.env.timeout(0)
            return

        self.status = ForklifStatus.MOVING
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
            if self.status == ForklifStatus.MOVING:
                self.status = ForklifStatus.IDLE
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
        if self.status == ForklifStatus.MOVING:
            self.status = ForklifStatus.IDLE

    def _move_along_route(
        self,
        waypoints: list[Position3D],
        update_interval: float = 0.05,
    ) -> Generator:
        """Move along a route polyline with a single accel/cruise/decel profile."""
        if len(waypoints) < 2:
            yield self.env.timeout(0)
            return

        self.status = ForklifStatus.MOVING
        start_pos = self.position
        target = waypoints[-1]
        height_change = target.z - start_pos.z

        def rot90(u: Position3D, sign: float) -> Position3D:
            if sign > 0:
                return Position3D(-u.y, u.x, 0)
            return Position3D(u.y, -u.x, 0)

        def normalize(vx: float, vy: float) -> Position3D:
            norm = math.hypot(vx, vy)
            if norm <= 1e-9:
                return Position3D(0.0, 0.0, 0)
            return Position3D(vx / norm, vy / norm, 0)

        def angle_between(u: Position3D, v: Position3D) -> float:
            dot = max(-1.0, min(1.0, u.x * v.x + u.y * v.y))
            return math.acos(dot)

        route_xy = [Position3D(wp.x, wp.y, 0) for wp in waypoints]
        compacted = []
        for p in route_xy:
            if not compacted or compacted[-1].distance_xy(p) > 1e-6:
                compacted.append(p)
        route_xy = compacted

        segments: list[dict] = []
        current = route_xy[0]
        turn_radius = max(0.0, getattr(self, "turn_radius", 1.0))

        for i in range(1, len(route_xy) - 1):
            prev_pt = route_xy[i - 1]
            corner = route_xy[i]
            next_pt = route_xy[i + 1]

            u1 = normalize(corner.x - prev_pt.x, corner.y - prev_pt.y)
            u2 = normalize(next_pt.x - corner.x, next_pt.y - corner.y)

            if (u1.x == 0 and u1.y == 0) or (u2.x == 0 and u2.y == 0):
                continue

            ang = angle_between(u1, u2)
            if turn_radius <= 0 or ang < 1e-3 or abs(math.pi - ang) < 1e-3:
                # Straight or U-turn; keep as sharp corner
                if current.distance_xy(corner) > 1e-6:
                    segments.append(
                        {"kind": "line", "start": current, "end": corner,
                         "length": current.distance_xy(corner)}
                    )
                    current = corner
                continue

            t = turn_radius * math.tan(ang / 2.0)
            incoming_len = corner.distance_xy(prev_pt)
            outgoing_len = corner.distance_xy(next_pt)
            available_in = corner.distance_xy(current)
            if t > incoming_len or t > outgoing_len or t > available_in:
                if current.distance_xy(corner) > 1e-6:
                    segments.append(
                        {"kind": "line", "start": current, "end": corner,
                         "length": current.distance_xy(corner)}
                    )
                    current = corner
                continue

            tangent_in = Position3D(corner.x - u1.x * t, corner.y - u1.y * t, 0)
            tangent_out = Position3D(corner.x + u2.x * t, corner.y + u2.y * t, 0)

            if current.distance_xy(tangent_in) > 1e-6:
                segments.append(
                    {"kind": "line", "start": current, "end": tangent_in,
                     "length": current.distance_xy(tangent_in)}
                )

            cross = u1.x * u2.y - u1.y * u2.x
            sign = 1.0 if cross > 0 else -1.0
            n1 = rot90(u1, sign)
            center = Position3D(
                tangent_in.x + n1.x * turn_radius,
                tangent_in.y + n1.y * turn_radius,
                0,
            )

            start_ang = math.atan2(tangent_in.y - center.y, tangent_in.x - center.x)
            end_ang = math.atan2(tangent_out.y - center.y, tangent_out.x - center.x)
            if sign > 0:
                delta = (end_ang - start_ang) % (2 * math.pi)
            else:
                delta = (start_ang - end_ang) % (2 * math.pi)
            arc_len = turn_radius * delta

            segments.append(
                {
                    "kind": "arc",
                    "center": center,
                    "radius": turn_radius,
                    "start_ang": start_ang,
                    "sign": sign,
                    "length": arc_len,
                }
            )

            current = tangent_out

        if current.distance_xy(route_xy[-1]) > 1e-6:
            segments.append(
                {"kind": "line", "start": current, "end": route_xy[-1],
                 "length": current.distance_xy(route_xy[-1])}
            )

        total_distance = sum(seg["length"] for seg in segments)

        horiz = self.movement_profile.horizontal
        a = horiz.acceleration
        d = horiz.deceleration
        v_max = horiz.max_speed

        accel_time = 0.0
        decel_time = 0.0
        cruise_time = 0.0
        accel_dist = 0.0
        cruise_dist = 0.0
        peak_speed = 0.0

        if total_distance > 0 and v_max > 0 and a > 0 and d > 0:
            accel_time = v_max / a
            decel_time = v_max / d
            accel_dist = 0.5 * a * accel_time ** 2
            decel_dist = 0.5 * d * decel_time ** 2

            if total_distance >= accel_dist + decel_dist:
                cruise_dist = total_distance - accel_dist - decel_dist
                cruise_time = cruise_dist / v_max
                peak_speed = v_max
            else:
                peak_speed = math.sqrt(2 * total_distance * a * d / (a + d))
                accel_time = peak_speed / a
                decel_time = peak_speed / d
                cruise_time = 0.0
                cruise_dist = 0.0
                accel_dist = 0.5 * a * accel_time ** 2

        horizontal_time = accel_time + cruise_time + decel_time

        def distance_at_time(t: float) -> float:
            if t <= 0 or total_distance <= 0:
                return 0.0
            if t <= accel_time:
                return 0.5 * a * t ** 2
            cruise_start_time = accel_time
            cruise_end_time = accel_time + cruise_time
            if t <= cruise_end_time:
                return accel_dist + peak_speed * (t - cruise_start_time)
            decel_elapsed = t - cruise_end_time
            dist_in_decel = peak_speed * decel_elapsed - 0.5 * d * decel_elapsed ** 2
            return accel_dist + cruise_dist + dist_in_decel

        def position_at_distance(dist: float) -> Position3D:
            if dist <= 0 or not segments:
                return route_xy[0]
            remaining = dist
            for seg in segments:
                if remaining <= seg["length"] + 1e-9:
                    if seg["kind"] == "line":
                        start = seg["start"]
                        end = seg["end"]
                        if seg["length"] <= 1e-9:
                            return end
                        frac = remaining / seg["length"]
                        return Position3D(
                            start.x + (end.x - start.x) * frac,
                            start.y + (end.y - start.y) * frac,
                            0,
                        )
                    center = seg["center"]
                    radius = seg["radius"]
                    sign = seg["sign"]
                    angle = seg["start_ang"] + sign * (remaining / radius)
                    return Position3D(
                        center.x + radius * math.cos(angle),
                        center.y + radius * math.sin(angle),
                        0,
                    )
                remaining -= seg["length"]
            return route_xy[-1]

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
        vertical_time = abs(height_change) / vertical_speed if vertical_speed > 0 else 0.0

        total_time = max(horizontal_time, vertical_time)
        if total_time <= 0:
            self.position = target
            self._consume_battery(total_distance)
            if self.status == ForklifStatus.MOVING:
                self.status = ForklifStatus.IDLE
            yield self.env.timeout(0)
            return

        elapsed = 0.0
        while elapsed < total_time:
            dt = min(update_interval, total_time - elapsed)
            yield self.env.timeout(dt)
            elapsed += dt

            if horizontal_time > 0:
                t_h = min(elapsed, horizontal_time)
                dist_traveled = distance_at_time(t_h)
                xy_pos = position_at_distance(dist_traveled)
            else:
                xy_pos = route_xy[-1]

            if vertical_time > 0:
                z_progress = min(elapsed / vertical_time, 1.0)
                z = start_pos.z + height_change * z_progress
            else:
                z = target.z

            self.position = Position3D(xy_pos.x, xy_pos.y, z)

        self.position = Position3D(target.x, target.y, target.z)
        self._consume_battery(total_distance)
        if self.status == ForklifStatus.MOVING:
            self.status = ForklifStatus.IDLE

    def move_to(self, target: Position3D, preferred_path_id: Optional[str] = None, update_interval: float = 0.05) -> Generator:
        """Move to a target, preferring predefined paths when available.

        If a router and path network are available, route via the nearest or
        specified path and traverse waypoints in sequence, constraining motion
        to those predefined paths. Falls back to direct movement if no paths.

        Pure vertical movements (XY unchanged) bypass routing to avoid forcing
        through ground-level waypoints.
        """
        # Avoid any routing/resume delays if we're already at the target.
        if self.position.distance_to(target) < 0.01:
            yield self.env.timeout(0)
            return

        if self.resume_delay_s > 0 and self.status == ForklifStatus.IDLE:
            yield self.env.timeout(self.resume_delay_s)

        # Check if this is a pure vertical movement
        xy_distance = self.position.distance_xy(target)
        is_vertical_only = xy_distance < 0.01

        if self.router and not is_vertical_only:
            if self.route_calc_delay_s > 0:
                yield self.env.timeout(self.route_calc_delay_s)
            path_id = preferred_path_id or self.router.nearest_path_id(
                self.position) or self.router.nearest_path_id(target)
            route = self.router.route_between_nodes(
                self.position, target, path_id)
            yield from self._move_along_route(route.waypoints, update_interval)
            return

        # Fallback: direct movement (also used for vertical-only movements)
        yield from self._move_direct_to(target, update_interval)

    def estimate_travel_time(self, start: Position3D, end: Position3D) -> float:
        if self.router:
            xy_distance = self.router.distance_between(start, end)
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
        dwell_status: Optional[ForklifStatus] = None,
    ) -> Generator:
        """Move to position, lift to shelf level, dwell, then return to ground."""
        if target_pos is None:
            yield self.env.timeout(dwell_time_s)
            return

        if self.position != target_pos:
            yield from self.move_to(target_pos, update_interval=update_interval)

        if self.lift_profile and shelf_level > 0:
            shelf_height_m = self.lift_profile.height_for_level(shelf_level)
            elevated_pos = target_pos._replace(z=shelf_height_m)
            yield from self.move_to(elevated_pos, update_interval=update_interval)

        if dwell_time_s > 0:
            if dwell_status is not None:
                self.status = dwell_status
            yield self.env.timeout(dwell_time_s)
            if self.status == dwell_status:
                self.status = ForklifStatus.IDLE

        if self.lift_profile and shelf_level > 0:
            ground_pos = target_pos._replace(z=0)
            yield from self.move_to(ground_pos, update_interval=update_interval)

    def elevate(self, height_change: float) -> Generator:
        """Move load up/down by height_change meters."""
        travel_time = self.movement_profile.vertical_travel_time(height_change)

        yield self.env.timeout(travel_time)

    def is_available(self) -> bool:
        """Check if forklift is available for next task."""
        return (
            self.status == ForklifStatus.IDLE
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

    def __init__(
        self,
        env: simpy.Environment,
        count: int = 0,
        name: str = "fleet",
        home_position: Optional[Position3D] = None,
        charging_station: Optional[ChargingStation] = None,
        **kwargs
    ):
        """Initialize ForkliftFleet."""
        self.env = env
        self.forklifts = []
        self._available_forklifts = []
        self._active_assignments = {}
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
        return ForkliftAssignment(request=req, forklift=forklift)

    def release(self, assignment: Optional[ForkliftAssignment]) -> None:
        """Release a previously seized transporter."""
        if assignment is None:
            return
        forklift = assignment.forklift
        if self._active_assignments.pop(forklift.id, None) is None:
            return
        forklift.is_reserved = False
        if forklift.status != ForklifStatus.MAINTENANCE:
            forklift.status = ForklifStatus.IDLE
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
    ) -> Generator:
        """Apply return-home and charging behavior after a completed task."""
        return_policy = self.return_home_policy
        home_pos = self.resolve_home_position(forklift)
        if home_pos is not None and return_policy != "stay":
            should_return = return_policy == "always"
            if return_policy == "idle":
                should_return = self.waiting_requests_count == 0
            if should_return and forklift.position.distance_xy(home_pos) > 0.01:
                yield from forklift.move_to(home_pos)

        if forklift.needs_charging():
            yield from forklift.charge_if_needed()

    def count_total(self) -> int:
        """Get total number of forklifts."""
        return len(self.forklifts)

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
    turn_radius: float = 1.0,
    route_calc_delay_s: float = 0.0,
    resume_delay_s: float = 0.0,
    discharge_per_meter: float = 0.0,
    charge_rate_per_second: float = 0.0,
    charge_when_below: float = 0.20,
    charge_until: float = 0.95,
    initial_battery_soc: float = 1.0,
    name_prefix: str = "forklift"
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
    )

    for i in range(count):
        fl = Forklift(
            id=f"{name_prefix}_{i}",
            env=env,
            movement_profile=movement_profile,
            lift_profile=lift_profile,
            position=home_position,
            router=router,
            turn_radius=turn_radius,
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
