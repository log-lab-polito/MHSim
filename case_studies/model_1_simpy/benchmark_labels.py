"""Model 1 movement benchmark labels and shared benchmark types."""

from __future__ import annotations
from dataclasses import dataclass

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

BENCHMARK_STAT_FIELDS: list[tuple[str, str]] = [
    ("average", "avg"),
    ("minimum", "min"),
    ("maximum", "max"),
    ("std_dev_pop", "std dev (pop)"),
]

BENCHMARK_STAT_NAME_MAP: dict[str, str] = {
    "avg": "average",
    "min": "minimum",
    "max": "maximum",
    "std dev (pop)": "std_dev_pop",
    "std dev (sample)": "std_dev_sample",
}


@dataclass(frozen=True)
class BenchmarkStats:
    average: float
    minimum: float
    maximum: float
    std_dev_pop: float
    std_dev_sample: float | None = None
    count: int | None = None

SUMMARY_METRICS: list[tuple[str, str]] = [
    ("created", "Created"),
    ("completed", "Completed"),
    ("avg_wip", "Avg WIP"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
]

BENCHMARK_METRIC_PREFIX = "benchmark_"

BENCHMARK_STAT_DISPLAY_LABELS: dict[str, str] = {
    "average": "avg",
    "minimum": "min",
    "maximum": "max",
    "std_dev_pop": "std",
}

BENCHMARK_AVG_ONLY = "benchmark_avg_only"
