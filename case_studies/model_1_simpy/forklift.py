"""
Refactored Forklift and ForkliftFleet for 3D movement simulation.

Forklifts are now independent agents with their own movement profiles.
ForkliftFleet manages a collection of independent Forklift instances.
"""

from __future__ import annotations

import simpy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, Generator
from enum import Enum

from .movement import Position3D, MovementProfile, HorizontalMovement, VerticalMovement
from .routing import Router
from .pallet import Pallet


class ForklifStatus(Enum):
    """Forklift operational status."""
    IDLE = "idle"
    MOVING = "moving"
    LOADING = "loading"
    UNLOADING = "unloading"


@dataclass
class Forklift:
    """Independent forklift agent with movement simulation."""

    # Identity
    id: str
    env: simpy.Environment

    # Movement profile
    movement_profile: MovementProfile

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
        if self.position.distance_xy(target) < 0.01:
            yield self.env.timeout(0)
            return

        self.status = ForklifStatus.MOVING
        start_pos = self.position

        from .movement import AcceleratingInterpolator
        interpolator = AcceleratingInterpolator(
            start_pos, target, self.movement_profile.horizontal)

        travel_time = interpolator.travel_time
        elapsed = 0.0
        while elapsed < travel_time:
            dt = min(update_interval, travel_time - elapsed)
            yield self.env.timeout(dt)
            elapsed += dt
            self.position = interpolator.update(dt)

        self.position = target
        if self.status == ForklifStatus.MOVING:
            self.status = ForklifStatus.IDLE

    def move_to(self, target: Position3D, preferred_path_id: Optional[str] = None, update_interval: float = 0.05) -> Generator:
        """Move to a target, preferring predefined paths when available.

        If a router and path network are available, route via the nearest or
        specified path and traverse waypoints in sequence, constraining motion
        to those predefined paths. Falls back to direct movement if no paths.
        """
        if self.router:
            path_id = preferred_path_id or self.router.nearest_path_id(
                self.position) or self.router.nearest_path_id(target)
            route = self.router.route_between_nodes(
                self.position, target, path_id)
            # Traverse route waypoints sequentially
            for wp in route.waypoints[1:]:  # skip current position
                yield from self._move_direct_to(wp, update_interval)
            return

        # Fallback: direct movement
        yield from self._move_direct_to(target, update_interval)

    def load(self, pallet: Pallet) -> Generator:
        """Load a pallet onto forklift."""
        self.status = ForklifStatus.LOADING
        self.current_load = pallet

        yield self.env.timeout(self.movement_profile.loading_time)

        if self.status == ForklifStatus.LOADING:
            self.status = ForklifStatus.IDLE

    def unload(self) -> Generator:
        """Unload current pallet."""
        self.status = ForklifStatus.UNLOADING

        yield self.env.timeout(self.movement_profile.unloading_time)

        pallet = self.current_load
        self.current_load = None

        if self.status == ForklifStatus.UNLOADING:
            self.status = ForklifStatus.IDLE

        return pallet

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

    # Legacy compatibility
    _resource: Optional[simpy.Resource] = None

    # Legacy parameters (stored for compatibility but not used in new system)
    count: int = 0
    store_time_s: float = 0.0
    retrieve_time_s: float = 0.0
    store_travel_time_s: float = 0.0
    retrieve_travel_time_s: float = 0.0
    travel_time_fn: Optional[callable] = None

    def __init__(
        self,
        env: simpy.Environment,
        count: int = 0,
        store_time_s: float = 0.0,
        retrieve_time_s: float = 0.0,
        store_travel_time_s: float = 0.0,
        retrieve_travel_time_s: float = 0.0,
        travel_time_fn: Optional[callable] = None,
        name: str = "fleet",
        **kwargs
    ):
        """Initialize ForkliftFleet with backward compatibility."""
        self.env = env
        self.forklifts = []
        self.name = name
        self.count = count
        self.store_time_s = store_time_s
        self.retrieve_time_s = retrieve_time_s
        self.store_travel_time_s = store_travel_time_s
        self.retrieve_travel_time_s = retrieve_travel_time_s
        self.travel_time_fn = travel_time_fn
        self._resource = simpy.Resource(self.env, capacity=max(1, count))

    # __post_init__ is no longer needed since we use __init__ directly

    def add_forklift(self, forklift: Forklift) -> None:
        """Add a forklift to the fleet."""
        self.forklifts.append(forklift)
        # Update resource capacity
        self._resource = simpy.Resource(self.env, capacity=len(self.forklifts))

    def get_available_forklift(self) -> Optional[Forklift]:
        """Get first available forklift."""
        for fl in self.forklifts:
            if fl.is_available():
                return fl
        return None

    def get_forklift(self, forklift_id: str) -> Optional[Forklift]:
        """Get forklift by ID."""
        for fl in self.forklifts:
            if fl.id == forklift_id:
                return fl
        return None

    def count_available(self) -> int:
        """Count available forklifts."""
        return sum(1 for fl in self.forklifts if fl.is_available())

    def count_total(self) -> int:
        """Get total number of forklifts."""
        return len(self.forklifts)

    # Legacy compatibility methods
    @property
    def resource(self) -> simpy.Resource:
        """Get underlying resource (for backwards compatibility)."""
        return self._resource

    def store(self, pallet: Pallet, inbound_pos=None, storage_pos=None):
        """
        Store operation: move forklift from inbound to storage.
        If inbound_pos and storage_pos are provided, actually move the forklift.
        Otherwise, fall back to legacy timing-based simulation.
        """
        with self._resource.request() as req:
            yield req

            # If we have an available forklift, use it for actual movement
            fl = self.get_available_forklift() if self.forklifts else None
            if fl and inbound_pos and storage_pos:
                # Actual movement-based store
                yield from fl.move_to(inbound_pos, update_interval=0.1)
                yield from fl.load(pallet)
                yield from fl.move_to(storage_pos, update_interval=0.1)
                yield from fl.unload()
                # Return to home if we have home position
                if hasattr(self, 'home_position') and self.home_position:
                    yield from fl.move_to(self.home_position, update_interval=0.1)
            else:
                # Fallback: legacy timing-based
                travel = self.store_travel_time_s if self.store_travel_time_s else (
                    self.travel_time_fn(
                        "store", pallet) if self.travel_time_fn else 0.0
                )
                yield self.env.timeout(travel + self.store_time_s)

    def retrieve(self, pallet: Pallet, storage_pos=None, outbound_pos=None):
        """
        Retrieve operation: move forklift from storage to outbound.
        If storage_pos and outbound_pos are provided, actually move the forklift.
        Otherwise, fall back to legacy timing-based simulation.
        """
        with self._resource.request() as req:
            yield req

            # If we have an available forklift, use it for actual movement
            fl = self.get_available_forklift() if self.forklifts else None
            if fl and storage_pos and outbound_pos:
                # Actual movement-based retrieve
                yield from fl.move_to(storage_pos, update_interval=0.1)
                yield from fl.load(pallet)
                yield from fl.move_to(outbound_pos, update_interval=0.1)
                yield from fl.unload()
                # Return to home if we have home position
                if hasattr(self, 'home_position') and self.home_position:
                    yield from fl.move_to(self.home_position, update_interval=0.1)
            else:
                # Fallback: legacy timing-based
                travel = self.retrieve_travel_time_s if self.retrieve_travel_time_s else (
                    self.travel_time_fn(
                        "retrieve", pallet) if self.travel_time_fn else 0.0
                )
                yield self.env.timeout(travel + self.retrieve_time_s)


def create_forklift_fleet(
    env: simpy.Environment,
    count: int,
    movement_profile: MovementProfile,
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
            position=home_position,
            router=router
        )
        fleet.add_forklift(fl)

    return fleet
