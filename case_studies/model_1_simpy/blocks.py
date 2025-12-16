from __future__ import annotations

import simpy
from random import Random
from typing import Optional

from .components import Pallet, ForkliftFleet
from .params import Model1Params
from .stats import Model1Stats


class Sink:
    def __init__(self, env: simpy.Environment, stats: Model1Stats, name: str = "sink"):
        self.env = env
        self.stats = stats
        self.name = name

    def handle(self, pallet: Pallet):
        # Make this a generator so upstream `yield from` never fails.
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
    ):
        self.env = env
        self.service_time_s = service_time_s
        self.next_block = next_block
        self.resource = simpy.Resource(env, capacity=capacity)
        self.name = name
        self.queue_capacity = queue_capacity

    def handle(self, pallet: Pallet):
        if self.queue_capacity and self.queue_capacity > 0:
            # Block upstream until there is room in the waiting line.
            while len(self.resource.queue) >= self.queue_capacity:
                yield self.env.timeout(0)
        with self.resource.request() as req:
            yield req
            yield self.env.timeout(self.service_time_s)
        if self.next_block:
            yield from self.next_block.handle(pallet)


class DelayBlock:
    def __init__(self, env: simpy.Environment, delay_s: float, next_block, name: str = "delay"):
        self.env = env
        self.delay_s = delay_s
        self.next_block = next_block
        self.name = name

    def handle(self, pallet: Pallet):
        yield self.env.timeout(self.delay_s)
        if self.next_block:
            yield from self.next_block.handle(pallet)


class StoreBlock:
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        next_block,
        name: str = "store",
    ):
        self.env = env
        self.storage = storage
        self.fleet = fleet
        self.next_block = next_block
        self.name = name

    def handle(self, pallet: Pallet):
        yield self.env.process(self.fleet.store(pallet))
        yield self.storage.put(1)
        if self.next_block:
            yield from self.next_block.handle(pallet)


class RetrieveBlock:
    def __init__(
        self,
        env: simpy.Environment,
        storage: simpy.Container,
        fleet: ForkliftFleet,
        next_block,
        name: str = "retrieve",
    ):
        self.env = env
        self.storage = storage
        self.fleet = fleet
        self.next_block = next_block
        self.name = name

    def handle(self, pallet: Pallet):
        yield self.storage.get(1)
        yield self.env.process(self.fleet.retrieve(pallet))
        if self.next_block:
            yield from self.next_block.handle(pallet)


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
        rate_per_s = self.params.arrival_rate_per_second()
        return self.rng.expovariate(rate_per_s) if rate_per_s > 0 else float("inf")

    def _batch_size(self) -> int:
        return self.rng.randint(
            self.params.pallet_per_arrival_min,
            self.params.pallet_per_arrival_max,
        )

    def _run(self):
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
