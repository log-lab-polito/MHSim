from __future__ import annotations

import simpy
from random import Random
from typing import Any, Optional, Callable, Generator

from .pallet import Pallet
from .forklift import ForkliftFleet, ForklifStatus, ForkliftAssignment
from .stats import SimulationStats
from .logger import SimulationLogger
from .movement import Position3D
from .storage_slots import StorageSlotManager, StorageSlot


PositionResolver = Optional[Callable[[Pallet], Optional[Position3D]] | Position3D]
DEFAULT_TRANSPORTER_ASSIGNMENT_KEY = "_transporter_assignment"


def _resolve_position(resolver: PositionResolver, pallet: Pallet):
    if callable(resolver):
        return resolver(pallet)
    return resolver


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


class Sink:
    def __init__(self, env: simpy.Environment, stats: SimulationStats, name: str = "sink", logger: Optional[SimulationLogger] = None):
        self.env = env
        self.stats = stats
        self.name = name
        self.logger = logger
        self.entered_count = 0

    def handle(self, pallet: Pallet):
        # Make this a generator so upstream `yield from` never fails.
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)
        yield self.env.timeout(0)
        duration = self.env.now - pallet.created_at
        self.stats.record_completed(duration)


class ServiceBlock:
    def __init__(
        self,
        env: simpy.Environment,
        service_time_s: float,
        next_block,
        name: str = "service",
        capacity: int = 1,
        queue_capacity: int = 0,
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.service_time_s = service_time_s
        self.next_block = next_block
        self.resource = simpy.Resource(env, capacity=capacity)
        self.name = name
        self.queue_capacity = queue_capacity
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)
        if self.queue_capacity and self.queue_capacity > 0:
            # Block upstream until there is room in the waiting line.
            while len(self.resource.queue) >= self.queue_capacity:
                yield self.env.timeout(0)
        with self.resource.request() as req:
            yield req
            yield self.env.timeout(self.service_time_s)
        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class DelayBlock:
    def __init__(self, env: simpy.Environment, delay_s: float, next_block, name: str = "delay", logger: Optional[SimulationLogger] = None):
        self.env = env
        self.delay_s = delay_s
        self.next_block = next_block
        self.name = name
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)
        yield self.env.timeout(self.delay_s)
        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class SeizeTransporterBlock:
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
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.fleet = fleet
        self.next_block = next_block
        self.name = name
        self.request_priority = request_priority
        self.near_position = near_position
        self.pending_attr = pending_attr
        self.assignment_key = assignment_key
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)

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

        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class ReleaseTransporterBlock:
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
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.fleet = fleet
        self.next_block = next_block
        self.name = name
        self.assignment_key = assignment_key
        self.apply_post_task_policy = apply_post_task_policy
        self.strict = strict
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)

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

        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class MoveByTransporterBlock:
    """Move a pallet using a seized transporter (or auto-seize when configured)."""

    def __init__(
        self,
        env: simpy.Environment,
        fleet: ForkliftFleet,
        next_block,
        name: str = "move_by_transporter",
        pickup_pos: PositionResolver = None,
        dropoff_pos: PositionResolver = None,
        loading_time_s: float = 0.0,
        unloading_time_s: float = 0.0,
        request_priority: int = 1,
        assignment_key: str = DEFAULT_TRANSPORTER_ASSIGNMENT_KEY,
        auto_seize_if_missing: bool = True,
        apply_post_task_policy_if_auto_seized: bool = True,
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.fleet = fleet
        self.next_block = next_block
        self.name = name
        self.pickup_pos = pickup_pos
        self.dropoff_pos = dropoff_pos
        self.loading_time_s = loading_time_s
        self.unloading_time_s = unloading_time_s
        self.request_priority = request_priority
        self.assignment_key = assignment_key
        self.auto_seize_if_missing = auto_seize_if_missing
        self.apply_post_task_policy_if_auto_seized = apply_post_task_policy_if_auto_seized
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)

        pickup = _resolve_position(self.pickup_pos, pallet)
        assignment = _get_assignment(pallet, assignment_key=self.assignment_key)
        auto_seized = assignment is None
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

        try:
            fl = assignment.forklift

            if pickup is not None:
                yield from fl.perform_lift(
                    pickup,
                    0,
                    dwell_time_s=self.loading_time_s,
                    dwell_status=ForklifStatus.LOADING,
                )
                fl.current_load = pallet

            dropoff = _resolve_position(self.dropoff_pos, pallet)
            if dropoff is not None:
                yield from fl.perform_lift(
                    dropoff,
                    0,
                    dwell_time_s=self.unloading_time_s,
                    dwell_status=ForklifStatus.UNLOADING,
                )
                fl.current_load = None

            if auto_seized and self.apply_post_task_policy_if_auto_seized:
                yield from _run_fleet_post_task(self.fleet, fl)
        finally:
            if auto_seized:
                self.fleet.release(assignment)

        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class StoreBlock:
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        slot_manager: StorageSlotManager,
        next_block,
        name: str = "store",
        inbound_pos=None,
        loading_time_s: float = 0.0,
        request_priority: int = 1,
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.storage = storage
        self.fleet = fleet
        self.slot_manager = slot_manager
        self.next_block = next_block
        self.name = name
        self.inbound_pos = inbound_pos
        self.loading_time_s = loading_time_s
        self.request_priority = request_priority
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)

        # Block until storage has room (hard capacity constraint)
        while self.storage.level >= self.storage.capacity:
            yield self.env.timeout(0.1)  # Poll every 0.1s until room available

        assignment = yield from _seize_forklift(
            self.fleet,
            priority=self.request_priority,
            pending_attr="pending_store",
            near_position=self.inbound_pos,
        )
        fl = assignment.forklift
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

            # Load at inbound (with elevation to shelf level)
            yield from fl.perform_lift(
                self.inbound_pos,
                0,
                dwell_time_s=self.loading_time_s,
                dwell_status=ForklifStatus.LOADING,
            )
            fl.current_load = pallet

            # Unload at storage (with elevation to shelf level)
            yield from fl.perform_lift(
                storage_slot.ground_pos,
                storage_slot.level,
                dwell_status=ForklifStatus.UNLOADING,
            )
            fl.current_load = None
            self.slot_manager.complete_store(storage_slot)

            yield from _run_fleet_post_task(self.fleet, fl)
        finally:
            self.fleet.release(assignment)

        self.finished_count += 1
        yield self.storage.put(1)
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class RetrieveBlock:
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        slot_manager: StorageSlotManager,
        next_block,
        name: str = "retrieve",
        outbound_pos=None,
        unloading_time_s: float = 0.0,
        request_priority: int = 1,
        logger: Optional[SimulationLogger] = None,
    ):
        self.env = env
        self.storage = storage
        self.fleet = fleet
        self.slot_manager = slot_manager
        self.next_block = next_block
        self.name = name
        self.outbound_pos = outbound_pos
        self.unloading_time_s = unloading_time_s
        self.request_priority = request_priority
        self.logger = logger
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now)
        yield self.storage.get(1)

        assignment = yield from _seize_forklift(
            self.fleet,
            priority=self.request_priority,
            pending_attr="pending_retrieve",
            near_position=self.outbound_pos,
        )
        fl = assignment.forklift
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

            # Load at storage (with elevation to shelf level)
            yield from fl.perform_lift(
                storage_slot.ground_pos,
                storage_slot.level,
                dwell_status=ForklifStatus.LOADING,
            )
            fl.current_load = pallet
            self.slot_manager.complete_retrieve(storage_slot)

            # Unload at outbound (with elevation to shelf level)
            yield from fl.perform_lift(
                self.outbound_pos,
                0,
                dwell_time_s=self.unloading_time_s,
                dwell_status=ForklifStatus.UNLOADING,
            )
            fl.current_load = None

            yield from _run_fleet_post_task(self.fleet, fl)
        finally:
            self.fleet.release(assignment)

        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class Source:
    def __init__(
        self,
        env: simpy.Environment,
        params: Any,
        stats: SimulationStats,
        rng: Random,
        first_block,
        name: str = "source",
    ):
        self.env = env
        self.params = params
        self.stats = stats
        self.rng = rng
        self.first_block = first_block
        self.name = name
        self._proc: Optional[simpy.Process] = None
        self._counter = 0

    def start(self):
        if self._proc is None:
            self._proc = self.env.process(self._run())

    def _next_interarrival(self) -> float:
        """Return deterministic interarrival time (not stochastic)."""
        rate_per_s = self.params.arrival_rate_per_second()
        # Deterministic: fixed interarrival time = 1/rate
        return (1.0 / rate_per_s) if rate_per_s > 0 else float("inf")

    def _batch_size(self) -> int:
        """In this model, always return single pallet per arrival."""
        return 1

    def _run(self):
        # First arrival at t=0 (matching AnyLogic firstArrivalMode behavior)
        batch = self._batch_size()
        self.stats.record_created(batch)
        for _ in range(batch):
            self._counter += 1
            pallet = Pallet(id=self._counter, created_at=self.env.now)
            self.env.process(self.first_block.handle(pallet))

        # Subsequent arrivals with fixed interarrival time
        while True:
            ia = self._next_interarrival()
            if ia == float("inf"):
                break
            yield self.env.timeout(ia)
            batch = self._batch_size()
            self.stats.record_created(batch)
            for _ in range(batch):
                self._counter += 1
                pallet = Pallet(id=self._counter, created_at=self.env.now)
                self.env.process(self.first_block.handle(pallet))
