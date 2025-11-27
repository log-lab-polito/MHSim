from __future__ import annotations

import simpy
from dataclasses import dataclass, field
from random import Random
from typing import Optional
from .environment import Environment
from .params import JobShopParams
from .stats import JobShopStats
from .processes import (
    raw_truck_generator,
    shipping_truck_generator,
    forklift_worker,
)

from jobshop_base.trace import Tracer, TraceConfig, set_tracer, traceln


def reporter(
    env: Environment,
    stats: JobShopStats,
    every_sim_seconds: float = 60.0,
):
    while True:
        yield env.timeout(every_sim_seconds)
        avg_tsys = (
            (sum(stats.sojourn_times) / len(stats.sojourn_times))
            if stats.sojourn_times
            else 0.0
        )

        traceln(
            f"REPORT  completed_parts={stats.completed_parts} "
            f"avg_Tsys={avg_tsys:.2f}s",
            color="grey",
            sim_time=env.now,
            channel="summary",
        )


@dataclass
class JobShopModel:
    params: JobShopParams
    report_interval_s: float = 60.0
    trace_log_file: Optional[str] = None
    trace_log_append: bool = False
    console_level: str = "full"  # full, summary, silent
    _tracer: Optional[Tracer] = field(init=False, default=None, repr=False)

    def __post_init__(self):
        self.rng = Random(self.params.random_seed)
        self.env = Environment()
        self.env.params = self.params
        self.env.stats = JobShopStats()
        self.env.rng = self.rng
        self.env.cnc = simpy.Resource(
            self.env, capacity=self.params.n_cnc_machines)
        self.env.worker = simpy.Resource(
            self.env, capacity=self.params.n_workers)
        self.env.forklift_tasks = simpy.PriorityStore(
            self.env
        )  # type: ignore[attr-defined]
        self.env.task_seq = 0
        self.env.shipping_buffer = []
        self.env.raw_storage_count = 0
        self.env.finished_storage_count = 0
        self.env.raw_wait_queue = []
        self.env.finished_wait_queue = []
        self.stats = self.env.stats
        self._tracer = Tracer(
            TraceConfig(
                enabled=True,
                use_color=True,
                prefix_time=False,
                log_path=self.trace_log_file,
                log_append=self.trace_log_append,
                console_level=self.console_level,
            )
        )
        set_tracer(self._tracer)

    def close_tracer(self) -> None:
        if self._tracer:
            self._tracer.close()
            self._tracer = None

    def setup(self):
        for i in range(self.params.n_forklifts):
            self.env.process(
                forklift_worker(
                    self.env,
                    name=f"FORKLIFT_{i + 1}",
                    params=self.params,
                    stats=self.stats,
                )
            )
        self.env.process(raw_truck_generator(
            self.env, self.params, self.stats))
        self.env.process(shipping_truck_generator(
            self.env, self.params, self.stats))
        self.env.process(
            reporter(
                self.env,
                self.stats,
                every_sim_seconds=self.report_interval_s,
            )
        )

    def run(self):
        self.setup()
        self.env.run(until=self.params.sim_time)
        return self.stats

    def report(self):
        sim_hours = self.params.sim_time / 3600.0
        avg_sys = self.stats.avg_time_in_system
        throughput = self.stats.throughput_per_hour(self.params.sim_time)
        traceln(
            "--- Job Shop (SimPy) Report ---",
            color="yellow",
            channel="summary",
        )
        print(f"Simulated time: {sim_hours:.2f} h")
        print(f"Completed parts: {self.stats.completed_parts}")
        print(
            "Average time in system: " f"{avg_sys:.2f} s ({avg_sys / 60:.2f} min)")
        print(f"Throughput: {throughput:.2f} parts/hour")
        print("Category times (avg minutes per part, share of total):")
        for label, minutes, pct in self.stats.category_breakdown():
            print(f" - {label}: {minutes:.2f} min ({pct:.0f}%)")
