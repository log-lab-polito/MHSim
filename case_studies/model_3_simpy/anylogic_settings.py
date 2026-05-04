"""AnyLogic Model 3 conveyor settings mirrored by SimPy Model 3.

The values below are taken from ``anylogic/Model 3/Model 3.alp``. They are
documentation and validation metadata only; the active SimPy parameters remain
defined by ``Model3Params``.
"""

ANYLOGIC_MODEL3_CONVEYOR_SETTINGS: dict[str, object] = {
    "source": {
        "arrival_type": "manual",
        "cyclic_event_time_s": 0.0,
        "cyclic_event_recurrence": "arrival_rate",
        "default_arrival_rate_s": 10.0,
    },
    "service1": {
        "delay_time_s": 10.0,
        "entity_location_queue": "A",
        "entity_location_delay": "A",
    },
    "conveyor": {
        "name": "conveyor",
        "start_node": "A",
        "end_node": "B",
        "start_xy": (160.0, 405.0),
        "end_xy": (430.0, 405.0),
        "length_m": 27.0,
        "speed_mps": 0.8,
        "gap_m": 0.3,
    },
    "service2": {
        "delay_time_s": 8.0,
    },
    "experiment": {
        "stop_time_s": 10800.0,
        "seed": 1,
        "simultaneous_events": "LIFO",
    },
}


ANYLOGIC_TO_SIMPY_PARAMETER_MAP: dict[str, str] = {
    "arrival_rate": "arrival_rate_s",
}
