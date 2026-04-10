from __future__ import annotations

from dataclasses import dataclass, field

from .traffic import TRAFFIC_WAIT_REASONS


@dataclass(frozen=True)
class TrafficWaitSummary:
    count: int
    total_s: float
    average_s: float


@dataclass
class SimulationStats:
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
        self.created += count

    def record_completed(self, duration: float) -> None:
        self.completed += 1
        self.time_in_system.append(duration)

    def record_traffic_wait(self, reason: str, duration_s: float) -> None:
        if reason not in self.traffic_wait_time_s:
            self.traffic_wait_time_s[reason] = 0.0
            self.traffic_wait_counts[reason] = 0
        self.traffic_wait_time_s[reason] += max(0.0, duration_s)
        self.traffic_wait_counts[reason] += 1

    def traffic_wait_summaries(self) -> dict[str, TrafficWaitSummary]:
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
        if not self.time_in_system:
            return 0.0
        return sum(self.time_in_system) / len(self.time_in_system)
