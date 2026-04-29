from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from mhsim.blocks import (
    ConveyorEnterBlock,
    ConveyorExitBlock,
    ConveyBlock,
    ServiceBlock,
    Sink,
    Source,
)
from mhsim.conveyor import Conveyor
from mhsim.cyclic_position_logger import CyclicPositionLogger
from mhsim.stats import SimulationStats

from .params import Model3Params


@dataclass
class Model3SimModel:
    params: Model3Params = field(default_factory=Model3Params)
    console_logging: bool = False
    enable_logging: bool = True

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = SimulationStats()

        self.logger: Optional[CyclicPositionLogger] = None
        if self.enable_logging:
            self.logger = CyclicPositionLogger(
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model3"
                )
            )

        self.conveyor = Conveyor(
            id="main_conveyor",
            env=self.env,
            length_m=self.params.conveyor_length_m,
            speed_mps=self.params.conveyor_speed_mps,
            max_items=self.params.conveyor_max_items,
            item_length_m=self.params.conveyor_item_length_m,
            min_gap_m=self.params.conveyor_min_gap_m,
        )

        self.sink = Sink(self.env, self.stats, name="sink", logger=self.logger)
        self.service2 = ServiceBlock(
            self.env,
            service_time_s=self.params.service2_time_s,
            next_block=self.sink,
            name="service2",
            logger=self.logger,
        )
        self.conveyor_exit = ConveyorExitBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.service2,
            name="conveyor_exit",
            logger=self.logger,
        )
        self.convey = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.conveyor_exit,
            name="convey",
            logger=self.logger,
        )
        self.conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.convey,
            name="conveyor_enter",
            logger=self.logger,
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.service1_time_s,
            next_block=self.conveyor_enter,
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

    def run(self, until: Optional[float] = None) -> SimulationStats:
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
            f"created={self.stats.created} conveyor_occ={self.conveyor.occupancy}"
        )
