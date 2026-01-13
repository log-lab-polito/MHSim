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
    RectangularNode,
    Shelf,
    Storage,
    Path,
    WarehouseLayout,
    Node,
)
from .forklift import Forklift, ForkliftFleet, create_forklift_fleet
from .routing import Router
from .params import Model1Params


class WarehouseBuilder:
    """Builder class for creating warehouse layouts with convenience methods."""

    def __init__(self):
        self.inbound: Optional[RectangularNode] = None
        self.outbound: Optional[RectangularNode] = None
        self.home: Optional[RectangularNode] = None
        self.storage = Storage()
        self.paths: list[Path] = []
        # For point/custom nodes
        self.nodes: list[Node] = []

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

    def add_node(
        self,
        node_id: str,
        position: Position3D,
        radius: float = 0.0,
        width: float = 1.0,
        depth: float = 1.0,
        height: float = 0.0,
    ) -> WarehouseBuilder:
        """Add a navigation node (point node or small rectangular area)."""
        node = RectangularNode(node_id, position, width, depth, height)
        self.nodes.append(node)
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
            self.inbound = RectangularNode(
                "inbound", Position3D(0, 0, 0), 20, 10, 2.5)
        if not self.outbound:
            self.outbound = RectangularNode(
                "outbound", Position3D(100, 0, 0), 20, 10, 2.5
            )
        if not self.home:
            self.home = RectangularNode(
                "home", Position3D(50, 50, 0), 10, 10, 2.5)

        layout = WarehouseLayout(
            inbound_area=self.inbound,
            outbound_area=self.outbound,
            forklifts_home=self.home,
            storage=self.storage,
            paths=self.paths,
            other_nodes=self.nodes,
        )
        return layout


class MovementProfileBuilder:
    """Builder for forklift movement profiles."""

    def __init__(self):
        self.max_speed = 5.0
        self.acceleration = 2.0
        self.deceleration = 2.0
        self.elevation_speed = 1.0
        self.loading_time = 10.0
        self.unloading_time = 10.0

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

    def set_loading_time(self, time_s: float) -> MovementProfileBuilder:
        """Set load time."""
        self.loading_time = time_s
        return self

    def set_unloading_time(self, time_s: float) -> MovementProfileBuilder:
        """Set unload time."""
        self.unloading_time = time_s
        return self

    def from_params(self, params: Model1Params) -> MovementProfileBuilder:
        """Load configuration from Model1Params."""
        self.max_speed = params.forklift_max_speed_mps
        self.acceleration = params.forklift_acceleration_mps2
        self.deceleration = params.forklift_deceleration_mps2
        self.elevation_speed = params.forklift_elevation_speed_mps
        self.loading_time = params.forklift_loading_time_s
        self.unloading_time = params.forklift_unloading_time_s
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
            loading_time=self.loading_time,
            unloading_time=self.unloading_time,
        )


