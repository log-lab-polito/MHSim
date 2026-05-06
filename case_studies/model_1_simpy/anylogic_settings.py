"""AnyLogic Model 1 transporter settings mirrored by SimPy Model 1.

The values below are taken from ``anylogic/Model 1/Model 1.alp``. They are
documentation and validation metadata only; the active SimPy parameters remain
defined by ``Model1Params``.
"""

ANYLOGIC_MODEL1_TRANSPORTER_SETTINGS: dict[str, object] = {
    "source": {
        "arrival_type": "manual",
        "cyclic_event_time_s": 0.0,
        "cyclic_event_recurrence": "arrival_rate_s",
        "cyclic_logger_recurrence_s": 0.1,
        "default_arrival_rate_s": 120.0,
    },
    "transporter_fleet": {
        "agent_type": "Forklift",
        "capacity_parameter": "forklift_capacity",
        "home_nodes": ["home_location_forklifts"],
        "maximum_speed_parameter": "forklift_max_speed_ms",
        "acceleration_parameter": "forklift_acceleration_ms2",
        "deceleration_parameter": "forklift_acceleration_ms2",
        "turn_radius": "1.0 m inferred from cyclic trace around node C",
        "route_calculation_delay_s": 0.0,
        "resume_movement_delay_s": 0.0,
        "line_guided_update_timestep_s": 0.5,
    },
    "transporter_control": {
        "automatic_navigation": "AnyLogic default",
        "avoid_collisions": False,
        "collision_detection_timeout_s": 0.0,
    },
    "move_by_transporter": {
        "fleet": "forklifts_fleet",
        "destination_node": "B",
        "loading_time_s": 1.0,
        "unloading_time_s": 1.0,
        "release_policy": "AnyLogic default",
    },
    "path_network": {
        "home_node": "home_location_forklifts",
        "nodes": ["A", "B", "C"],
        "paths": ["path", "AC", "CB"],
        "bidirectional": True,
        "speed_limited": False,
    },
    "experiment": {
        "stop_time_s": 3600.0,
        "seed": 1,
        "simultaneous_events": "LIFO",
        "a_position_code": "600.0 - 5.0 * displacement_m",
        "b_position_code": "600.0 + 5.0 * displacement_m",
        "parameter_variation_geometry": (
            "uses original A/B markup positions because the Simulation "
            "experiment before-run relocation code is not part of the "
            "Parameter Variation experiment"
        ),
    },
    "measured_residuals": {
        "straight_segment_travel": (
            "Straight A->B legs match AnyLogic within ~0.014 s (0.16 %) in all "
            "64 Parameter Variation cases and within ~0.014 s in the "
            "Simulation experiment. SimPy uses the analytical kinematic time "
            "from `HorizontalMovement.travel_time` via the top-up in "
            "`_move_along_route` (see 2026-05-05 entry in docs/decisions.md)."
        ),
        "L_shape_seize_to_loading_start": (
            "home->A (L-shape with smoothed 90 deg turn at C) now matches "
            "AnyLogic's Simulation experiment within ~0.00005 s and all 64 "
            "Parameter Variation cases within ~0.00008 s. The matching "
            "behavior uses a 1.0 m turn radius inferred from the cyclic trace "
            "and AnyLogic's 0.5 s `lineGuidedUpdateTimestep` for cornered "
            "route speed-profile recomputation. Straight A->B legs remain on "
            "the analytical profile."
        ),
        "forklift_utilization": (
            "Simulation experiment utilization now differs by about -0.00118 "
            "units after aligning line-guided profile updates to the global "
            "controller cadence. Parameter Variation still shows a "
            "deterministic utilization residual around -0.00709 units, "
            "isolated to post-unload return-home accounting rather than "
            "MoveByTransporter task timing. The range comparison derives "
            "`implied_return_home_busy_s` to expose that residual directly."
        ),
    },
}


ANYLOGIC_TO_SIMPY_PARAMETER_MAP: dict[str, str] = {
    "arrival_rate_s": "arrival_rate_s",
    "forklift_capacity": "n_forklifts",
    "forklift_max_speed_ms": "forklift_max_speed",
    "forklift_acceleration_ms2": "forklift_acceleration",
    "displacement_m": "displacement_m",
}
