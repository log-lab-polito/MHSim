"""Factory and initialization utilities for SimPy Model 2."""

from __future__ import annotations

import simpy

from mhsim.forklift import ForkliftFleet, LiftProfile, create_forklift_fleet
from mhsim.movement import (
    HorizontalMovement,
    MovementProfile,
    Position3D,
    VerticalMovement,
)
from mhsim.routing import NodeJunction, Router
from mhsim.spatial import Path, PointNode, RectangularNode, Storage, WarehouseLayout

from .params import Model2Params


def create_model2_warehouse(
    env: simpy.Environment,
    params: Model2Params,
    *,
    stats: object | None = None,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """Create the simplified Model 2 warehouse and transporter fleet."""
    receiving_area = PointNode("receiving_area", Position3D(16, 40.5, 0))
    outbound_area = PointNode("outbound_area", Position3D(43, 40.5, 0))
    home_area = RectangularNode(
        "home_location_forklifts", Position3D(23, 26, 0), 12.0, 4.0, 2.5
    )
    storage_rack = PointNode("storage_rack", Position3D(29, 40.5, 0))
    # AnyLogic Model 2 defines the path graph with explicit intermediate nodes.
    # Keep the same fixed positions here instead of tuning geometry to match
    # benchmark outputs.
    top_left = PointNode("node1", Position3D(23, 35.5, 0))
    top_mid = PointNode("node4", Position3D(29, 35.5, 0))
    top_right = PointNode("node", Position3D(35, 35.5, 0))
    left_mid = PointNode("node5", Position3D(23, 40.5, 0))
    right_mid = PointNode("node6", Position3D(35, 40.5, 0))
    home_exit = PointNode("home_exit", Position3D(29, 30, 0))

    # AnyLogic's route finder never uses the bottom loop (path1, path7, path9):
    # neither the Model 2 nor the Model 5 probe traverses it in 18 000 s, although
    # it looks shorter between receiving and the rack, so it is left out (ledger H7).
    paths = [
        Path(
            "home_area",
            [
                Position3D(29, 28, 0),
                home_exit.get_access_point(),
            ],
        ),
        Path(
            "path",
            [
                top_right.get_access_point(),
                top_mid.get_access_point(),
            ],
        ),
        Path(
            "path5",
            [
                top_mid.get_access_point(),
                top_left.get_access_point(),
            ],
        ),
        Path(
            "path2",
            [
                top_right.get_access_point(),
                right_mid.get_access_point(),
            ],
        ),
        Path(
            "path3",
            [
                top_left.get_access_point(),
                left_mid.get_access_point(),
            ],
        ),
        Path(
            "path6",
            [
                left_mid.get_access_point(),
                receiving_area.get_access_point(),
            ],
        ),
        Path(
            "path8",
            [
                right_mid.get_access_point(),
                outbound_area.get_access_point(),
            ],
        ),
        Path(
            "path11",
            [
                storage_rack.get_access_point(),
                right_mid.get_access_point(),
            ],
        ),
        Path(
            "path4",
            [
                home_exit.get_access_point(),
                top_mid.get_access_point(),
            ],
        ),
    ]

    layout = WarehouseLayout(
        inbound_area=receiving_area,
        outbound_area=outbound_area,
        forklifts_home=home_area,
        storage=Storage(),
        paths=paths,
    )
    layout.receiving_area = receiving_area
    layout.storage_rack = storage_rack
    layout.extra_nodes = [
        storage_rack,
        top_left,
        top_mid,
        top_right,
        left_mid,
        right_mid,
        home_exit,
    ]

    movement_profile = MovementProfile(
        horizontal=HorizontalMovement(
            max_speed=params.forklift_max_speed,
            acceleration=params.forklift_acceleration,
            deceleration=params.forklift_deceleration,
        ),
        elevation=VerticalMovement(speed=params.forklift_elevation_speed),
    )
    lift_profile = LiftProfile(
        shelf_height=params.shelf_height,
        elevation_speed=params.forklift_elevation_speed,
        lowering_speed=params.forklift_lowering_speed,
    )

    # AnyLogic point nodes (docs/forklift_rules/R6): node4, node5 and node6 have a 10 px
    # radius with every path ending on the boundary (1 m arcs); node and node1 have zero
    # radius (sharp turns). The home-area crossing lies inside the home node (R3).
    router = Router(
        layout,
        junctions={
            (29.0, 35.5): NodeJunction(path_end_offset_m=1.0),
            (23.0, 40.5): NodeJunction(path_end_offset_m=1.0),
            (35.0, 40.5): NodeJunction(path_end_offset_m=1.0),
            (35.0, 35.5): NodeJunction(path_end_offset_m=0.0),
            (23.0, 35.5): NodeJunction(path_end_offset_m=0.0),
            (29.0, 30.0): NodeJunction(path_end_offset_m=0.0),
        },
        node_crossing_paths={"home_area"},
    )
    fleet = create_forklift_fleet(
        env=env,
        count=params.n_forklifts,
        movement_profile=movement_profile,
        lift_profile=lift_profile,
        router=router,
        # Model the transporter home location as the area center; routing to the
        # network starts from the explicit home-exit connector above.
        home_position=home_area.get_access_point(),
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
