from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Callable, Optional, Generator, Any

import simpy


ANYLOGIC_CONVEYOR_LOCATION_KEY = "_anylogic_conveyor_location"


@dataclass(frozen=True)
class ConveyorLocation:
    """Exact AnyLogic-style location on a conveyor path."""

    conveyor: "Conveyor"
    offset_m: float

    def __post_init__(self) -> None:
        if self.offset_m < 0:
            raise ValueError("offset_m must be >= 0")
        if self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")


@dataclass
class Conveyor:
    """AnyLogic-style conveyor path with occupancy and headway constraints."""

    # Public constructor fields keep unit suffixes because case-study params,
    # range CSVs, and AnyLogic comparison tooling expose those names.
    id: str
    env: simpy.Environment
    length_m: float
    speed_mps: float
    max_items: Optional[int] = None
    item_length_m: float = 1.0
    min_gap_m: float = 0.0
    entry_poll_interval_s: float = 0.05
    points: tuple[tuple[float, float], ...] = ()
    network: Optional["ConveyorNetwork"] = None

    def __post_init__(self) -> None:
        if self.points:
            self.length_m = _polyline_length(self.points)
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
        self._agent_offsets: dict[int, float] = {}

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

    def place_agent(self, agent: Any, offset_m: float) -> ConveyorLocation:
        """Record the logical conveyor location of an agent."""
        location = ConveyorLocation(self, offset_m)
        self._agent_offsets[id(agent)] = location.offset_m
        if hasattr(agent, "attributes"):
            agent.attributes[ANYLOGIC_CONVEYOR_LOCATION_KEY] = location
        return location

    def move_agent_to(self, agent: Any, offset_m: float) -> ConveyorLocation:
        return self.place_agent(agent, offset_m)

    def remove_agent(self, agent: Any) -> None:
        self._agent_offsets.pop(id(agent), None)
        if hasattr(agent, "attributes"):
            agent.attributes.pop(ANYLOGIC_CONVEYOR_LOCATION_KEY, None)

    def agent_offset(self, agent: Any) -> float | None:
        return self._agent_offsets.get(id(agent))


@dataclass
class ConveyorSpur:
    """Transfer point that moves items from one conveyor onto another.

    The clearance and merge-window behavior is calibrated through the active
    AnyLogic-backed Model 4 spur/merge comparison workflow.
    """

    # Public constructor fields keep unit suffixes because case-study params,
    # range CSVs, and AnyLogic comparison tooling expose those names.
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
    offset_m: Optional[float] = None
    on_right_side: bool = True

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
        if self.offset_m is None:
            self.offset_m = self.target_offset_m

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


@dataclass
class PositionOnConveyor:
    """AnyLogic Position on Conveyor markup."""

    id: str
    conveyor: Conveyor
    offset_m: float
    initially_blocked: bool = False
    poll_interval_s: float = 0.05
    on_leading_edge_enter: Optional[Callable[[Any], None]] = None
    on_trailing_edge_exit: Optional[Callable[[Any], None]] = None
    on_cell_enter: Optional[Callable[[Any], None]] = None
    on_cell_exit: Optional[Callable[[Any], None]] = None

    def __post_init__(self) -> None:
        if self.offset_m < 0 or self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")
        self._blocked = bool(self.initially_blocked)
        self._agents: dict[int, Any] = {}

    def block(self) -> None:
        self._blocked = True

    def unblock(self) -> None:
        self._blocked = False

    def is_blocked(self) -> bool:
        return self._blocked

    def wait_until_unblocked(self, env: simpy.Environment) -> Generator:
        while self._blocked:
            yield env.timeout(self.poll_interval_s)

    def leading_edge_enter(self, agent: Any) -> None:
        self._agents[id(agent)] = agent
        if self.on_leading_edge_enter is not None:
            self.on_leading_edge_enter(agent)

    def trailing_edge_exit(self, agent: Any) -> None:
        self._agents.pop(id(agent), None)
        if self.on_trailing_edge_exit is not None:
            self.on_trailing_edge_exit(agent)

    def contains(self, agent: Any) -> bool:
        return id(agent) in self._agents

    def get_agent(self) -> Any | None:
        return next(iter(self._agents.values()), None)

    def remove_agent(self) -> Any | None:
        agent = self.get_agent()
        if agent is not None:
            self._agents.pop(id(agent), None)
            self.conveyor.remove_agent(agent)
        return agent

    def location(self) -> ConveyorLocation:
        return ConveyorLocation(self.conveyor, self.offset_m)


