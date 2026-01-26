"""
Refactored Forklift and ForkliftFleet for 3D movement simulation.

Forklifts are now independent agents with their own movement profiles.
ForkliftFleet manages a collection of independent Forklift instances.
"""

from __future__ import annotations

import simpy
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

    def __post_init__(self):
        """Initialize forklift process."""
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
        # Check if this is a pure vertical movement
        xy_distance = self.position.distance_xy(target)
        is_vertical_only = xy_distance < 0.01

        if self.router and not is_vertical_only:
            path_id = preferred_path_id or self.router.nearest_path_id(
                self.position) or self.router.nearest_path_id(target)
            route = self.router.route_between_nodes(
                self.position, target, path_id)
            # Traverse route waypoints sequentially
            for wp in route.waypoints[1:]:  # skip current position
                yield from self._move_direct_to(wp, update_interval)
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

        yield self.env.timeout(dwell_time_s)

        if self.lift_profile and shelf_level > 0:
            ground_pos = target_pos._replace(z=0)
            yield from self.move_to(ground_pos, update_interval=update_interval)

    def elevate(self, height_change: float) -> Generator:
        """Move load up/down by height_change meters."""
        travel_time = self.movement_profile.vertical_travel_time(height_change)

        yield self.env.timeout(travel_time)

    def is_available(self) -> bool:
        """Check if forklift is available for next task."""
        return self.status == ForklifStatus.IDLE and self.current_load is None


@dataclass
class ForkliftFleet:
    """Independent fleet manager for multiple forklifts."""

    env: simpy.Environment
    forklifts: list[Forklift] = field(default_factory=list)
    name: str = "fleet"

    # Resource for managing forklift allocation
    _resource: Optional[simpy.Resource] = None

    def __init__(
        self,
        env: simpy.Environment,
        count: int = 0,
        name: str = "fleet",
        **kwargs
    ):
        """Initialize ForkliftFleet."""
        self.env = env
        self.forklifts = []
        self.name = name
        self._resource = simpy.PriorityResource(
            self.env, capacity=max(1, count))
        self.busy_store = 0
        self.busy_retrieve = 0
        # Track pending requests (waiting in queue) per operation
        self.pending_store = 0
        self.pending_retrieve = 0

    # __post_init__ is no longer needed since we use __init__ directly

    def add_forklift(self, forklift: Forklift) -> None:
        """Add a forklift to the fleet."""
        self.forklifts.append(forklift)
        # Update resource capacity
        # Preserve PriorityResource so request(priority=...) works
        self._resource = simpy.PriorityResource(
            self.env, capacity=len(self.forklifts))

    def get_available_forklift(self) -> Optional[Forklift]:
        """Get first available forklift."""
        for fl in self.forklifts:
            if fl.is_available():
                return fl
        return None

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
        name_prefix: Prefix for forklift IDs

    Returns:
        ForkliftFleet with initialized forklifts
    """
    if home_position is None:
        home_position = Position3D(0, 0, 0)

    fleet = ForkliftFleet(env, name=f"{name_prefix}_fleet")

    for i in range(count):
        fl = Forklift(
            id=f"{name_prefix}_{i}",
            env=env,
            movement_profile=movement_profile,
            lift_profile=lift_profile,
            position=home_position,
            router=router
        )
        fleet.add_forklift(fl)

    return fleet
