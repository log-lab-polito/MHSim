from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

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
from mhsim.random_streams import JavaRandom
from mhsim.stats import SimulationStats

from .params import Model6Params
from .setup import Model6Markup, create_model6_markup


@dataclass
class Model6SimModel:
    params: Model6Params = field(default_factory=Model6Params)
    console_logging: bool = False

    def __post_init__(self) -> None:
        self.env = simpy.Environment()
        self.timing_rng = JavaRandom(self.params.timing_random_seed)
        self.item_count_rng = JavaRandom(self.params.item_count_random_seed)
        self.unbatch_rng = JavaRandom(self.params.unbatch_random_seed)
        self.stats = SimulationStats()
        self.main_conveyor_occupancy_end = 0
        self.storage_conveyor_occupancy_end = 0
        self.empty_pallets_completed = 0
        self.loose_items_created = 0
        self._loaded_pallet_counter = 0
        self.diagnostic_events: list[str] = []
        self.debug_events: list[str] = []
        self.rng_events: list[str] = []
        self._item_count_replay = self._replay_iter(self.params.item_count_replay)
        self._unbatch_count_replay = self._replay_iter(self.params.unbatch_count_replay)

        self.markup = create_model6_markup(
            self.env,
            self.params,
            on_unbatch_started=self._on_unbatch_station_started,
            on_unbatch_released=self._on_unbatch_station_released,
            on_batch_released=self._on_batch_station_released,
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
            on_exit=self._on_loaded_pallet_conveyor_exit,
        )
        self.convey_loaded_pallet_to_exit = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.loaded_pallet_conveyor_exit,
            name="conveyLoadedPalletToExit",
            source_position=self.markup.batch_transfer_point,
            target_conveyor=self.conveyor,
            enforce_source_position_headway=True,
            on_enter=self._on_loaded_pallet_convey_enter,
        )
        self.batch = BatchBlock(
            self.env,
            batch_size=self.params.batch_size,
            new_batch_factory=self._new_loaded_pallet,
            next_block=self.convey_loaded_pallet_to_exit,
            name="batch",
            permanent=True,
            on_add=self._on_batch_add,
            on_exit=self._on_batch_exit,
        )
        self.convey_items_to_batch_station = ConveyBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.batch,
            name="conveyItemsToBatchStation",
            source_position=self.markup.unbatch_transfer_point,
            target_station=self.markup.batch_station,
            enforce_source_position_headway=True,
        )
        self.item_conveyor_enter = ConveyorEnterBlock(
            self.env,
            conveyor=self.conveyor,
            next_block=self.convey_items_to_batch_station,
            name="itemConveyorEnter",
            position=self.markup.unbatch_transfer_point,
            enforce_position_headway=True,
            on_at_enter=self._on_item_conveyor_enter,
        )
        self.loose_item_source = Source(
            self.env,
            params=self.params,
            stats=self.stats,
            rng=self.timing_rng,
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
            remove_from_conveyor_on_exit=(
                self.params.empty_pallet_remove_from_storage_conveyor
            ),
            enforce_source_position_headway=True,
            on_exit=self._on_empty_pallet_transfer_exit,
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
            on_at_enter=self._on_pallet_conveyor_enter,
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
            rng=self.timing_rng,
            first_block=self.inbound_pallet_service,
            name="inboundPalletSource",
            interarrival_time_s=self._interarrival_time(),
            entity_factory=self._new_inbound_pallet,
            on_exit=self._on_inbound_pallet_exit,
            record_created=False,
        )

    def _service_time(self, mean_s: float, name: str) -> DurationValue:
        return make_service_time(self.params, self.timing_rng, mean_s, name)

    def _interarrival_time(self) -> DurationValue | None:
        if not self.params.random_arrival_times:
            return None
        return make_duration_sampler(
            self.params.arrival_rate_s,
            rng=self.timing_rng,
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
        replay_value = self._next_replay_value(
            "source_item_count",
            self.params.min_items_per_pallet,
            self.params.max_items_per_pallet,
            self._item_count_replay,
        )
        pallet.attributes["current_nof_items"] = (
            replay_value
            if replay_value is not None
            else self._rng_randint(
                "source_item_count",
                self.item_count_rng,
                self.params.min_items_per_pallet,
                self.params.max_items_per_pallet,
            )
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
        self._record_diagnostic_event(
            "unbatch_started",
            pallet,
            current_nof_items=current_nof_items,
        )
        replay_value = self._next_replay_value(
            "unbatch_items_count",
            1,
            max(1, current_nof_items),
            self._unbatch_count_replay,
        )
        items_count = (
            replay_value
            if replay_value is not None
            else self._rng_randint(
                "unbatch_items_count",
                self.unbatch_rng,
                1,
                max(1, current_nof_items),
            )
        )
        self.loose_items_created += items_count
        self._record_diagnostic_event(
            "loose_items_injected",
            pallet,
            items_count=items_count,
        )
        self.loose_item_source.inject(items_count)

    def _on_unbatch_station_released(self, pallet: Pallet) -> None:
        self._record_debug_event(
            "unbatch_station_released",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
            storage_occ=self.storage_conveyor_occupancy_end,
        )

    def _on_batch_station_released(self, pallet: Pallet) -> None:
        self._record_debug_event(
            "batch_station_released",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
            storage_occ=self.storage_conveyor_occupancy_end,
        )

    def _on_pallet_conveyor_enter(self, pallet: Pallet) -> None:
        self.main_conveyor_occupancy_end += 1
        self._record_debug_event(
            "pallet_conveyor_enter",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
        )

    def _on_item_conveyor_enter(self, pallet: Pallet) -> None:
        self.main_conveyor_occupancy_end += 1
        self._record_debug_event(
            "item_conveyor_enter",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
        )

    def _on_loaded_pallet_convey_enter(self, pallet: Pallet) -> None:
        self.main_conveyor_occupancy_end += 1
        self._record_debug_event(
            "loaded_pallet_convey_enter",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
        )

    def _on_loaded_pallet_conveyor_exit(self, pallet: Pallet) -> None:
        self.main_conveyor_occupancy_end = max(
            0,
            self.main_conveyor_occupancy_end - 1,
        )
        self._record_debug_event(
            "loaded_pallet_conveyor_exit",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
        )

    def _on_batch_add(self, pallet: Pallet, _batch: Pallet | None) -> None:
        self.main_conveyor_occupancy_end = max(
            0,
            self.main_conveyor_occupancy_end - 1,
        )
        self._record_debug_event(
            "batch_add",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
        )

    def _on_empty_pallet_transfer_exit(self, pallet: Pallet) -> None:
        self.main_conveyor_occupancy_end = max(
            0,
            self.main_conveyor_occupancy_end - 1,
        )
        self.storage_conveyor_occupancy_end += 1
        self._record_debug_event(
            "empty_pallet_transfer_exit",
            pallet,
            main_occ=self.main_conveyor_occupancy_end,
            storage_occ=self.storage_conveyor_occupancy_end,
        )

    def _on_empty_pallet_enter(self, pallet: Pallet) -> None:
        self.empty_pallets_completed += 1
        self.storage_conveyor_occupancy_end = max(
            0,
            self.storage_conveyor_occupancy_end - 1,
        )
        self._record_diagnostic_event(
            "empty_pallet_sink_enter",
            pallet,
            storage_occ=self.storage_conveyor_occupancy_end,
        )

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

    def _on_batch_exit(self, pallet: Pallet) -> None:
        self._record_diagnostic_event(
            "batch_released",
            pallet,
            batched_item_count=pallet.attributes.get("batched_item_count", ""),
            batches_created=self.batch.batches_created,
        )

    def _on_completed_pallet_enter(self, pallet: Pallet) -> None:
        cycle_start = float(pallet.attributes.get("cycle_start_time", pallet.created_at))
        cycle_time_s = self.env.now - cycle_start
        self._record_diagnostic_event(
            "completed_pallet_sink_enter",
            pallet,
            cycle_time_s=cycle_time_s,
        )
        self.stats.record_completed(cycle_time_s)

    def _record_diagnostic_event(
        self,
        event: str,
        pallet: Pallet | None = None,
        **details: object,
    ) -> None:
        if len(self.diagnostic_events) >= self.params.diagnostic_trace_limit:
            return
        parts = [f"t={self.env.now:.6f}", f"event={event}"]
        if pallet is not None:
            parts.append(f"pallet_id={pallet.id}")
            entity_type = pallet.attributes.get("entity_type")
            if entity_type is not None:
                parts.append(f"entity_type={entity_type}")
        for key, value in details.items():
            parts.append(f"{key}={value}")
        self.diagnostic_events.append(",".join(parts))

    def _record_debug_event(
        self,
        event: str,
        pallet: Pallet | None = None,
        **details: object,
    ) -> None:
        if len(self.debug_events) >= self.params.diagnostic_trace_limit:
            return
        parts = [f"t={self.env.now:.6f}", f"event={event}"]
        if pallet is not None:
            parts.append(f"pallet_id={pallet.id}")
            entity_type = pallet.attributes.get("entity_type")
            if entity_type is not None:
                parts.append(f"entity_type={entity_type}")
        for key, value in details.items():
            parts.append(f"{key}={value}")
        self.debug_events.append(",".join(parts))

    @staticmethod
    def _replay_iter(values: tuple[int, ...] | None) -> Iterator[int] | None:
        return iter(values) if values is not None else None

    def _next_replay_value(
        self,
        event: str,
        low: int,
        high: int,
        replay: Iterator[int] | None,
    ) -> int | None:
        if replay is None:
            return None
        try:
            value = int(next(replay))
        except StopIteration:
            if self.params.random_replay_strict:
                raise RuntimeError(f"Replay values exhausted for {event}")
            return None
        if not low <= value <= high:
            raise ValueError(
                f"Replay value for {event} must be in {low}..{high}, got {value}"
            )
        self._record_rng_event(f"replay_{event}", low=low, high=high, value=value)
        return value

    def _rng_next_double(self, event: str, rng: JavaRandom) -> float:
        value = rng.next_double()
        self._record_rng_event(event, value=value)
        return value

    def _rng_randint(
        self,
        event: str,
        rng: JavaRandom,
        low: int,
        high: int,
    ) -> int:
        value = rng.randint(low, high)
        self._record_rng_event(event, low=low, high=high, value=value)
        return value

    def _record_rng_event(self, event: str, **details: object) -> None:
        if len(self.rng_events) >= self.params.diagnostic_trace_limit:
            return
        parts = [f"t={self.env.now:.6f}", f"event={event}"]
        for key, value in details.items():
            if isinstance(value, float):
                parts.append(f"{key}={value:.17g}")
            else:
                parts.append(f"{key}={value}")
        self.rng_events.append(",".join(parts))

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
            f"main_occ={self.main_conveyor_occupancy_end} "
            f"storage_occ={self.storage_conveyor_occupancy_end} "
            f"physical_main_occ={self.conveyor.occupancy} "
            f"physical_storage_occ={self.storage_conveyor.occupancy} "
            f"empty_pallets={self.empty_pallets_completed} "
            f"loose_items={self.loose_items_created} "
            f"batches={self.batch.batches_created}"
        )
