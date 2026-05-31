#!/usr/bin/env python3
"""Compare AnyLogic Model 1 benchmark output against fresh SimPy runs."""

from __future__ import annotations
import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from mhsim.reporting import build_forklift_movement_benchmark_rows

from .benchmark_labels import (
    ANYLOGIC_BENCHMARK_KEY_MAP,
    MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
)
from .anylogic_range import Model1RangeValues, range_values_for_iteration
from .model import Model1SimModel
from .params import Model1Params


ANYLOGIC_SUMMARY_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Displacement (m)": "displacement_m",
    "Forklift capacity": "forklift_capacity",
    "Forklift max speed (m/s)": "forklift_max_speed",
    "Forklift acceleration (m/s/s)": "forklift_acceleration",
    "Created": "created",
    "Completed": "completed",
    "Avg WIP": "avg_wip",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
    "Forklifts Utilization (%)": "forklift_utilization",
}

SUMMARY_METRICS = [
    ("created", "Created"),
    ("completed", "Completed"),
    ("avg_wip", "Avg WIP"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
]
OPTIONAL_SUMMARY_METRICS = [
    ("forklift_utilization", "Forklifts Utilization (%)"),
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


# TODO AnyLogicBenchmarkRow and SimPyBenchmarkRow are exactly the same. We may use the same dataclass for them.
@dataclass(frozen=True)
class AnyLogicBenchmarkRow:
    iteration: int
    arrival_rate_s: float
    forklift_capacity: int
    forklift_max_speed: float | None
    forklift_acceleration: float | None
    displacement_m: float | None
    created: int
    completed: int
    avg_wip: float
    avg_time_in_system_s: float
    throughput_per_hour: float
    forklift_utilization: float | None
    benchmarks: dict[str, BenchmarkStats]


@dataclass(frozen=True)
class SimPyBenchmarkRow:
    iteration: int
    arrival_rate_s: float
    forklift_capacity: int
    created: int
    completed: int
    avg_wip: float
    avg_time_in_system_s: float
    throughput_per_hour: float
    forklift_utilization: float
    benchmarks: dict[str, BenchmarkStats]


def _parse_number(text: str) -> int | float:
    value = float(text.strip())
    return int(value) if value.is_integer() else value


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
            "created",
            "completed",
            "avg_wip",
            "avg_time_in_system_s",
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
                field_name
                for field_name in required_benchmark_fields
                if field_name not in values
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
                forklift_max_speed=(
                    None
                    if "forklift_max_speed" not in current_values
                    else float(current_values["forklift_max_speed"])
                ),
                forklift_acceleration=(
                    None
                    if "forklift_acceleration" not in current_values
                    else float(current_values["forklift_acceleration"])
                ),
                displacement_m=(
                    None
                    if "displacement_m" not in current_values
                    else float(current_values["displacement_m"])
                ),
                created=int(current_values["created"]),
                completed=int(current_values["completed"]),
                avg_wip=float(current_values["avg_wip"]),
                avg_time_in_system_s=float(current_values["avg_time_in_system_s"]),
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


def _parameter_values_for_anylogic_row(
    anylogic_row: AnyLogicBenchmarkRow,
) -> Model1RangeValues:
    if (
        anylogic_row.forklift_max_speed is not None
        and anylogic_row.forklift_acceleration is not None
        and anylogic_row.displacement_m is not None
    ):
        return Model1RangeValues(
            arrival_rate_s=anylogic_row.arrival_rate_s,
            n_forklifts=anylogic_row.forklift_capacity,
            forklift_max_speed=anylogic_row.forklift_max_speed,
            forklift_acceleration=anylogic_row.forklift_acceleration,
            displacement_m=anylogic_row.displacement_m,
        )
    return range_values_for_iteration(anylogic_row.iteration)


def run_simpy_benchmark(
    anylogic_row: AnyLogicBenchmarkRow, *, sim_time: float
) -> SimPyBenchmarkRow:
    params = Model1Params()
    params.sim_time = sim_time
    range_values = _parameter_values_for_anylogic_row(anylogic_row)
    params.arrival_rate_s = range_values.arrival_rate_s
    params.n_forklifts = range_values.n_forklifts
    params.forklift_max_speed = range_values.forklift_max_speed
    params.forklift_acceleration = range_values.forklift_acceleration
    params.displacement_m = range_values.displacement_m

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
        created=stats.created,
        completed=stats.completed,
        avg_wip=(stats.avg_time_in_system * (stats.completed / sim_time) if sim_time else 0.0),
        avg_time_in_system_s=stats.avg_time_in_system,
        throughput_per_hour=((stats.completed / sim_time) * 3600.0 if sim_time else 0.0),
        forklift_utilization=model.fleet.utilization,
        benchmarks=benchmarks,
    )

def _numeric_diff(anylogic_value: int | float, simpy_value: int | float) -> float:
    return float(simpy_value) - float(anylogic_value)


def _percent_diff(anylogic_value: int | float, simpy_value: int | float) -> float | None:
    if math.isclose(float(anylogic_value), float(simpy_value), rel_tol=1e-9, abs_tol=1e-9):
        return 0.0
    if abs(float(anylogic_value)) < 1e-9 and abs(float(simpy_value)) < 1e-9:
        return None
    if math.isclose(float(anylogic_value), 0.0):
        return None
    return abs(_numeric_diff(anylogic_value, simpy_value)) / abs(float(anylogic_value)) * 100.0


def _status(anylogic_value: int | float, simpy_value: int | float) -> str:
    if math.isclose(float(anylogic_value), float(simpy_value), rel_tol=1e-9, abs_tol=1e-9):
        return "MATCH"
    pct = _percent_diff(anylogic_value, simpy_value)
    if pct is None or pct < 1:
        return "MATCH"
    if pct < 2:
        return "CLOSE"
    return "DIFF"


def _format_value(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int) or math.isclose(float(value), round(float(value))):
        return f"{float(value):.0f}"
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def _format_diff(value: float) -> str:
    return f"{value:+.6f}".rstrip("0").rstrip(".")


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%".rstrip("0").rstrip(".")


def _print_table(headers: list[str], rows: list[list[str]], *, indent: str = "") -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def render(values: list[str]) -> str:
        return indent + "  ".join(
            value.ljust(widths[idx]) for idx, value in enumerate(values)
        )

    print(render(headers))
    print(indent + "  ".join("-" * width for width in widths))
    for row in rows:
        print(render(row))


def _ordered_benchmark_metrics(
    anylogic_rows: list[AnyLogicBenchmarkRow],
) -> list[tuple[str, str]]:
    present_keys = {metric_key for row in anylogic_rows for metric_key in row.benchmarks}
    ordered_metrics: list[tuple[str, str]] = []
    seen: set[str] = set()

    for metric_key, label in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS.items():
        if metric_key not in present_keys:
            continue
        ordered_metrics.append((metric_key, label))
        seen.add(metric_key)

    for metric_key in sorted(present_keys):
        if metric_key in seen:
            continue
        ordered_metrics.append((metric_key, metric_key))

    return ordered_metrics


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
    range_values = _parameter_values_for_anylogic_row(anylogic_row)
    return {
        "iteration": anylogic_row.iteration,
        "arrival_rate_s": anylogic_row.arrival_rate_s,
        "forklift_capacity": anylogic_row.forklift_capacity,
        "forklift_max_speed": range_values.forklift_max_speed,
        "forklift_acceleration": range_values.forklift_acceleration,
        "displacement_m": range_values.displacement_m,
        "section": section,
        "metric_key": metric_key,
        "metric": metric_label,
        "stat": stat,
        "anylogic_value": anylogic_value,
        "simpy_value": simpy_value,
        "simpy_count": simpy_count,
        "diff": _numeric_diff(anylogic_value, simpy_value),
        "diff_pct": _percent_diff(anylogic_value, simpy_value),
        "status": _status(anylogic_value, simpy_value),
    }


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
        "forklift_max_speed",
        "forklift_acceleration",
        "displacement_m",
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

        benchmark_metrics = _ordered_benchmark_metrics(anylogic_rows)
        for anylogic_row, simpy_row in zip(anylogic_rows, simpy_rows):
            for metric_key, label in SUMMARY_METRICS:
                writer.writerow(
                    _build_csv_row(
                        anylogic_row=anylogic_row,
                        section="summary",
                        metric_key=metric_key,
                        metric_label=label,
                        stat="value",
                        anylogic_value=getattr(anylogic_row, metric_key),
                        simpy_value=getattr(simpy_row, metric_key),
                        simpy_count=None,
                    )
                )
            for metric_key, label in OPTIONAL_SUMMARY_METRICS:
                anylogic_value = getattr(anylogic_row, metric_key)
                if anylogic_value is None:
                    continue
                writer.writerow(
                    _build_csv_row(
                        anylogic_row=anylogic_row,
                        section="summary",
                        metric_key=metric_key,
                        metric_label=label,
                        stat="value",
                        anylogic_value=anylogic_value,
                        simpy_value=getattr(simpy_row, metric_key),
                        simpy_count=None,
                    )
                )

            for metric_key, label in benchmark_metrics:
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


def print_report(
    anylogic_rows: list[AnyLogicBenchmarkRow], simpy_rows: list[SimPyBenchmarkRow]
) -> None:
    print("=" * 112)
    print("MODEL 1 BENCHMARK COMPARISON: ANYLOGIC vs SIMPY")
    print("=" * 112)
    print("Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval")

    benchmark_metrics = _ordered_benchmark_metrics(anylogic_rows)
    for anylogic_row, simpy_row in zip(anylogic_rows, simpy_rows):
        print("\n" + "-" * 112)
        range_values = _parameter_values_for_anylogic_row(anylogic_row)
        print(
            f"ITERATION #{anylogic_row.iteration}  "
            f"arrival_s={_format_value(anylogic_row.arrival_rate_s)}  "
            f"forklifts={anylogic_row.forklift_capacity}  "
            f"speed={_format_value(range_values.forklift_max_speed)}  "
            f"accel={_format_value(range_values.forklift_acceleration)}  "
            f"displacement={_format_value(range_values.displacement_m)}"
        )

        print("\nSummary metrics:")
        summary_metrics = list(SUMMARY_METRICS)
        if anylogic_row.forklift_utilization is not None:
            summary_metrics.extend(OPTIONAL_SUMMARY_METRICS)
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
                for metric_key, label in summary_metrics
            ],
            indent="  ",
        )

        print("\nForklift benchmark metrics:")
        benchmark_rows: list[list[str]] = []
        for metric_key, label in benchmark_metrics:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic Model 1 benchmark text against fresh SimPy runs."
    )
    parser.add_argument(
        "--anylogic",
        required=True,
        help="Path to the AnyLogic benchmark output text file.",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=3600.0,
        help="SimPy run duration for each benchmark iteration.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV export path for the comparison table.",
    )
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_benchmark_output(args.anylogic)
    simpy_rows = [run_simpy_benchmark(row, sim_time=args.sim_time) for row in anylogic_rows]
    print_report(anylogic_rows, simpy_rows)
    if args.csv:
        output_path = write_comparison_csv(anylogic_rows, simpy_rows, args.csv)
        print(f"\nCSV export: {output_path}")


if __name__ == "__main__":
    main()
