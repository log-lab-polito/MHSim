from __future__ import annotations

import csv
from dataclasses import dataclass, field
import math
from pathlib import Path
from random import Random
from typing import Callable, Optional

import simpy

from mhsim.blocks import ServiceBlock, Sink
from mhsim.conveyor import Conveyor, ConveyorSpur
from mhsim.pallet import Pallet
from mhsim.random_variables import (
    DurationValue,
    make_duration_sampler,
    sample_duration_s,
)
from mhsim.stats import SimulationStats

from .params import Model4Params
from .setup import (
    create_model4_branch_conveyor,
    create_model4_main_conveyor,
    create_model4_spur,
)


TraceDetails = dict[str, object]
TraceCallback = Callable[..., None]
CONVEYOR_EDGE_TRACE_LENGTH_M = 1.0
# AnyLogic's path edge callbacks expose a short spur-side backlog that is
# separate from the higher-level Convey block backlog used for throughput.
BRANCH_EXIT_TRACE_QUEUE_CAPACITY = 3
BRANCH_TRAILING_ENTRY_TRACE_QUEUE_CAPACITY = 5
TRACE_DETAIL_FIELDNAMES = tuple(f"detail_{index}" for index in range(1, 13))

TRACE_FIELDNAMES = (
    "time_s",
    "event",
    "pallet_id",
    "origin",
    "cycle_time_s",
    "main_conveyor_occupancy",
    "branch_conveyor_occupancy",
    "main_conveyor_entered",
    "main_conveyor_exited",
    "branch_conveyor_entered",
    "branch_conveyor_exited",
    "spur_transferred",
) + TRACE_DETAIL_FIELDNAMES


def _delayed_trace(
    env: simpy.Environment,
    delay_s: float,
    trace_callback: Optional[TraceCallback],
    event: str,
    pallet: Pallet,
    details: TraceDetails | None = None,
):
    yield env.timeout(delay_s)
    if trace_callback:
        trace_callback(event, pallet, details)


def _edge_trace_time_s(conveyor: Conveyor) -> float:
    return conveyor.travel_time_s(CONVEYOR_EDGE_TRACE_LENGTH_M)


def _trace_detail_values(details: TraceDetails | None) -> dict[str, object]:
    values: dict[str, object] = {
        field_name: "" for field_name in TRACE_DETAIL_FIELDNAMES
    }
    if not details:
        return values
    for field_name, (key, value) in zip(TRACE_DETAIL_FIELDNAMES, details.items()):
        values[field_name] = f"{key}={value}"
    return values


class TimedSource:
    """Minimal source used for multi-line test models."""

    def __init__(
        self,
        env: simpy.Environment,
        stats: SimulationStats,
        interarrival_time_s: DurationValue,
        first_block,
        pallet_id_supplier: Callable[[], int],
        origin: str,
        name: str,
        trace_callback: Optional[TraceCallback] = None,
    ):
        self.env = env
        self.stats = stats
        self.interarrival_time_s = interarrival_time_s
        self.first_block = first_block
        self.pallet_id_supplier = pallet_id_supplier
        self.origin = origin
        self.name = name
        self.trace_callback = trace_callback
        self._proc: Optional[simpy.Process] = None
        self.emitted_count = 0

    def start(self):
        if self._proc is None:
            self._proc = self.env.process(self._run())

    def _next_interarrival(self) -> float:
        if not callable(self.interarrival_time_s) and self.interarrival_time_s <= 0:
            return float("inf")
        return sample_duration_s(
            self.interarrival_time_s,
            name=f"{self.name}.interarrival_time_s",
        )

    def _emit_one(self) -> None:
        self.stats.record_created(1)
        self.emitted_count += 1
        pallet = Pallet(
            id=self.pallet_id_supplier(),
            created_at=self.env.now,
            attributes={"origin": self.origin},
        )
        if self.trace_callback:
            self.trace_callback(f"{self.name}_exit", pallet)
        self.env.process(self.first_block.handle(pallet))

    def _run(self):
        while True:
            ia = self._next_interarrival()
            if ia == float("inf"):
                break
            yield self.env.timeout(ia)
            self._emit_one()


class OriginTrackingSink:
    def __init__(
        self,
        sink: Sink,
        trace_callback: Optional[TraceCallback] = None,
    ):
        self.sink = sink
        self.trace_callback = trace_callback
        self.completed_by_origin: dict[str, int] = {}

    @property
    def entered_count(self) -> int:
        return self.sink.entered_count

    def handle(self, pallet: Pallet):
        if self.trace_callback:
            self.trace_callback("sink_enter", pallet)
        origin = str(pallet.attributes.get("origin", "unknown"))
        self.completed_by_origin[origin] = self.completed_by_origin.get(origin, 0) + 1
        yield from self.sink.handle(pallet)


