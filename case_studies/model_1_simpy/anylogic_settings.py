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
        "turn_radius": "AnyLogic default",
        "route_calculation_delay_s": 0.0,
        "resume_movement_delay_s": 0.0,
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
        "forklift_utilization": (
            "With Model 1 task phase timings aligned, SimPy remains about "
            "0.0116 utilization units higher than the AnyLogic timing export. "
            "The residual is isolated to post-unload return-home/utilization "
            "accounting, not MoveByTransporter load/unload task timing."
        ),
        "parameter_variation_range": (
            "The range export uses original A/B geometry, but acceleration=2 "
            "movement windows still differ after geometry alignment. Treat the "
            "range comparison as diagnostic until the routed acceleration "
            "profile is reverse-engineered for that experiment."
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
