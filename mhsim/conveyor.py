from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Generator

import simpy


@dataclass
class Conveyor:
    """Simple conveyor model with occupancy and entry headway constraints."""

    id: str
    env: simpy.Environment
    length_m: float
    speed_mps: float
    max_items: Optional[int] = None
    item_length_m: float = 1.0
    min_gap_m: float = 0.0
    entry_poll_interval_s: float = 0.05

    def __post_init__(self) -> None:
        if self.length_m < 0:
            raise ValueError("length_m must be >= 0")
        if self.speed_mps <= 0:
            raise ValueError("speed_mps must be > 0")
        if self.max_items is not None and self.max_items <= 0:
            raise ValueError("max_items must be > 0 when specified")
        self._entry_mutex = simpy.Resource(self.env, capacity=1)
        self._next_entry_time = 0.0
        self._occupancy = 0
        self.total_entered = 0
        self.total_exited = 0

    @property
    def occupancy(self) -> int:
        return self._occupancy

    def entry_headway_time_s(self) -> float:
        footprint = max(0.0, self.item_length_m + self.min_gap_m)
        return footprint / self.speed_mps if footprint > 0 else 0.0

    def travel_time_s(self, distance_m: Optional[float] = None) -> float:
        distance = self.length_m if distance_m is None else distance_m
        if distance < 0:
            raise ValueError("distance_m must be >= 0")
        return distance / self.speed_mps

    def _has_capacity(self) -> bool:
        return self.max_items is None or self._occupancy < self.max_items

    def enter(self) -> Generator:
        while not self._has_capacity():
            yield self.env.timeout(self.entry_poll_interval_s)

        with self._entry_mutex.request() as req:
            yield req
            while not self._has_capacity():
                yield self.env.timeout(self.entry_poll_interval_s)

            wait_time = max(0.0, self._next_entry_time - self.env.now)
            if wait_time > 0:
                yield self.env.timeout(wait_time)

            self._occupancy += 1
            self.total_entered += 1
            self._next_entry_time = max(self._next_entry_time, self.env.now) + self.entry_headway_time_s()

    def leave(self) -> None:
        if self._occupancy <= 0:
            raise RuntimeError(f"Conveyor {self.id} leave() called with empty occupancy")
        self._occupancy -= 1
        self.total_exited += 1


@dataclass
class ConveyorSpur:
    """Transfer point that moves items from one conveyor onto another."""

    id: str
    env: simpy.Environment
    source_conveyor: Conveyor
    target_conveyor: Conveyor
    target_offset_m: float = 0.0

    def __post_init__(self) -> None:
        if self.source_conveyor is self.target_conveyor:
            raise ValueError("source_conveyor and target_conveyor must be different")
        if self.target_offset_m < 0:
            raise ValueError("target_offset_m must be >= 0")
        if self.target_offset_m > self.target_conveyor.length_m:
            raise ValueError("target_offset_m must be within the target conveyor length")
        self._transfer_mutex = simpy.Resource(self.env, capacity=1)
        self.total_transferred = 0

    def remaining_target_distance_m(self) -> float:
        return self.target_conveyor.length_m - self.target_offset_m

    def transfer(self) -> Generator:
        with self._transfer_mutex.request() as req:
            yield req
            yield from self.target_conveyor.enter()
            self.source_conveyor.leave()
            self.total_transferred += 1
