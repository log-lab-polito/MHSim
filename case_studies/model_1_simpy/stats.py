from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from mhsim.stats import SimulationStats


# Keep the original six benchmark keys first because the Model 2 comparison
# workflow still maps AnyLogic's legacy text export onto them.
FORKLIFT_MOVEMENT_BENCHMARK_LABELS: dict[str, str] = {
    "store_seize_to_load_start_s": "Store legacy: seize -> load start",
    "store_load_duration_s": "Store legacy: load start -> load finish",
    "store_unload_finish_to_release_s": "Store legacy: load finish -> release",
    "retrieve_seize_to_load_start_s": "Retrieve legacy: seize -> unload start",
    "retrieve_load_duration_s": "Retrieve legacy: unload start -> unload finish",
    "retrieve_unload_finish_to_release_s": "Retrieve legacy: unload finish -> release",
    "store_enter_to_seize_s": "Store: enter -> seize",
    "store_seize_to_loading_start_s": "Store: seize -> loading start",
    "store_loading_duration_s": "Store: loading start -> loading finish",
    "store_loading_finish_to_unloading_start_s": (
        "Store: loading finish -> unloading start"
    ),
    "store_unloading_duration_s": (
        "Store: unloading start -> unloading finish"
    ),
    "store_unloading_finish_to_release_s": (
        "Store: unloading finish -> release"
    ),
    "retrieve_enter_to_seize_s": "Retrieve: enter -> seize",
    "retrieve_seize_to_loading_start_s": (
        "Retrieve: seize -> loading start"
    ),
    "retrieve_loading_duration_s": (
        "Retrieve: loading start -> loading finish"
    ),
    "retrieve_loading_finish_to_unloading_start_s": (
        "Retrieve: loading finish -> unloading start"
    ),
    "retrieve_unloading_duration_s": (
        "Retrieve: unloading start -> unloading finish"
    ),
    "retrieve_unloading_finish_to_release_s": (
        "Retrieve: unloading finish -> release"
    ),
}
FORKLIFT_MOVEMENT_RENAMED_METRIC_KEYS: dict[str, str] = {
    "store_exact_enter_to_seize_s": "store_enter_to_seize_s",
    "store_exact_seize_to_loading_start_s": "store_seize_to_loading_start_s",
    "store_exact_loading_duration_s": "store_loading_duration_s",
    "store_exact_loading_finish_to_unloading_start_s": (
        "store_loading_finish_to_unloading_start_s"
    ),
    "store_exact_unloading_duration_s": "store_unloading_duration_s",
    "store_exact_unloading_finish_to_release_s": (
        "store_unloading_finish_to_release_s"
    ),
    "retrieve_exact_enter_to_seize_s": "retrieve_enter_to_seize_s",
    "retrieve_exact_seize_to_loading_start_s": (
        "retrieve_seize_to_loading_start_s"
    ),
    "retrieve_exact_loading_duration_s": "retrieve_loading_duration_s",
    "retrieve_exact_loading_finish_to_unloading_start_s": (
        "retrieve_loading_finish_to_unloading_start_s"
    ),
    "retrieve_exact_unloading_duration_s": "retrieve_unloading_duration_s",
    "retrieve_exact_unloading_finish_to_release_s": (
        "retrieve_unloading_finish_to_release_s"
    ),
}
PHASE_FORKLIFT_MOVEMENT_BENCHMARK_LABELS: dict[str, str] = {
    metric_key: label
    for metric_key, label in FORKLIFT_MOVEMENT_BENCHMARK_LABELS.items()
    if label.startswith(("Store:", "Retrieve:"))
}
FORKLIFT_MOVEMENT_BENCHMARK_ORDER = tuple(FORKLIFT_MOVEMENT_BENCHMARK_LABELS)


@dataclass(frozen=True)
class DurationBenchmarkSummary:
    count: int
    average: float
    minimum: float
    maximum: float
    std_dev: float


def _summarize_samples(samples: list[float]) -> DurationBenchmarkSummary | None:
    if not samples:
        return None
    return DurationBenchmarkSummary(
        count=len(samples),
        average=statistics.fmean(samples),
        minimum=min(samples),
        maximum=max(samples),
        std_dev=statistics.pstdev(samples),
    )


@dataclass
class Model1Stats(SimulationStats):
    forklift_movement_samples: dict[str, list[float]] = field(
        default_factory=lambda: {
            metric_name: [] for metric_name in FORKLIFT_MOVEMENT_BENCHMARK_ORDER
        }
    )

    def record_forklift_movement(self, metric_name: str, duration: float) -> None:
        self.forklift_movement_samples.setdefault(metric_name, []).append(duration)

    def forklift_movement_summaries(self) -> dict[str, DurationBenchmarkSummary]:
        summaries: dict[str, DurationBenchmarkSummary] = {}
        seen: set[str] = set()

        for metric_name in FORKLIFT_MOVEMENT_BENCHMARK_ORDER:
            seen.add(metric_name)
            summary = _summarize_samples(
                self.forklift_movement_samples.get(metric_name, [])
            )
            if summary is not None:
                summaries[metric_name] = summary

        for metric_name, samples in self.forklift_movement_samples.items():
            if metric_name in seen:
                continue
            summary = _summarize_samples(samples)
            if summary is not None:
                summaries[metric_name] = summary

        return summaries
