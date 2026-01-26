"""
Factory and initialization utilities for 3D warehouse simulation.

Provides helper functions to easily set up the complete warehouse system with
all spatial elements, movement profiles, and forklift fleets.
"""

from __future__ import annotations

import simpy
from typing import Optional

from .movement import (
    Position3D,
    MovementProfile,
    HorizontalMovement,
    VerticalMovement,
)
from .spatial import (
    PointNode,
    RectangularNode,
    Shelf,
    Storage,
    Path,
    WarehouseLayout,
    Node,
)
from .forklift import ForkliftFleet, LiftProfile, create_forklift_fleet
from .routing import Router
from .params import Model1Params


class WarehouseBuilder:
    """Builder class for creating warehouse layouts with convenience methods."""

    def __init__(self):
        self.inbound: Optional[Node] = None
        self.outbound: Optional[Node] = None
        self.home: Optional[RectangularNode] = None
        self.storage = Storage()
        self.paths: list[Path] = []

    def set_inbound_area(
        self,
        position: Position3D,
        width: float = 20.0,
        depth: float = 10.0,
        height: float = 2.5,
    ) -> WarehouseBuilder:
        """Configure the inbound receiving area."""
        self.inbound = RectangularNode(
            "inbound", position, width, depth, height)
        return self

    def set_inbound_area_point(
        self,
        position: Position3D,
    ) -> WarehouseBuilder:
        """Configure the inbound receiving area as a point node."""
        self.inbound = PointNode("inbound", position)
        return self

    def set_outbound_area(
        self,
        position: Position3D,
        width: float = 20.0,
        depth: float = 10.0,
        height: float = 2.5,
    ) -> WarehouseBuilder:
        """Configure the outbound shipping area."""
        self.outbound = RectangularNode(
            "outbound", position, width, depth, height)
        return self

    def set_outbound_area_point(
        self,
        position: Position3D,
    ) -> WarehouseBuilder:
        """Configure the outbound shipping area as a point node."""
        self.outbound = PointNode("outbound", position)
        return self

    def set_forklifts_home(
        self,
        position: Position3D,
        width: float = 10.0,
        depth: float = 10.0,
        height: float = 2.5,
    ) -> WarehouseBuilder:
        """Configure the home/parking area for forklifts."""
        self.home = RectangularNode("home", position, width, depth, height)
        return self

    def add_shelf(
        self,
        shelf_id: str,
        position: Position3D,
        levels: int = 6,
        positions_per_level: int = 10,
        cell_depth: float = 1.0,
        level_height: float = 1.5,
        position_spacing: float = 1.2,
    ) -> WarehouseBuilder:
        """Add a shelf to the storage area."""
        shelf = Shelf(
            id=shelf_id,
            position=position,
            levels=levels,
            positions_per_level=positions_per_level,
            cell_depth=cell_depth,
            level_height=level_height,
            position_spacing=position_spacing,
        )
        self.storage.add_shelf(shelf)
        return self

    def add_path(
        self,
        path_id: str,
        waypoints: list[Position3D] | None = None,
        bidirectional: bool = True,
    ) -> WarehouseBuilder:
        """Add a navigation path between areas."""
        if waypoints is None:
            waypoints = []
        path = Path(id=path_id, waypoints=waypoints,
                    bidirectional=bidirectional)
        self.paths.append(path)
        return self

    def build(self) -> WarehouseLayout:
        """Build the complete warehouse layout."""
        if not self.inbound:
            self.inbound = PointNode(
                "inbound", Position3D(16, 40.5, 0))
        if not self.outbound:
            self.outbound = PointNode(
                "outbound", Position3D(43, 40.5, 0))
        if not self.home:
            self.home = RectangularNode(
                "home", Position3D(5, 5, 0), 1.0, 1.0, 0.25)

        layout = WarehouseLayout(
            inbound_area=self.inbound,
            outbound_area=self.outbound,
            forklifts_home=self.home,
            storage=self.storage,
            paths=self.paths,
        )
        return layout


