from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from case_studies.model_1_simpy.stats import Model1Stats
from mhsim.blocks import DelayBlock, MoveByTransporterBlock, ServiceBlock, Sink, Source
from mhsim.logger import SimulationLogger

from .params import Model2Params
from .setup import create_model2_warehouse


@dataclass
class Model2SimModel:
    params: Model2Params = field(default_factory=Model2Params)
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
                    self.params, "log_filename_prefix", "simpy_model2"
                )
            )

        self.layout, self.router, self.fleet = create_model2_warehouse(
            self.env, self.params, stats=self.stats
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
        self.move_to_outbound = MoveByTransporterBlock(
            self.env,
            fleet=self.fleet,
            next_block=self.service2,
            name="moveToOutbound",
            pickup_pos=self.layout.storage_rack.get_access_point(),
            dropoff_pos=self.layout.outbound_area.get_access_point(),
            loading_time_s=self.params.retrieve_loading_time_s,
            unloading_time_s=self.params.retrieve_unloading_time_s,
            # Match AnyLogic Model 2 release behavior: after the outbound move,
            # the transporter returns to its home location only when no other
            # tasks are queued.
            apply_post_task_policy_if_auto_seized=True,
            stats=self.stats,
            benchmark_prefix="retrieve",
            logger=self.logger,
        )
        self.delay = DelayBlock(
            self.env,
            delay_s=self.params.delay_time_s,
            next_block=self.move_to_outbound,
            name="delay",
            logger=self.logger,
        )
        self.move_to_storage = MoveByTransporterBlock(
            self.env,
            fleet=self.fleet,
            next_block=self.delay,
            name="moveToStorage",
            pickup_pos=self.layout.receiving_area.get_access_point(),
            dropoff_pos=self.layout.storage_rack.get_access_point(),
            loading_time_s=self.params.store_loading_time_s,
            unloading_time_s=self.params.store_unloading_time_s,
            # Match AnyLogic's release behavior: return to the current home
            # location only when the fleet has no queued work. When a retrieve
            # is already waiting, the transporter remains at storage and the
            # retrieve leg still starts loading immediately.
            apply_post_task_policy_if_auto_seized=True,
            stats=self.stats,
            benchmark_prefix="store",
            logger=self.logger,
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.service1_time_s,
            next_block=self.move_to_storage,
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

    def get_storage_level(self) -> int:
        return max(
            0,
            getattr(self.delay, "entered_count", 0)
            - getattr(self.delay, "completed_count", 0),
        )

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} storage_level={self.get_storage_level()}"
        )
