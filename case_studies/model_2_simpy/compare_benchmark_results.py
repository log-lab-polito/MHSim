#!/usr/bin/env python3
"""
Compare AnyLogic Model 2 benchmark output against fresh SimPy runs.

The AnyLogic input is expected to contain one or more iteration blocks like:

ITERATION #0
PARAMETERS
    Arrival rate (s): 48.0
    Forklift capacity: 2
    Delay time (s): 180.0
RESULTS
    Created: 376
    ...
    Seize to Loading time (s)
      avg = ...
      min = ...
      max = ...
      std dev (pop) = ...
      std dev (sample) = ...
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from case_studies.model_1_simpy.model import Model1SimModel
from case_studies.model_1_simpy.reporting import build_forklift_movement_benchmark_rows
from .params import Model2Params


ANYLOGIC_SUMMARY_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Forklift capacity": "forklift_capacity",
    "Delay time (s)": "delay_time_s",
    "Created": "created",
    "Completed": "completed",
    "In flight": "in_flight",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Storage level": "storage_level",
    "Throughput (/h)": "throughput_per_hour",
    "Forklifts Utilization (%)": "forklift_utilization",
}

ANYLOGIC_BENCHMARK_KEY_MAP = {
    "Seize to Loading time (s)": "store_seize_to_load_start_s",
    "Loading time (s)": "store_load_duration_s",
    "Loading to Release time (s)": "store_load_finish_to_release_s",
    "Seize to Unloading time (s)": "retrieve_seize_to_unload_start_s",
    "Unloading time (s)": "retrieve_unload_duration_s",
    "Unloading to release time (s)": "retrieve_unload_finish_to_release_s",
}

SUMMARY_METRICS = [
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("storage_level", "Storage level"),
    ("throughput_per_hour", "Throughput (/h)"),
]

BENCHMARK_METRICS = [
    ("store_seize_to_load_start_s", "Seize to Loading time (s)"),
    ("store_load_duration_s", "Loading time (s)"),
    ("store_load_finish_to_release_s", "Loading to Release time (s)"),
    ("retrieve_seize_to_unload_start_s", "Seize to Unloading time (s)"),
    ("retrieve_unload_duration_s", "Unloading time (s)"),
    ("retrieve_unload_finish_to_release_s", "Unloading to release time (s)"),
]

BENCHMARK_STAT_FIELDS = [
    ("average", "avg"),
    ("minimum", "min"),
    ("maximum", "max"),
    ("std_dev_pop", "std dev (pop)"),
]

BENCHMARK_STAT_NAME_MAP = {
    "avg": "average",
    "min": "minimum",
    "max": "maximum",
    "std dev (pop)": "std_dev_pop",
    "std dev (sample)": "std_dev_sample",
}


@dataclass(frozen=True)
class BenchmarkStats:
    average: float
    minimum: float
    maximum: float
    std_dev_pop: float
    std_dev_sample: float | None = None
    count: int | None = None


@dataclass(frozen=True)
class AnyLogicBenchmarkRow:
    iteration: int
    arrival_rate_s: float
    forklift_capacity: int
    delay_time_s: float
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    storage_level: int
    throughput_per_hour: float
    forklift_utilization: float | None
    benchmarks: dict[str, BenchmarkStats]


@dataclass(frozen=True)
class SimPyBenchmarkRow:
    iteration: int
    arrival_rate_s: float
    forklift_capacity: int
    delay_time_s: float
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    storage_level: int
    throughput_per_hour: float
    benchmarks: dict[str, BenchmarkStats]


def parse_anylogic_benchmark_output(path: str | Path) -> list[AnyLogicBenchmarkRow]:
    iteration_re = re.compile(r"^ITERATION #(\d+)\s*$")
    key_value_re = re.compile(r"^\s*([^:]+):\s*(.+?)\s*$")
    benchmark_stat_re = re.compile(
        r"^\s*(avg|min|max|std dev \(pop\)|std dev \(sample\))\s*=\s*(.+?)\s*$"
    )

    rows: list[AnyLogicBenchmarkRow] = []
    current_iteration: int | None = None
    current_values: dict[str, int | float] = {}
    current_benchmarks: dict[str, dict[str, float]] = {}
    current_benchmark_key: str | None = None

    def finalize_current() -> None:
        nonlocal current_iteration, current_values, current_benchmarks, current_benchmark_key
        if current_iteration is None:
            return

        required_summary_fields = [
            "arrival_rate_s",
            "forklift_capacity",
            "delay_time_s",
            "created",
            "completed",
            "in_flight",
            "avg_time_in_system_s",
            "storage_level",
            "throughput_per_hour",
        ]
        missing = [name for name in required_summary_fields if name not in current_values]
        if missing:
            raise ValueError(
                f"AnyLogic iteration #{current_iteration} is missing fields: {', '.join(missing)}"
            )

        benchmarks: dict[str, BenchmarkStats] = {}
        for metric_key, values in current_benchmarks.items():
            required_benchmark_fields = [
                "average",
                "minimum",
                "maximum",
                "std_dev_pop",
            ]
            missing_fields = [
                field_name for field_name in required_benchmark_fields if field_name not in values
            ]
            if missing_fields:
                raise ValueError(
                    f"AnyLogic iteration #{current_iteration} benchmark '{metric_key}' "
                    f"is missing fields: {', '.join(missing_fields)}"
                )
            benchmarks[metric_key] = BenchmarkStats(
                average=values["average"],
                minimum=values["minimum"],
                maximum=values["maximum"],
                std_dev_pop=values["std_dev_pop"],
                std_dev_sample=values.get("std_dev_sample"),
            )

        rows.append(
            AnyLogicBenchmarkRow(
                iteration=current_iteration,
                arrival_rate_s=float(current_values["arrival_rate_s"]),
                forklift_capacity=int(current_values["forklift_capacity"]),
                delay_time_s=float(current_values["delay_time_s"]),
                created=int(current_values["created"]),
                completed=int(current_values["completed"]),
                in_flight=int(current_values["in_flight"]),
                avg_time_in_system_s=float(current_values["avg_time_in_system_s"]),
                storage_level=int(current_values["storage_level"]),
                throughput_per_hour=float(current_values["throughput_per_hour"]),
                forklift_utilization=(
                    None
                    if "forklift_utilization" not in current_values
                    else float(current_values["forklift_utilization"])
                ),
                benchmarks=benchmarks,
            )
        )

        current_iteration = None
        current_values = {}
        current_benchmarks = {}
        current_benchmark_key = None

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            iteration_match = iteration_re.match(line)
            if iteration_match:
                finalize_current()
                current_iteration = int(iteration_match.group(1))
                continue

            if current_iteration is None or not stripped:
                continue

            if stripped in {"PARAMETERS", "RESULTS"}:
                current_benchmark_key = None
                continue
            if stripped.startswith("WARNING"):
                continue

            benchmark_stat_match = benchmark_stat_re.match(line)
            if benchmark_stat_match and current_benchmark_key is not None:
                stat_name, raw_value = benchmark_stat_match.groups()
                stat_key = BENCHMARK_STAT_NAME_MAP[stat_name]
                current_benchmarks.setdefault(current_benchmark_key, {})[stat_key] = float(
                    raw_value
                )
                continue

            benchmark_key = ANYLOGIC_BENCHMARK_KEY_MAP.get(stripped)
            if benchmark_key is not None:
                current_benchmark_key = benchmark_key
                current_benchmarks.setdefault(benchmark_key, {})
                continue

            current_benchmark_key = None
            key_value_match = key_value_re.match(line)
            if not key_value_match:
                continue

            label, raw_value = key_value_match.groups()
            normalized_key = ANYLOGIC_SUMMARY_KEY_MAP.get(label)
            if normalized_key is None:
                continue
            current_values[normalized_key] = _parse_number(raw_value)

    finalize_current()
    return rows


def run_simpy_benchmark(anylogic_row: AnyLogicBenchmarkRow, *, sim_time: float) -> SimPyBenchmarkRow:
    params = Model2Params()
    params.sim_time = sim_time
    params.arrival_rate_per_min = 60.0 / anylogic_row.arrival_rate_s
    params.n_forklifts = anylogic_row.forklift_capacity
    params.delay_time_s = anylogic_row.delay_time_s

    model = Model1SimModel(params=params, console_logging=False, enable_logging=False)
    stats = model.run()

    benchmarks: dict[str, BenchmarkStats] = {}
    for row in build_forklift_movement_benchmark_rows(stats):
        benchmarks[row["metric_key"]] = BenchmarkStats(
            average=float(row["avg_s"]),
            minimum=float(row["min_s"]),
            maximum=float(row["max_s"]),
            std_dev_pop=float(row["std_dev_s"]),
            count=int(row["count"]),
        )

    return SimPyBenchmarkRow(
        iteration=anylogic_row.iteration,
        arrival_rate_s=anylogic_row.arrival_rate_s,
        forklift_capacity=anylogic_row.forklift_capacity,
        delay_time_s=anylogic_row.delay_time_s,
        created=stats.created,
        completed=stats.completed,
        in_flight=stats.created - stats.completed,
        avg_time_in_system_s=stats.avg_time_in_system,
        storage_level=int(model.storage.level),
        throughput_per_hour=((stats.completed / sim_time) * 3600.0 if sim_time else 0.0),
        benchmarks=benchmarks,
    )


def write_comparison_csv(
    anylogic_rows: list[AnyLogicBenchmarkRow],
    simpy_rows: list[SimPyBenchmarkRow],
    output_path: str | Path,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "iteration",
        "arrival_rate_s",
        "forklift_capacity",
        "delay_time_s",
        "section",
        "metric_key",
        "metric",
        "stat",
        "anylogic_value",
        "simpy_value",
        "simpy_count",
        "diff",
        "diff_pct",
        "status",
    ]

    with output.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for anylogic_row, simpy_row in zip(anylogic_rows, simpy_rows):
            for metric_key, label in SUMMARY_METRICS:
                anylogic_value = getattr(anylogic_row, metric_key)
                simpy_value = getattr(simpy_row, metric_key)
                writer.writerow(
                    _build_csv_row(
                        anylogic_row=anylogic_row,
                        section="summary",
                        metric_key=metric_key,
                        metric_label=label,
                        stat="value",
                        anylogic_value=anylogic_value,
                        simpy_value=simpy_value,
                        simpy_count=None,
                    )
                )

            for metric_key, label in BENCHMARK_METRICS:
                anylogic_stats = anylogic_row.benchmarks.get(metric_key)
                simpy_stats = simpy_row.benchmarks.get(metric_key)
                if anylogic_stats is None or simpy_stats is None:
                    continue
                for field_name, stat_label in BENCHMARK_STAT_FIELDS:
                    writer.writerow(
                        _build_csv_row(
                            anylogic_row=anylogic_row,
                            section="benchmark",
                            metric_key=metric_key,
                            metric_label=label,
                            stat=stat_label,
                            anylogic_value=getattr(anylogic_stats, field_name),
                            simpy_value=getattr(simpy_stats, field_name),
                            simpy_count=simpy_stats.count,
                        )
                    )

    return output


def print_report(anylogic_rows: list[AnyLogicBenchmarkRow], simpy_rows: list[SimPyBenchmarkRow]) -> None:
    print("=" * 112)
    print("MODEL 2 BENCHMARK COMPARISON: ANYLOGIC vs SIMPY")
    print("=" * 112)
    print("Arrival conversion used for SimPy: arrival_rate_per_min = 60 / arrival_rate_s")

    for anylogic_row, simpy_row in zip(anylogic_rows, simpy_rows):
        print("\n" + "-" * 112)
        print(
            f"ITERATION #{anylogic_row.iteration}  "
            f"arrival_s={_format_value(anylogic_row.arrival_rate_s)}  "
            f"forklifts={anylogic_row.forklift_capacity}  "
            f"delay_s={_format_value(anylogic_row.delay_time_s)}"
        )

        if anylogic_row.forklift_utilization is not None:
            print(
                "AnyLogic reported forklift utilization: "
                f"{_format_value(anylogic_row.forklift_utilization)} "
                "(no direct SimPy comparator in this script)"
            )

        print("\nSummary metrics:")
        _print_table(
            ["Metric", "AnyLogic", "SimPy", "Diff", "Diff %", "Status"],
            [
                [
                    label,
                    _format_value(getattr(anylogic_row, metric_key)),
                    _format_value(getattr(simpy_row, metric_key)),
                    _format_diff(
                        _numeric_diff(
                            getattr(anylogic_row, metric_key),
                            getattr(simpy_row, metric_key),
                        )
                    ),
                    _format_percent(
                        _percent_diff(
                            getattr(anylogic_row, metric_key),
                            getattr(simpy_row, metric_key),
                        )
                    ),
                    _status(
                        getattr(anylogic_row, metric_key),
                        getattr(simpy_row, metric_key),
                    ),
                ]
                for metric_key, label in SUMMARY_METRICS
            ],
            indent="  ",
        )

        print("\nForklift benchmark metrics:")
        benchmark_rows: list[list[str]] = []
        for metric_key, label in BENCHMARK_METRICS:
            anylogic_stats = anylogic_row.benchmarks.get(metric_key)
            simpy_stats = simpy_row.benchmarks.get(metric_key)
            if anylogic_stats is None or simpy_stats is None:
                benchmark_rows.append(
                    [label, "-", "missing", "missing", "n/a", "n/a", "DIFF", "n/a"]
                )
                continue

            for field_name, stat_label in BENCHMARK_STAT_FIELDS:
                anylogic_value = getattr(anylogic_stats, field_name)
                simpy_value = getattr(simpy_stats, field_name)
                benchmark_rows.append(
                    [
                        label,
                        stat_label,
                        _format_value(anylogic_value),
                        _format_value(simpy_value),
                        _format_diff(_numeric_diff(anylogic_value, simpy_value)),
                        _format_percent(_percent_diff(anylogic_value, simpy_value)),
                        _status(anylogic_value, simpy_value),
                        "n/a" if simpy_stats.count is None else str(simpy_stats.count),
                    ]
                )

        _print_table(
            ["Metric", "Stat", "AnyLogic", "SimPy", "Diff", "Diff %", "Status", "SimPy n"],
            benchmark_rows,
            indent="  ",
        )


def _build_csv_row(
    *,
    anylogic_row: AnyLogicBenchmarkRow,
    section: str,
    metric_key: str,
    metric_label: str,
    stat: str,
    anylogic_value: int | float,
    simpy_value: int | float,
    simpy_count: int | None,
) -> dict[str, str | int | float | None]:
    diff = _numeric_diff(anylogic_value, simpy_value)
    diff_pct = _percent_diff(anylogic_value, simpy_value)
    return {
        "iteration": anylogic_row.iteration,
        "arrival_rate_s": anylogic_row.arrival_rate_s,
        "forklift_capacity": anylogic_row.forklift_capacity,
        "delay_time_s": anylogic_row.delay_time_s,
        "section": section,
        "metric_key": metric_key,
        "metric": metric_label,
        "stat": stat,
        "anylogic_value": anylogic_value,
        "simpy_value": simpy_value,
        "simpy_count": simpy_count,
        "diff": diff,
        "diff_pct": diff_pct,
        "status": _status(anylogic_value, simpy_value),
    }


def _parse_number(raw_value: str) -> int | float:
    value = raw_value.strip()
    if re.search(r"[.eE]", value):
        return float(value)
    return int(value)


def _numeric_diff(anylogic_value: int | float, simpy_value: int | float) -> float:
    return float(simpy_value) - float(anylogic_value)


def _percent_diff(anylogic_value: int | float, simpy_value: int | float) -> float | None:
    baseline = abs(float(anylogic_value))
    if baseline < 1e-12:
        return None
    return ((float(simpy_value) - float(anylogic_value)) / baseline) * 100.0


def _values_match(left: int | float, right: int | float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)


def _status(anylogic_value: int | float, simpy_value: int | float) -> str:
    if _values_match(anylogic_value, simpy_value):
        return "MATCH"
    diff_pct = _percent_diff(anylogic_value, simpy_value)
    if diff_pct is not None and abs(diff_pct) < 1.0:
        return "CLOSE"
    return "DIFF"


def _format_value(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    text = f"{value:.6f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_diff(value: float) -> str:
    text = f"{value:+.6f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    text = f"{value:+.2f}%"
    if ".00%" in text:
        text = text.replace(".00%", "%")
    return text


def _print_table(header: list[str], rows: list[list[str]], *, indent: str = "") -> None:
    if not rows:
        print(f"{indent}<no rows>")
        return

    widths = [len(column) for column in header]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(
        indent
        + "  ".join(value.ljust(widths[index]) for index, value in enumerate(header))
    )
    print(indent + "  ".join("-" * width for width in widths))
    for row in rows:
        print(
            indent
            + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic Model 2 benchmark text against fresh SimPy runs."
    )
    parser.add_argument(
        "--anylogic",
        required=True,
        help="Path to the AnyLogic benchmark output text file.",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=18000.0,
        help="SimPy stop time in seconds. Default matches the current Model 2 run length.",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=None,
        help="Optional single iteration number to compare.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV export path for the flattened comparison rows.",
    )
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_benchmark_output(args.anylogic)
    if args.iteration is not None:
        anylogic_rows = [row for row in anylogic_rows if row.iteration == args.iteration]
        if not anylogic_rows:
            raise ValueError(f"Iteration #{args.iteration} was not found in {args.anylogic}")

    simpy_rows = [
        run_simpy_benchmark(row, sim_time=args.sim_time)
        for row in anylogic_rows
    ]

    print_report(anylogic_rows, simpy_rows)

    if args.csv:
        output_path = write_comparison_csv(anylogic_rows, simpy_rows, args.csv)
        print(f"\nCSV export: {output_path}")


if __name__ == "__main__":
    main()