def create_warehouse_with_standard_config(
    env: simpy.Environment,
    params: Model1Params,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """
    Create a complete warehouse system matching AnyLogic Model 1 exactly.

    This warehouse includes:
    - Receiving area (inbound): X=80, Y=320, 80×170 m
    - Outbound area: X=430, Y=320, 80×170 m
    - Forklift home: X=240, Y=260, 100×40 m
    - Storage: 2 racks × 10 bays × 6 shelves (2.4m depth, 1.0m shelf height)
    - 7 navigation nodes and 9 paths for routing

    Args:
        env: SimPy environment
        params: Model1Params with configuration

    Returns:
        Tuple of (WarehouseLayout, Router, ForkliftFleet)
    """
    # Build warehouse layout with AnyLogic coordinates
    layout = (
        WarehouseBuilder()
        # Main areas - matching AnyLogic positions
        .set_inbound_area(Position3D(80, 320, 0), width=80, depth=170)
        .set_outbound_area(Position3D(430, 320, 0), width=80, depth=170)
        .set_forklifts_home(Position3D(240, 260, 0), width=100, depth=40)
        # Storage racks - 2 racks, back-to-back, 10 bays each
        # Rack 1 and Rack 2 positioned at storage center (340, 380)
        .add_shelf(
            "rack_1",
            Position3D(340, 380, 0),
            levels=6,
            positions_per_level=10,
            cell_depth=2.4,  # AnyLogic rack depth
            level_height=1.0,  # AnyLogic shelf height
            position_spacing=1.0,  # Standard bay spacing
        )
        .add_shelf(
            "rack_2",
            Position3D(340, 410, 0),  # Back-to-back placement (offset in Y)
            levels=6,
            positions_per_level=10,
            cell_depth=2.4,
            level_height=1.0,
            position_spacing=1.0,
        )
        # Navigation nodes - point nodes for routing
        # Top nodes
        .add_node("node", Position3D(350, 355, 0), radius=0)
        .add_node("node1", Position3D(230, 355, 0), radius=0)
        # Bottom nodes
        .add_node("node2", Position3D(350, 453, 0), radius=0)
        .add_node("node3", Position3D(230, 453, 0), radius=0)
        # Junction nodes with radius=10
        .add_node("node4", Position3D(290, 355, 0), radius=10)
        .add_node("node5", Position3D(230, 405, 0), radius=10)
        .add_node("node6", Position3D(350, 405, 0), radius=10)
        # Paths - navigation routes connecting nodes (aligned and connected)
        # Top horizontal: 230 → 290 → 350 @ y=355
        .add_path(
            "path_top",
            [
                Position3D(230, 355, 0),
                Position3D(290, 355, 0),
                Position3D(350, 355, 0),
            ],
        )
        # Bottom horizontal: 230 → 290 → 350 @ y=453
        .add_path(
            "path_bottom",
            [
                Position3D(230, 453, 0),
                Position3D(290, 453, 0),
                Position3D(350, 453, 0),
            ],
        )
        # Left vertical: 355 → 405 → 453 @ x=230
        .add_path(
            "left_vertical",
            [
                Position3D(230, 355, 0),
                Position3D(230, 405, 0),
                Position3D(230, 453, 0),
            ],
        )
        # Right vertical: 355 → 405 → 453 @ x=350
        .add_path(
            "right_vertical",
            [
                Position3D(350, 355, 0),
                Position3D(350, 405, 0),
                Position3D(350, 453, 0),
            ],
        )
        # Center vertical: 355 → 405 → 453 @ x=290
        .add_path(
            "center_vertical",
            [
                Position3D(290, 355, 0),
                Position3D(290, 405, 0),
                Position3D(290, 453, 0),
            ],
        )
        # Connectors: tie areas and shelves to the grid so paths are truly connected
        # Inbound connector: inbound access (120,405) -> left vertical node (230,405)
        .add_path(
            "inbound_connector",
            [
                Position3D(120, 405, 0),
                Position3D(230, 405, 0),
            ],
        )
        # Outbound connector: right vertical node (350,405) -> outbound access (470,405)
        .add_path(
            "outbound_connector",
            [
                Position3D(350, 405, 0),
                Position3D(470, 405, 0),
            ],
        )
        # Home connector: home access (290,280) -> center vertical node (290,355)
        .add_path(
            "home_connector",
            [
                Position3D(290, 280, 0),
                Position3D(290, 355, 0),
            ],
        )
        # Rack connectors: from shelf access to nearest right vertical nodes
        .add_path(
            "rack1_connector",
            [
                Position3D(344.5, 377.6, 0),  # rack_1 access
                Position3D(350, 377.6, 0),
                Position3D(350, 355, 0),
            ],
        )
        .add_path(
            "rack2_connector",
            [
                Position3D(344.5, 407.6, 0),  # rack_2 access
                Position3D(350, 407.6, 0),
                Position3D(350, 405, 0),
            ],
        )
        .build()
    )

    # Build movement profile from params
    movement_profile = MovementProfileBuilder().from_params(params).build()

    # Create router
    router = Router(layout)

    # Create forklift fleet
    fleet = create_forklift_fleet(
        env=env,
        count=params.n_forklifts,
        movement_profile=movement_profile,
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
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """
    Create a warehouse system with custom configuration.

    Args:
        env: SimPy environment
        warehouse_builder: Configured WarehouseBuilder
        movement_profile: Movement profile for forklifts
        n_forklifts: Number of forklifts in the fleet

    Returns:
        Tuple of (WarehouseLayout, Router, ForkliftFleet)
    """
    layout = warehouse_builder.build()
    router = Router(layout)

    fleet = create_forklift_fleet(
        env=env,
        count=n_forklifts,
        movement_profile=movement_profile,
        router=router,
        home_position=layout.forklifts_home.get_access_point(),
        name_prefix="fl",
    )

    return layout, router, fleet
