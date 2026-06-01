from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Generator

import simpy


@dataclass
class Conveyor:
    """Simple conveyor model with occupancy and entry headway constraints."""
	# TODO rename variables removing the unit specs. Instead, specify the unit in a comment (like we did eg. in HorizontalMovement definition).
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
        with self._entry_mutex.request() as req:
            yield req
            while not self._has_capacity():
                yield self.env.timeout(self.entry_poll_interval_s)

            wait_time = max(0.0, self._next_entry_time - self.env.now)
            if wait_time > 0:
                yield self.env.timeout(wait_time)

            self._occupancy += 1
            self.total_entered += 1
            self._next_entry_time = (
                max(self._next_entry_time, self.env.now)
                + self.entry_headway_time_s()
            )

    def leave(self) -> None:
        if self._occupancy <= 0:
            raise RuntimeError(f"Conveyor {self.id} leave() called with empty occupancy")
        self._occupancy -= 1
        self.total_exited += 1

    def occupy_without_entry_headway(self) -> Generator:
        """Occupy this conveyor from an interior transfer point."""
        while not self._has_capacity():
            yield self.env.timeout(self.entry_poll_interval_s)
        self._occupancy += 1
        self.total_entered += 1


@dataclass
class ConveyorSpur:
    """Transfer point that moves items from one conveyor onto another."""
	# TODO rename variables removing the unit specs. Instead, specify the unit in a comment (like we did eg. in HorizontalMovement definition).
    # TODO double check if this ConveyorSpur implementation is correctly mirroing the Anylogic ConveyorSpur entity.
    id: str
    env: simpy.Environment
    source_conveyor: Conveyor
    target_conveyor: Conveyor
    target_offset_m: float = 0.0
    merge_clearance_distance_m: Optional[float] = None
    source_before_target_clearance_distance_m: Optional[float] = None
    source_after_target_clearance_distance_m: Optional[float] = None
    source_merge_queue_capacity: Optional[int] = None
    source_merge_queue_handoff_delay_s: float = 0.0

    def __post_init__(self) -> None:
        if self.source_conveyor is self.target_conveyor:
            raise ValueError("source_conveyor and target_conveyor must be different")
        if self.target_offset_m < 0:
            raise ValueError("target_offset_m must be >= 0")
        if self.target_offset_m > self.target_conveyor.length_m:
            raise ValueError("target_offset_m must be within the target conveyor length")
        if (
            self.source_merge_queue_capacity is not None
            and self.source_merge_queue_capacity <= 0
        ):
            raise ValueError("source_merge_queue_capacity must be > 0 when specified")
        self._merge_mutex = simpy.Resource(self.env, capacity=1)
        self._source_merge_queue = (
            simpy.Resource(self.env, capacity=self.source_merge_queue_capacity)
            if self.source_merge_queue_capacity is not None
            else None
        )
        self._next_merge_time = 0.0
        self._last_merge_time = 0.0
        self._last_merge_path: Optional[str] = None
        self._target_merge_arrivals: list[float] = []
        self.total_transferred = 0

    def remaining_target_distance_m(self) -> float:
        return self.target_conveyor.length_m - self.target_offset_m

    def merge_headway_time_s(self) -> float:
        if self.merge_clearance_distance_m is None:
            clearance = (
                self.target_conveyor.item_length_m
                + self.target_conveyor.min_gap_m
            )
        else:
            clearance = self.merge_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def source_after_target_headway_time_s(self) -> float:
        if self.source_after_target_clearance_distance_m is None:
            return self.merge_headway_time_s()
        clearance = self.source_after_target_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def source_before_target_headway_time_s(self) -> float:
        if self.source_before_target_clearance_distance_m is None:
            return 0.0
        clearance = self.source_before_target_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def register_target_merge_arrival(self, time_s: float) -> None:
        self._target_merge_arrivals.append(time_s)
        self._target_merge_arrivals.sort()

    def _discard_target_merge_arrivals_before(self, time_s: float) -> None:
        tolerance_s = 1e-9
        while (
            self._target_merge_arrivals
            and self._target_merge_arrivals[0] < time_s - tolerance_s
        ):
            self._target_merge_arrivals.pop(0)

    def _consume_target_merge_arrival(self, time_s: float) -> None:
        tolerance_s = 1e-6
        for index, arrival_time in enumerate(self._target_merge_arrivals):
            if abs(arrival_time - time_s) <= tolerance_s:
                self._target_merge_arrivals.pop(index)
                return
            if arrival_time > time_s + tolerance_s:
                return

    def _wait_for_target_approach_clearance(self) -> Generator:
        lookahead_s = self.source_before_target_headway_time_s()
        if lookahead_s <= 0:
            return

        while True:
            self._discard_target_merge_arrivals_before(self.env.now)
            if not self._target_merge_arrivals:
                return
            next_target_arrival_s = self._target_merge_arrivals[0]
            wait_time_s = next_target_arrival_s - self.env.now
            if wait_time_s > lookahead_s:
                return
            yield self.env.timeout(max(0.0, wait_time_s) + 1e-10)

    def reserve_merge_window(
        self,
        *,
        full_headway_on_conflict: bool = False,
        merge_path: str = "target",
    ) -> Generator:
        """Reserve the shared target-conveyor merge point.

        The default behavior consumes only the remaining tail of the current
        headway window. Some exploratory traces need a full fresh wait on
        conflict, so that mode is available explicitly.
        """
        if merge_path == "source":
            yield from self._wait_for_target_approach_clearance()
        else:
            self._consume_target_merge_arrival(self.env.now)

        with self._merge_mutex.request() as req:
            yield req
            headway_time_s = self.merge_headway_time_s()
            next_merge_time = self._next_merge_time
            if (
                merge_path == "source"
                and self._last_merge_path == "target"
                and self.source_after_target_clearance_distance_m is not None
            ):
                next_merge_time = max(
                    next_merge_time,
                    self._last_merge_time + self.source_after_target_headway_time_s(),
                )
            wait_time = max(0.0, next_merge_time - self.env.now)
            if wait_time > 0:
                if full_headway_on_conflict:
                    yield self.env.timeout(headway_time_s)
                else:
                    yield self.env.timeout(wait_time)
            self._last_merge_time = self.env.now
            self._last_merge_path = merge_path
            self._next_merge_time = (
                max(self._next_merge_time, self.env.now)
                + headway_time_s
            )

    def transfer(self) -> Generator:
        if self._source_merge_queue is None:
            yield from self._transfer_with_reserved_source_slot()
            return

        with self._source_merge_queue.request() as req:
            yield req
            # Let target-conveyor arrivals at the same timestamp join the
            # merge queue before a newly unblocked spur follower does.
            if self.source_merge_queue_handoff_delay_s > 0:
                yield self.env.timeout(self.source_merge_queue_handoff_delay_s)
            yield from self._transfer_with_reserved_source_slot()

    def _transfer_with_reserved_source_slot(self) -> Generator:
        while True:
            while not self.target_conveyor._has_capacity():
                yield self.env.timeout(self.target_conveyor.entry_poll_interval_s)
            yield from self.reserve_merge_window(merge_path="source")
            if self.target_conveyor._has_capacity():
                break
        self.source_conveyor.leave()
        yield from self.target_conveyor.occupy_without_entry_headway()
        self.total_transferred += 1
