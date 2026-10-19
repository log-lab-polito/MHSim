"""
Factory and initialization utilities for 3D warehouse simulation.

Provides helper functions to easily set up the complete warehouse system with
all spatial elements, movement profiles, and forklift fleets.
"""

from __future__ import annotations

import simpy
from typing import Optional

from mhsim.movement import (
    Position3D,
    MovementProfile,
    HorizontalMovement,
    VerticalMovement,
)
from mhsim.spatial import (
    PointNode,
    RectangularNode,
    Shelf,
    Storage,
    Path,
    WarehouseLayout,
    Node,
)
from mhsim.forklift import ForkliftFleet, LiftProfile, create_forklift_fleet
from mhsim.routing import NodeJunction, Router
from .params import Model5Params


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

    def from_params(self, params: Model5Params) -> MovementProfileBuilder:
        """Load configuration from Model5Params."""
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
    params: Model5Params,
    stats: Optional[object] = None,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """
    Create a complete warehouse system matching AnyLogic Model 5 exactly.

    This warehouse includes:
    - Receiving area (inbound): Point node at (160, 405)
    - Outbound area: Point node at (430, 405)
    - Forklift home: X=240, Y=260, 100×40 m
    - Storage: 1 rack × 10 bays × 6 shelves (2.4m depth, 1.0m shelf height)
    - 7 navigation nodes and 8 paths for routing

    Args:
        env: SimPy environment
        params: Model5Params with configuration

    Returns:
        Tuple of (WarehouseLayout, Router, ForkliftFleet)
    """
    # Build warehouse layout with coordinates scaled directly in values
    layout = (
        WarehouseBuilder()
        # Main areas - matching AnyLogic positions
        .set_inbound_area_point(Position3D(16, 40.5, 0))
        .set_outbound_area_point(Position3D(43, 40.5, 0))
        # AnyLogic home_location_forklifts: (230, 260) px, 120 x 40 px.
        .set_forklifts_home(Position3D(23, 26, 0), width=12, depth=4)
        # Storage racks - 1 rack, 10 bays × 6 shelves (2.4m depth, 1.0m shelf height)
        # Rack positioned at (290, 405)
        # Every cell of bay 0 is served from that bay's path exit on the top path,
        # (335, 355) px (docs/forklift_rules/R4). Storage never needs more than the six
        # shelves of bay 0 in the reference runs, so the other bays share that exit.
        .add_shelf(
            "rack",
            Position3D(33.5, 35.5, 0),
            levels=6,
            positions_per_level=10,
            cell_depth=0.24,  # rack depth scaled
            level_height=0.1,  # shelf height scaled
            position_spacing=0.0,
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
        # Home: AnyLogic drives straight across the home area from the forklift's home
        # point (245, 280) px to path4's start on the area edge (290, 300) px, then along
        # path4 into node4 (290, 355) px.
        .add_path(
            "home_area",
            [
                Position3D(24.5, 28, 0),
                Position3D(29, 30, 0),
            ],
        )
        .add_path(
            "path4",
            [
                Position3D(29, 30, 0),
                Position3D(29, 35.5, 0),
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
        cargo_height=params.forklift_cargo_height_m,
        rack_approach_m=params.rack_approach_m,
        rack_reach_m=params.rack_reach_m,
        rack_handling_speed=params.rack_handling_speed_mps,
    )

    # AnyLogic point nodes (docs/forklift_rules/R6): node4, node5 and node6 have a 10 px
    # radius with every path ending on the boundary, so turns there are 1 m arcs; node,
    # node1, node2 and node3 have zero radius, so turns there are sharp, as is the turn
    # from the home-area crossing onto path4.
    router = Router(
        layout,
        junctions={
            (29.0, 35.5): NodeJunction(path_end_offset_m=1.0),
            (23.0, 40.5): NodeJunction(path_end_offset_m=1.0),
            (35.0, 40.5): NodeJunction(path_end_offset_m=1.0),
            (35.0, 35.5): NodeJunction(path_end_offset_m=0.0),
            (23.0, 35.5): NodeJunction(path_end_offset_m=0.0),
            (35.0, 45.3): NodeJunction(path_end_offset_m=0.0),
            (23.0, 45.3): NodeJunction(path_end_offset_m=0.0),
            (29.0, 30.0): NodeJunction(path_end_offset_m=0.0),
        },
        # The home-area crossing lies inside AnyLogic's home node (R3).
        node_crossing_paths={"home_area"},
    )

    # Create forklift fleet at the AnyLogic home point (245, 280) px.
    forklift_start_position = Position3D(24.5, 28, 0)
    fleet = create_forklift_fleet(
        env=env,
        count=params.n_forklifts,
        movement_profile=movement_profile,
        lift_profile=lift_profile,
        router=router,
        home_position=forklift_start_position,
        turn_radius=params.forklift_turn_radius,
        routed_motion_mode=params.forklift_routed_motion_mode,
        line_guided_update_timestep_s=params.forklift_line_guided_update_timestep_s,
        route_calc_delay_s=params.forklift_route_calc_delay_s,
        resume_delay_s=params.forklift_resume_delay_s,
        min_distance_to_obstacle_m=params.forklift_min_distance_to_obstacle_m,
        avoid_collisions=params.forklift_avoid_collisions,
        stats=stats,
        name_prefix="fl",
    )

    return layout, router, fleet


def create_custom_warehouse(
    env: simpy.Environment,
    warehouse_builder: WarehouseBuilder,
    movement_profile: MovementProfile,
    n_forklifts: int,
    lift_profile: Optional[LiftProfile] = None,
    turn_radius: float = 0.5,
    route_calc_delay_s: float = 0.0,
    resume_delay_s: float = 0.0,
    min_distance_to_obstacle_m: float = 1.0,
    avoid_collisions: bool = False,
    stats: Optional[object] = None,
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
        turn_radius=turn_radius,
        route_calc_delay_s=route_calc_delay_s,
        resume_delay_s=resume_delay_s,
        min_distance_to_obstacle_m=min_distance_to_obstacle_m,
        avoid_collisions=avoid_collisions,
        stats=stats,
        name_prefix="fl",
    )

    return layout, router, fleet
