from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from pathlib import Path
from typing import Optional

import simpy

from mhsim.stats import Model5Stats
from mhsim.blocks import MoveByTransporterBlock, Sink, Source
from mhsim.cyclic_position_logger import CyclicPositionLogger
from mhsim.random_variables import DurationValue, make_duration_sampler, make_service_time

from .benchmark_labels import MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS
from .params import Model1Params
from .setup import create_model1_warehouse

# Case-study traces go to the repository's logs/, wherever the run is launched.
REPO_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


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
                log_dir=REPO_LOG_DIR,
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model1"
                ),
                # Model 1 keeps internal coordinates scaled by /10 from the
                # AnyLogic presentation, but the reference cyclic log records
                # the original presentation x/y coordinates.
                position_scale=10.0,
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
            loading_time_s=self._service_time(
                self.params.move_loading_time_s,
                "moveByTransporter.loading",
            ),
            unloading_time_s=self._service_time(
                self.params.move_unloading_time_s,
                "moveByTransporter.unloading",
            ),
            apply_post_task_policy_if_auto_seized=True,
            stats=self.stats,
            benchmark_prefix="move",
            benchmark_loading_boundary_offset_s=(
                self.params.move_benchmark_loading_boundary_offset_s
            ),
            logger=self.logger,
        )
        self.source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.rng,
            first_block=self.move_by_transporter,
            name="source",
            interarrival_time_s=self._interarrival_time(),
        )

    def _service_time(self, mean_s: float, name: str) -> DurationValue:
        return make_service_time(self.params, self.rng, mean_s, name)

    def _interarrival_time(self) -> DurationValue | None:
        if not self.params.random_arrival_times:
            return None
        return make_duration_sampler(
            self.params.arrival_rate_s,
            rng=self.rng,
            distribution=self.params.arrival_time_distribution,
            name="source.interarrival_time_s",
        )

    def run(self, until: Optional[float] = None) -> Model5Stats:
        if self.logger:
            self.logger.open()
        try:
            if self.logger:
                self.logger.start(
                    self.env,
                    self.fleet.forklifts,
                    interval_s=self.params.log_interval_s,
                )
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
        avg_wip = (
            self.stats.avg_time_in_system * (self.stats.completed / self.env.now)
            if self.env.now else 0.0
        )
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} avg_wip={avg_wip:.2f}"
        )
