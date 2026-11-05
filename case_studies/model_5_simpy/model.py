from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from pathlib import Path
from typing import Optional

import simpy

from mhsim.blocks import DelayBlock, RetrieveBlock, ServiceBlock, Sink, Source, StoreBlock
from mhsim.cyclic_position_logger import CyclicPositionLogger
from .params import Model5Params
from mhsim.random_variables import DurationValue, make_duration_sampler, make_service_time
from .setup import create_warehouse_with_standard_config
from .stats import Model5Stats
from mhsim.storage_slots import StorageSlotManager

# Case-study traces go to the repository's logs/, wherever the run is launched.
REPO_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


@dataclass
class Model5SimModel:
    params: Model5Params = field(default_factory=Model5Params)
    console_logging: bool = False
    enable_logging: bool = True

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = Model5Stats()

        self.logger: Optional[CyclicPositionLogger] = None
        if self.enable_logging:
            self.logger = CyclicPositionLogger(
                log_dir=REPO_LOG_DIR,
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model5"
                )
            )

        self.layout, self.router, self.fleet = create_warehouse_with_standard_config(
            self.env, self.params, stats=self.stats
        )

        self.storage = simpy.Container(
            self.env, capacity=self.params.storage_capacity, init=0
        )

        homes = {(f.home_position.x, f.home_position.y) for f in self.fleet.forklifts if f.home_position}
        if len(homes) <= 1:
            # One shared home; with per-forklift home spots (R9) each keeps its own.
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
            service_time_s=self._service_time(self.params.service2_time_s, "service2"),
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
            unloading_time_s=self._service_time(self.params.unloading_time_s, "retrieve.unloading"),
            request_priority=self.params.forklift_retrieve_priority,
            logger=self.logger,
        )
        self.delay = DelayBlock(
            self.env,
            delay_s=self._service_time(self.params.delay_time_s, "delay"),
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
            loading_time_s=self._service_time(self.params.loading_time_s, "store.loading"),
            request_priority=self.params.forklift_store_priority,
            logger=self.logger,
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service1_time_s, "service1"),
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
            interarrival_time_s=self._interarrival_time(),
        )

    def _service_time(self, mean_s: float, name: str) -> DurationValue:
        return make_service_time(self.params, self.rng, mean_s, name)

    def _interarrival_time(self) -> DurationValue | None:
        if not self.params.random_arrival_times:
            return None
        mean_s = 1.0 / self.params.arrival_rate_per_second()
        return make_duration_sampler(
            mean_s,
            rng=self.rng,
            distribution=self.params.arrival_time_distribution,
            name="source.interarrival_time_s",
        )

    def run(self, until: Optional[float] = None) -> Model5Stats:
        if self.logger:
            self.logger.open()
        try:
            if self.logger:
                self.logger.start(self.env, self.fleet.forklifts)
            self.source.start()
            stop_time = until if until is not None else self.params.sim_time
            # SimPy does not process events exactly at ``until``. AnyLogic
            # includes source events on the stop boundary, so advance by a
            # tiny epsilon to keep the final cyclic arrival visible.
            self.env.run(until=stop_time + 1e-9)
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
