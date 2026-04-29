from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from case_studies.model_5_simpy.stats import Model5Stats
from mhsim.blocks import MoveByTransporterBlock, Sink, Source
from mhsim.cyclic_position_logger import CyclicPositionLogger

from .benchmark_labels import MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS
from .params import Model1Params
from .setup import create_model1_warehouse


@dataclass
class Model1SimModel:
    params: Model1Params = field(default_factory=Model1Params)
    console_logging: bool = False
    enable_logging: bool = True

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = Model5Stats()
        self.stats.forklift_movement_benchmark_labels = (
            MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS
        )

        self.logger: Optional[CyclicPositionLogger] = None
        if self.enable_logging:
            self.logger = CyclicPositionLogger(
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model1"
                )
            )

        self.layout, self.router, self.fleet = create_model1_warehouse(
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
        self.move_by_transporter = MoveByTransporterBlock(
            self.env,
            fleet=self.fleet,
            next_block=self.sink,
            name="moveByTransporter",
            pickup_pos=self.layout.A.get_access_point(),
            dropoff_pos=self.layout.B.get_access_point(),
            loading_time_s=self.params.move_loading_time_s,
            unloading_time_s=self.params.move_unloading_time_s,
            apply_post_task_policy_if_auto_seized=True,
            stats=self.stats,
            benchmark_prefix="move",
            logger=self.logger,
        )
        self.source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.rng,
            first_block=self.move_by_transporter,
            name="source",
        )

    def run(self, until: Optional[float] = None) -> Model5Stats:
        if self.logger:
            self.logger.open()
        try:
            if self.logger:
                self.logger.start(self.env, self.fleet.forklifts)
            self.source.start()
            stop_time = until if until is not None else self.params.sim_time
            # AnyLogic's cyclic source event at the final stop time still
            # injects an entity, leaving it in flight. SimPy's run(until=t)
            # stops before events scheduled exactly at t, so advance by a
            # tiny epsilon to process only same-time events at the boundary.
            self.env.run(until=stop_time + 1e-9)
            if self.console_logging:
                self._log_summary()
        finally:
            if self.logger:
                self.logger.close()
                print(f"Log file created: {self.logger.log_file}")
        return self.stats

    def _log_summary(self) -> None:
        in_flight = self.stats.created - self.stats.completed
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} in_flight={in_flight}"
        )
