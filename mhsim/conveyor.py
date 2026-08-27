"""AnyLogic-shaped conveyor network: paths, positions, stations, and spurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Callable, Optional, Generator, Any

import simpy


ANYLOGIC_CONVEYOR_LOCATION_KEY = "_anylogic_conveyor_location"
ANYLOGIC_PENDING_STATION_RELEASES_KEY = "_anylogic_pending_station_releases"


@dataclass(frozen=True)
class ConveyorLocation:
    """Exact AnyLogic-style location on a conveyor path."""

    conveyor: "Conveyor"
    offset_m: float

    def __post_init__(self) -> None:
        """Validate that the offset lies on the conveyor.

        Raises:
            ValueError: If `offset_m` is negative or beyond the conveyor's
                length.
        """
        if self.offset_m < 0:
            raise ValueError("offset_m must be >= 0")
        if self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")


@dataclass
class PendingStationRelease:
    """Station resource release held until downstream flow accepts the agent."""

    station: "ConveyorSimpleStation"
    request: simpy.events.Event
    release_delay_s: float
    released: bool = False


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
        """Derive length from geometry where given, validate, and build state.

        When `points` is supplied, `length_m` is overwritten with the
        polyline length, so geometry always wins over a hand-set length.

        Raises:
            ValueError: If `length_m` is negative, `speed_mps` is not
                positive, or `max_items` is set but not positive.
        """
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
        self._interior_entry_mutexes: dict[float, simpy.Resource] = {}
        self._next_interior_entry_time: dict[float, float] = {}
        self._occupancy = 0
        self.total_entered = 0
        self.total_exited = 0
        self._agent_offsets: dict[int, float] = {}

    @property
    def occupancy(self) -> int:
        """Number of items currently on the conveyor."""
        return self._occupancy

    def entry_headway_time_s(self) -> float:
        """Minimum time between successive entries at the conveyor head.

        Returns:
            Seconds for one item footprint — length plus gap — to clear the
            entry point at conveyor speed. Zero when the footprint is zero,
            which lets items enter without spacing.
        """
        footprint = max(0.0, self.item_length_m + self.min_gap_m)
        return footprint / self.speed_mps if footprint > 0 else 0.0

    def travel_time_s(self, distance_m: Optional[float] = None) -> float:
        """Time to travel a distance along the conveyor at its fixed speed.

        Args:
            distance_m: Distance in metres. Defaults to the full conveyor
                length.

        Returns:
            Travel time in seconds.

        Raises:
            ValueError: If the distance is negative.
        """
        distance = self.length_m if distance_m is None else distance_m
        if distance < 0:
            raise ValueError("distance_m must be >= 0")
        return distance / self.speed_mps

    def _has_capacity(self) -> bool:
        return self.max_items is None or self._occupancy < self.max_items

    def enter(self) -> Generator:
        """Occupy the conveyor at its head, waiting for capacity and headway.

        A SimPy process. Entries are serialised through a mutex so concurrent
        callers queue rather than all passing the same capacity check, then
        each waits out the entry headway.

        Yields:
            SimPy events while waiting for capacity and spacing.
        """
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
        """Release one unit of occupancy as an item leaves the conveyor.

        Raises:
            RuntimeError: If the conveyor is already empty, which indicates
                unbalanced enter and leave calls rather than a modelling
                condition.
        """
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

    def reserve_offset_headway(
        self,
        offset_m: float,
        is_available: Callable[[], bool] | None = None,
        wait_until_available: Callable[[], Generator] | None = None,
    ) -> Generator:
        """Reserve local cell/gap clearance at an interior conveyor point.

        AnyLogic position-based entries need local cell/gap clearance. The
        reservation is keyed by offset so independent positions do not
        serialize each other.
        """
        if offset_m < 0 or offset_m > self.length_m:
            raise ValueError("offset_m must be within the conveyor length")

        offset_key = round(float(offset_m), 9)
        mutex = self._interior_entry_mutexes.get(offset_key)
        if mutex is None:
            mutex = simpy.Resource(self.env, capacity=1)
            self._interior_entry_mutexes[offset_key] = mutex

        with mutex.request() as req:
            yield req
            while True:
                while is_available is not None and not is_available():
                    if wait_until_available is not None:
                        yield from wait_until_available()
                    else:
                        yield self.env.timeout(self.entry_poll_interval_s)
                next_entry_time = self._next_interior_entry_time.get(offset_key, 0.0)
                wait_time = max(0.0, next_entry_time - self.env.now)
                if wait_time > 0:
                    yield self.env.timeout(wait_time)
                    continue
                if is_available is None or is_available():
                    break

            self._next_interior_entry_time[offset_key] = (
                max(self._next_interior_entry_time.get(offset_key, 0.0), self.env.now)
                + self.entry_headway_time_s()
            )

    def occupy_at_offset_with_headway(
        self,
        offset_m: float,
        is_available: Callable[[], bool] | None = None,
        wait_until_available: Callable[[], Generator] | None = None,
    ) -> Generator:
        """Occupy this conveyor from an interior point with local spacing."""
        while not self._has_capacity():
            yield self.env.timeout(self.entry_poll_interval_s)
        yield from self.reserve_offset_headway(
            offset_m,
            is_available=is_available,
            wait_until_available=wait_until_available,
        )
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
        """Update an agent's recorded position along this conveyor.

        Args:
            agent: Agent to move.
            offset_m: New offset in metres from the conveyor head.

        Returns:
            The new location. Equivalent to `place_agent`; the separate
            name reads better at call sites that move rather than admit.
        """
        return self.place_agent(agent, offset_m)

    def remove_agent(self, agent: Any) -> None:
        """Forget an agent's position, clearing its location attribute.

        Args:
            agent: Agent to remove. Removing an unknown agent is a no-op, so
                cleanup paths can call this unconditionally.
        """
        self._agent_offsets.pop(id(agent), None)
        if hasattr(agent, "attributes"):
            agent.attributes.pop(ANYLOGIC_CONVEYOR_LOCATION_KEY, None)

    def agent_offset(self, agent: Any) -> float | None:
        """Look up an agent's offset along this conveyor.

        Args:
            agent: Agent to query.

        Returns:
            Offset in metres from the conveyor head, or `None` if the agent
            is not on this conveyor.
        """
        return self._agent_offsets.get(id(agent))


@dataclass
class ConveyorSpur:
    """Transfer point that moves items from one conveyor onto another.

    The clearance and merge-window behavior is validated through the active
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
        """Validate the spur geometry and build its merge-control state.

        `offset_m` defaults to `target_offset_m` when not given, so the
        spur meets the target where it says it does.

        Raises:
            ValueError: If source and target are the same conveyor, if
                `target_offset_m` falls outside the target conveyor, or if
                `source_merge_queue_capacity` is set but not positive.
        """
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
        """Distance from the merge point to the end of the target conveyor.

        Returns:
            Remaining distance in metres, used to time an item's run-out after
            it merges.
        """
        return self.target_conveyor.length_m - self.target_offset_m

    def merge_headway_time_s(self) -> float:
        """Minimum time between successive merges onto the target conveyor.

        Returns:
            Seconds for the required clearance to pass the merge point at
            target speed. Falls back to the target's own item footprint —
            length plus gap — when no explicit clearance is configured.
        """
        if self.merge_clearance_distance_m is None:
            clearance = (
                self.target_conveyor.item_length_m
                + self.target_conveyor.min_gap_m
            )
        else:
            clearance = self.merge_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def source_after_target_headway_time_s(self) -> float:
        """Headway required when a source item follows a target-line item.

        Returns:
            Seconds of clearance, defaulting to `merge_headway_time_s`
            when no direction-specific clearance is configured.
        """
        if self.source_after_target_clearance_distance_m is None:
            return self.merge_headway_time_s()
        clearance = self.source_after_target_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def source_before_target_headway_time_s(self) -> float:
        """Headway required when a source item precedes a target-line item.

        Returns:
            Seconds of clearance, or `0.0` when none is configured, which
            lets a merging item slot in immediately ahead.
        """
        if self.source_before_target_clearance_distance_m is None:
            return 0.0
        clearance = self.source_before_target_clearance_distance_m
        return clearance / self.target_conveyor.speed_mps if clearance > 0 else 0.0

    def register_target_merge_arrival(self, time_s: float) -> None:
        """Announce when an item travelling the target line reaches the merge.

        Lets the spur reserve a window for traffic already on the target
        conveyor, so a merging item does not claim a slot that is spoken for.

        Args:
            time_s: Simulation time in seconds at which the item is expected.
        """
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
        """Move one item from the source conveyor onto the target conveyor.

        A SimPy process. When a source merge queue is configured, the item
        first takes a queue slot so upstream pressure is bounded; otherwise it
        goes straight to reserving a merge slot.

        Yields:
            SimPy events while queuing and waiting for the merge window.
        """
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
        """Validate the offset and initialise blocking state.

        Raises:
            ValueError: If `offset_m` falls outside the conveyor.
        """
        if self.offset_m < 0 or self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")
        self._block_count = 1 if self.initially_blocked else 0
        self._agents: dict[int, Any] = {}
        self._unblocked_event: simpy.events.Event | None = None

    def block(self) -> None:
        """Add one block to this position, stopping items from passing.

        Blocks nest: two calls need two `unblock` calls to clear, so
        independent callers cannot release each other's holds.
        """
        self._block_count += 1

    def unblock(self) -> None:
        """Remove one block, waking waiting items when the last one clears.

        Unblocking an already-clear position is a no-op rather than an error.
        """
        self._block_count = max(0, self._block_count - 1)
        if (
            self._block_count == 0
            and self._unblocked_event is not None
            and not self._unblocked_event.triggered
        ):
            self._unblocked_event.succeed()

    def is_blocked(self) -> bool:
        """Whether at least one block is currently held on this position."""
        return self._block_count > 0

    def wait_until_unblocked(self, env: simpy.Environment) -> Generator:
        """Wait until every block on this position has been released.

        A SimPy process. Returns immediately when the position is already
        clear.

        Args:
            env: Environment used to create the wake-up event.

        Yields:
            An event that fires when the block count reaches zero.
        """
        while self.is_blocked():
            if self._unblocked_event is None or self._unblocked_event.triggered:
                self._unblocked_event = env.event()
            yield self._unblocked_event

    def leading_edge_enter(self, agent: Any) -> None:
        """Record an agent's leading edge reaching this position.

        Args:
            agent: Arriving agent. The `on_leading_edge_enter` callback
                fires after the agent is registered.
        """
        self._agents[id(agent)] = agent
        if self.on_leading_edge_enter is not None:
            self.on_leading_edge_enter(agent)

    def trailing_edge_exit(self, agent: Any) -> None:
        """Record an agent's trailing edge clearing this position.

        Args:
            agent: Departing agent. The `on_trailing_edge_exit` callback
                fires after the agent is deregistered.
        """
        self._agents.pop(id(agent), None)
        if self.on_trailing_edge_exit is not None:
            self.on_trailing_edge_exit(agent)

    def contains(self, agent: Any) -> bool:
        """Whether the given agent currently occupies this position.

        Args:
            agent: Agent to test.

        Returns:
            True if the agent's leading edge has entered and its trailing
            edge has not yet cleared.
        """
        return id(agent) in self._agents

    def get_agent(self) -> Any | None:
        """Return any one agent at this position.

        Returns:
            The first registered agent, or `None` when the position is
            empty. Positions normally hold at most one agent.
        """
        return next(iter(self._agents.values()), None)

    def remove_agent(self) -> Any | None:
        """Remove an agent from this position and from the conveyor.

        Returns:
            The removed agent, or `None` when the position was empty.
        """
        agent = self.get_agent()
        if agent is not None:
            self._agents.pop(id(agent), None)
            self.conveyor.remove_agent(agent)
        return agent

    def location(self) -> ConveyorLocation:
        """Return this position as a conveyor location.

        Returns:
            A `ConveyorLocation` at this position's offset.
        """
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
    entry_offset_m: float | None = None
    poll_interval_s: float = 0.05
    enforce_physical_occupancy: bool = False
    physical_release_delay_s: float | Callable[[Any], float] | None = None
    blocking_position: Optional[PositionOnConveyor] = None
    on_process_started: Optional[Callable[[Any], None]] = None
    on_process_finished: Optional[Callable[[Any], None]] = None
    on_released: Optional[Callable[[Any], None]] = None

    def __post_init__(self) -> None:
        """Validate station geometry and build its resource and agent state.

        Raises:
            ValueError: If `offset_m` or `entry_offset_m` falls outside
                the conveyor, or if `length_m` or `capacity` is
                negative.
        """
        if self.offset_m < 0 or self.offset_m > self.conveyor.length_m:
            raise ValueError("offset_m must be within the conveyor length")
        if self.entry_offset_m is not None and (
            self.entry_offset_m < 0 or self.entry_offset_m > self.conveyor.length_m
        ):
            raise ValueError("entry_offset_m must be within the conveyor length")
        if self.length_m < 0:
            raise ValueError("length_m must be >= 0")
        if self.capacity < 0:
            raise ValueError("capacity must be >= 0")
        self._resource = simpy.Resource(self.env, capacity=max(1, self.capacity or 1))
        self._agents: dict[int, Any] = {}
        self._capacity_batch_waiting: list[
            tuple[Any, simpy.events.Event, simpy.events.Event]
        ] = []

    def set_capacity(self, capacity: int) -> None:
        """Change how many agents the station may hold, mid-run if needed.

        Args:
            capacity: New capacity. Zero closes the station, holding arriving
                agents until capacity is restored.

        Raises:
            ValueError: If `capacity` is negative.
        """
        if capacity < 0:
            raise ValueError("capacity must be >= 0")
        self.capacity = capacity
        self._resource._capacity = max(1, capacity or 1)

    def get_capacity(self) -> int:
        """Return the station's configured capacity."""
        return self.capacity

    def contains(self, agent: Any) -> bool:
        """Whether the given agent is currently held at this station.

        Args:
            agent: Agent to test.

        Returns:
            True if the agent is in the station.
        """
        return id(agent) in self._agents

    def get_agents(self) -> list[Any]:
        """Return every agent currently at the station.

        Returns:
            A new list in arrival order, safe to iterate while the station
            changes.
        """
        return list(self._agents.values())

    def size(self) -> int:
        """Number of agents currently held at the station."""
        return len(self._agents)

    def process(self, agent: Any) -> Generator:
        """Admit an agent, hold it for its processing time, and release it.

        A SimPy process. Under the `capacity_full` mode with capacity
        above one, agents are batched and released together; otherwise each is
        processed on arrival.

        Args:
            agent: Agent entering the station.

        Yields:
            SimPy events while waiting for capacity and for processing.
        """
        if self.processing_mode == "capacity_full" and self.capacity > 1:
            yield from self._process_when_capacity_full(agent)
            return

        while self.capacity == 0:
            yield self.env.timeout(self.poll_interval_s)
        req = self._resource.request()
        yield req
        self._agents[id(agent)] = agent
        self._block_position()
        if self.on_process_started is not None:
            self.on_process_started(agent)
            # AnyLogic runs callbacks and same-time block handoffs in the
            # engine event queue. Let entities injected by onProcessStarted
            # reach downstream conveyor-position arbitration before this agent
            # leaves the station flow.
            yield self.env.timeout(0)
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
        self._unblock_position()

        if self.enforce_physical_occupancy:
            release_delay_s = self._physical_release_delay_s(agent)
            # AnyLogic keeps the station capacity occupied until the material
            # item physically clears the station, but the downstream block can
            # start as soon as processing finishes.
            self.env.process(self._release_after(agent, req, release_delay_s))
        else:
            self._release(agent, req)

    def _process_when_capacity_full(self, agent: Any) -> Generator:
        while self.capacity == 0:
            yield self.env.timeout(self.poll_interval_s)
        req = self._resource.request()
        yield req
        self._agents[id(agent)] = agent
        done = self.env.event()
        self._capacity_batch_waiting.append((agent, req, done))
        if len(self._capacity_batch_waiting) >= self.capacity:
            batch = self._capacity_batch_waiting[: self.capacity]
            del self._capacity_batch_waiting[: self.capacity]
            self.env.process(self._process_capacity_batch(batch))
        yield done

    def _process_capacity_batch(
        self,
        batch: list[tuple[Any, simpy.events.Event, simpy.events.Event]],
    ) -> Generator:
        lead_agent = batch[0][0]
        self._block_position()
        if self.on_process_started is not None:
            self.on_process_started(lead_agent)
            yield self.env.timeout(0)

        duration_s = (
            self.process_time_s(lead_agent)
            if callable(self.process_time_s)
            else self.process_time_s
        )
        if duration_s < 0:
            raise ValueError("station process_time_s must be >= 0")
        if duration_s > 0:
            yield self.env.timeout(duration_s)
        if self.on_process_finished is not None:
            self.on_process_finished(lead_agent)
        self._unblock_position()

        for agent, req, done in batch:
            if self.enforce_physical_occupancy:
                release_delay_s = self._physical_release_delay_s(agent)
                self.env.process(self._release_after(agent, req, release_delay_s))
            else:
                self._release(agent, req)
            if not done.triggered:
                done.succeed()

    def _block_position(self) -> None:
        if self.blocking_position is not None:
            self.blocking_position.block()

    def _unblock_position(self) -> None:
        if self.blocking_position is not None:
            self.blocking_position.unblock()

    def _physical_release_delay_s(self, agent: Any) -> float:
        if self.physical_release_delay_s is None:
            footprint_m = self.length_m + self.conveyor.item_length_m
            delay_s = self.conveyor.travel_time_s(footprint_m)
        elif callable(self.physical_release_delay_s):
            delay_s = self.physical_release_delay_s(agent)
        else:
            delay_s = self.physical_release_delay_s
        if delay_s < 0:
            raise ValueError("physical_release_delay_s must be >= 0")
        return delay_s

    def _release_after(self, agent: Any, req: simpy.events.Event, delay_s: float) -> Generator:
        pre_release_block_s = 0.0
        if self.blocking_position is not None:
            pre_release_block_s = min(delay_s, self.conveyor.entry_headway_time_s())

        unblocked_delay_s = delay_s - pre_release_block_s
        if unblocked_delay_s > 0:
            yield self.env.timeout(unblocked_delay_s)
        if pre_release_block_s > 0 and self.blocking_position is not None:
            self.blocking_position.block()
            yield self.env.timeout(pre_release_block_s)
            self.blocking_position.unblock()
        elif delay_s > 0:
            yield self.env.timeout(delay_s)
        self._release(agent, req)

    def _defer_release_until_downstream(
        self,
        agent: Any,
        req: simpy.events.Event,
        delay_s: float,
    ) -> None:
        if not hasattr(agent, "attributes"):
            self.env.process(self._release_after(agent, req, delay_s))
            return
        releases = agent.attributes.setdefault(
            ANYLOGIC_PENDING_STATION_RELEASES_KEY,
            [],
        )
        releases.append(
            PendingStationRelease(
                station=self,
                request=req,
                release_delay_s=delay_s,
            )
        )

    def release_pending(self, agent: Any, release: PendingStationRelease) -> Generator:
        """Complete a deferred station release once downstream accepts.

        A SimPy process, and idempotent: an already-released handle returns
        immediately, so callers need not track state.

        Args:
            agent: Agent being released.
            release: Handle returned when the release was deferred.

        Yields:
            A timeout covering the physical clearance delay, if any.

        Parity:
            The station keeps its physical cell occupied while the agent is
            handed downstream, then clears over the station's own length at
            conveyor speed, matching AnyLogic rather than freeing the cell the
            instant the agent leaves.
        """
        if release.released:
            return
        # A conveyor station keeps its physical cell occupied while the agent
        # is handed to the downstream block, then clears over the station's
        # own exported length at conveyor speed.
        if release.release_delay_s > 0:
            yield self.env.timeout(release.release_delay_s)
        release.released = True
        self._release(agent, release.request)

    def _release(self, agent: Any, req: simpy.events.Event) -> None:
        self._agents.pop(id(agent), None)
        if self.on_released is not None:
            self.on_released(agent)
        self._resource.release(req)

    def location(self) -> ConveyorLocation:
        """Return the station's entry point as a conveyor location.

        Returns:
            A `ConveyorLocation` at `entry_offset_m` where one is
            configured, otherwise at `offset_m`.
        """
        offset_m = self.offset_m if self.entry_offset_m is None else self.entry_offset_m
        return ConveyorLocation(self.conveyor, offset_m)


