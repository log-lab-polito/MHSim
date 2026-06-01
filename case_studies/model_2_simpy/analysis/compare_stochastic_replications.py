#!/usr/bin/env python3
"""Compare stochastic AnyLogic and SimPy replication samples for Model 2."""

from __future__ import annotations

from pathlib import Path

from mhsim_analysis.stochastic_comparison import (
    MetricComparison,
    MetricSpec,
    ReplicationRow,
    StochasticComparisonGroup,
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
    "ANYLOGIC_PARAMETER_KEY_MAP",
    "COMPARISON_SPEC",
    "METRICS",
    "MetricComparison",
    "ReplicationRow",
    "StochasticComparisonGroup",
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
    MetricSpec("avg_wip", "Avg WIP"),
    MetricSpec("avg_time_in_system_s", "Avg cycle (s)"),
    MetricSpec("storage_level", "Storage level"),
    MetricSpec("throughput_per_hour", "Throughput (/h)"),
    MetricSpec("forklift_utilization", "Forklifts Utilization (%)"),
)

ANYLOGIC_KEY_MAP = {
    "Created": "created",
    "Completed": "completed",
    "Avg WIP": "avg_wip",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Storage level": "storage_level",
    "Throughput (/h)": "throughput_per_hour",
    "Forklifts Utilization (%)": "forklift_utilization",
}

ANYLOGIC_PARAMETER_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Forklift capacity": "n_forklifts",
    "Delay time (s)": "delay_time_s",
    "Random arrivals": "random_arrival_times",
    "Random services": "random_service_times",
}

COMPARISON_SPEC = StochasticComparisonSpec(
    title="MODEL 2 STOCHASTIC REPLICATION COMPARISON",
    description="Compare Model 2 stochastic AnyLogic and SimPy replication outputs.",
    metrics=METRICS,
    anylogic_key_map=ANYLOGIC_KEY_MAP,
    default_anylogic_path="logs/anylogic_model_2_stochastic_replications.txt",
    default_simpy_runs_path="logs/model_2_stochastic_replications_runs.csv",
    anylogic_parameter_key_map=ANYLOGIC_PARAMETER_KEY_MAP,
    default_replications_per_iteration=50,
    default_expected_iterations=36,
)


def parse_anylogic_replication_log(path: str | Path) -> list[ReplicationRow]:
    return _parse_anylogic_replication_log(
        path,
        metrics=METRICS,
        anylogic_key_map=ANYLOGIC_KEY_MAP,
        anylogic_parameter_key_map=ANYLOGIC_PARAMETER_KEY_MAP,
    )


def load_simpy_replication_csv(path: str | Path) -> list[ReplicationRow]:
    return _load_simpy_replication_csv(path, metrics=METRICS)


def main() -> None:
    run_stochastic_comparison_cli(COMPARISON_SPEC)


if __name__ == "__main__":
    main()
