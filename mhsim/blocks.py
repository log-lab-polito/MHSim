from __future__ import annotations

from abc import ABC, abstractmethod
import simpy
from random import Random
from typing import Any, Optional, Callable, Generator, Union

from .pallet import Pallet
from .forklift import (
    ForkliftFleet,
    ForkliftStatus,
    ForkliftAssignment,
    ForkliftMovementOverrides,
)
from .stats import SimulationStats
from .cyclic_position_logger import CyclicPositionLogger
from .movement import Position3D
from .conveyor import Conveyor, ConveyorSpur
from .conveyor import (
    ANYLOGIC_CONVEYOR_LOCATION_KEY,
    ANYLOGIC_PENDING_STATION_RELEASES_KEY,
    ConveyorLocation,
    PositionOnConveyor,
    ConveyorSimpleStation,
    PendingStationRelease,
)
from .storage_slots import StorageSlotManager, StorageSlot
from .random_variables import DurationValue, sample_duration_s


PositionResolver = Optional[Union[Callable[[Pallet], Optional[Position3D]], Position3D]]
DistanceResolver = Optional[Union[Callable[[Pallet], float], float]]
DEFAULT_TRANSPORTER_ASSIGNMENT_KEY = "_transporter_assignment"


def _resolve_position(
    resolver: PositionResolver,
    pallet: Pallet,
) -> Optional[Position3D]:
    if callable(resolver):
        return resolver(pallet)
    return resolver


def _resolve_distance(resolver: DistanceResolver, pallet: Pallet) -> Optional[float]:
    if callable(resolver):
        return resolver(pallet)
    return resolver


def _release_pending_station_releases(pallet: Pallet) -> Generator:
    releases = pallet.attributes.pop(ANYLOGIC_PENDING_STATION_RELEASES_KEY, [])
    if not isinstance(releases, list):
        return
    for release in releases:
        if isinstance(release, PendingStationRelease):
            yield from release.station.release_pending(pallet, release)
            # AnyLogic's LIFO same-time mode lets newly unblocked station
            # entrants run before the releasing downstream block continues.
            yield release.station.env.timeout(0)


def _get_assignment(
    pallet: Pallet,
    assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
) -> Optional[ForkliftAssignment]:
    value = pallet.attributes.get(assignment_key)
    return value if isinstance(value, ForkliftAssignment) else None


def _set_assignment(
    pallet: Pallet,
    assignment: ForkliftAssignment,
    assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
) -> None:
    pallet.attributes[assignment_key] = assignment


def _clear_assignment(
    pallet: Pallet,
    assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
) -> Optional[ForkliftAssignment]:
    value = pallet.attributes.pop(assignment_key, None)
    return value if isinstance(value, ForkliftAssignment) else None


def _seize_forklift(
    fleet: ForkliftFleet,
    priority: int,
    pending_attr: Optional[str] = None,
    near_position=None,
) -> Generator[object, object, ForkliftAssignment]:
    if pending_attr and hasattr(fleet, pending_attr):
        setattr(fleet, pending_attr, getattr(fleet, pending_attr) + 1)
    try:
        assignment = yield from fleet.seize(
            priority=priority,
            near_position=near_position,
        )
    finally:
        if pending_attr and hasattr(fleet, pending_attr):
            setattr(fleet, pending_attr, max(0, getattr(fleet, pending_attr) - 1))
    return assignment


def _run_fleet_post_task(fleet: ForkliftFleet, forklift) -> Generator:
    yield from fleet.run_post_task_policy(forklift)


def _record_forklift_movement_duration(
    stats: Optional[object],
    metric_name: str,
    start_time: float,
    end_time: float,
) -> None:
    recorder = getattr(stats, "record_forklift_movement", None)
    if callable(recorder):
        recorder(metric_name, max(0.0, end_time - start_time))


def _record_move_by_transporter_benchmarks(
    stats: Optional[object],
    benchmark_prefix: Optional[str],
    *,
    enter_at: float,
    seize_at: float,
    load_started_at: float,
    load_finished_at: float,
    unload_started_at: float,
    unload_finished_at: float,
    release_at: float,
) -> None:
    if not benchmark_prefix:
        return

    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_enter_to_seize_s",
        enter_at,
        seize_at,
    )
    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_seize_to_loading_start_s",
        seize_at,
        load_started_at,
    )
    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_loading_duration_s",
        load_started_at,
        load_finished_at,
    )
    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_loading_finish_to_unloading_start_s",
        load_finished_at,
        unload_started_at,
    )
    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_unloading_duration_s",
        unload_started_at,
        unload_finished_at,
    )
    _record_forklift_movement_duration(
        stats,
        f"{benchmark_prefix}_unloading_finish_to_release_s",
        unload_finished_at,
        release_at,
    )