class MovementProfileBuilder:
    """Builder for forklift movement profiles."""

    def __init__(self):
        self.max_speed = 5.0
        self.acceleration = 2.0
        self.deceleration = 2.0
        self.elevation_speed = 1.0

    def set_max_speed(self, speed_mps: float) -> MovementProfileBuilder:
        """Set maximum horizontal speed."""
        self.max_speed = speed_mps
        return self

    def set_acceleration(self, accel_mps2: float) -> MovementProfileBuilder:
        """Set horizontal acceleration."""
        self.acceleration = accel_mps2
        return self

    def set_deceleration(self, decel_mps2: float) -> MovementProfileBuilder:
        """Set horizontal deceleration."""
        self.deceleration = decel_mps2
        return self

    def set_elevation_speed(self, speed_mps: float) -> MovementProfileBuilder:
        """Set vertical movement speed."""
        self.elevation_speed = speed_mps
        return self

    def from_params(self, params: Model1Params) -> MovementProfileBuilder:
        """Load configuration from Model1Params."""
        self.max_speed = params.forklift_max_speed
        self.acceleration = params.forklift_acceleration
        self.deceleration = params.forklift_deceleration
        self.elevation_speed = params.forklift_elevation_speed
        return self

    def build(self) -> MovementProfile:
        """Build the movement profile."""
        horizontal = HorizontalMovement(
            max_speed=self.max_speed,
            acceleration=self.acceleration,
            deceleration=self.deceleration,
        )
        vertical = VerticalMovement(speed=self.elevation_speed)
        return MovementProfile(
            horizontal=horizontal,
            elevation=vertical,
        )


