"""Model 5 movement benchmark labels and shared benchmark types."""

from __future__ import annotations
from dataclasses import dataclass

from mhsim.stats import FORKLIFT_MOVEMENT_BENCHMARK_LABELS

MODEL5_FORKLIFT_MOVEMENT_BENCHMARK_LABELS = FORKLIFT_MOVEMENT_BENCHMARK_LABELS

ANYLOGIC_BENCHMARK_KEY_MAP: dict[str, str] = {
    "Seize to Loading time (s)": "store_seize_to_load_start_s",
    "Loading time (s)": "store_load_duration_s",
    "Loading to Release time (s)": "store_unload_finish_to_release_s",
    "Seize to Unloading time (s)": "retrieve_seize_to_load_start_s",
    "Unloading time (s)": "retrieve_load_duration_s",
    "Unloading to release time (s)": "retrieve_unload_finish_to_release_s",
    "Store: seize -> loading start": "store_seize_to_loading_start_s",
    "Store: loading start -> loading finish": "store_loading_duration_s",
    "Store: loading finish -> unloading start": (
        "store_loading_finish_to_unloading_start_s"
    ),
    "Store: unloading start -> unloading finish": "store_unloading_duration_s",
    "Store: unloading finish -> release": "store_unloading_finish_to_release_s",
    "Retrieve: seize -> loading start": "retrieve_seize_to_loading_start_s",
    "Retrieve: loading start -> loading finish": "retrieve_loading_duration_s",
    "Retrieve: loading finish -> unloading start": (
        "retrieve_loading_finish_to_unloading_start_s"
    ),
    "Retrieve: unloading start -> unloading finish": "retrieve_unloading_duration_s",
    "Retrieve: unloading finish -> release": "retrieve_unloading_finish_to_release_s",
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