class TraceableServiceBlock(ServiceBlock):
    """ServiceBlock with AnyLogic-style event trace hooks for Model 4."""

    def __init__(
        self,
        env: simpy.Environment,
        service_time_s: DurationValue,
        next_block,
        *,
        event_prefix: str,
        name: str = "service",
        capacity: int = 1,
        queue_capacity: int = 0,
        trace_callback: Optional[TraceCallback] = None,
    ):
        super().__init__(
            env,
            service_time_s=service_time_s,
            next_block=next_block,
            name=name,
            capacity=capacity,
            queue_capacity=queue_capacity,
        )
        self.event_prefix = event_prefix
        self.trace_callback = trace_callback

    def _trace(self, suffix: str, pallet: Pallet) -> None:
        if self.trace_callback:
            self.trace_callback(f"{self.event_prefix}_{suffix}", pallet)

    def handle(self, pallet: Pallet):
        self.entered_count += 1
        self._trace("enter", pallet)
        if self.logger:
            self.logger.log_event(
                f"{self.name} block", f"Pallet {pallet.id}", self.env.now
            )
        if self.queue_capacity and self.queue_capacity > 0:
            while len(self.resource.queue) >= self.queue_capacity:
                yield self.env.timeout(0)
        with self.resource.request() as req:
            yield req
            self._trace("delay_enter", pallet)
            yield self.env.timeout(self.sample_service_time_s())
        self.finished_count += 1
        self._trace("at_exit", pallet)
        if self.next_block:
            exit_traced = False

            def trace_exit_once() -> None:
                nonlocal exit_traced
                if not exit_traced:
                    self._trace("exit", pallet)
                    exit_traced = True

            handle_from_service = getattr(
                self.next_block,
                "handle_from_service",
                None,
            )
            if callable(handle_from_service):
                yield from handle_from_service(pallet, trace_exit_once)
            else:
                trace_exit_once()
                yield from self.next_block.handle(pallet)
        else:
            self._trace("exit", pallet)
        self.completed_count += 1


class MainConveyBlock:
    """AnyLogic Model 4 main Convey block surface."""

    def __init__(
        self,
        env: simpy.Environment,
        conveyor: Conveyor,
        next_block,
        spur: ConveyorSpur | None = None,
        trace_callback: Optional[TraceCallback] = None,
    ):
        self.env = env
        self.conveyor = conveyor
        self.next_block = next_block
        self.spur = spur
        self.trace_callback = trace_callback
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0

    def _trace(
        self,
        event: str,
        pallet: Pallet,
        details: TraceDetails | None = None,
    ) -> None:
        if self.trace_callback:
            self.trace_callback(event, pallet, details)

    def _trace_later(
        self,
        delay_s: float,
        event: str,
        pallet: Pallet,
        details: TraceDetails | None = None,
    ) -> None:
        if self.trace_callback is None:
            return
        if delay_s <= 0:
            self._trace(event, pallet, details)
            return
        self.env.process(
            _delayed_trace(
                self.env,
                delay_s,
                self.trace_callback,
                event,
                pallet,
                details,
            )
        )

    def handle(self, pallet: Pallet):
        yield from self._handle(pallet, None)

    def handle_from_service(self, pallet: Pallet, trace_service_exit) -> None:
        yield from self._handle(pallet, trace_service_exit)

    def _handle(self, pallet: Pallet, trace_service_exit):
        yield from self.conveyor.enter()
        if trace_service_exit:
            trace_service_exit()
        self.entered_count += 1
        self._trace("main_convey_enter", pallet)
        self._trace("main_convey_on_conveyor", pallet)
        self._trace("main_conveyor_leading_edge_enter", pallet)
        self._trace_later(
            _edge_trace_time_s(self.conveyor),
            "main_conveyor_trailing_edge_enter",
            pallet,
        )
        if self.spur is None:
            yield self.env.timeout(self.conveyor.travel_time_s())
        else:
            time_to_merge = self.conveyor.travel_time_s(self.spur.target_offset_m)
            self.spur.register_target_merge_arrival(self.env.now + time_to_merge)
            yield self.env.timeout(time_to_merge)
            self._trace("main_convey_merge_request", pallet)
            yield from self.spur.reserve_merge_window(merge_path="target")
            self._trace("main_convey_merge_release", pallet)
            yield self.env.timeout(
                self.conveyor.travel_time_s(
                    self.spur.remaining_target_distance_m()
                )
            )
        self._trace("main_convey_at_exit", pallet)
        self._trace("main_conveyor_leading_edge_exit", pallet)
        self.conveyor.leave()
        self.finished_count += 1
        self._trace("main_convey_exit", pallet)
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


