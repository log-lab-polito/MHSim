from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Optional

import simpy

from mhsim.blocks import (
    BatchBlock,
    ConveyorEnterBlock,
    ConveyorExitBlock,
    ConveyBlock,
    ServiceBlock,
    Sink,
    Source,
)
from mhsim.pallet import Pallet
from mhsim.random_variables import (
    DurationValue,
    make_duration_sampler,
    make_service_time,
)
from mhsim.stats import SimulationStats

from .params import Model6Params
from .setup import Model6Markup, create_model6_markup


@dataclass
class Model6SimModel:
    params: Model6Params = field(default_factory=Model6Params)
    console_logging: bool = False

    def __post_init__(self) -> None:
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.item_count_rng = Random(self.params.item_count_random_seed)
        self.unbatch_rng = Random(self.params.unbatch_random_seed)
        self.stats = SimulationStats()
        self.empty_pallets_completed = 0
        self.loose_items_created = 0
        self._loaded_pallet_counter = 0

        self.markup = create_model6_markup(
            self.env,
            self.params,
            on_unbatch_started=self._on_unbatch_station_started,
        )
        self.conveyor = self.markup.conveyor
        self.storage_conveyor = self.markup.storage_conveyor

        self.completed_pallet_sink = Sink(
            self.env,
            self.stats,
            name="completedPalletSink",
            on_enter=self._on_completed_pallet_enter,
            record_stats=False,
        )
        self.outbound_pallet_service = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service2_time_s, "service2"),
            next_block=self.completed_pallet_sink,
            name="outboundPalletService",
        )
        self.loaded_pallet_conveyor_exit = ConveyorExitBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.outbound_pallet_service,
            name="loadedPalletConveyorExit",
        )
        self.convey_loaded_pallet_to_exit = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.loaded_pallet_conveyor_exit,
            name="conveyLoadedPalletToExit",
            source_position=self.markup.batch_transfer_point,
            target_conveyor=self.conveyor,
        )
        self.batch = BatchBlock(
            self.env,
            batch_size=self.params.batch_size,
            new_batch_factory=self._new_loaded_pallet,
            next_block=self.convey_loaded_pallet_to_exit,
            name="batch",
            permanent=True,
        )
        self.convey_items_to_batch_station = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.batch,
            name="conveyItemsToBatchStation",
            source_position=self.markup.unbatch_transfer_point,
            target_station=self.markup.batch_station,
        )
        self.item_conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.convey_items_to_batch_station,
            name="itemConveyorEnter",
            position=self.markup.unbatch_transfer_point,
        )
        self.loose_item_source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.rng,
            first_block=self.item_conveyor_enter,
            name="looseItemSource",
            entity_factory=self._new_loose_item,
            record_created=False,
        )

        self.empty_pallet_sink = Sink(
            self.env,
            self.stats,
            name="emptyPalletSink",
            on_enter=self._on_empty_pallet_enter,
            record_stats=False,
        )
        self.covey_empty_pallet_to_storage = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.empty_pallet_sink,
            name="coveyEmptyPalletToStorage",
            source_position=self.markup.unbatch_transfer_point,
            target_conveyor=self.storage_conveyor,
            remove_from_conveyor_on_exit=True,
        )
        self.convey_pallet_to_unbatch_station = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.covey_empty_pallet_to_storage,
            name="conveyPalletToUnbatchStation",
            target_station=self.markup.unbatch_station,
        )
        self.pallet_conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.convey_pallet_to_unbatch_station,
            name="palletConveyorEnter",
        )
        self.inbound_pallet_service = ServiceBlock(
            self.env,
            service_time_s=self._service_time(self.params.service1_time_s, "service1"),
            next_block=self.pallet_conveyor_enter,
            name="inboundPalletService",
        )
        self.inbound_pallet_source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.rng,
            first_block=self.inbound_pallet_service,
            name="inboundPalletSource",
            interarrival_time_s=self._interarrival_time(),
            entity_factory=self._new_inbound_pallet,
            on_exit=self._on_inbound_pallet_exit,
            record_created=False,
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
            name="inboundPalletSource.interarrival_time_s",
        )

    def _new_inbound_pallet(self, entity_id: int, now_s: float) -> Pallet:
        return Pallet(
            id=entity_id,
            created_at=now_s,
            attributes={"entity_type": "inbound_pallet"},
        )

    def _on_inbound_pallet_exit(self, pallet: Pallet) -> None:
        pallet.created_at = self.env.now
        pallet.attributes["cycle_start_time"] = self.env.now
        pallet.attributes["current_nof_items"] = self.item_count_rng.randint(
            self.params.min_items_per_pallet,
            self.params.max_items_per_pallet,
        )
        self.stats.record_created()

    def _new_loose_item(self, entity_id: int, now_s: float) -> Pallet:
        return Pallet(
            id=entity_id,
            created_at=now_s,
            attributes={"entity_type": "loose_item"},
        )

    def _on_unbatch_station_started(self, pallet: Pallet) -> None:
        current_nof_items = int(pallet.attributes.get("current_nof_items", 1))
        items_count = self.unbatch_rng.randint(1, max(1, current_nof_items))
        self.loose_items_created += items_count
        self.loose_item_source.inject(items_count)

    def _on_empty_pallet_enter(self, _pallet: Pallet) -> None:
        self.empty_pallets_completed += 1

    def _new_loaded_pallet(self, originals: list[Pallet]) -> Pallet:
        self._loaded_pallet_counter += 1
        return Pallet(
            id=self._loaded_pallet_counter,
            created_at=self.env.now,
            attributes={
                "entity_type": "loaded_pallet",
                "cycle_start_time": 0.0,
                "batched_item_count": len(originals),
            },
        )

    def _on_completed_pallet_enter(self, pallet: Pallet) -> None:
        cycle_start = float(pallet.attributes.get("cycle_start_time", pallet.created_at))
        self.stats.record_completed(self.env.now - cycle_start)

    def run(self, until: Optional[float] = None) -> SimulationStats:
        self.inbound_pallet_source.start()
        stop_time = until if until is not None else self.params.sim_time
        self.env.run(until=stop_time + 1e-9)
        if self.console_logging:
            self._log_summary()
        return self.stats

    def _log_summary(self) -> None:
        throughput_per_hour = (
            self.stats.completed / self.env.now * 3600.0 if self.env.now else 0.0
        )
        print(
            f"created={self.stats.created} completed={self.stats.completed} "
            f"avg_cycle={self.stats.avg_time_in_system:.2f}s "
            f"throughput={throughput_per_hour:.2f}/h "
            f"main_occ={self.conveyor.occupancy} "
            f"storage_occ={self.storage_conveyor.occupancy}"
        )
