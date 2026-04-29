"""Model 1 movement benchmark labels.

Model 1 is a single MoveByTransporter flow. AnyLogic's checked-in reference
exports still print these timings as Store lines, but SimPy records them as
Move metrics to reflect the current model semantics.
"""

MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS: dict[str, str] = {
    "move_enter_to_seize_s": "Move: enter -> seize",
    "move_seize_to_loading_start_s": "Move: seize -> loading start",
    "move_loading_duration_s": "Move: loading start -> loading finish",
    "move_loading_finish_to_unloading_start_s": (
        "Move: loading finish -> unloading start"
    ),
    "move_unloading_duration_s": "Move: unloading start -> unloading finish",
    "move_unloading_finish_to_release_s": "Move: unloading finish -> release",
}

ANYLOGIC_BENCHMARK_KEY_MAP: dict[str, str] = {
    "Move: seize -> loading start": "move_seize_to_loading_start_s",
    "Move: loading start -> loading finish": "move_loading_duration_s",
    "Move: loading finish -> unloading start": (
        "move_loading_finish_to_unloading_start_s"
    ),
    "Move: unloading start -> unloading finish": "move_unloading_duration_s",
    "Move: unloading finish -> release": "move_unloading_finish_to_release_s",
}
