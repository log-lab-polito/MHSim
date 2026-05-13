#!/usr/bin/env python3
"""Compare stochastic AnyLogic and SimPy replication samples for Model 4."""

from __future__ import annotations

from pathlib import Path

from mhsim.stochastic_comparison import (
    MetricComparison,
    MetricSpec,
    ReplicationRow,
    StochasticComparisonSpec,
    compare_metric,
    load_simpy_replication_csv as _load_simpy_replication_csv,
    parse_anylogic_replication_log as _parse_anylogic_replication_log,
    run_stochastic_comparison_cli,
    values_for as _values_for,
    write_stochastic_comparison_csv as _write_csv,
)


__all__ = [
    "ANYLOGIC_KEY_MAP",
    "COMPARISON_SPEC",
    "METRICS",
    "MetricComparison",
    "ReplicationRow",
    "_values_for",
    "_write_csv",
    "compare_metric",
    "load_simpy_replication_csv",
    "main",
    "parse_anylogic_replication_log",
]


METRICS = (
    MetricSpec("created", "Created"),
    MetricSpec("completed", "Completed"),
    MetricSpec("main_completed", "Main completed"),
    MetricSpec("branch_completed", "Branch completed"),
    MetricSpec("in_flight", "In flight"),
    MetricSpec("avg_time_in_system_s", "Avg cycle (s)"),
    MetricSpec("throughput_per_hour", "Throughput (/h)"),
)

ANYLOGIC_KEY_MAP = {
    "Created": "created",
    "Completed": "completed",
    "Main completed": "main_completed",
    "Branch completed": "branch_completed",
    "In flight": "in_flight",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
}

COMPARISON_SPEC = StochasticComparisonSpec(
    title="MODEL 4 STOCHASTIC REPLICATION COMPARISON",
    description="Compare Model 4 stochastic AnyLogic and SimPy replication outputs.",
    metrics=METRICS,
    anylogic_key_map=ANYLOGIC_KEY_MAP,
    default_anylogic_path="anylogic/Model 4/log_file.txt",
    default_simpy_runs_path="logs/model_4_stochastic_replications_runs.csv",
)


def parse_anylogic_replication_log(path: str | Path) -> list[ReplicationRow]:
    return _parse_anylogic_replication_log(
        path,
        metrics=METRICS,
        anylogic_key_map=ANYLOGIC_KEY_MAP,
    )


def load_simpy_replication_csv(path: str | Path) -> list[ReplicationRow]:
    return _load_simpy_replication_csv(path, metrics=METRICS)


def main() -> None:
    run_stochastic_comparison_cli(COMPARISON_SPEC)


if __name__ == "__main__":
    main()