@dataclass
class ConveyorSimpleStation:
    """AnyLogic Station markup for simple processing on a conveyor."""

    id: str
    env: simpy.Environment
    conveyor: Conveyor
    offset_m: float
    length_m: float = 4.0
    capacity: int = 1
    process_time_s: float | Callable[[Any], float] = 0.0
    processing_mode: str = "agent_enters"
    poll_interval_s: float = 0.05
    on_process_started: Optional[Callable[[Any], None]] = None
    on_process_finished: Optional[Callable[[Any], None]] = None

    def __post_init__(self) -> None:
        if self.offset_m < 0 or self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")
        if self.length_m < 0:
            raise ValueError("length_m must be >= 0")
        if self.capacity < 0:
            raise ValueError("capacity must be >= 0")
        self._resource = simpy.Resource(self.env, capacity=max(1, self.capacity or 1))
        self._agents: dict[int, Any] = {}

    def set_capacity(self, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("capacity must be >= 0")
        self.capacity = capacity
        self._resource._capacity = max(1, capacity or 1)

    def get_capacity(self) -> int:
        return self.capacity

    def contains(self, agent: Any) -> bool:
        return id(agent) in self._agents

    def get_agents(self) -> list[Any]:
        return list(self._agents.values())

    def size(self) -> int:
        return len(self._agents)

    def process(self, agent: Any) -> Generator:
        while self.capacity == 0:
            yield self.env.timeout(self.poll_interval_s)
        with self._resource.request() as req:
            yield req
            self._agents[id(agent)] = agent
            if self.on_process_started is not None:
                self.on_process_started(agent)
            duration_s = (
                self.process_time_s(agent)
                if callable(self.process_time_s)
                else self.process_time_s
            )
            if duration_s < 0:
                raise ValueError("station process_time_s must be >= 0")
            if duration_s > 0:
                yield self.env.timeout(duration_s)
            if self.on_process_finished is not None:
                self.on_process_finished(agent)
            self._agents.pop(id(agent), None)

    def location(self) -> ConveyorLocation:
        return ConveyorLocation(self.conveyor, self.offset_m)


@dataclass
class ConveyorNetwork:
    """Container for AnyLogic material-handling conveyor markup."""

    id: str
    conveyors: dict[str, Conveyor] = field(default_factory=dict)
    positions: dict[str, PositionOnConveyor] = field(default_factory=dict)
    stations: dict[str, ConveyorSimpleStation] = field(default_factory=dict)
    spurs: dict[str, ConveyorSpur] = field(default_factory=dict)

    def add_conveyor(self, conveyor: Conveyor) -> Conveyor:
        conveyor.network = self
        self.conveyors[conveyor.id] = conveyor
        return conveyor

    def add_position(self, position: PositionOnConveyor) -> PositionOnConveyor:
        self.positions[position.id] = position
        return position

    def add_station(self, station: ConveyorSimpleStation) -> ConveyorSimpleStation:
        self.stations[station.id] = station
        return station

    def add_spur(self, spur: ConveyorSpur) -> ConveyorSpur:
        self.spurs[spur.id] = spur
        return spur

    def find_spur(self, source: Conveyor, target: Conveyor) -> ConveyorSpur | None:
        for spur in self.spurs.values():
            if spur.source_conveyor is source and spur.target_conveyor is target:
                return spur
        return None

    def positions_between(
        self,
        conveyor: Conveyor,
        start_m: float,
        end_m: float,
    ) -> list[PositionOnConveyor]:
        low, high = sorted((start_m, end_m))
        positions = [
            position
            for position in self.positions.values()
            if position.conveyor is conveyor and low < position.offset_m <= high
        ]
        reverse = end_m < start_m
        return sorted(positions, key=lambda item: item.offset_m, reverse=reverse)


def _polyline_length(points: tuple[tuple[float, float], ...]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(points, points[1:])
    )


ConveyorPath = Conveyor