@dataclass
class ConveyorNetwork:
    """Container for AnyLogic material-handling conveyor markup."""

    id: str
    conveyors: dict[str, Conveyor] = field(default_factory=dict)
    positions: dict[str, PositionOnConveyor] = field(default_factory=dict)
    stations: dict[str, ConveyorSimpleStation] = field(default_factory=dict)
    spurs: dict[str, ConveyorSpur] = field(default_factory=dict)

    def add_conveyor(self, conveyor: Conveyor) -> Conveyor:
        """Register a conveyor and back-link it to this network.

        Args:
            conveyor: Conveyor to add. Its `network` is set to this one.

        Returns:
            The same conveyor, so registration can be inlined at
            construction.
        """
        conveyor.network = self
        self.conveyors[conveyor.id] = conveyor
        return conveyor

    def add_position(self, position: PositionOnConveyor) -> PositionOnConveyor:
        """Register a position on a conveyor.

        Args:
            position: Position to add, keyed by its identifier.

        Returns:
            The same position, so registration can be inlined.
        """
        self.positions[position.id] = position
        return position

    def add_station(self, station: ConveyorSimpleStation) -> ConveyorSimpleStation:
        """Register a station on a conveyor.

        Args:
            station: Station to add, keyed by its identifier.

        Returns:
            The same station, so registration can be inlined.
        """
        self.stations[station.id] = station
        return station

    def add_spur(self, spur: ConveyorSpur) -> ConveyorSpur:
        """Register a spur between two conveyors.

        Args:
            spur: Spur to add, keyed by its identifier.

        Returns:
            The same spur, so registration can be inlined.
        """
        self.spurs[spur.id] = spur
        return spur

    def find_spur(self, source: Conveyor, target: Conveyor) -> ConveyorSpur | None:
        """Find the spur connecting one conveyor to another.

        Args:
            source: Conveyor items leave.
            target: Conveyor items merge onto.

        Returns:
            The matching spur, or `None` if the two are not connected.
            Direction matters: a spur is not found by its reverse.
        """
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
        """List the positions lying on a stretch of one conveyor.

        Args:
            conveyor: Conveyor to search.
            start_m: One end of the stretch, in metres.
            end_m: The other end. The two may be given in either order.

        Returns:
            Matching positions in increasing offset order.
        """
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
