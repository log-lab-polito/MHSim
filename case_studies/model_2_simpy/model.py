from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from mhsim.stats import Model5Stats
from mhsim.blocks import DelayBlock, MoveByTransporterBlock, ServiceBlock, Sink, Source
from mhsim.cyclic_position_logger import CyclicPositionLogger
from mhsim.forklift import ForkliftMovementOverrides
from mhsim.movement import Position3D
from mhsim.random_variables import DurationValue, make_duration_sampler, make_service_time

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
        self.stats = Model5Stats()

        self.logger: Optional[CyclicPositionLogger] = None
        if self.enable_logging:
            self.logger = CyclicPositionLogger(
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
            service_time_s=self._service_time(self.params.service2_time_s, "service2"),
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
            dropoff_pos=Position3D(
                self.params.retrieve_dropoff_x,
                self.params.retrieve_dropoff_y,
                self.params.retrieve_dropoff_z,
            ),
            loading_time_s=self._service_time(
                self.params.retrieve_loading_time_s,
                "moveToOutbound.loading",
            ),
            unloading_time_s=self._service_time(
                self.params.retrieve_unloading_time_s,
                "moveToOutbound.unloading",
            ),
            # Keep the outbound release/return policy explicit so parity runs
            # can test whether AnyLogic releases-and-returns or leaves the
            # forklift parked after this specific block.
            apply_post_task_policy_if_auto_seized=(
                self.params.move_to_outbound_apply_post_task_policy
            ),
            stats=self.stats,
            benchmark_prefix="retrieve",
            pickup_movement_overrides=self._movement_overrides(
                self.params.move_to_outbound_pickup_routed_motion_mode
            ),
            dropoff_movement_overrides=self._movement_overrides(
                self.params.move_to_outbound_dropoff_routed_motion_mode
            ),
            logger=self.logger,
        )
        self.delay = DelayBlock(
            self.env,
            delay_s=self._service_time(self.params.delay_time_s, "delay"),
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
            loading_time_s=self._service_time(
                self.params.store_loading_time_s,
                "moveToStorage.loading",
            ),
            unloading_time_s=self._service_time(
                self.params.store_unloading_time_s,
                "moveToStorage.unloading",
            ),
            # Keep the storage release/return policy independent from outbound;
            # AnyLogic's visible timing suggests the two blocks can differ.
            apply_post_task_policy_if_auto_seized=(
                self.params.move_to_storage_apply_post_task_policy
            ),
            stats=self.stats,
            benchmark_prefix="store",
            pickup_movement_overrides=self._movement_overrides(
                self.params.move_to_storage_pickup_routed_motion_mode
            ),
            dropoff_movement_overrides=self._movement_overrides(
                self.params.move_to_storage_dropoff_routed_motion_mode
            ),
            logger=self.logger,
        )
        self.service1 = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service1_time_s, "service1"),
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

    @staticmethod
    def _movement_overrides(
        routed_motion_mode: str | None,
    ) -> ForkliftMovementOverrides | None:
        if routed_motion_mode is None:
            return None
        return ForkliftMovementOverrides(routed_motion_mode=routed_motion_mode)

    def run(self, until: Optional[float] = None) -> Model5Stats:
        if self.logger:
            self.logger.open()
        try:
            if self.logger:
                self.logger.start(self.env, self.fleet.forklifts)
            self.source.start()
            stop_time = until if until is not None else self.params.sim_time
            # SimPy does not process events exactly at ``until``. AnyLogic and
            # Model 1 include source events on the stop boundary, so advance by
            # a tiny epsilon to keep the final cyclic arrival visible.
            self.env.run(until=stop_time + 1e-9)
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
            - getattr(self.delay, "finished_count", 0),
        )

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} storage_level={self.get_storage_level()}"
        )
