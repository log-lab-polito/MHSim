#!/usr/bin/env python3
"""Compare stochastic AnyLogic and SimPy replication samples for Model 6."""

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
    "OPTIONAL_METRICS",
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
    MetricSpec("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    MetricSpec("main_conveyor_occupancy_end", "Main conveyor occupancy end"),
    MetricSpec("storage_conveyor_occupancy_end", "Storage conveyor occupancy end"),
    MetricSpec("empty_pallets_completed", "Empty pallets completed"),
    MetricSpec("loose_items_created", "Loose items created"),
    MetricSpec("batches_created", "Batches created"),
)

ANYLOGIC_KEY_MAP = {
    "Created": "created",
    "Completed": "completed",
    "Avg WIP": "avg_wip",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
    "Main conveyor occupancy end": "main_conveyor_occupancy_end",
    "Storage conveyor occupancy end": "storage_conveyor_occupancy_end",
    "Empty pallets completed": "empty_pallets_completed",
    "Loose items created": "loose_items_created",
    "Batches created": "batches_created",
}

ANYLOGIC_PARAMETER_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Conveyor Speed (m/s)": "conveyor_speed_mps",
    "Conveyor Gap (m)": "conveyor_gap_m",
    "Min items per pallet": "min_items_per_pallet",
    "Max items per pallet": "max_items_per_pallet",
    "Random arrivals": "random_arrival_times",
    "Random services": "random_service_times",
}

COMPARISON_SPEC = StochasticComparisonSpec(
    title="MODEL 6 STOCHASTIC REPLICATION COMPARISON",
    description="Compare Model 6 stochastic AnyLogic and SimPy replication outputs.",
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    anylogic_key_map=ANYLOGIC_KEY_MAP,
    default_anylogic_path="anylogic/Model 6/log_file_stochastic.txt",
    default_simpy_runs_path="logs/model_6_stochastic_replications_runs.csv",
    anylogic_parameter_key_map=ANYLOGIC_PARAMETER_KEY_MAP,
    default_replications_per_iteration=100,
    default_expected_iterations=2,
)


def parse_anylogic_replication_log(path: str | Path) -> list[ReplicationRow]:
    return _parse_anylogic_replication_log(
        path,
        metrics=METRICS,
        optional_metrics=OPTIONAL_METRICS,
        anylogic_key_map=ANYLOGIC_KEY_MAP,
        anylogic_parameter_key_map=ANYLOGIC_PARAMETER_KEY_MAP,
    )


def load_simpy_replication_csv(path: str | Path) -> list[ReplicationRow]:
    return _load_simpy_replication_csv(path, metrics=(*METRICS, *OPTIONAL_METRICS))


def main() -> None:
    run_stochastic_comparison_cli(COMPARISON_SPEC)


if __name__ == "__main__":
    main()
