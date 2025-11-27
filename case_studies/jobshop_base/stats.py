from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class JobShopBaseStats:
    """Common job shop statistics."""

    completed_parts: int = 0
    generated_parts: int = 0
    trucks_received: int = 0
    pallets_created: int = 0
    completed_pallets: int = 0
    pallets_shipped: int = 0
    forklift_tasks_completed: int = 0
    forklift_distance_m: float = 0.0
    forklift_travel_time_s: float = 0.0
    shipping_trucks_arrived: int = 0
    shipping_trucks_departed_full: int = 0
    shipping_trucks_departed_partial: int = 0
    sojourn_times: List[float] = field(default_factory=list)
    pallet_wait_times: List[float] = field(default_factory=list)
    time_unloading_raw_s: float = 0.0
    time_raw_storage_s: float = 0.0
    time_moving_raw_to_cnc_s: float = 0.0
    time_processing_and_palletizing_s: float = 0.0
    time_moving_finished_to_storage_s: float = 0.0
    time_finished_storage_s: float = 0.0
    time_shipping_finished_s: float = 0.0

    @property
    def avg_time_in_system(self) -> float:
        return sum(self.sojourn_times) / len(self.sojourn_times) if self.sojourn_times else 0.0

    @property
    def avg_pallet_wait(self) -> float:
        if not self.pallet_wait_times:
            return 0.0
        return sum(self.pallet_wait_times) / len(self.pallet_wait_times)

    def throughput_per_hour(self, sim_time: float) -> float:
        hours = sim_time / 3600.0
        return self.completed_parts / hours if hours > 0.0 else 0.0

    # Category helpers -------------------------------------------------
    def add_time(self, field_name: str, seconds: float, parts: int = 1) -> None:
        """Accumulate time for the given category across multiple parts."""
        if seconds <= 0.0 or parts <= 0:
            return
        current = getattr(self, field_name, 0.0)
        setattr(self, field_name, current + seconds * parts)

    @property
    def total_part_time_s(self) -> float:
        return (
            self.time_unloading_raw_s
            + self.time_raw_storage_s
            + self.time_moving_raw_to_cnc_s
            + self.time_processing_and_palletizing_s
            + self.time_moving_finished_to_storage_s
            + self.time_finished_storage_s
            + self.time_shipping_finished_s
        )

    def category_breakdown(self) -> List[tuple[str, float, float]]:
        """Returns (label, avg_minutes_per_part, percent_of_total) tuples."""
        totals = [
            ("Unloading raw material", self.time_unloading_raw_s),
            ("Raw material in storage", self.time_raw_storage_s),
            ("Moving raw material to CNC Machine", self.time_moving_raw_to_cnc_s),
            ("Processing and palletizing", self.time_processing_and_palletizing_s),
            ("Moving finished part to storage",
             self.time_moving_finished_to_storage_s),
            ("Finished part in storage", self.time_finished_storage_s),
            ("Shipping finished part", self.time_shipping_finished_s),
        ]
        total_time = self.total_part_time_s
        parts = max(1, self.completed_parts)
        breakdown = []
        for label, seconds in totals:
            avg_per_part_min = (
                seconds / parts / 60.0) if self.completed_parts else 0.0
            pct = (seconds / total_time * 100.0) if total_time > 0 else 0.0
            breakdown.append((label, avg_per_part_min, pct))
        return breakdown
