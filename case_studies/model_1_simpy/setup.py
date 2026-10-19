"""Factory and initialization utilities for SimPy Model 1."""

from __future__ import annotations

import simpy

from mhsim.forklift import ForkliftFleet, create_forklift_fleet
from mhsim.movement import (
    HorizontalMovement,
    MovementProfile,
    Position3D,
    VerticalMovement,
)
from mhsim.routing import NodeJunction, Router
from mhsim.spatial import Path, PointNode, RectangularNode, Storage, WarehouseLayout

from .params import Model1Params


def create_model1_warehouse(
    env: simpy.Environment,
    params: Model1Params,
    *,
    stats: object | None = None,
) -> tuple[WarehouseLayout, Router, ForkliftFleet]:
    """Create the new single-move AnyLogic Model 1 transporter layout.

    The AnyLogic source has only three material-handling markup nodes in the
    active path network: a forklift home area, a central point node, and the
    A/B points. Coordinates mirror AnyLogic Model 1 presentation
    coordinates divided by 10. AnyLogic's before-run code moves A and B to
    ``600 +/- 5 * displacement_m``; after the same scale conversion,
    that is ``60 +/- 0.5 * displacement_m`` in SimPy.
    """
    if params.apply_displacement_geometry:
        a_x = 60.0 - 0.5 * params.displacement_m
        b_x = 60.0 + 0.5 * params.displacement_m
    else:
        # The AnyLogic Parameter Variation experiment prints displacement
        # values but does not run the Simulation experiment's before-run code
        # that repositions A and B. Keep the original markup geometry for
        # range validation instead of applying the displacement parameter.
        a_x = 50.0
        b_x = 70.0

    home_area = RectangularNode(
        "home_location_forklifts", Position3D(55.0, 30.0, 0), 10.0, 4.0, 0.0
    )
    node_a = PointNode("A", Position3D(a_x, 40.0, 0.0))
    node_b = PointNode("B", Position3D(b_x, 40.0, 0.0))
    node_c = PointNode("C", Position3D(60.0, 40.0, 0.0))

    paths = [
        Path(
            "path",
            [
                home_area.get_access_point(),
                node_c.get_access_point(),
            ],
        ),
        Path(
            "AC",
            [
                node_a.get_access_point(),
                node_c.get_access_point(),
            ],
        ),
        Path(
            "CB",
            [
                node_c.get_access_point(),
                node_b.get_access_point(),
            ],
        ),
    ]

    layout = WarehouseLayout(
        inbound_area=node_a,
        outbound_area=node_b,
        forklifts_home=home_area,
        storage=Storage(),
        paths=paths,
    )
    layout.A = node_a
    layout.B = node_b
    layout.C = node_c
    layout.extra_nodes = [node_c]

    movement_profile = MovementProfile(
        horizontal=HorizontalMovement(
            max_speed=params.forklift_max_speed,
            acceleration=params.forklift_acceleration,
            # AnyLogic Model 1 binds deceleration to forklift_acceleration_ms2.
            deceleration=(
                params.forklift_deceleration
                if params.forklift_deceleration is not None
                else params.forklift_acceleration
            ),
        ),
        # Model 1 has no separate fork elevation/lowering parameter in the ALP.
        # Targets are ground-level, so this fallback is not part of parity timing.
        elevation=VerticalMovement(speed=1.0),
    )

    # AnyLogic's node C has a 10 px radius: paths `path` and `AC` end on its boundary,
    # 1 m from the centre, while `CB` starts at the centre itself. The router follows
    # AnyLogic's in-node connector for that geometry (docs/forklift_rules/R6).
    router = Router(
        layout,
        junctions={
            (node_c.position.x, node_c.position.y): NodeJunction(
                path_end_offset_m=1.0,
                centre_attached=((node_b.position.x, node_b.position.y),),
            )
        },
    )
    fleet = create_forklift_fleet(
        env=env,
        count=params.n_forklifts,
        movement_profile=movement_profile,
        lift_profile=None,
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
