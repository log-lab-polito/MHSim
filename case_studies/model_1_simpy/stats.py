from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from mhsim.stats import SimulationStats


FORKLIFT_MOVEMENT_BENCHMARK_LABELS: dict[str, str] = {
    "store_seize_to_load_start_s": "Store: seize -> load start",
    "store_load_duration_s": "Store: load start -> load finish",
    "store_unload_finish_to_release_s": "Store: unload finish -> release",
    "retrieve_seize_to_load_start_s": "Retrieve: seize -> load start",
    "retrieve_load_duration_s": "Retrieve: load start -> load finish",
    "retrieve_unload_finish_to_release_s": "Retrieve: unload finish -> release",
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
