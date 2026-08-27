"""Statistics accumulation, traffic-wait rollups, and forklift benchmark summaries."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .traffic import TRAFFIC_WAIT_REASONS


@dataclass(frozen=True)
class TrafficWaitSummary:
    """Aggregated waiting time for one traffic-wait reason.

    Attributes:
        count: Number of separate waits recorded.
        total_s: Total time waited, in seconds.
        average_s: Mean wait in seconds, or `0.0` when `count` is zero.
    """

    count: int
    total_s: float
    average_s: float


@dataclass
class SimulationStats:
    """Run-level counters shared by every model.

    Case studies either use this directly or subclass it, as `Model5Stats`
    does, to add domain-specific samples.

    Attributes:
        created: Entities emitted by the source blocks.
        completed: Entities that reached a sink. Lags `created` by the
            work in progress.
        time_in_system: One cycle time in seconds per completed entity, in
            completion order.
        traffic_wait_time_s: Total seconds waited, keyed by reason. Pre-seeded
            with every reason in `mhsim.traffic.TRAFFIC_WAIT_REASONS`.
        traffic_wait_counts: Number of waits, keyed by the same reasons.
    """

    created: int = 0
    completed: int = 0
    time_in_system: list[float] = field(default_factory=list)
    traffic_wait_time_s: dict[str, float] = field(
        default_factory=lambda: {reason: 0.0 for reason in TRAFFIC_WAIT_REASONS}
    )
    traffic_wait_counts: dict[str, int] = field(
        default_factory=lambda: {reason: 0 for reason in TRAFFIC_WAIT_REASONS}
    )

    def record_created(self, count: int = 1) -> None:
        """Count newly created entities.

        Args:
            count: How many entities were created. Sources that emit in
                batches pass the batch size.
        """
        self.created += count

    def record_completed(self, duration: float) -> None:
        """Record one entity reaching a sink.

        Args:
            duration: Cycle time in seconds, measured from the entity's
                `created_at` to now.
        """
        self.completed += 1
        self.time_in_system.append(duration)

    def record_traffic_wait(self, reason: str, duration_s: float) -> None:
        """Add one traffic wait to the running totals.

        Args:
            reason: Wait reason. Unknown reasons are registered on first use
                rather than rejected, so models may add their own.
            duration_s: Time waited in seconds. Negative values are clamped to
                zero, but still increment the count.
        """
        if reason not in self.traffic_wait_time_s:
            self.traffic_wait_time_s[reason] = 0.0
            self.traffic_wait_counts[reason] = 0
        self.traffic_wait_time_s[reason] += max(0.0, duration_s)
        self.traffic_wait_counts[reason] += 1

    def traffic_wait_summaries(self) -> dict[str, TrafficWaitSummary]:
        """Summarise accumulated traffic waits by reason.

        Returns:
            One `TrafficWaitSummary` per reason that actually saw a wait,
            keyed by reason name in alphabetical order. Reasons with no
            recorded time and no count are omitted, so a model that never
            experiences congestion yields an empty mapping rather than a table
            of zeroes.
        """
        summaries: dict[str, TrafficWaitSummary] = {}
        all_reasons = set(self.traffic_wait_time_s) | set(self.traffic_wait_counts)
        for reason in sorted(all_reasons):
            count = self.traffic_wait_counts.get(reason, 0)
            total_s = self.traffic_wait_time_s.get(reason, 0.0)
            if count <= 0 and total_s <= 0:
                continue
            summaries[reason] = TrafficWaitSummary(
                count=count,
                total_s=total_s,
                average_s=(total_s / count) if count > 0 else 0.0,
            )
        return summaries

    @property
    def avg_time_in_system(self) -> float:
        """Mean cycle time in seconds over completed entities, or `0.0`.

        Entities still in progress at the end of the run do not contribute.
        """
        if not self.time_in_system:
            return 0.0
        return sum(self.time_in_system) / len(self.time_in_system)


# Keep the original six benchmark keys first because the Model 5 comparison
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
PHASE_FORKLIFT_MOVEMENT_BENCHMARK_LABELS: dict[str, str] = {
    metric_key: label
    for metric_key, label in FORKLIFT_MOVEMENT_BENCHMARK_LABELS.items()
    if label.startswith(("Store:", "Retrieve:"))
}
FORKLIFT_MOVEMENT_BENCHMARK_ORDER = tuple(FORKLIFT_MOVEMENT_BENCHMARK_LABELS)


@dataclass(frozen=True)
class DurationBenchmarkSummary:
    """Descriptive statistics for one instrumented movement sub-phase.

    Attributes:
        count: Number of samples.
        average: Arithmetic mean in seconds.
        minimum: Shortest sample in seconds.
        maximum: Longest sample in seconds.
        std_dev: Population standard deviation in seconds, not the sample
            estimate, so a single observation yields `0.0`.
    """

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
class Model5Stats(SimulationStats):
    """Warehouse statistics adding per-phase forklift movement timings.

    Extends `SimulationStats` with the instrumentation behind the Model 5
    forklift benchmark tables.

    Attributes:
        forklift_movement_samples: Durations in seconds keyed by metric name,
            pre-seeded with every key in
            `FORKLIFT_MOVEMENT_BENCHMARK_ORDER`.
    """

    forklift_movement_samples: dict[str, list[float]] = field(
        default_factory=lambda: {
            metric_name: [] for metric_name in FORKLIFT_MOVEMENT_BENCHMARK_ORDER
        }
    )

    def record_forklift_movement(self, metric_name: str, duration: float) -> None:
        """Record one movement sub-phase duration.

        Args:
            metric_name: Benchmark key, normally one of
                `FORKLIFT_MOVEMENT_BENCHMARK_ORDER`. Unknown keys are
                accepted and appear after the known ones in summaries.
            duration: Elapsed time in seconds.
        """
        self.forklift_movement_samples.setdefault(metric_name, []).append(duration)

    def forklift_movement_summaries(self) -> dict[str, DurationBenchmarkSummary]:
        """Summarise every movement sub-phase that collected samples.

        Returns:
            One `DurationBenchmarkSummary` per metric with at least one
            sample. Keys in `FORKLIFT_MOVEMENT_BENCHMARK_ORDER` come first
            in that order, followed by any model-specific keys in insertion
            order; metrics with no samples are omitted entirely.

        Parity:
            The fixed ordering exists so generated benchmark tables line up
            row-for-row with AnyLogic's export without a join.
        """
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
