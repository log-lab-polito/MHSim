from __future__ import annotations

import math
import simpy
from dataclasses import dataclass, field
from random import Random
from typing import Optional

from .blocks import (
    DelayBlock,
    RetrieveBlock,
    ServiceBlock,
    Sink,
    Source,
    StoreBlock,
)
from .components import ForkliftFleet
from .params import Model1Params
from .stats import Model1Stats


@dataclass
class Model1SimModel:
    params: Model1Params = field(default_factory=Model1Params)
    console_logging: bool = False

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = Model1Stats()
        self.travel_time_fn = self._build_travel_time_fn()

        self.storage = simpy.Container(
            self.env, capacity=self.params.storage_capacity, init=0
        )
        self.fleet = ForkliftFleet(
            self.env,
            count=self.params.n_forklifts,
            store_time_s=self.params.forklift_store_time_s,
            retrieve_time_s=self.params.forklift_retrieve_time_s,
            store_travel_time_s=self.params.forklift_store_travel_time_s,
            retrieve_travel_time_s=self.params.forklift_retrieve_travel_time_s,
            travel_time_fn=self.travel_time_fn,
        )

        self.sink = Sink(self.env, self.stats, name="sink")
        # Downstream service after retrieval
        self.service2 = ServiceBlock(
            self.env,
            service_time_s=self.params.service2_time_s,
            next_block=self.sink,
            name="service2",
            queue_capacity=self.params.service2_queue_capacity,
        )
        self.retrieve = RetrieveBlock(
            self.env,
            storage=self.storage,
            fleet=self.fleet,
            next_block=self.service2,
            name="retrieve",
        )
        self.delay = DelayBlock(
            self.env,
            delay_s=self.params.delay_time_s,
            next_block=self.retrieve,
            name="delay",
        )
        self.store = StoreBlock(
            self.env,
            storage=self.storage,
            fleet=self.fleet,
            next_block=self.delay,
            name="store",
        )
        # Upstream service before storage
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.service1_time_s,
            next_block=self.store,
            name="service1",
            queue_capacity=self.params.service1_queue_capacity,
        )
        self.source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.rng,
            first_block=self.service1,
            name="source",
        )

    def run(self, until: Optional[float] = None) -> Model1Stats:
        self.source.start()
        stop_time = until if until is not None else self.params.sim_time
        self.env.run(until=stop_time)
        if self.console_logging:
            self._log_summary()
        return self.stats

    def _build_travel_time_fn(self):
        params = self.params
        rng = self.rng

        def multiplier() -> float:
            cv = params.travel_time_noise_cv
            if cv <= 0:
                return 1.0
            sigma = math.sqrt(math.log(1 + cv * cv))
            mu = -0.5 * sigma * sigma
            return rng.lognormvariate(mu, sigma)

        def fn(task: str, pallet=None) -> float:
            dist = params.store_distance_m if task == "store" else params.retrieve_distance_m
            if params.forklift_speed_mps <= 0:
                return 0.0
            base = dist / params.forklift_speed_mps
            return base * multiplier()

        return fn

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} storage_level={self.storage.level}"
        )