class Block(ABC):
    """Base lifecycle shape shared by AnyLogic-style process blocks."""

    def __init__(
        self,
        env: simpy.Environment,
        name: str,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        self.env = env
        self.name = name
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def _log_event(self, pallet: Pallet) -> None:
        if self.logger:
            self.logger.log_event(
                f"{self.name} block",
                f"Pallet {pallet.id}",
                self.env.now,
            )

    def _record_enter(self, pallet: Pallet) -> None:
        self.entered_count += 1
        self._log_event(pallet)

    def _record_finish(self) -> None:
        self.finished_count += 1

    def _record_complete(self) -> None:
        self.completed_count += 1

    @abstractmethod
    def handle(self, pallet: Pallet) -> Generator:
        """Process one pallet."""


class PassThroughBlock(Block):
    """Base for blocks that forward pallets to a downstream block."""

    def __init__(
        self,
        env: simpy.Environment,
        next_block,
        name: str,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, name=name, logger=logger)
        self.next_block = next_block

    def _forward(self, pallet: Pallet) -> Generator:
        if self.next_block:
            yield from self.next_block.handle(pallet)


class Sink(Block):
    def __init__(
        self,
        env: simpy.Environment,
        stats: SimulationStats,
        name: str = "sink",
        logger: Optional[CyclicPositionLogger] = None,
        on_enter: Optional[Callable[[Pallet], None]] = None,
        record_stats: bool = True,
    ):
        super().__init__(env=env, name=name, logger=logger)
        self.stats = stats
        self.on_enter = on_enter
        self.record_stats = record_stats

    def handle(self, pallet: Pallet):
        # Make this a generator so upstream `yield from` never fails.
        self._record_enter(pallet)
        if self.on_enter is not None:
            self.on_enter(pallet)
        yield self.env.timeout(0)
        if self.record_stats:
            duration = self.env.now - pallet.created_at
            self.stats.record_completed(duration)


class ServiceBlock(PassThroughBlock):
    def __init__(
        self,
        env: simpy.Environment,
        service_time_s: DurationValue,
        next_block,
        name: str = "service",
        capacity: int = 1,
        queue_capacity: int = 0,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.service_time_s = service_time_s
        self.resource = simpy.Resource(env, capacity=capacity)
        self.queue_capacity = queue_capacity
        self.queue_entered_count = 0
        self.delay_entered_count = 0

    def sample_service_time_s(self) -> float:
        return sample_duration_s(
            self.service_time_s,
            name=f"{self.name}.service_time_s",
        )

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        if self.queue_capacity and self.queue_capacity > 0:
            # Block upstream until there is room in the waiting line.
            while len(self.resource.queue) >= self.queue_capacity:
                yield self.env.timeout(0)
        self.queue_entered_count += 1
        with self.resource.request() as req:
            yield req
            self.delay_entered_count += 1
            yield self.env.timeout(self.sample_service_time_s())
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class DelayBlock(PassThroughBlock):
    """Pure time-delay block without queue or resource semantics."""

    def __init__(self, env: simpy.Environment, delay_s: DurationValue, next_block, name: str = "delay", logger: Optional[CyclicPositionLogger] = None):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.delay_s = delay_s

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        yield self.env.timeout(sample_duration_s(self.delay_s, name=f"{self.name}.delay_s"))
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class ConveyorEnterBlock(PassThroughBlock):
    """AnyLogic-style conveyor entry block."""

    def __init__(
        self,
        env: simpy.Environment,
        conveyor: Conveyor,
        next_block,
        name: str = "conveyor_enter",
        position: PositionOnConveyor | None = None,
        offset_m: float = 0.0,
        enforce_position_headway: bool = False,
        on_at_enter_before_physical_entry: bool = False,
        on_at_enter: Optional[Callable[[Pallet], None]] = None,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.conveyor = conveyor
        self.position = position
        self.offset_m = offset_m
        self.enforce_position_headway = enforce_position_headway
        self.on_at_enter_before_physical_entry = on_at_enter_before_physical_entry
        self.on_at_enter = on_at_enter

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        if self.on_at_enter is not None and self.on_at_enter_before_physical_entry:
            self.on_at_enter(pallet)
        if self.position is not None:
            if self.on_at_enter_before_physical_entry and self.enforce_position_headway:
                yield from self._complete_hanging_position_entry(pallet)
            elif self.enforce_position_headway:
                yield from self.conveyor.occupy_at_offset_with_headway(
                    self.position.offset_m,
                    is_available=lambda: not self.position.is_blocked(),
                    wait_until_available=lambda: self.position.wait_until_unblocked(
                        self.env,
                    ),
                )
                self.conveyor.place_agent(pallet, self.position.offset_m)
                self.position.leading_edge_enter(pallet)
            else:
                yield from self.position.wait_until_unblocked(self.env)
                yield from self.conveyor.occupy_without_entry_headway()
                self.conveyor.place_agent(pallet, self.position.offset_m)
                self.position.leading_edge_enter(pallet)
        elif self.offset_m > 0:
            if self.enforce_position_headway:
                yield from self.conveyor.occupy_at_offset_with_headway(self.offset_m)
            else:
                yield from self.conveyor.occupy_without_entry_headway()
            self.conveyor.place_agent(pallet, self.offset_m)
        else:
            yield from self.conveyor.enter()
            self.conveyor.place_agent(pallet, 0.0)
        if self.on_at_enter is not None and not self.on_at_enter_before_physical_entry:
            self.on_at_enter(pallet)
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()

    def _complete_hanging_position_entry(self, pallet: Pallet) -> Generator:
        if self.position is None:
            return
        entry_time_s = self.conveyor.entry_headway_time_s()
        while True:
            yield from self.conveyor.reserve_offset_headway(
                self.position.offset_m,
                is_available=lambda: not self.position.is_blocked(),
                wait_until_available=lambda: self.position.wait_until_unblocked(
                    self.env,
                ),
            )
            if self.position.is_blocked():
                continue
            if entry_time_s > 0:
                yield self.env.timeout(entry_time_s)
            if self.position.is_blocked():
                continue
            yield from self.conveyor.occupy_without_entry_headway()
            self.conveyor.place_agent(pallet, self.position.offset_m)
            self.position.leading_edge_enter(pallet)
            return


class ConveyBlock(PassThroughBlock):
    """AnyLogic-style conveyor travel block."""

    def __init__(
        self,
        env: simpy.Environment,
        conveyor: Conveyor,
        next_block,
        name: str = "convey",
        distance_m: DistanceResolver = None,
        source_position: PositionOnConveyor | None = None,
        target_position: PositionOnConveyor | None = None,
        target_station: ConveyorSimpleStation | None = None,
        target_conveyor: Conveyor | None = None,
        route_conveyors: tuple[Conveyor, ...] = (),
        remove_from_conveyor_on_exit: bool = False,
        enforce_source_position_headway: bool = False,
        on_enter: Optional[Callable[[Pallet], None]] = None,
        on_at_exit: Optional[Callable[[Pallet], None]] = None,
        on_exit: Optional[Callable[[Pallet], None]] = None,
        on_target_conveyor_enter: Optional[Callable[[Pallet, Conveyor], None]] = None,
        on_target_conveyor_exit: Optional[Callable[[Pallet, Conveyor], None]] = None,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.conveyor = conveyor
        # Distance is measured in meters.
        self.distance_m = distance_m
        self.source_position = source_position
        self.target_position = target_position
        self.target_station = target_station
        self.target_conveyor = target_conveyor
        self.route_conveyors = route_conveyors
        self.remove_from_conveyor_on_exit = remove_from_conveyor_on_exit
        self.enforce_source_position_headway = enforce_source_position_headway
        self.on_enter = on_enter
        self.on_at_exit = on_at_exit
        self.on_exit = on_exit
        self.on_target_conveyor_enter = on_target_conveyor_enter
        self.on_target_conveyor_exit = on_target_conveyor_exit

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        if self.on_enter is not None:
            self.on_enter(pallet)
        yield from self._convey(pallet)
        if self.on_at_exit is not None:
            self.on_at_exit(pallet)
        if self.target_station is None:
            yield from _release_pending_station_releases(pallet)
        if self.on_exit is not None:
            self.on_exit(pallet)
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()

    def _current_location(self, pallet: Pallet) -> ConveyorLocation:
        location = pallet.attributes.get(ANYLOGIC_CONVEYOR_LOCATION_KEY)
        if isinstance(location, ConveyorLocation):
            return location
        if self.source_position is not None:
            return self.source_position.location()
        return ConveyorLocation(self.conveyor, 0.0)

    def _target_location(self) -> ConveyorLocation | None:
        if self.target_station is not None:
            return self.target_station.location()
        if self.target_position is not None:
            return self.target_position.location()
        if self.target_conveyor is not None and self.target_conveyor is self.conveyor:
            return ConveyorLocation(self.target_conveyor, self.target_conveyor.length_m)
        return None

    def _wait_for_positions(
        self,
        pallet: Pallet,
        conveyor: Conveyor,
        start_m: float,
        end_m: float,
    ) -> Generator:
        network = conveyor.network
        if network is None:
            return
        for position in network.positions_between(conveyor, start_m, end_m):
            yield from position.wait_until_unblocked(self.env)
            position.leading_edge_enter(pallet)
            position.trailing_edge_exit(pallet)

    def _move_on_conveyor(
        self,
        pallet: Pallet,
        conveyor: Conveyor,
        start_m: float,
        end_m: float,
    ) -> Generator:
        cursor_m = start_m
        network = conveyor.network
        positions = (
            network.positions_between(conveyor, start_m, end_m)
            if network is not None
            else []
        )
        for position in positions:
            segment_m = abs(position.offset_m - cursor_m)
            if segment_m > 0:
                yield self.env.timeout(conveyor.travel_time_s(segment_m))
            conveyor.move_agent_to(pallet, position.offset_m)
            yield from position.wait_until_unblocked(self.env)
            position.leading_edge_enter(pallet)
            position.trailing_edge_exit(pallet)
            cursor_m = position.offset_m
        remaining_m = abs(end_m - cursor_m)
        if remaining_m > 0:
            yield self.env.timeout(conveyor.travel_time_s(remaining_m))
        conveyor.move_agent_to(pallet, end_m)

    def _convey(self, pallet: Pallet) -> Generator:
        if (
            not isinstance(
                pallet.attributes.get(ANYLOGIC_CONVEYOR_LOCATION_KEY),
                ConveyorLocation,
            )
            and self.source_position is not None
        ):
            yield from self.source_position.wait_until_unblocked(self.env)
            if self.enforce_source_position_headway:
                yield from self.source_position.conveyor.occupy_at_offset_with_headway(
                    self.source_position.offset_m,
                )
            else:
                yield from self.source_position.conveyor.occupy_without_entry_headway()
            self.source_position.conveyor.place_agent(
                pallet,
                self.source_position.offset_m,
            )
            self.source_position.leading_edge_enter(pallet)
        current = self._current_location(pallet)
        target = self._target_location()
        if target is not None and target.conveyor is current.conveyor:
            yield from self._move_on_conveyor(
                pallet,
                current.conveyor,
                current.offset_m,
                target.offset_m,
            )
            if self.target_station is not None:
                yield from self.target_station.process(pallet)
            return

        if self.target_conveyor is not None and self.target_conveyor is not current.conveyor:
            network = current.conveyor.network
            spur = network.find_spur(current.conveyor, self.target_conveyor) if network else None
            if spur is None:
                raise RuntimeError(
                    f"No conveyor spur route from {current.conveyor.id} to {self.target_conveyor.id}"
                )
            spur_offset = float(spur.offset_m if spur.offset_m is not None else spur.target_offset_m)
            yield from self._move_on_conveyor(
                pallet,
                current.conveyor,
                current.offset_m,
                spur_offset,
            )
            current.conveyor.remove_agent(pallet)
            yield from spur.transfer()
            self.target_conveyor.place_agent(pallet, 0.0)
            if self.on_target_conveyor_enter is not None:
                self.on_target_conveyor_enter(pallet, self.target_conveyor)
            yield from self._move_on_conveyor(
                pallet,
                self.target_conveyor,
                0.0,
                self.target_conveyor.length_m,
            )
            if self.on_target_conveyor_exit is not None:
                self.on_target_conveyor_exit(pallet, self.target_conveyor)
            if self.remove_from_conveyor_on_exit:
                self.target_conveyor.leave()
                self.target_conveyor.remove_agent(pallet)
            return

        distance = _resolve_distance(self.distance_m, pallet)
        if distance is None:
            distance = self.conveyor.length_m - current.offset_m
        target_offset = min(self.conveyor.length_m, current.offset_m + distance)
        yield from self._move_on_conveyor(
            pallet,
            current.conveyor,
            current.offset_m,
            target_offset,
        )


class ConveyorExitBlock(PassThroughBlock):
    """AnyLogic-style conveyor exit block."""

    def __init__(
        self,
        env: simpy.Environment,
        conveyor: Conveyor,
        next_block,
        name: str = "conveyor_exit",
        on_exit: Optional[Callable[[Pallet], None]] = None,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.conveyor = conveyor
        self.on_exit = on_exit

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        location = pallet.attributes.get(ANYLOGIC_CONVEYOR_LOCATION_KEY)
        conveyor = self.conveyor
        if isinstance(location, ConveyorLocation):
            conveyor = location.conveyor
        conveyor.leave()
        conveyor.remove_agent(pallet)
        if self.on_exit is not None:
            self.on_exit(pallet)
        yield self.env.timeout(0)
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class BatchBlock(PassThroughBlock):
    """AnyLogic permanent Batch block."""

    def __init__(
        self,
        env: simpy.Environment,
        batch_size: int,
        new_batch_factory: Callable[[list[Pallet]], Pallet],
        next_block,
        name: str = "batch",
        permanent: bool = True,
        logger: Optional[CyclicPositionLogger] = None,
        on_add: Optional[Callable[[Pallet, Pallet | None], None]] = None,
        on_exit: Optional[Callable[[Pallet], None]] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        self.batch_size = batch_size
        self.new_batch_factory = new_batch_factory
        self.permanent = permanent
        self.on_add = on_add
        self.on_exit = on_exit
        self._queue: list[Pallet] = []
        self.batches_created = 0

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        yield from _release_pending_station_releases(pallet)
        location = pallet.attributes.get(ANYLOGIC_CONVEYOR_LOCATION_KEY)
        if isinstance(location, ConveyorLocation):
            location.conveyor.leave()
            location.conveyor.remove_agent(pallet)
        self._queue.append(pallet)
        if self.on_add is not None:
            self.on_add(pallet, None)
        self._record_finish()
        if len(self._queue) >= self.batch_size:
            originals = [self._queue.pop(0) for _ in range(self.batch_size)]
            batch = self.new_batch_factory(originals)
            self.batches_created += 1
            if self.on_exit is not None:
                self.on_exit(batch)
            yield from self._forward(batch)
            self._record_complete()
        else:
            yield self.env.timeout(0)
            self._record_complete()


class ConveyorSpurBlock(PassThroughBlock):
    """AnyLogic-style conveyor spur transfer block."""

    def __init__(
        self,
        env: simpy.Environment,
        spur: ConveyorSpur,
        next_block,
        name: str = "conveyor_spur",
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.spur = spur

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        yield from self.spur.transfer()
        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class SeizeTransporterBlock(PassThroughBlock):
    """Reserve a specific transporter and attach it to the pallet context."""

    def __init__(
        self,
        env: simpy.Environment,
        fleet: ForkliftFleet,
        next_block,
        name: str = "seize_transporter",
        request_priority: int = 1,
        near_position: PositionResolver = None,
        pending_attr: Optional[str] = None,
        assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.fleet = fleet
        self.request_priority = request_priority
        self.near_position = near_position
        self.pending_attr = pending_attr
        self.assignment_key = assignment_key

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)

        if _get_assignment(pallet, assignment_key=self.assignment_key) is not None:
            raise RuntimeError(
                f"Pallet {pallet.id} already has an active transporter assignment"
            )

        near_pos = _resolve_position(self.near_position, pallet)
        assignment = yield from _seize_forklift(
            self.fleet,
            priority=self.request_priority,
            pending_attr=self.pending_attr,
            near_position=near_pos,
        )
        _set_assignment(pallet, assignment, assignment_key=self.assignment_key)

        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class ReleaseTransporterBlock(PassThroughBlock):
    """Release a previously seized transporter from pallet context."""

    def __init__(
        self,
        env: simpy.Environment,
        fleet: ForkliftFleet,
        next_block,
        name: str = "release_transporter",
        assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
        apply_post_task_policy: bool = True,
        strict: bool = True,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.fleet = fleet
        self.assignment_key = assignment_key
        self.apply_post_task_policy = apply_post_task_policy
        self.strict = strict

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)

        assignment = _clear_assignment(pallet, assignment_key=self.assignment_key)
        if assignment is None:
            if self.strict:
                raise RuntimeError(
                    f"Pallet {pallet.id} has no transporter assignment to release"
                )
        else:
            fl = assignment.forklift
            if self.apply_post_task_policy:
                yield from _run_fleet_post_task(self.fleet, fl)
            self.fleet.release(assignment)

        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class MoveByTransporterBlock(PassThroughBlock):
    """Move a pallet using a seized transporter (or auto-seize when configured)."""

    def __init__(
        self,
        env: simpy.Environment,
        fleet: ForkliftFleet,
        next_block,
        name: str = "move_by_transporter",
        pickup_pos: PositionResolver = None,
        dropoff_pos: PositionResolver = None,
        loading_time_s: DurationValue = 0.0,
        unloading_time_s: DurationValue = 0.0,
        request_priority: int = 1,
        assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
        auto_seize_if_missing: bool = True,
        apply_post_task_policy_if_auto_seized: bool = True,
        stats: Optional[object] = None,
        benchmark_prefix: Optional[str] = None,
        benchmark_loading_boundary_offset_s: float = 0.0,
        pickup_movement_overrides: Optional[ForkliftMovementOverrides] = None,
        dropoff_movement_overrides: Optional[ForkliftMovementOverrides] = None,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.fleet = fleet
        self.pickup_pos = pickup_pos
        self.dropoff_pos = dropoff_pos
        self.loading_time_s = loading_time_s
        self.unloading_time_s = unloading_time_s
        self.request_priority = request_priority
        self.assignment_key = assignment_key
        self.auto_seize_if_missing = auto_seize_if_missing
        self.apply_post_task_policy_if_auto_seized = apply_post_task_policy_if_auto_seized
        self.stats = stats
        self.benchmark_prefix = (
            benchmark_prefix.lower() if benchmark_prefix is not None else None
        )
        self.benchmark_loading_boundary_offset_s = max(
            0.0, benchmark_loading_boundary_offset_s
        )
        self.pickup_movement_overrides = pickup_movement_overrides
        self.dropoff_movement_overrides = dropoff_movement_overrides

    @staticmethod
    def _sample_dwell_time_s(value: DurationValue, *, name: str) -> float:
        if callable(value):
            return sample_duration_s(value, name=name)
        duration_s = float(value)
        if duration_s < 0:
            raise ValueError(f"{name} must be non-negative, got {duration_s}")
        return duration_s

    def sample_loading_time_s(self) -> float:
        return self._sample_dwell_time_s(
            self.loading_time_s,
            name=f"{self.name}.loading_time_s",
        )

    def sample_unloading_time_s(self) -> float:
        return self._sample_dwell_time_s(
            self.unloading_time_s,
            name=f"{self.name}.unloading_time_s",
        )

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)

        enter_at = self.env.now
        downstream_process: Optional[simpy.Process] = None
        pickup = _resolve_position(self.pickup_pos, pallet)
        assignment = _get_assignment(pallet, assignment_key=self.assignment_key)
        auto_seized = assignment is None
        seize_at = enter_at
        if auto_seized:
            if not self.auto_seize_if_missing:
                raise RuntimeError(
                    f"Pallet {pallet.id} requires a transporter assignment before {self.name}"
                )
            assignment = yield from _seize_forklift(
                self.fleet,
                priority=self.request_priority,
                near_position=pickup,
            )
            seize_at = self.env.now

        try:
            fl = assignment.forklift
            load_started_at = seize_at
            load_finished_at = seize_at
            unload_started_at = seize_at
            unload_finished_at = seize_at

            def mark_load_start(timestamp: float) -> None:
                nonlocal load_started_at
                load_started_at = timestamp

            def mark_load_end(timestamp: float) -> None:
                nonlocal load_finished_at
                load_finished_at = timestamp

            def mark_unload_start(timestamp: float) -> None:
                nonlocal unload_started_at
                unload_started_at = timestamp

            def mark_unload_end(timestamp: float) -> None:
                nonlocal unload_finished_at
                unload_finished_at = timestamp

            if pickup is not None:
                loading_time_s = self.sample_loading_time_s()
                yield from fl.perform_lift(
                    pickup,
                    0,
                    dwell_time_s=loading_time_s,
                    dwell_status=ForkliftStatus.LOADING,
                    on_dwell_start=mark_load_start,
                    on_dwell_end=mark_load_end,
                    movement_overrides=self.pickup_movement_overrides,
                )
                fl.current_load = pallet

            dropoff = _resolve_position(self.dropoff_pos, pallet)
            if dropoff is not None:
                unloading_time_s = self.sample_unloading_time_s()
                yield from fl.perform_lift(
                    dropoff,
                    0,
                    dwell_time_s=unloading_time_s,
                    dwell_status=ForkliftStatus.UNLOADING,
                    on_dwell_start=mark_unload_start,
                    on_dwell_end=mark_unload_end,
                    movement_overrides=self.dropoff_movement_overrides,
                )
                fl.current_load = None

            release_at = self.env.now
            benchmark_load_started_at = load_started_at
            benchmark_load_finished_at = load_finished_at
            if self.benchmark_loading_boundary_offset_s > 0:
                # AnyLogic's MoveByTransporter timing callbacks can report the
                # loading boundary before the SimPy dwell starts. Keep this as
                # benchmark attribution only; the physical movement lifecycle
                # remains unchanged.
                offset = min(
                    self.benchmark_loading_boundary_offset_s,
                    max(0.0, load_started_at - seize_at),
                )
                benchmark_load_started_at = load_started_at - offset
                benchmark_load_finished_at = load_finished_at - offset
            _record_move_by_transporter_benchmarks(
                self.stats,
                self.benchmark_prefix,
                enter_at=enter_at,
                seize_at=seize_at,
                load_started_at=benchmark_load_started_at,
                load_finished_at=benchmark_load_finished_at,
                unload_started_at=unload_started_at,
                unload_finished_at=unload_finished_at,
                release_at=release_at,
            )

            # AnyLogic's MoveByTransporter releases the item flow as soon as the
            # unload completes. The transporter's idle return-home behavior is a
            # post-task concern and must not inflate pallet cycle time.
            if (
                auto_seized
                and self.apply_post_task_policy_if_auto_seized
                and self.next_block is not None
            ):
                downstream_process = self.env.process(self.next_block.handle(pallet))

            if auto_seized and self.apply_post_task_policy_if_auto_seized:
                yield from _run_fleet_post_task(self.fleet, fl)
        finally:
            if auto_seized:
                self.fleet.release(assignment)

        self._record_finish()
        if downstream_process is None:
            yield from self._forward(pallet)
        self._record_complete()


class StoreBlock(PassThroughBlock):
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        slot_manager: StorageSlotManager,
        stats: Optional[object],
        next_block,
        name: str = "store",
        inbound_pos=None,
        loading_time_s: DurationValue = 0.0,
        request_priority: int = 1,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.storage = storage
        self.fleet = fleet
        self.slot_manager = slot_manager
        self.stats = stats
        self.inbound_pos = inbound_pos
        self.loading_time_s = loading_time_s
        self.request_priority = request_priority

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        enter_at = self.env.now

        # Block until storage has room (hard capacity constraint)
        while self.storage.level >= self.storage.capacity:
            yield self.env.timeout(0.1)  # Poll every 0.1s until room available

        assignment = yield from _seize_forklift(
            self.fleet,
            priority=self.request_priority,
            pending_attr="pending_store",
            near_position=self.inbound_pos,
        )
        seize_at = self.env.now
        fl = assignment.forklift
        load_started_at = seize_at
        load_finished_at = seize_at
        unload_started_at = seize_at
        unload_finished_at = seize_at
        try:
            storage_slot: StorageSlot | None = None
            while storage_slot is None:
                storage_slot = self.slot_manager.reserve_for_store(
                    lambda slot: fl.estimate_travel_time(
                        self.inbound_pos._replace(z=0) if self.inbound_pos else fl.position,
                        slot.ground_pos,
                    )
                    + fl.lift_cycle_time(slot.level)
                )
                if storage_slot is None:
                    yield self.env.timeout(0.1)

            def mark_load_start(timestamp: float) -> None:
                nonlocal load_started_at
                load_started_at = timestamp

            def mark_load_end(timestamp: float) -> None:
                nonlocal load_finished_at
                load_finished_at = timestamp

            def mark_unload_start(timestamp: float) -> None:
                nonlocal unload_started_at
                unload_started_at = timestamp

            def mark_unload_end(timestamp: float) -> None:
                nonlocal unload_finished_at
                unload_finished_at = timestamp

            # Load at inbound (with elevation to shelf level)
            yield from fl.perform_lift(
                self.inbound_pos,
                0,
                dwell_time_s=sample_duration_s(self.loading_time_s, name=f"{self.name}.loading_time_s") if self.loading_time_s else 0.0,
                dwell_status=ForkliftStatus.LOADING,
                on_dwell_start=mark_load_start,
                on_dwell_end=mark_load_end,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_enter_to_seize_s",
                enter_at,
                seize_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_seize_to_loading_start_s",
                seize_at,
                load_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_loading_duration_s",
                load_started_at,
                load_finished_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_seize_to_load_start_s",
                seize_at,
                load_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_load_duration_s",
                load_started_at,
                load_finished_at,
            )
            fl.current_load = pallet

            # Unload at storage (with elevation to shelf level)
            yield from fl.perform_lift(
                storage_slot.ground_pos,
                storage_slot.level,
                dwell_status=ForkliftStatus.UNLOADING,
                on_dwell_start=mark_unload_start,
                on_dwell_end=mark_unload_end,
            )
            fl.current_load = None
            self.slot_manager.complete_store(storage_slot)

            yield from _run_fleet_post_task(self.fleet, fl)
            release_at = self.env.now
            _record_forklift_movement_duration(
                self.stats,
                "store_loading_finish_to_unloading_start_s",
                load_finished_at,
                unload_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_unloading_duration_s",
                unload_started_at,
                unload_finished_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_unloading_finish_to_release_s",
                unload_finished_at,
                release_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "store_unload_finish_to_release_s",
                load_finished_at,
                release_at,
            )
        finally:
            self.fleet.release(assignment)

        self._record_finish()
        yield self.storage.put(1)
        yield from self._forward(pallet)
        self._record_complete()


class RetrieveBlock(PassThroughBlock):
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        slot_manager: StorageSlotManager,
        stats: Optional[object],
        next_block,
        name: str = "retrieve",
        outbound_pos=None,
        unloading_time_s: DurationValue = 0.0,
        request_priority: int = 1,
        logger: Optional[CyclicPositionLogger] = None,
    ):
        super().__init__(env=env, next_block=next_block, name=name, logger=logger)
        self.storage = storage
        self.fleet = fleet
        self.slot_manager = slot_manager
        self.stats = stats
        self.outbound_pos = outbound_pos
        self.unloading_time_s = unloading_time_s
        self.request_priority = request_priority

    def handle(self, pallet: Pallet):
        self._record_enter(pallet)
        enter_at = self.env.now
        yield self.storage.get(1)

        assignment = yield from _seize_forklift(
            self.fleet,
            priority=self.request_priority,
            pending_attr="pending_retrieve",
            near_position=self.outbound_pos,
        )
        seize_at = self.env.now
        fl = assignment.forklift
        load_started_at = seize_at
        load_finished_at = seize_at
        unload_started_at = seize_at
        unload_finished_at = seize_at
        try:
            storage_slot: StorageSlot | None = None
            while storage_slot is None:
                storage_slot = self.slot_manager.reserve_for_retrieve(
                    lambda slot: fl.estimate_travel_time(
                        slot.ground_pos,
                        self.outbound_pos._replace(z=0) if self.outbound_pos else fl.position,
                    )
                    + fl.lift_cycle_time(slot.level)
                )
                if storage_slot is None:
                    yield self.env.timeout(0.1)

            def mark_load_start(timestamp: float) -> None:
                nonlocal load_started_at
                load_started_at = timestamp

            def mark_load_end(timestamp: float) -> None:
                nonlocal load_finished_at
                load_finished_at = timestamp

            # Load at storage (with elevation to shelf level)
            yield from fl.perform_lift(
                storage_slot.ground_pos,
                storage_slot.level,
                dwell_status=ForkliftStatus.LOADING,
                on_dwell_start=mark_load_start,
                on_dwell_end=mark_load_end,
            )
            fl.current_load = pallet
            self.slot_manager.complete_retrieve(storage_slot)

            def mark_unload_start(timestamp: float) -> None:
                nonlocal unload_started_at
                unload_started_at = timestamp

            def mark_unload_end(timestamp: float) -> None:
                nonlocal unload_finished_at
                unload_finished_at = timestamp

            # Unload at outbound (with elevation to shelf level)
            yield from fl.perform_lift(
                self.outbound_pos,
                0,
                dwell_time_s=sample_duration_s(self.unloading_time_s, name=f"{self.name}.unloading_time_s") if self.unloading_time_s else 0.0,
                dwell_status=ForkliftStatus.UNLOADING,
                on_dwell_start=mark_unload_start,
                on_dwell_end=mark_unload_end,
            )
            fl.current_load = None

            yield from _run_fleet_post_task(self.fleet, fl)
            release_at = self.env.now
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_enter_to_seize_s",
                enter_at,
                seize_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_seize_to_loading_start_s",
                seize_at,
                load_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_loading_duration_s",
                load_started_at,
                load_finished_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_loading_finish_to_unloading_start_s",
                load_finished_at,
                unload_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_unloading_duration_s",
                unload_started_at,
                unload_finished_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_unloading_finish_to_release_s",
                unload_finished_at,
                release_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_seize_to_load_start_s",
                seize_at,
                unload_started_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_load_duration_s",
                unload_started_at,
                unload_finished_at,
            )
            _record_forklift_movement_duration(
                self.stats,
                "retrieve_unload_finish_to_release_s",
                unload_finished_at,
                release_at,
            )
        finally:
            self.fleet.release(assignment)

        self._record_finish()
        yield from self._forward(pallet)
        self._record_complete()


class Source:
    def __init__(
        self,
        env: simpy.Environment,
        params: Any,
        stats: SimulationStats,
        rng: Random,
        first_block,
        name: str = "source",
        interarrival_time_s: DurationValue | None = None,
        entity_factory: Optional[Callable[[int, float], Pallet]] = None,
        on_exit: Optional[Callable[[Pallet], None]] = None,
        record_created: bool = True,
        push_protocol: bool = False,
        discard_hanging_entities: bool = False,
    ):
        self.env = env
        self.params = params
        self.stats = stats
        self.rng = rng
        self.first_block = first_block
        self.name = name
        self.interarrival_time_s = interarrival_time_s
        self.entity_factory = entity_factory
        self.on_exit = on_exit
        self.record_created = record_created
        self.push_protocol = push_protocol
        self.discard_hanging_entities = discard_hanging_entities
        self._proc: Optional[simpy.Process] = None
        self._counter = 0
        self.emitted_count = 0

    def start(self):
        if self._proc is None:
            self._proc = self.env.process(self._run())

    def _next_interarrival(self) -> float:
        """Return the next interarrival time."""
        if self.interarrival_time_s is not None:
            return sample_duration_s(
                self.interarrival_time_s,
                name=f"{self.name}.interarrival_time_s",
            )
        rate_per_s = self.params.arrival_rate_per_second()
        # Deterministic: fixed interarrival time = 1/rate
        return (1.0 / rate_per_s) if rate_per_s > 0 else float("inf")

    def _batch_size(self) -> int:
        """In this model, always return single pallet per arrival."""
        return 1

    def _new_entity(self) -> Pallet:
        self._counter += 1
        if self.entity_factory is not None:
            return self.entity_factory(self._counter, self.env.now)
        return Pallet(id=self._counter, created_at=self.env.now)

    def inject(self, n: int = 1) -> None:
        """Generate agents immediately, matching AnyLogic Source.inject()."""
        if n < 0:
            raise ValueError("inject count must be >= 0")
        self._emit(n)

    def _emit(self, count: int) -> None:
        if count <= 0:
            return
        if self.record_created:
            self.stats.record_created(count)
        for _ in range(count):
            pallet = self._new_entity()
            self.emitted_count += 1
            if self.on_exit is not None:
                self.on_exit(pallet)
            self.env.process(self.first_block.handle(pallet))

    def _run(self):
        # First arrival at t=0 (matching AnyLogic firstArrivalMode behavior)
        self._emit(self._batch_size())

        # Subsequent arrivals with fixed interarrival time
        while True:
            ia = self._next_interarrival()
            if ia == float("inf"):
                break
            yield self.env.timeout(ia)
            self._emit(self._batch_size())