class BranchConveyBlock:
    """AnyLogic Model 4 branch Convey block, including the physical spur transfer."""

    def __init__(
        self,
        env: simpy.Environment,
        branch_conveyor: Conveyor,
        spur: ConveyorSpur,
        next_block,
        trace_callback: Optional[TraceCallback] = None,
    ):
        self.env = env
        self.branch_conveyor = branch_conveyor
        self.spur = spur
        self.next_block = next_block
        self.trace_callback = trace_callback
        self.entered_count = 0
        self.finished_count = 0
        self.completed_count = 0
        self._exit_edge_trace_queue = simpy.Resource(
            self.env,
            capacity=BRANCH_EXIT_TRACE_QUEUE_CAPACITY,
        )
        self._trailing_entry_trace_queue = simpy.Resource(
            self.env,
            capacity=BRANCH_TRAILING_ENTRY_TRACE_QUEUE_CAPACITY,
        )

    def _trace(
        self,
        event: str,
        pallet: Pallet,
        details: TraceDetails | None = None,
    ) -> None:
        if self.trace_callback:
            self.trace_callback(event, pallet, details)

    def _trace_later(
        self,
        delay_s: float,
        event: str,
        pallet: Pallet,
        details: TraceDetails | None = None,
    ) -> None:
        if self.trace_callback is None:
            return
        if delay_s <= 0:
            self._trace(event, pallet, details)
            return
        self.env.process(
            _delayed_trace(
                self.env,
                delay_s,
                self.trace_callback,
                event,
                pallet,
                details,
            )
        )

    def _source_merge_queue_in_use(self) -> int | str:
        queue = self.spur._source_merge_queue
        return "" if queue is None else queue.count

    def _source_merge_queue_waiting(self) -> int | str:
        queue = self.spur._source_merge_queue
        return "" if queue is None else len(queue.queue)

    def _next_target_arrival_s(self) -> float | str:
        if not self.spur._target_merge_arrivals:
            return ""
        return self.spur._target_merge_arrivals[0]

    def _spur_trace_details(self, **extra: object) -> TraceDetails:
        details: TraceDetails = {
            "branch_occ": self.branch_conveyor.occupancy,
            "target_occ": self.spur.target_conveyor.occupancy,
            "exit_queue_in_use": self._exit_edge_trace_queue.count,
            "exit_queue_waiting": len(self._exit_edge_trace_queue.queue),
            "source_queue_in_use": self._source_merge_queue_in_use(),
            "source_queue_waiting": self._source_merge_queue_waiting(),
            "next_merge_time_s": round(self.spur._next_merge_time, 10),
            "last_merge_path": self.spur._last_merge_path or "",
            "target_arrivals": len(self.spur._target_merge_arrivals),
            "next_target_arrival_s": self._next_target_arrival_s(),
            "spur_transferred": self.spur.total_transferred,
        }
        details.update(extra)
        return details

    def _leading_exit_travel_time_s(self) -> float:
        source_exit_distance_m = max(
            0.0,
            self.branch_conveyor.length_m - CONVEYOR_EDGE_TRACE_LENGTH_M,
        )
        return self.branch_conveyor.travel_time_s(source_exit_distance_m)

    def _blocked_trailing_exit_clear_time_s(self) -> float:
        edge_time_s = _edge_trace_time_s(self.branch_conveyor)
        # Saturated branch traces show trailing-edge exit clearance stretching
        # past the visible edge marker because the branch item is waiting in
        # the spur-side merge envelope, not only on the branch conveyor path.
        return max(
            edge_time_s,
            self.spur.merge_headway_time_s() + (edge_time_s / 2.0),
        )

    def _trace_trailing_edge_enter(self, pallet: Pallet, trailing_exit_event):
        yield self.env.timeout(_edge_trace_time_s(self.branch_conveyor))
        with self._trailing_entry_trace_queue.request() as req:
            yield req
            self._trace("branch_conveyor_trailing_edge_enter", pallet)
            yield trailing_exit_event

    def _trace_exit_edges(
        self,
        pallet: Pallet,
        target_transfer_event,
        leading_exit_event,
        trailing_exit_event,
    ):
        yield self.env.timeout(self._leading_exit_travel_time_s())
        requested_at_s = self.env.now
        self._trace(
            "diag_branch_exit_queue_request_state",
            pallet,
            self._spur_trace_details(requested_at_s=round(requested_at_s, 10)),
        )
        with self._exit_edge_trace_queue.request() as req:
            yield req
            blocked_at_exit = self.env.now > requested_at_s + 1e-9
            self._trace(
                "diag_branch_exit_queue_acquired_state",
                pallet,
                self._spur_trace_details(
                    request_wait_s=round(self.env.now - requested_at_s, 10),
                    blocked_at_exit=blocked_at_exit,
                ),
            )
            self._trace("branch_conveyor_leading_edge_exit", pallet)
            if not leading_exit_event.triggered:
                leading_exit_event.succeed()
            clear_time_s = (
                self._blocked_trailing_exit_clear_time_s()
                if blocked_at_exit
                else _edge_trace_time_s(self.branch_conveyor)
            )
            if clear_time_s > 0:
                yield self.env.timeout(clear_time_s)
            self._trace("branch_conveyor_trailing_edge_exit", pallet)
            if not trailing_exit_event.triggered:
                trailing_exit_event.succeed()
            yield target_transfer_event
            self._trace(
                "diag_branch_exit_queue_released_state",
                pallet,
                self._spur_trace_details(
                    held_s=round(self.env.now - requested_at_s, 10),
                ),
            )

    def handle(self, pallet: Pallet):
        yield from self._handle(pallet, None)

    def handle_from_service(self, pallet: Pallet, trace_service_exit) -> None:
        yield from self._handle(pallet, trace_service_exit)

    def _handle(self, pallet: Pallet, trace_service_exit):
        yield from self.branch_conveyor.enter()
        if trace_service_exit:
            trace_service_exit()
        self.entered_count += 1
        self._trace("branch_convey_enter", pallet)
        self._trace(
            "diag_branch_conveyor_accept_state",
            pallet,
            self._spur_trace_details(
                next_branch_entry_s=round(self.branch_conveyor._next_entry_time, 10),
            ),
        )
        self._trace("branch_convey_on_branch_conveyor", pallet)
        self._trace("branch_conveyor_leading_edge_enter", pallet)
        target_transfer_event = self.env.event()
        leading_exit_event = self.env.event()
        trailing_exit_event = self.env.event()
        self.env.process(
            self._trace_exit_edges(
                pallet,
                target_transfer_event,
                leading_exit_event,
                trailing_exit_event,
            )
        )
        if self.trace_callback is not None:
            self.env.process(
                self._trace_trailing_edge_enter(pallet, trailing_exit_event)
            )
        yield self.env.timeout(self.branch_conveyor.travel_time_s())
        # AnyLogic's spur handoff is gated by the branch path exit callback,
        # so keep this edge process active even when TRACE output is disabled.
        yield leading_exit_event
        self._trace("branch_convey_merge_request", pallet)
        merge_request_s = self.env.now
        self._trace(
            "diag_branch_merge_request_state",
            pallet,
            self._spur_trace_details(merge_request_s=round(merge_request_s, 10)),
        )
        yield from self.spur.transfer()
        if not target_transfer_event.triggered:
            target_transfer_event.succeed()
        self._trace("branch_convey_merge_release", pallet)
        self._trace(
            "diag_branch_merge_release_state",
            pallet,
            self._spur_trace_details(
                merge_wait_s=round(self.env.now - merge_request_s, 10),
            ),
        )
        yield self.env.timeout(
            self.spur.target_conveyor.travel_time_s(
                self.spur.remaining_target_distance_m()
            )
        )
        self._trace("branch_convey_at_exit", pallet)
        self._trace("main_conveyor_leading_edge_exit", pallet)
        self.spur.target_conveyor.leave()
        self.finished_count += 1
        self._trace("branch_convey_exit", pallet)
        if self.next_block:
            yield from self.next_block.handle(pallet)
        self.completed_count += 1