def create_warehouse_with_standard_config(
    env: simpy.Environment,
    params: Model1Params,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """
    Create a complete warehouse system matching AnyLogic Model 1 exactly.

    This warehouse includes:
    - Receiving area (inbound): Point node at (160, 405)
    - Outbound area: Point node at (430, 405)
    - Forklift home: X=240, Y=260, 100×40 m
    - Storage: 2 racks × 10 bays × 6 shelves (2.4m depth, 1.0m shelf height)
    - 7 navigation nodes and 9 paths for routing

    Args:
        env: SimPy environment
        params: Model1Params with configuration

    Returns:
        Tuple of (WarehouseLayout, Router, ForkliftFleet)
    """
    # Build warehouse layout with coordinates scaled directly in values
    layout = (
        WarehouseBuilder()
        # Main areas - matching AnyLogic positions
        .set_inbound_area_point(Position3D(16, 40.5, 0))
        .set_outbound_area_point(Position3D(43, 40.5, 0))
        .set_forklifts_home(Position3D(24, 26, 0), width=10, depth=4)
        # Storage racks - 2 racks, back-to-back, 10 bays each
        # Rack 1 and Rack 2 positioned at storage center (340, 380)
        .add_shelf(
            "rack_1",
            Position3D(34, 38, 0),
            levels=6,
            positions_per_level=10,
            cell_depth=0.24,  # rack depth scaled
            level_height=0.1,  # shelf height scaled
            position_spacing=0.1,  # bay spacing scaled
        )
        .add_shelf(
            "rack_2",
            Position3D(34, 41, 0),  # Back-to-back placement (offset in Y)
            levels=6,
            positions_per_level=10,
            cell_depth=0.24,
            level_height=0.1,
            position_spacing=0.1,
        )
        # Paths - navigation routes connecting nodes (aligned and connected)
        # Top horizontal: 230 → 290 → 350 @ y=355
        .add_path(
            "path_top",
            [
                Position3D(23, 35.5, 0),
                Position3D(29, 35.5, 0),
                Position3D(35, 35.5, 0),
            ],
        )
        # Bottom horizontal: 230 → 290 → 350 @ y=453
        .add_path(
            "path_bottom",
            [
                Position3D(23, 45.3, 0),
                Position3D(29, 45.3, 0),
                Position3D(35, 45.3, 0),
            ],
        )
        # Left vertical: 355 → 405 → 453 @ x=230
        .add_path(
            "left_vertical",
            [
                Position3D(23, 35.5, 0),
                Position3D(23, 40.5, 0),
                Position3D(23, 45.3, 0),
            ],
        )
        # Right vertical: 355 → 405 → 453 @ x=350
        .add_path(
            "right_vertical",
            [
                Position3D(35, 35.5, 0),
                Position3D(35, 40.5, 0),
                Position3D(35, 45.3, 0),
            ],
        )
        # Center vertical: 355 → 405 → 453 @ x=290
        .add_path(
            "center_vertical",
            [
                Position3D(29, 35.5, 0),
                Position3D(29, 40.5, 0),
                Position3D(29, 45.3, 0),
            ],
        )
        # Connectors: tie areas and shelves to the grid so paths are truly connected
        # Inbound connector: inbound access (160,405) -> left vertical node (230,405)
        .add_path(
            "inbound_connector",
            [
                Position3D(16, 40.5, 0),
                Position3D(23, 40.5, 0),
            ],
        )
        # Outbound connector: right vertical node (350,405) -> outbound access (430,405)
        .add_path(
            "outbound_connector",
            [
                Position3D(35, 40.5, 0),
                Position3D(43, 40.5, 0),
            ],
        )
        # Home connector: home access (290,280) -> center vertical node (290,355)
        .add_path(
            "home_connector",
            [
                Position3D(29, 28, 0),
                Position3D(29, 35.5, 0),
            ],
        )
        # Rack connectors: from shelf access to nearest right vertical nodes
        .add_path(
            "rack1_connector",
            [
                Position3D(34.45, 37.76, 0),  # rack_1 access
                Position3D(35, 37.76, 0),
                Position3D(35, 35.5, 0),
            ],
        )
        .add_path(
            "rack2_connector",
            [
                Position3D(34.45, 40.76, 0),  # rack_2 access
                Position3D(35, 40.76, 0),
                Position3D(35, 40.5, 0),
            ],
        )
        .build()
    )

    # Build movement profile from params
    movement_profile = MovementProfileBuilder().from_params(params).build()
    lift_profile = LiftProfile(
        shelf_height=params.shelf_height,
        elevation_speed=params.forklift_elevation_speed,
        lowering_speed=params.forklift_lowering_speed,
    )

    # Create router
    router = Router(layout)

    # Create forklift fleet
    fleet = create_forklift_fleet(
        env=env,
        count=params.n_forklifts,
        movement_profile=movement_profile,
        lift_profile=lift_profile,
        router=router,
        home_position=layout.forklifts_home.get_access_point(),
        name_prefix="fl",
    )

    return layout, router, fleet


def create_custom_warehouse(
    env: simpy.Environment,
    warehouse_builder: WarehouseBuilder,
    movement_profile: MovementProfile,
    n_forklifts: int,
    lift_profile: Optional[LiftProfile] = None,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """
    Create a warehouse system with custom configuration.

    Args:
        env: SimPy environment
        warehouse_builder: Configured WarehouseBuilder
        movement_profile: Movement profile for forklifts
        n_forklifts: Number of forklifts in the fleet
        lift_profile: Lift profile for shelf operations (optional)

    Returns:
        Tuple of (WarehouseLayout, Router, ForkliftFleet)
    """
    layout = warehouse_builder.build()
    router = Router(layout)

    fleet = create_forklift_fleet(
        env=env,
        count=n_forklifts,
        movement_profile=movement_profile,
        lift_profile=lift_profile,
        router=router,
        home_position=layout.forklifts_home.get_access_point(),
        name_prefix="fl",
    )

    return layout, router, fleet
