from __future__ import annotations

import simpy
from random import Random
from typing import Optional

from .pallet import Pallet
from .forklift import ForkliftFleet
from .params import Model1Params
from .stats import Model1Stats
from .logger import SimulationLogger
from .storage_slots import StorageSlotManager, StorageSlot


class Sink:
    def __init__(self, env: simpy.Environment, stats: Model1Stats, name: str = "sink", logger: Optional[SimulationLogger] = None):
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
                self.name, f"Pallet {pallet.id}", self.env.now)
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

        # Request forklift from fleet with priority=2 (lower priority than retrieve)
        with self.fleet.resource.request(priority=2) as req:
            # Track waiting requests for visualization/metrics
            if hasattr(self.fleet, "pending_store"):
                self.fleet.pending_store += 1
            yield req  # Wait for forklift to be available
            if hasattr(self.fleet, "pending_store"):
                self.fleet.pending_store -= 1

            fl = self.fleet.get_available_forklift()
            if not fl:
                # Fallback if no forklift available (shouldn't happen)
                yield self.env.timeout(0)
            else:
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
                )

                # Unload at storage (with elevation to shelf level)
                yield from fl.perform_lift(
                    storage_slot.ground_pos,
                    storage_slot.level,
                )
                self.slot_manager.complete_store(storage_slot)

                # Do not force return-to-home; keep forklift at last position

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

        # Request forklift from fleet with priority=1 (higher priority than store)
        with self.fleet.resource.request(priority=1) as req:
            # Track waiting requests for visualization/metrics
            if hasattr(self.fleet, "pending_retrieve"):
                self.fleet.pending_retrieve += 1
            yield req  # Wait for forklift to be available
            if hasattr(self.fleet, "pending_retrieve"):
                self.fleet.pending_retrieve -= 1

            fl = self.fleet.get_available_forklift()
            if not fl:
                # Fallback if no forklift available (shouldn't happen)
                yield self.env.timeout(0)
            else:
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
                )
                self.slot_manager.complete_retrieve(storage_slot)

                # Unload at outbound (with elevation to shelf level)
                yield from fl.perform_lift(
                    self.outbound_pos,
                    0,
                    dwell_time_s=self.unloading_time_s,
                )

                # Do not force return-to-home; keep forklift at last position

        self.finished_count += 1
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class Source:
    def __init__(
        self,
        env: simpy.Environment,
        params: Model1Params,
        stats: Model1Stats,
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
