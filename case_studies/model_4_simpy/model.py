from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import simpy

from mhsim.blocks import (
    ConveyorEnterBlock,
    ConveyorExitBlock,
    ConveyorSpurBlock,
    ConveyBlock,
    ServiceBlock,
    Sink,
)
from mhsim.conveyor import Conveyor, ConveyorSpur
from mhsim.logger import SimulationLogger
from mhsim.pallet import Pallet
from mhsim.stats import SimulationStats

from .params import Model4Params


class DeterministicSource:
    """Minimal deterministic source used for multi-line test models."""

    def __init__(
        self,
        env: simpy.Environment,
        stats: SimulationStats,
        arrival_rate_per_second: float,
        first_block,
        pallet_id_supplier: Callable[[], int],
        origin: str,
        name: str,
    ):
        self.env = env
        self.stats = stats
        self.arrival_rate_per_second = arrival_rate_per_second
        self.first_block = first_block
        self.pallet_id_supplier = pallet_id_supplier
        self.origin = origin
        self.name = name
        self._proc: Optional[simpy.Process] = None
        self.emitted_count = 0

    def start(self):
        if self._proc is None:
            self._proc = self.env.process(self._run())

    def _next_interarrival(self) -> float:
        if self.arrival_rate_per_second <= 0:
            return float("inf")
        return 1.0 / self.arrival_rate_per_second

    def _emit_one(self) -> None:
        self.stats.record_created(1)
        self.emitted_count += 1
        pallet = Pallet(
            id=self.pallet_id_supplier(),
            created_at=self.env.now,
            attributes={"origin": self.origin},
        )
        self.env.process(self.first_block.handle(pallet))

    def _run(self):
        self._emit_one()
        while True:
            ia = self._next_interarrival()
            if ia == float("inf"):
                break
            yield self.env.timeout(ia)
            self._emit_one()


class OriginTrackingSink:
    def __init__(self, sink: Sink):
        self.sink = sink
        self.completed_by_origin: dict[str, int] = {}

    @property
    def entered_count(self) -> int:
        return self.sink.entered_count

    def handle(self, pallet: Pallet):
        origin = str(pallet.attributes.get("origin", "unknown"))
        self.completed_by_origin[origin] = self.completed_by_origin.get(origin, 0) + 1
        yield from self.sink.handle(pallet)


@dataclass
class Model4SimModel:
    params: Model4Params = field(default_factory=Model4Params)
    console_logging: bool = False
    enable_logging: bool = True

    def __post_init__(self):
        self.env = simpy.Environment()
        self.stats = SimulationStats()
        self._pallet_counter = 0

        self.logger: Optional[SimulationLogger] = None
        if self.enable_logging:
            self.logger = SimulationLogger(
                filename_prefix=getattr(
                    self.params, "log_filename_prefix", "simpy_model4"
                )
            )

        self.main_conveyor = Conveyor(
            id="main_conveyor",
            env=self.env,
            length_m=self.params.main_conveyor_length_m,
            speed_mps=self.params.main_conveyor_speed_mps,
            max_items=self.params.main_conveyor_max_items,
            item_length_m=self.params.main_conveyor_item_length_m,
            min_gap_m=self.params.main_conveyor_min_gap_m,
        )
        self.branch_conveyor = Conveyor(
            id="branch_conveyor",
            env=self.env,
            length_m=self.params.branch_conveyor_length_m,
            speed_mps=self.params.branch_conveyor_speed_mps,
            max_items=self.params.branch_conveyor_max_items,
            item_length_m=self.params.branch_conveyor_item_length_m,
            min_gap_m=self.params.branch_conveyor_min_gap_m,
        )
        self.spur = ConveyorSpur(
            id="branch_to_main_spur",
            env=self.env,
            source_conveyor=self.branch_conveyor,
            target_conveyor=self.main_conveyor,
            target_offset_m=self.params.spur_merge_offset_m,
        )

        self.base_sink = Sink(self.env, self.stats, name="sink", logger=self.logger)
        self.sink = OriginTrackingSink(self.base_sink)
        self.service2 = ServiceBlock(
            self.env,
            service_time_s=self.params.downstream_service_time_s,
            next_block=self.sink,
            name="service2",
            logger=self.logger,
        )
        self.main_conveyor_exit = ConveyorExitBlock(
            self.env,
            conveyor=self.main_conveyor,
            next_block=self.service2,
            name="main_conveyor_exit",
            logger=self.logger,
        )
        self.main_convey = ConveyBlock(
            self.env,
            conveyor=self.main_conveyor,
            next_block=self.main_conveyor_exit,
            name="main_convey",
            logger=self.logger,
        )
        self.main_conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.main_conveyor,
            next_block=self.main_convey,
            name="main_conveyor_enter",
            logger=self.logger,
        )
        self.main_service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.main_service_time_s,
            next_block=self.main_conveyor_enter,
            name="main_service1",
            logger=self.logger,
        )

        self.branch_merge_convey = ConveyBlock(
            self.env,
            conveyor=self.main_conveyor,
            distance_m=self.spur.remaining_target_distance_m(),
            next_block=self.main_conveyor_exit,
            name="branch_merge_convey",
            logger=self.logger,
        )
        self.conveyor_spur = ConveyorSpurBlock(
            self.env,
            spur=self.spur,
            next_block=self.branch_merge_convey,
            name="conveyor_spur",
            logger=self.logger,
        )
        self.branch_convey = ConveyBlock(
            self.env,
            conveyor=self.branch_conveyor,
            next_block=self.conveyor_spur,
            name="branch_convey",
            logger=self.logger,
        )
        self.branch_conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.branch_conveyor,
            next_block=self.branch_convey,
            name="branch_conveyor_enter",
            logger=self.logger,
        )
        self.branch_service1 = ServiceBlock(
            self.env,
            service_time_s=self.params.branch_service_time_s,
            next_block=self.branch_conveyor_enter,
            name="branch_service1",
            logger=self.logger,
        )

        self.main_source = DeterministicSource(
            self.env,
            stats=self.stats,
            arrival_rate_per_second=self.params.main_arrival_rate_per_second(),
            first_block=self.main_service1,
            pallet_id_supplier=self._next_pallet_id,
            origin="main",
            name="main_source",
        )
        self.branch_source = DeterministicSource(
            self.env,
            stats=self.stats,
            arrival_rate_per_second=self.params.branch_arrival_rate_per_second(),
            first_block=self.branch_service1,
            pallet_id_supplier=self._next_pallet_id,
            origin="branch",
            name="branch_source",
        )

    def _next_pallet_id(self) -> int:
        self._pallet_counter += 1
        return self._pallet_counter

    def run(self, until: Optional[float] = None) -> SimulationStats:
        if self.logger:
            self.logger.open()
        try:
            self.main_source.start()
            self.branch_source.start()
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
            f"main_created={self.main_source.emitted_count} "
            f"branch_created={self.branch_source.emitted_count} "
            f"main_occ={self.main_conveyor.occupancy} "
            f"branch_occ={self.branch_conveyor.occupancy} "
            f"spur_transfers={self.spur.total_transferred}"
        )
