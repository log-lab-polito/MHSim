from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Model1Stats:
    created: int = 0
    completed: int = 0
    time_in_system: list[float] = field(default_factory=list)

    def record_created(self, count: int = 1) -> None:
        self.created += count

    def record_completed(self, duration: float) -> None:
        self.completed += 1
        self.time_in_system.append(duration)

    @property
    def avg_time_in_system(self) -> float:
        if not self.time_in_system:
            return 0.0
        return sum(self.time_in_system) / len(self.time_in_system)
