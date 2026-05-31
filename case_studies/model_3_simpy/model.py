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
from mhsim.random_variables import DurationValue, make_duration_sampler, make_service_time
from mhsim.stats import SimulationStats

from .params import Model3Params
from .setup import create_model3_conveyor


@dataclass
class Model3SimModel:
    params: Model3Params = field(default_factory=Model3Params)
    console_logging: bool = False

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = SimulationStats()

        self.conveyor = create_model3_conveyor(self.env, self.params)

        self.sink = Sink(self.env, self.stats, name="sink")
        self.service2 = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service2_time_s, "service2"),
            next_block=self.sink,
            name="service2",
        )
        self.conveyor_exit = ConveyorExitBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.service2,
            name="conveyor_exit",
        )
        self.convey = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.conveyor_exit,
            name="convey",
        )
        self.conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.convey,
            name="conveyor_enter",
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service1_time_s, "service1"),
            next_block=self.conveyor_enter,
            name="service1",
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
        return make_duration_sampler(
            self.params.arrival_rate_s,
            rng=self.rng,
            distribution=self.params.arrival_time_distribution,
            name="source.interarrival_time_s",
        )

    def run(self, until: Optional[float] = None) -> SimulationStats:
        self.source.start()
        stop_time = until if until is not None else self.params.sim_time
        # AnyLogic's cyclic source event at the final stop time still injects
        # an entity. SimPy run(until=t) stops before events scheduled exactly
        # at t, so advance by a tiny epsilon to process boundary events.
        self.env.run(until=stop_time + 1e-9)
        if self.console_logging:
            self._log_summary()
        return self.stats

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} conveyor_occ={self.conveyor.occupancy}"
        )