@dataclass
class Model4SimModel:
    params: Model4Params = field(default_factory=Model4Params)
    console_logging: bool = False
    trace_enabled: bool = False
    trace_events: list[dict[str, object]] = field(init=False, default_factory=list)

    def __post_init__(self):
        self.env = simpy.Environment()
        self.rng = Random(self.params.random_seed)
        self.stats = SimulationStats()
        self._pallet_counter = 0

        self.main_conveyor = create_model4_main_conveyor(self.env, self.params)
        self.branch_conveyor = create_model4_branch_conveyor(self.env, self.params)
        self.spur = create_model4_spur(
            self.env,
            self.params,
            branch_conveyor=self.branch_conveyor,
            main_conveyor=self.main_conveyor,
        )
        trace_callback = self._trace if self.trace_enabled else None

        self.base_sink = Sink(self.env, self.stats, name="sink")
        self.sink = OriginTrackingSink(
            self.base_sink,
            trace_callback=trace_callback,
        )
        self.downstream_service = TraceableServiceBlock(
            self.env,
            service_time_s=self._service_time(
                self.params.downstream_service_time_s,
                "downstreamService",
            ),
            next_block=self.sink,
            event_prefix="downstream_service",
            name="downstreamService",
            trace_callback=trace_callback,
        )
        self.service2 = self.downstream_service
        self.main_convey = MainConveyBlock(
            self.env,
            conveyor=self.main_conveyor,
            next_block=self.downstream_service,
            spur=self.spur,
            trace_callback=trace_callback,
        )
        self.main_service = TraceableServiceBlock(
            self.env,
            service_time_s=self._service_time(
                self.params.main_service_time_s,
                "mainService",
            ),
            next_block=self.main_convey,
            event_prefix="main_service",
            name="mainService",
            trace_callback=trace_callback,
        )
        self.main_service1 = self.main_service

        self.branch_convey = BranchConveyBlock(
            self.env,
            branch_conveyor=self.branch_conveyor,
            spur=self.spur,
            next_block=self.downstream_service,
            trace_callback=trace_callback,
        )
        self.branch_service = TraceableServiceBlock(
            self.env,
            service_time_s=self._service_time(
                self.params.branch_service_time_s,
                "branchService",
            ),
            next_block=self.branch_convey,
            event_prefix="branch_service",
            name="branchService",
            trace_callback=trace_callback,
        )
        self.branch_service1 = self.branch_service

        self.main_source = TimedSource(
            self.env,
            stats=self.stats,
            interarrival_time_s=self._arrival_time(
                self.params.main_arrival_time_s,
                "main_source",
            ),
            first_block=self.main_service,
            pallet_id_supplier=self._next_pallet_id,
            origin="main",
            name="main_source",
            trace_callback=trace_callback,
        )
        self.branch_source = TimedSource(
            self.env,
            stats=self.stats,
            interarrival_time_s=self._arrival_time(
                self.params.branch_arrival_time_s,
                "branch_source",
            ),
            first_block=self.branch_service,
            pallet_id_supplier=self._next_pallet_id,
            origin="branch",
            name="branch_source",
            trace_callback=trace_callback,
        )

    def _service_time(self, mean_s: float, name: str) -> DurationValue:
        if not self.params.random_service_times:
            return mean_s
        return make_duration_sampler(
            mean_s,
            rng=self.rng,
            distribution=self.params.service_time_distribution,
            triangular_spread=self.params.service_time_triangular_spread,
            name=f"{name}.service_time_s",
        )

    def _arrival_time(self, mean_s: float, name: str) -> DurationValue:
        if not self.params.random_arrival_times:
            return mean_s
        return make_duration_sampler(
            mean_s,
            rng=self.rng,
            distribution=self.params.arrival_time_distribution,
            name=f"{name}.interarrival_time_s",
        )

    def _next_pallet_id(self) -> int:
        self._pallet_counter += 1
        return self._pallet_counter

    def _trace(
        self,
        event: str,
        pallet: Pallet,
        details: TraceDetails | None = None,
    ) -> None:
        if not self.trace_enabled:
            return

        self.trace_events.append(
            {
                "time_s": self.env.now,
                "event": event,
                "pallet_id": pallet.id,
                "origin": str(pallet.attributes.get("origin", "")),
                "cycle_time_s": (
                    self.env.now - pallet.created_at if event == "sink_enter" else ""
                ),
                "main_conveyor_occupancy": self.main_conveyor.occupancy,
                "branch_conveyor_occupancy": self.branch_conveyor.occupancy,
                "main_conveyor_entered": self.main_conveyor.total_entered,
                "main_conveyor_exited": self.main_conveyor.total_exited,
                "branch_conveyor_entered": self.branch_conveyor.total_entered,
                "branch_conveyor_exited": self.branch_conveyor.total_exited,
                "spur_transferred": self.spur.total_transferred,
                **_trace_detail_values(details),
            }
        )

    def write_trace_csv(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=TRACE_FIELDNAMES)
            writer.writeheader()
            writer.writerows(self.trace_events)
        return output_path

    def run(self, until: Optional[float] = None) -> SimulationStats:
        self.main_source.start()
        self.branch_source.start()
        stop_time = until if until is not None else self.params.sim_time
        self.env.run(until=math.nextafter(stop_time, math.inf))
        if self.console_logging:
            self._log_summary()
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
