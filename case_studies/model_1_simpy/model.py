from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from .blocks import DelayBlock, RetrieveBlock, ServiceBlock, Sink, Source, StoreBlock
from mhsim.logger import SimulationLogger
from .params import Model1Params
from .setup import create_warehouse_with_standard_config
from .stats import Model1Stats
from mhsim.storage_slots import StorageSlotManager


@dataclass
class Model1SimModel:
    params: Model1Params = field(default_factory=Model1Params)
    console_logging: bool = False
    enable_logging: bool = True

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = Model1Stats()

        self.logger: Optional[SimulationLogger] = None
        if self.enable_logging:
            self.logger = SimulationLogger(
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model1"
                )
            )

        self.layout, self.router, self.fleet = create_warehouse_with_standard_config(
            self.env, self.params, stats=self.stats
        )

        self.storage = simpy.Container(
            self.env, capacity=self.params.storage_capacity, init=0
        )

        if self.fleet.forklifts:
            home_position = self.fleet.forklifts[0].position
        else:
            home_position = self.layout.forklifts_home.get_access_point()
        if hasattr(self.fleet, "set_home_position"):
            self.fleet.set_home_position(home_position)
        else:
            self.fleet.home_position = home_position
        self.fleet.return_home_policy = self.params.forklift_return_home_policy

        self.sink = Sink(self.env, self.stats, name="sink", logger=self.logger)
        self.service2 = ServiceBlock(
            self.env,
            service_time_s=self.params.service2_time_s,
            next_block=self.sink,
            name="service2",
            logger=self.logger,
        )

        self.slot_manager = StorageSlotManager(
            self.layout.storage,
            store_policy=self.params.storage_store_policy,
            retrieve_policy=self.params.storage_retrieve_policy,
        )

        self.retrieve = RetrieveBlock(
            self.env,
            storage=self.storage,
            fleet=self.fleet,
            slot_manager=self.slot_manager,
            stats=self.stats,
            next_block=self.service2,
            name="retrieve",
            outbound_pos=self.layout.outbound_area.get_access_point(),
            unloading_time_s=self.params.unloading_time_s,
            request_priority=self.params.forklift_retrieve_priority,
            logger=self.logger,
        )
        self.delay = DelayBlock(
            self.env,
            delay_s=self.params.delay_time_s,
            next_block=self.retrieve,
            name="delay",
            logger=self.logger,
        )
        self.store = StoreBlock(
            self.env,
            storage=self.storage,
            fleet=self.fleet,
            slot_manager=self.slot_manager,
            stats=self.stats,
            next_block=self.delay,
            name="store",
            inbound_pos=self.layout.inbound_area.get_access_point(),
            loading_time_s=self.params.loading_time_s,
            request_priority=self.params.forklift_store_priority,
            logger=self.logger,
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.service1_time_s,
            next_block=self.store,
            name="service1",
            logger=self.logger,
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
        if self.logger:
            self.logger.open()
        try:
            self.source.start()
            stop_time = until if until is not None else self.params.sim_time
            self.env.run(until=stop_time)
            if self.console_logging:
                self._log_summary()
        finally:
            if self.logger:
                self.logger.close()
                print(f"Log file created: {self.logger.log_file}")
        return self.stats

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} storage_level={self.storage.level}"
        )

    def get_storage_level(self) -> int:
        return int(self.storage.level)
