from __future__ import annotations

import csv
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Callable, Optional

import simpy

from mhsim.blocks import ServiceBlock, Sink
from mhsim.conveyor import Conveyor, ConveyorSpur
from mhsim.pallet import Pallet
from mhsim.stats import SimulationStats

from .params import Model4Params
from .setup import (
    create_model4_branch_conveyor,
    create_model4_main_conveyor,
    create_model4_spur,
)


TraceCallback = Callable[[str, Pallet], None]

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
)


class DeterministicSource:
    """Minimal deterministic source used for multi-line test models."""

    def __init__(
        self,
        env: simpy.Environment,
        stats: SimulationStats,
        arrival_interval_s: float,
        first_block,
        pallet_id_supplier: Callable[[], int],
        origin: str,
        name: str,
        trace_callback: Optional[TraceCallback] = None,
    ):
        self.env = env
        self.stats = stats
        self.arrival_interval_s = arrival_interval_s
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
        if self.arrival_interval_s <= 0:
            return float("inf")
        return self.arrival_interval_s

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
        service_time_s: float,
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
            yield self.env.timeout(self.service_time_s)
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

    def _trace(self, event: str, pallet: Pallet) -> None:
        if self.trace_callback:
            self.trace_callback(event, pallet)

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

    def _trace(self, event: str, pallet: Pallet) -> None:
        if self.trace_callback:
            self.trace_callback(event, pallet)

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
        self._trace("branch_convey_on_branch_conveyor", pallet)
        yield self.env.timeout(self.branch_conveyor.travel_time_s())
        self._trace("branch_convey_merge_request", pallet)
        yield from self.spur.transfer()
        self._trace("branch_convey_merge_release", pallet)
        yield self.env.timeout(
            self.spur.target_conveyor.travel_time_s(
                self.spur.remaining_target_distance_m()
            )
        )
        self._trace("branch_convey_at_exit", pallet)
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

        self.base_sink = Sink(self.env, self.stats, name="sink")
        self.sink = OriginTrackingSink(
            self.base_sink,
            trace_callback=self._trace,
        )
        self.downstream_service = TraceableServiceBlock(
            self.env,
            service_time_s=self.params.downstream_service_time_s,
            next_block=self.sink,
            event_prefix="downstream_service",
            name="downstreamService",
            trace_callback=self._trace,
        )
        self.service2 = self.downstream_service
        self.main_convey = MainConveyBlock(
            self.env,
            conveyor=self.main_conveyor,
            next_block=self.downstream_service,
            spur=self.spur,
            trace_callback=self._trace,
        )
        self.main_service = TraceableServiceBlock(
            self.env,
            service_time_s=self.params.main_service_time_s,
            next_block=self.main_convey,
            event_prefix="main_service",
            name="mainService",
            trace_callback=self._trace,
        )
        self.main_service1 = self.main_service

        self.branch_convey = BranchConveyBlock(
            self.env,
            branch_conveyor=self.branch_conveyor,
            spur=self.spur,
            next_block=self.downstream_service,
            trace_callback=self._trace,
        )
        self.branch_service = TraceableServiceBlock(
            self.env,
            service_time_s=self.params.branch_service_time_s,
            next_block=self.branch_convey,
            event_prefix="branch_service",
            name="branchService",
            trace_callback=self._trace,
        )
        self.branch_service1 = self.branch_service

        self.main_source = DeterministicSource(
            self.env,
            stats=self.stats,
            arrival_interval_s=self.params.main_arrival_time_s,
            first_block=self.main_service,
            pallet_id_supplier=self._next_pallet_id,
            origin="main",
            name="main_source",
            trace_callback=self._trace,
        )
        self.branch_source = DeterministicSource(
            self.env,
            stats=self.stats,
            arrival_interval_s=self.params.branch_arrival_time_s,
            first_block=self.branch_service,
            pallet_id_supplier=self._next_pallet_id,
            origin="branch",
            name="branch_source",
            trace_callback=self._trace,
        )

    def _next_pallet_id(self) -> int:
        self._pallet_counter += 1
        return self._pallet_counter

    def _trace(self, event: str, pallet: Pallet) -> None:
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
