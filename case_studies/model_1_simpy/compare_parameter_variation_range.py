#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 1 parameter-variation range runs.

This comparison focuses on the summary metrics, like the Model 1 range audit.
For per-phase forklift timing details on one or more matching iterations, use
`case_studies.model_1_simpy.compare_benchmark_results` against the same
AnyLogic text export.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from case_studies.model_1_simpy.compare_benchmark_results import (
    BENCHMARK_STAT_FIELDS,
    BenchmarkStats,
    MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
    parse_anylogic_benchmark_output,
)
from case_studies.model_1_simpy.anylogic_range import range_values_for_iteration


METRICS = [
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
]
OPTIONAL_METRICS = [
    ("forklift_utilization", "Forklifts Utilization (%)"),
]
BENCHMARK_METRIC_PREFIX = "benchmark_"
BENCHMARK_STAT_LABELS = {field_name: label for field_name, label in BENCHMARK_STAT_FIELDS}
BENCHMARK_STAT_DISPLAY_LABELS = {
    "average": "avg",
    "minimum": "min",
    "maximum": "max",
    "std_dev_pop": "std",
}
BENCHMARK_AVG_ONLY = "benchmark_avg_only"


@dataclass(frozen=True)
class AnyLogicRangeRow:
    iteration: int
    arrival_rate_s: float
    forklift_capacity: int
    forklift_max_speed: float
    forklift_acceleration: float
    displacement_m: float
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    throughput_per_hour: float
    forklift_utilization: float | None
    benchmarks: dict[str, BenchmarkStats]

    @property
    def match_key(self) -> tuple[float, int, float, float, float]:
        return (
            self.arrival_rate_s,
            self.forklift_capacity,
            self.forklift_max_speed,
            self.forklift_acceleration,
            self.displacement_m,
        )


@dataclass(frozen=True)
class SimPyRangeSummaryRow:
    iteration: int
    replications: int
    arrival_rate_s: float
    forklift_capacity: int
    forklift_max_speed: float
    forklift_acceleration: float
    displacement_m: float
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    throughput_per_hour: float
    forklift_utilization: float | None
    benchmarks: dict[str, BenchmarkStats]

    @property
    def match_key(self) -> tuple[float, int, float, float, float]:
        return (
            self.arrival_rate_s,
            self.forklift_capacity,
            self.forklift_max_speed,
            self.forklift_acceleration,
            self.displacement_m,
        )


@dataclass(frozen=True)
class SimPyRangeRunRow:
    iteration: int
    replication: int
    arrival_rate_s: float
    forklift_capacity: int
    forklift_max_speed: float
    forklift_acceleration: float
    displacement_m: float
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    throughput_per_hour: float
    forklift_utilization: float | None
    benchmarks: dict[str, BenchmarkStats]


@dataclass(frozen=True)
class ComparisonContext:
    validation_issues: list[str]
    anylogic_by_key: dict[tuple[float, int, float, float, float], AnyLogicRangeRow]
    simpy_by_key: dict[tuple[float, int, float, float, float], SimPyRangeSummaryRow]
    common_keys: list[tuple[float, int, float, float, float]]
    anylogic_only: list[tuple[float, int, float, float, float]]
    simpy_only: list[tuple[float, int, float, float, float]]


@dataclass(frozen=True)
class MetricComparisonRow:
    metric_name: str
    label: str
    anylogic_value: int | float
    simpy_value: int | float
    diff: float
    diff_pct: float | None
    status: str


@dataclass(frozen=True)
class OverviewRow:
    metric_name: str
    label: str
    match_count: int
    close_count: int
    diff_count: int
    worst_diff: float
    worst_pct: float | None
    worst_case: tuple[float, int, float, float, float] | None


@dataclass(frozen=True)
class OffenderRow:
    rank: int
    metric_name: str
    label: str
    key: tuple[float, int, float, float, float]
    anylogic_iteration: int
    simpy_iteration: int
    anylogic_value: int | float
    simpy_value: int | float
    diff: float
    diff_pct: float | None
    status: str
    severity: float


@dataclass(frozen=True)
class IterationReportRow:
    key: tuple[float, int, float, float, float]
    anylogic_iteration: int
    simpy_iteration: int
    case_label: str
    benchmark_rows: list[MetricComparisonRow]
    summary_rows: list[MetricComparisonRow]


@dataclass(frozen=True)
class ReportData:
    context: ComparisonContext
    overview_rows: list[OverviewRow]
    offender_rows: list[OffenderRow]
    iteration_rows: list[IterationReportRow]
    exact_match_metrics: list[str]
    close_or_diff_rows: list[OverviewRow]


def parse_anylogic_range_output(path: str | Path) -> list[AnyLogicRangeRow]:
    rows: list[AnyLogicRangeRow] = []
    for row in parse_anylogic_benchmark_output(path):
        range_values = range_values_for_iteration(row.iteration)
        forklift_max_speed = (
            row.forklift_max_speed
            if row.forklift_max_speed is not None
            else range_values.forklift_max_speed
        )
        forklift_acceleration = (
            row.forklift_acceleration
            if row.forklift_acceleration is not None
            else range_values.forklift_acceleration
        )
        displacement_m = (
            row.displacement_m
            if row.displacement_m is not None
            else range_values.displacement_m
        )
        rows.append(
            AnyLogicRangeRow(
                iteration=row.iteration,
                arrival_rate_s=row.arrival_rate_s,
                forklift_capacity=row.forklift_capacity,
                forklift_max_speed=forklift_max_speed,
                forklift_acceleration=forklift_acceleration,
                displacement_m=displacement_m,
                created=row.created,
                completed=row.completed,
                in_flight=row.in_flight,
                avg_time_in_system_s=row.avg_time_in_system_s,
                throughput_per_hour=row.throughput_per_hour,
                forklift_utilization=row.forklift_utilization,
                benchmarks=row.benchmarks,
            )
        )
    return rows


def load_simpy_summary_rows(path: str | Path) -> list[SimPyRangeSummaryRow]:
    rows: list[SimPyRangeSummaryRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                SimPyRangeSummaryRow(
                    iteration=_int_field(record, "iteration"),
                    replications=_int_field(record, "replications"),
                    arrival_rate_s=_float_field(record, "param_arrival_rate_s"),
                    forklift_capacity=_int_field(record, "param_n_forklifts"),
                    forklift_max_speed=_float_field(record, "param_forklift_max_speed"),
                    forklift_acceleration=_float_field(record, "param_forklift_acceleration"),
                    displacement_m=_float_field(record, "param_displacement_m"),
                    created=_metric_int_field(record, "created"),
                    completed=_metric_int_field(record, "completed"),
                    in_flight=_metric_int_field(record, "in_flight"),
                    avg_time_in_system_s=_metric_float_field(
                        record, "avg_time_in_system_s"
                    ),
                    throughput_per_hour=_metric_float_field(
                        record, "throughput_per_hour"
                    ),
                    forklift_utilization=_optional_metric_float_field(
                        record, "forklift_utilization"
                    ),
                    benchmarks=_load_summary_benchmarks(record),
                )
            )
    return rows


def load_simpy_run_rows(path: str | Path) -> list[SimPyRangeRunRow]:
    rows: list[SimPyRangeRunRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                SimPyRangeRunRow(
                    iteration=_int_field(record, "iteration"),
                    replication=_int_field(record, "replication"),
                    arrival_rate_s=_float_field(record, "param_arrival_rate_s"),
                    forklift_capacity=_int_field(record, "param_n_forklifts"),
                    forklift_max_speed=_float_field(record, "param_forklift_max_speed"),
                    forklift_acceleration=_float_field(record, "param_forklift_acceleration"),
                    displacement_m=_float_field(record, "param_displacement_m"),
                    created=_int_field(record, "metric_created"),
                    completed=_int_field(record, "metric_completed"),
                    in_flight=_int_field(record, "metric_in_flight"),
                    avg_time_in_system_s=_float_field(
                        record, "metric_avg_time_in_system_s"
                    ),
                    throughput_per_hour=_float_field(
                        record, "metric_throughput_per_hour"
                    ),
                    forklift_utilization=_optional_float_field(
                        record, "metric_forklift_utilization"
                    ),
                    benchmarks=_load_run_benchmarks(record),
                )
            )
    return rows


def validate_simpy_runs(
    summary_rows: list[SimPyRangeSummaryRow],
    run_rows: list[SimPyRangeRunRow],
) -> list[str]:
    issues: list[str] = []
    metrics = _available_simpy_metrics(summary_rows, run_rows)
    summary_by_iteration = {row.iteration: row for row in summary_rows}
    runs_by_iteration: dict[int, list[SimPyRangeRunRow]] = {}
    for row in run_rows:
        runs_by_iteration.setdefault(row.iteration, []).append(row)

    for iteration, rows in sorted(runs_by_iteration.items()):
        first = rows[0]
        for other in rows[1:]:
            for field_name, _ in metrics:
                if not _values_match(
                    _metric_value(first, field_name),
                    _metric_value(other, field_name),
                ):
                    issues.append(
                        f"SimPy iteration {iteration} differs across replications "
                        f"for '{field_name}': replication {first.replication}="
                        f"{_metric_value(first, field_name)} vs replication {other.replication}="
                        f"{_metric_value(other, field_name)}"
                    )
        summary = summary_by_iteration.get(iteration)
        if summary is None:
            issues.append(f"SimPy summary is missing iteration {iteration}")
            continue
        for field_name, _ in metrics:
            if not _values_match(
                _metric_value(first, field_name),
                _metric_value(summary, field_name),
            ):
                issues.append(
                    f"SimPy summary mismatch for iteration {iteration} field '{field_name}': "
                    f"summary={_metric_value(summary, field_name)} runs={_metric_value(first, field_name)}"
                )
    return issues


def print_comparison_report(
    anylogic_rows: list[AnyLogicRangeRow],
    simpy_summary_rows: list[SimPyRangeSummaryRow],
    simpy_run_rows: list[SimPyRangeRunRow],
    *,
    view: str,
    metric_name: str,
    top: int,
) -> None:
    context = build_comparison_context(anylogic_rows, simpy_summary_rows, simpy_run_rows)
    _print_report_header(context)
    _print_unmatched(context)

    if not context.common_keys:
        print("\nNo common parameter combinations found.")
        return

    if view == "full":
        _print_full_view(context)
    elif view == "overview":
        _print_overview_view(context)
    elif view == "matrix":
        _print_matrix_view(context, metric_name=metric_name)
    elif view == "offenders":
        _print_offenders_view(context, metric_name=metric_name, top=top)
    elif view == "report":
        _print_report_view(context, metric_name=metric_name, top=top)
    elif view == "all":
        _print_overview_view(context)
        _print_matrix_view(context, metric_name=metric_name)
        _print_offenders_view(context, metric_name=metric_name, top=top)
        _print_full_view(context)
    else:
        raise ValueError(f"Unsupported view: {view}")


def build_comparison_context(
    anylogic_rows: list[AnyLogicRangeRow],
    simpy_summary_rows: list[SimPyRangeSummaryRow],
    simpy_run_rows: list[SimPyRangeRunRow],
) -> ComparisonContext:
    validation_issues = validate_simpy_runs(simpy_summary_rows, simpy_run_rows)
    anylogic_by_key = {row.match_key: row for row in anylogic_rows}
    simpy_by_key = {row.match_key: row for row in simpy_summary_rows}

    anylogic_keys = set(anylogic_by_key)
    simpy_keys = set(simpy_by_key)
    common_keys = sorted(anylogic_keys & simpy_keys)
    anylogic_only = sorted(anylogic_keys - simpy_keys)
    simpy_only = sorted(simpy_keys - anylogic_keys)
    return ComparisonContext(
        validation_issues=validation_issues,
        anylogic_by_key=anylogic_by_key,
        simpy_by_key=simpy_by_key,
        common_keys=common_keys,
        anylogic_only=anylogic_only,
        simpy_only=simpy_only,
    )


def render_comparison_report_text(
    context: ComparisonContext,
    *,
    view: str,
    metric_name: str,
    top: int,
) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        _print_report_header(context)
        _print_unmatched(context)

        if not context.common_keys:
            print("\nNo common parameter combinations found.")
        elif view == "full":
            _print_full_view(context)
        elif view == "overview":
            _print_overview_view(context)
        elif view == "matrix":
            _print_matrix_view(context, metric_name=metric_name)
        elif view == "offenders":
            _print_offenders_view(context, metric_name=metric_name, top=top)
        elif view == "report":
            _print_report_view(context, metric_name=metric_name, top=top)
        elif view == "all":
            _print_overview_view(context)
            _print_matrix_view(context, metric_name=metric_name)
            _print_offenders_view(context, metric_name=metric_name, top=top)
            _print_full_view(context)
        else:
            raise ValueError(f"Unsupported view: {view}")
    return output.getvalue()


def build_report_data(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> ReportData:
    overview_rows = _build_overview_rows(context)
    offender_rows = _build_offender_rows(context, metric_name=metric_name, top=top)
    iteration_rows = _build_iteration_report_rows(context)
    exact_match_metrics = [
        row.label
        for row in overview_rows
        if row.close_count == 0 and row.diff_count == 0
    ]
    close_or_diff_rows = [
        row
        for row in overview_rows
        if row.close_count > 0 or row.diff_count > 0
    ]
    return ReportData(
        context=context,
        overview_rows=overview_rows,
        offender_rows=offender_rows,
        iteration_rows=iteration_rows,
        exact_match_metrics=exact_match_metrics,
        close_or_diff_rows=close_or_diff_rows,
    )


def _build_overview_rows(context: ComparisonContext) -> list[OverviewRow]:
    rows: list[OverviewRow] = []
    for field_name, label in _comparison_metrics(context):
        counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
        worst_diff: tuple[float, float, tuple[float, int, float, float, float]] | None = None
        worst_pct: tuple[float, float | None, tuple[float, int, float, float, float]] | None = None

        for anylogic, simpy in _matched_rows(context):
            metric_row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            counts[metric_row.status] += 1
            diff_rank = abs(metric_row.diff)
            pct_rank = abs(metric_row.diff_pct) if metric_row.diff_pct is not None else -1.0

            if worst_diff is None or diff_rank > worst_diff[0]:
                worst_diff = (diff_rank, metric_row.diff, anylogic.match_key)
            if worst_pct is None or pct_rank > worst_pct[0]:
                worst_pct = (pct_rank, metric_row.diff_pct, anylogic.match_key)

        rows.append(
            OverviewRow(
                metric_name=field_name,
                label=label,
                match_count=counts["MATCH"],
                close_count=counts["CLOSE"],
                diff_count=counts["DIFF"],
                worst_diff=0.0 if worst_diff is None else worst_diff[1],
                worst_pct=None if worst_pct is None else worst_pct[1],
                worst_case=None if worst_pct is None else worst_pct[2],
            )
        )
    return rows


def _build_offender_rows(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> list[OffenderRow]:
    offenders: list[OffenderRow] = []
    for anylogic, simpy in _matched_rows(context):
        for field_name, label in _selected_metrics(
            metric_name, _comparison_metrics(context)
        ):
            metric_row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            severity = (
                abs(metric_row.diff_pct)
                if metric_row.diff_pct is not None
                else abs(metric_row.diff)
            )
            offenders.append(
                OffenderRow(
                    rank=0,
                    metric_name=field_name,
                    label=label,
                    key=anylogic.match_key,
                    anylogic_iteration=anylogic.iteration,
                    simpy_iteration=simpy.iteration,
                    anylogic_value=metric_row.anylogic_value,
                    simpy_value=metric_row.simpy_value,
                    diff=metric_row.diff,
                    diff_pct=metric_row.diff_pct,
                    status=metric_row.status,
                    severity=severity,
                )
            )

    offenders.sort(
        key=lambda item: (
            item.severity,
            abs(item.diff),
            item.key[0],
            item.key[1],
            item.key[2],
            item.key[3],
            item.key[4],
            item.label,
        ),
        reverse=True,
    )
    return [
        OffenderRow(
            rank=index,
            metric_name=row.metric_name,
            label=row.label,
            key=row.key,
            anylogic_iteration=row.anylogic_iteration,
            simpy_iteration=row.simpy_iteration,
            anylogic_value=row.anylogic_value,
            simpy_value=row.simpy_value,
            diff=row.diff,
            diff_pct=row.diff_pct,
            status=row.status,
            severity=row.severity,
        )
        for index, row in enumerate(offenders[:top], start=1)
    ]


def _build_iteration_report_rows(context: ComparisonContext) -> list[IterationReportRow]:
    metrics = _comparison_metrics(context)
    benchmark_metrics = [
        (field_name, label)
        for field_name, label in metrics
        if field_name.startswith(BENCHMARK_METRIC_PREFIX)
    ]
    summary_metrics = [
        (field_name, label)
        for field_name, label in metrics
        if not field_name.startswith(BENCHMARK_METRIC_PREFIX)
    ]
    rows: list[IterationReportRow] = []
    for anylogic, simpy in _matched_rows(context):
        rows.append(
            IterationReportRow(
                key=anylogic.match_key,
                anylogic_iteration=anylogic.iteration,
                simpy_iteration=simpy.iteration,
                case_label=_format_case(anylogic.match_key),
                benchmark_rows=[
                    _build_metric_comparison_row(anylogic, simpy, field_name, label)
                    for field_name, label in benchmark_metrics
                ],
                summary_rows=[
                    _build_metric_comparison_row(anylogic, simpy, field_name, label)
                    for field_name, label in summary_metrics
                ],
            )
        )
    return rows


def _build_metric_comparison_row(
    anylogic: AnyLogicRangeRow,
    simpy: SimPyRangeSummaryRow,
    field_name: str,
    label: str,
) -> MetricComparisonRow:
    anylogic_value = _metric_value(anylogic, field_name)
    simpy_value = _metric_value(simpy, field_name)
    diff = _numeric_diff(anylogic_value, simpy_value)
    diff_pct = _percent_diff(anylogic_value, simpy_value)
    return MetricComparisonRow(
        metric_name=field_name,
        label=label,
        anylogic_value=anylogic_value,
        simpy_value=simpy_value,
        diff=diff,
        diff_pct=diff_pct,
        status=_status(anylogic_value, simpy_value),
    )


def _print_report_header(context: ComparisonContext) -> None:
    print("=" * 92)
    print("PARAMETER VARIATION RANGE COMPARISON: ANYLOGIC vs SIMPY")
    print("=" * 92)

    if context.validation_issues:
        print("SimPy consistency check: FAIL")
        for issue in context.validation_issues:
            print(f"  - {issue}")
    else:
        print("SimPy consistency check: PASS")

    print(
        f"Matched parameter combinations: {len(context.common_keys)}  "
        f"AnyLogic-only: {len(context.anylogic_only)}  SimPy-only: {len(context.simpy_only)}"
    )
    print("Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval")


def _print_unmatched(context: ComparisonContext) -> None:
    if context.anylogic_only:
        print("\nAnyLogic combinations without a matching SimPy summary row:")
        for key in context.anylogic_only:
            print(
                f"  {_format_case(key)}"
            )

    if context.simpy_only:
        print("\nSimPy combinations without a matching AnyLogic row:")
        for key in context.simpy_only:
            print(
                f"  {_format_case(key)}"
            )


def _matched_rows(
    context: ComparisonContext,
) -> list[tuple[AnyLogicRangeRow, SimPyRangeSummaryRow]]:
    return [
        (
            context.anylogic_by_key[key],
            context.simpy_by_key[key],
        )
        for key in context.common_keys
    ]


def _available_simpy_metrics(
    summary_rows: list[SimPyRangeSummaryRow],
    run_rows: list[SimPyRangeRunRow],
) -> list[tuple[str, str]]:
    metrics = list(METRICS)
    for field_name, label in OPTIONAL_METRICS:
        if any(getattr(row, field_name) is not None for row in summary_rows) and any(
            getattr(row, field_name) is not None for row in run_rows
        ):
            metrics.append((field_name, label))
    metrics.extend(_available_benchmark_metrics(summary_rows, run_rows))
    return metrics


def _comparison_metrics(
    context: ComparisonContext,
) -> list[tuple[str, str]]:
    metrics = list(METRICS)
    matched = _matched_rows(context)
    for field_name, label in OPTIONAL_METRICS:
        if matched and all(
            getattr(anylogic, field_name) is not None
            and getattr(simpy, field_name) is not None
            for anylogic, simpy in matched
        ):
            metrics.append((field_name, label))
    metrics.extend(_comparison_benchmark_metrics(matched))
    return metrics


def _selected_metrics(
    metric_name: str,
    available_metrics: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    metric_name = _normalize_selected_metric_name(metric_name)
    if metric_name == "all":
        return available_metrics
    if metric_name == BENCHMARK_AVG_ONLY:
        return [
            (field_name, label)
            for field_name, label in available_metrics
            if field_name.startswith(BENCHMARK_METRIC_PREFIX)
            and field_name.endswith("__average")
        ]
    for field_name, label in available_metrics:
        if field_name == metric_name:
            return [(field_name, label)]
    raise ValueError(f"Unsupported metric: {metric_name}")


def _normalize_selected_metric_name(metric_name: str) -> str:
    if metric_name in {"all", BENCHMARK_AVG_ONLY}:
        return metric_name

    benchmark_name = metric_name
    if benchmark_name.startswith(BENCHMARK_METRIC_PREFIX):
        benchmark_name = benchmark_name[len(BENCHMARK_METRIC_PREFIX) :]

    if "__" in benchmark_name:
        metric_key, stat_field = benchmark_name.rsplit("__", 1)
        if metric_key in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
            return _benchmark_metric_name(metric_key, stat_field)
        return metric_name

    if benchmark_name in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
        return _benchmark_metric_name(benchmark_name, "average")
    return metric_name


def _print_full_view(context: ComparisonContext) -> None:
    metrics = _comparison_metrics(context)
    print("\nMatched comparisons:")
    for anylogic, simpy in _matched_rows(context):
        print(
            f"\narrival_s={anylogic.arrival_rate_s:g}  "
            f"forklifts={anylogic.forklift_capacity}  "
            f"speed={anylogic.forklift_max_speed:g}  "
            f"accel={anylogic.forklift_acceleration:g}  "
            f"displacement={anylogic.displacement_m:g}  "
            f"AnyLogic iteration={anylogic.iteration}  SimPy iteration={simpy.iteration}"
        )
        print(
            f"  {'Metric':<40} {'AnyLogic':>14} {'SimPy':>14} "
            f"{'Diff':>14} {'Diff %':>10} {'Status':>8}"
        )
        print(f"  {'-' * 102}")
        for field_name, label in metrics:
            anylogic_value = _metric_value(anylogic, field_name)
            simpy_value = _metric_value(simpy, field_name)
            diff = _numeric_diff(anylogic_value, simpy_value)
            diff_pct = _percent_diff(anylogic_value, simpy_value)
            print(
                f"  {_truncate(label, 40):<40} "
                f"{_format_value(anylogic_value):>14} "
                f"{_format_value(simpy_value):>14} "
                f"{_format_diff(diff):>14} "
                f"{_format_percent(diff_pct):>10} "
                f"{_status(anylogic_value, simpy_value):>8}"
            )


def _print_overview_view(context: ComparisonContext) -> None:
    metrics = _comparison_metrics(context)
    print("\nOverview:")
    print(
        f"  {'Metric':<40} {'Match':>7} {'Close':>7} {'Diff':>7} "
        f"{'Worst Diff':>14} {'Worst %':>10} {'Worst Case':>22}"
    )
    print(f"  {'-' * 114}")

    for field_name, label in metrics:
        counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
        worst_diff: tuple[float, float, tuple[float, int, float, float, float]] | None = None
        worst_pct: tuple[float, float | None, tuple[float, int, float, float, float]] | None = None

        for anylogic, simpy in _matched_rows(context):
            anylogic_value = _metric_value(anylogic, field_name)
            simpy_value = _metric_value(simpy, field_name)
            diff = _numeric_diff(anylogic_value, simpy_value)
            diff_pct = _percent_diff(anylogic_value, simpy_value)
            status = _status(anylogic_value, simpy_value)
            counts[status] += 1

            diff_rank = abs(diff)
            pct_rank = abs(diff_pct) if diff_pct is not None else -1.0
            key = anylogic.match_key

            if worst_diff is None or diff_rank > worst_diff[0]:
                worst_diff = (diff_rank, diff, key)
            if worst_pct is None or pct_rank > worst_pct[0]:
                worst_pct = (pct_rank, diff_pct, key)

        worst_diff_value = 0.0 if worst_diff is None else worst_diff[1]
        worst_pct_value = None if worst_pct is None else worst_pct[1]
        worst_case_key = None if worst_pct is None else worst_pct[2]
        print(
            f"  {_truncate(label, 40):<40} "
            f"{counts['MATCH']:>7} {counts['CLOSE']:>7} {counts['DIFF']:>7} "
            f"{_format_diff(worst_diff_value):>14} "
            f"{_format_percent(worst_pct_value):>10} "
            f"{_format_case(worst_case_key):>22}"
        )

    print("\nStatus thresholds: MATCH = exact, CLOSE = <1% difference, DIFF = >=1% difference")


def _print_matrix_view(context: ComparisonContext, *, metric_name: str) -> None:
    matched = _matched_rows(context)
    arrivals = sorted({row.arrival_rate_s for row, _ in matched})
    forklifts = sorted({row.forklift_capacity for row, _ in matched})
    speeds = sorted({row.forklift_max_speed for row, _ in matched})
    accelerations = sorted({row.forklift_acceleration for row, _ in matched})
    displacements = sorted({row.displacement_m for row, _ in matched})
    metric_items = _selected_metrics(metric_name, _comparison_metrics(context))

    print("\nHotspot matrices:")
    print("Cells show status and percent difference relative to AnyLogic.")
    print("Legend: MATCH = exact, C = close (<1%), D = diff (>=1%)")

    for field_name, label in metric_items:
        for forklift_capacity in forklifts:
            for speed in speeds:
                for acceleration in accelerations:
                    for displacement in displacements:
                        print(
                            f"\n{label} | forklifts={forklift_capacity} "
                            f"speed={speed:g} accel={acceleration:g} displacement={displacement:g}"
                        )
                        header = ["arrival", "status"]
                        rows: list[list[str]] = []
                        for arrival_rate_s in arrivals:
                            key = (
                                arrival_rate_s,
                                forklift_capacity,
                                speed,
                                acceleration,
                                displacement,
                            )
                            anylogic = context.anylogic_by_key.get(key)
                            simpy = context.simpy_by_key.get(key)
                            if anylogic is None or simpy is None:
                                rows.append([f"a={arrival_rate_s:g}", "---"])
                                continue
                            rows.append(
                                [
                                    f"a={arrival_rate_s:g}",
                                    _matrix_cell(
                                        _metric_value(anylogic, field_name),
                                        _metric_value(simpy, field_name),
                                    ),
                                ]
                            )
                        _print_table(header, rows, indent="  ")


def _print_offenders_view(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> None:
    offenders: list[
        tuple[
            float,
            str,
            tuple[float, int, float, float, float],
            int,
            int,
            int | float,
            int | float,
            float,
            float | None,
            str,
        ]
    ] = []
    for anylogic, simpy in _matched_rows(context):
        for field_name, label in _selected_metrics(
            metric_name, _comparison_metrics(context)
        ):
            anylogic_value = _metric_value(anylogic, field_name)
            simpy_value = _metric_value(simpy, field_name)
            diff = _numeric_diff(anylogic_value, simpy_value)
            diff_pct = _percent_diff(anylogic_value, simpy_value)
            severity = abs(diff_pct) if diff_pct is not None else abs(diff)
            offenders.append(
                (
                    severity,
                    label,
                    anylogic.match_key,
                    anylogic.iteration,
                    simpy.iteration,
                    anylogic_value,
                    simpy_value,
                    diff,
                    diff_pct,
                    _status(anylogic_value, simpy_value),
                )
            )

    offenders.sort(
        key=lambda item: (
            item[0],
            abs(item[7]),
            item[2][0],
            item[2][1],
            item[2][2],
            item[2][3],
            item[2][4],
            item[1],
        ),
        reverse=True,
    )

    print(f"\nTop offenders (top {top}):")
    header = [
        "Rank",
        "Metric",
        "Case",
        "AnyLogic it",
        "SimPy it",
        "Diff",
        "Diff %",
        "Status",
    ]
    rows: list[list[str]] = []
    for index, offender in enumerate(offenders[:top], start=1):
        (
            _severity,
            label,
            key,
            anylogic_iteration,
            simpy_iteration,
            _anylogic_value,
            _simpy_value,
            diff,
            diff_pct,
            status,
        ) = offender
        rows.append(
            [
                str(index),
                label,
                _format_case(key),
                str(anylogic_iteration),
                str(simpy_iteration),
                _format_diff(diff),
                _format_percent(diff_pct),
                status,
            ]
        )
    _print_table(header, rows, indent="  ")


def _print_report_view(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> None:
    report = build_report_data(context, metric_name=metric_name, top=top)

    print("\nReport summary:")
    if report.close_or_diff_rows:
        print("  Metrics needing attention:")
        _print_table(
            [
                "Metric",
                "Match",
                "Close",
                "Diff",
                "Worst Diff",
                "Worst %",
                "Worst Case",
            ],
            [
                [
                    row.label,
                    str(row.match_count),
                    str(row.close_count),
                    str(row.diff_count),
                    _format_diff(row.worst_diff),
                    _format_percent(row.worst_pct),
                    _format_case(row.worst_case),
                ]
                for row in report.close_or_diff_rows
            ],
            indent="    ",
        )
    else:
        print("  No CLOSE or DIFF metrics found.")

    print("\n  Exact-match metrics:")
    if report.exact_match_metrics:
        for label in report.exact_match_metrics:
            print(f"    - {label}")
    else:
        print("    <none>")

    print(f"\nTop offenders (top {top}):")
    _print_table(
        [
            "Rank",
            "Metric",
            "Case",
            "AnyLogic it",
            "SimPy it",
            "Diff",
            "Diff %",
            "Status",
        ],
        [
            [
                str(row.rank),
                row.label,
                _format_case(row.key),
                str(row.anylogic_iteration),
                str(row.simpy_iteration),
                _format_diff(row.diff),
                _format_percent(row.diff_pct),
                row.status,
            ]
            for row in report.offender_rows
        ],
        indent="  ",
    )
    print("\nNotes:")
    print("  Status thresholds: MATCH = exact, CLOSE = <1% difference, DIFF = >=1% difference")
    print("  Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval")
    print("  HTML reports include a dropdown for per-iteration benchmark details.")


def render_html_report(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> str:
    report = build_report_data(context, metric_name=metric_name, top=top)
    iteration_data = [
        {
            "label": (
                f"AnyLogic {row.anylogic_iteration} / SimPy {row.simpy_iteration} - "
                f"{row.case_label}"
            ),
            "anylogicIteration": row.anylogic_iteration,
            "simpyIteration": row.simpy_iteration,
            "caseLabel": row.case_label,
            "benchmarkRows": [
                _metric_row_json(metric_row)
                for metric_row in row.benchmark_rows
            ],
            "summaryRows": [
                _metric_row_json(metric_row)
                for metric_row in row.summary_rows
            ],
        }
        for row in report.iteration_rows
    ]
    iteration_json = json.dumps(iteration_data, ensure_ascii=True)

    validation_items = "".join(
        f"<li>{_html_escape(issue)}</li>"
        for issue in context.validation_issues
    )
    validation_html = (
        f"<ul>{validation_items}</ul>"
        if context.validation_issues
        else "<p class=\"pass-text\">PASS</p>"
    )
    attention_rows = "".join(
        "<tr>"
        f"<td>{_html_escape(row.label)}</td>"
        f"<td>{row.match_count}</td>"
        f"<td>{row.close_count}</td>"
        f"<td>{row.diff_count}</td>"
        f"<td>{_html_escape(_format_diff(row.worst_diff))}</td>"
        f"<td>{_html_escape(_format_percent(row.worst_pct))}</td>"
        f"<td>{_html_escape(_format_case(row.worst_case))}</td>"
        "</tr>"
        for row in report.close_or_diff_rows
    )
    if not attention_rows:
        attention_rows = (
            "<tr><td colspan=\"7\" class=\"empty\">No CLOSE or DIFF metrics found.</td></tr>"
        )
    exact_metrics = "".join(
        f"<li>{_html_escape(label)}</li>"
        for label in report.exact_match_metrics
    ) or "<li>None</li>"
    offender_rows = "".join(_offender_html_row(row) for row in report.offender_rows)
    unmatched_html = _unmatched_html(context)
    option_items = "".join(
        f"<option value=\"{index}\">{_html_escape(row['label'])}</option>"
        for index, row in enumerate(iteration_data)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Model 1 Range Comparison Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --border: #d9dde5;
      --text: #20242c;
      --muted: #656d7a;
      --match: #1d7f45;
      --close: #9a6a00;
      --diff: #b42318;
      --header: #eef1f6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px 28px 16px;
      background: #242a34;
      color: white;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; font-weight: 650; }}
    header p {{ margin: 0; color: #d8dde6; }}
    main {{ padding: 22px 28px 32px; max-width: 1280px; margin: 0 auto; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 18px;
      padding: 18px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    h3 {{ margin: 18px 0 10px; font-size: 15px; }}
    .summary-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      margin-top: 14px;
    }}
    .summary-card {{
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .summary-card .label {{ color: var(--muted); font-size: 12px; }}
    .summary-card .value {{ font-size: 22px; font-weight: 650; margin-top: 3px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px 9px; text-align: left; vertical-align: top; }}
    th {{ background: var(--header); color: #343a46; font-weight: 650; position: sticky; top: 0; }}
    tbody tr:hover {{ background: #f9fafc; }}
    .numeric {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--border); border-radius: 6px; }}
    .badge {{ border-radius: 999px; color: white; display: inline-block; font-size: 12px; font-weight: 650; padding: 2px 8px; }}
    .MATCH {{ background: var(--match); }}
    .CLOSE {{ background: var(--close); }}
    .DIFF {{ background: var(--diff); }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; align-items: end; }}
    label {{ display: grid; gap: 4px; color: var(--muted); font-size: 12px; }}
    select, input {{
      border: 1px solid var(--border);
      border-radius: 6px;
      min-height: 34px;
      padding: 6px 8px;
      background: white;
      color: var(--text);
      font: inherit;
    }}
    #iteration-select {{ min-width: min(760px, 100%); }}
    details {{ border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 650; }}
    .muted {{ color: var(--muted); }}
    .empty {{ color: var(--muted); text-align: center; }}
    .pass-text {{ color: var(--match); font-weight: 650; margin: 0; }}
    th.sortable {{ cursor: pointer; }}
    th.sortable::after {{ content: " sort"; color: var(--muted); font-size: 11px; font-weight: 400; }}
  </style>
</head>
<body>
  <header>
    <h1>Model 1 Parameter Variation Range Comparison</h1>
    <p>AnyLogic vs SimPy benchmark report</p>
  </header>
  <main>
    <section>
      <h2>Run Summary</h2>
      <div>{validation_html}</div>
      <div class="summary-grid">
        <div class="summary-card"><div class="label">Matched combinations</div><div class="value">{len(context.common_keys)}</div></div>
        <div class="summary-card"><div class="label">AnyLogic-only</div><div class="value">{len(context.anylogic_only)}</div></div>
        <div class="summary-card"><div class="label">SimPy-only</div><div class="value">{len(context.simpy_only)}</div></div>
        <div class="summary-card"><div class="label">Top offender limit</div><div class="value">{top}</div></div>
      </div>
      <p class="muted">Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval.</p>
    </section>

    <section>
      <h2>Metrics Needing Attention</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Metric</th><th class="numeric">Match</th><th class="numeric">Close</th><th class="numeric">Diff</th><th class="numeric">Worst Diff</th><th class="numeric">Worst %</th><th>Worst Case</th></tr></thead>
          <tbody>{attention_rows}</tbody>
        </table>
      </div>
      <details>
        <summary>Exact-match metrics</summary>
        <ul>{exact_metrics}</ul>
      </details>
    </section>

    <section>
      <h2>Top Offenders</h2>
      <div class="table-wrap">
        <table id="offenders-table">
          <thead><tr><th class="sortable" data-type="number">Rank</th><th class="sortable">Metric</th><th>Case</th><th class="sortable" data-type="number">AnyLogic it</th><th class="sortable" data-type="number">SimPy it</th><th class="sortable" data-type="number">Diff</th><th class="sortable" data-type="number">Diff %</th><th class="sortable">Status</th></tr></thead>
          <tbody>{offender_rows}</tbody>
        </table>
      </div>
    </section>

    {unmatched_html}

    <section>
      <h2>Iteration Benchmark Details</h2>
      <div class="controls">
        <label>Iteration
          <select id="iteration-select">{option_items}</select>
        </label>
        <label>Metric filter
          <input id="metric-filter" type="search" placeholder="Filter metric labels">
        </label>
        <label>Status
          <select id="status-filter">
            <option value="all">All statuses</option>
            <option value="MATCH">MATCH</option>
            <option value="CLOSE">CLOSE</option>
            <option value="DIFF">DIFF</option>
          </select>
        </label>
      </div>
      <p id="iteration-case" class="muted"></p>
      <h3>Benchmark phases</h3>
      <div class="table-wrap"><table><thead><tr><th>Metric</th><th class="numeric">AnyLogic</th><th class="numeric">SimPy</th><th class="numeric">Diff</th><th class="numeric">Diff %</th><th>Status</th></tr></thead><tbody id="benchmark-body"></tbody></table></div>
      <h3>Summary metrics</h3>
      <div class="table-wrap"><table><thead><tr><th>Metric</th><th class="numeric">AnyLogic</th><th class="numeric">SimPy</th><th class="numeric">Diff</th><th class="numeric">Diff %</th><th>Status</th></tr></thead><tbody id="summary-body"></tbody></table></div>
    </section>
  </main>
  <script>
    const iterationData = {iteration_json};

    function escapeHtml(value) {{
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function renderRows(rows, target) {{
      const metricFilter = document.getElementById('metric-filter').value.toLowerCase();
      const statusFilter = document.getElementById('status-filter').value;
      const visibleRows = rows.filter(row => {{
        const matchesMetric = row.label.toLowerCase().includes(metricFilter);
        const matchesStatus = statusFilter === 'all' || row.status === statusFilter;
        return matchesMetric && matchesStatus;
      }});
      if (!visibleRows.length) {{
        target.innerHTML = '<tr><td colspan="6" class="empty">No matching rows.</td></tr>';
        return;
      }}
      target.innerHTML = visibleRows.map(row => `
        <tr>
          <td>${{escapeHtml(row.label)}}</td>
          <td class="numeric">${{escapeHtml(row.anylogic)}}</td>
          <td class="numeric">${{escapeHtml(row.simpy)}}</td>
          <td class="numeric">${{escapeHtml(row.diff)}}</td>
          <td class="numeric">${{escapeHtml(row.diffPct)}}</td>
          <td><span class="badge ${{row.status}}">${{escapeHtml(row.status)}}</span></td>
        </tr>
      `).join('');
    }}

    function renderIteration() {{
      const index = Number(document.getElementById('iteration-select').value || 0);
      const row = iterationData[index];
      if (!row) return;
      document.getElementById('iteration-case').textContent =
        `AnyLogic iteration ${{row.anylogicIteration}} / SimPy iteration ${{row.simpyIteration}} - ${{row.caseLabel}}`;
      renderRows(row.benchmarkRows, document.getElementById('benchmark-body'));
      renderRows(row.summaryRows, document.getElementById('summary-body'));
    }}

    function makeSortable(table) {{
      table.querySelectorAll('th.sortable').forEach((header, columnIndex) => {{
        let ascending = true;
        header.addEventListener('click', () => {{
          const type = header.dataset.type || 'text';
          const rows = Array.from(table.tBodies[0].rows);
          rows.sort((left, right) => {{
            const leftCell = left.cells[columnIndex];
            const rightCell = right.cells[columnIndex];
            const leftValue = leftCell.dataset.sort || leftCell.textContent.trim();
            const rightValue = rightCell.dataset.sort || rightCell.textContent.trim();
            if (type === 'number') {{
              return (Number(leftValue) || 0) - (Number(rightValue) || 0);
            }}
            return leftValue.localeCompare(rightValue);
          }});
          if (!ascending) rows.reverse();
          ascending = !ascending;
          rows.forEach(row => table.tBodies[0].appendChild(row));
        }});
      }});
    }}

    document.getElementById('iteration-select').addEventListener('change', renderIteration);
    document.getElementById('metric-filter').addEventListener('input', renderIteration);
    document.getElementById('status-filter').addEventListener('change', renderIteration);
    makeSortable(document.getElementById('offenders-table'));
    renderIteration();
  </script>
</body>
</html>
"""


def _metric_row_json(row: MetricComparisonRow) -> dict[str, str]:
    return {
        "label": row.label,
        "anylogic": _format_value(row.anylogic_value),
        "simpy": _format_value(row.simpy_value),
        "diff": _format_diff(row.diff),
        "diffPct": _format_percent(row.diff_pct),
        "status": row.status,
    }


def _offender_html_row(row: OffenderRow) -> str:
    diff_pct_sort = "" if row.diff_pct is None else f"{row.diff_pct:.12g}"
    return (
        "<tr>"
        f"<td class=\"numeric\" data-sort=\"{row.rank}\">{row.rank}</td>"
        f"<td>{_html_escape(row.label)}</td>"
        f"<td>{_html_escape(_format_case(row.key))}</td>"
        f"<td class=\"numeric\" data-sort=\"{row.anylogic_iteration}\">{row.anylogic_iteration}</td>"
        f"<td class=\"numeric\" data-sort=\"{row.simpy_iteration}\">{row.simpy_iteration}</td>"
        f"<td class=\"numeric\" data-sort=\"{row.diff:.12g}\">{_html_escape(_format_diff(row.diff))}</td>"
        f"<td class=\"numeric\" data-sort=\"{diff_pct_sort}\">{_html_escape(_format_percent(row.diff_pct))}</td>"
        f"<td><span class=\"badge {row.status}\">{_html_escape(row.status)}</span></td>"
        "</tr>"
    )


def _unmatched_html(context: ComparisonContext) -> str:
    if not context.anylogic_only and not context.simpy_only:
        return ""
    anylogic_rows = "".join(
        f"<li>{_html_escape(_format_case(key))}</li>"
        for key in context.anylogic_only
    ) or "<li>None</li>"
    simpy_rows = "".join(
        f"<li>{_html_escape(_format_case(key))}</li>"
        for key in context.simpy_only
    ) or "<li>None</li>"
    return f"""
    <section>
      <h2>Unmatched Combinations</h2>
      <details open>
        <summary>AnyLogic-only</summary>
        <ul>{anylogic_rows}</ul>
      </details>
      <details open>
        <summary>SimPy-only</summary>
        <ul>{simpy_rows}</ul>
      </details>
    </section>
"""


def _html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _metric_float_field(record: dict[str, str], metric_name: str) -> float:
    direct = record.get(f"metric_{metric_name}")
    if direct not in (None, ""):
        return float(direct)
    mean = record.get(f"metric_{metric_name}_mean")
    if mean not in (None, ""):
        return float(mean)
    raise KeyError(f"CSV row is missing metric field '{metric_name}'")


def _optional_metric_float_field(record: dict[str, str], metric_name: str) -> float | None:
    direct = record.get(f"metric_{metric_name}")
    if direct not in (None, ""):
        return float(direct)
    mean = record.get(f"metric_{metric_name}_mean")
    if mean not in (None, ""):
        return float(mean)
    return None


def _metric_int_field(record: dict[str, str], metric_name: str) -> int:
    return int(round(_metric_float_field(record, metric_name)))


def _int_field(record: dict[str, str], field_name: str) -> int:
    value = record.get(field_name)
    if value in (None, ""):
        raise KeyError(f"CSV row is missing field '{field_name}'")
    return int(value)


def _float_field(record: dict[str, str], field_name: str) -> float:
    value = record.get(field_name)
    if value in (None, ""):
        raise KeyError(f"CSV row is missing field '{field_name}'")
    return float(value)


def _optional_float_field(record: dict[str, str], field_name: str) -> float | None:
    value = record.get(field_name)
    if value in (None, ""):
        return None
    return float(value)


def _benchmark_metric_name(metric_key: str, stat_field: str) -> str:
    return f"{BENCHMARK_METRIC_PREFIX}{metric_key}__{stat_field}"


def _decode_benchmark_metric_name(metric_name: str) -> tuple[str, str] | None:
    if not metric_name.startswith(BENCHMARK_METRIC_PREFIX):
        return None
    payload = metric_name[len(BENCHMARK_METRIC_PREFIX) :]
    if "__" not in payload:
        return None
    metric_key, stat_field = payload.rsplit("__", 1)
    return metric_key, stat_field


def _benchmark_metric_label(metric_name: str) -> str:
    decoded = _decode_benchmark_metric_name(metric_name)
    if decoded is None:
        return metric_name
    metric_key, stat_field = decoded
    metric_label = MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS.get(metric_key, metric_key)
    stat_label = BENCHMARK_STAT_DISPLAY_LABELS.get(
        stat_field,
        BENCHMARK_STAT_LABELS.get(stat_field, stat_field),
    )
    return f"{metric_label} [{stat_label}]"


def _metric_value(row: AnyLogicRangeRow | SimPyRangeSummaryRow | SimPyRangeRunRow, metric_name: str) -> int | float:
    decoded = _decode_benchmark_metric_name(metric_name)
    if decoded is None:
        value = getattr(row, metric_name)
        assert value is not None
        return value
    benchmark_key, stat_field = decoded
    benchmark = row.benchmarks[benchmark_key]
    return getattr(benchmark, stat_field)


def _load_summary_benchmarks(record: dict[str, str]) -> dict[str, BenchmarkStats]:
    benchmarks: dict[str, BenchmarkStats] = {}
    for metric_key in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
        values: dict[str, float] = {}
        for stat_field, _stat_label in BENCHMARK_STAT_FIELDS:
            value = _optional_metric_float_field(
                record,
                _benchmark_metric_name(metric_key, stat_field),
            )
            if value is not None:
                values[stat_field] = value
        if len(values) == len(BENCHMARK_STAT_FIELDS):
            benchmarks[metric_key] = BenchmarkStats(
                average=values["average"],
                minimum=values["minimum"],
                maximum=values["maximum"],
                std_dev_pop=values["std_dev_pop"],
            )
    return benchmarks


def _load_run_benchmarks(record: dict[str, str]) -> dict[str, BenchmarkStats]:
    benchmarks: dict[str, BenchmarkStats] = {}
    for metric_key in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
        values: dict[str, float] = {}
        for stat_field, _stat_label in BENCHMARK_STAT_FIELDS:
            value = _optional_float_field(
                record,
                f"metric_{_benchmark_metric_name(metric_key, stat_field)}",
            )
            if value is not None:
                values[stat_field] = value
        if len(values) == len(BENCHMARK_STAT_FIELDS):
            benchmarks[metric_key] = BenchmarkStats(
                average=values["average"],
                minimum=values["minimum"],
                maximum=values["maximum"],
                std_dev_pop=values["std_dev_pop"],
            )
    return benchmarks


def _available_benchmark_metrics(
    summary_rows: list[SimPyRangeSummaryRow],
    run_rows: list[SimPyRangeRunRow],
) -> list[tuple[str, str]]:
    metrics: list[tuple[str, str]] = []
    common_benchmark_keys = set.intersection(
        *[
            {key for row in rows for key in row.benchmarks}
            for rows in (summary_rows, run_rows)
        ]
    ) if summary_rows and run_rows else set()
    for metric_key in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
        if metric_key not in common_benchmark_keys:
            continue
        for stat_field, _stat_label in BENCHMARK_STAT_FIELDS:
            metric_name = _benchmark_metric_name(metric_key, stat_field)
            metrics.append((metric_name, _benchmark_metric_label(metric_name)))
    return metrics


def _comparison_benchmark_metrics(
    matched: list[tuple[AnyLogicRangeRow, SimPyRangeSummaryRow]],
) -> list[tuple[str, str]]:
    if not matched:
        return []
    common_benchmark_keys = set.intersection(
        *[
            set(anylogic.benchmarks) & set(simpy.benchmarks)
            for anylogic, simpy in matched
        ]
    )
    metrics: list[tuple[str, str]] = []
    for metric_key in MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS:
        if metric_key not in common_benchmark_keys:
            continue
        for stat_field, _stat_label in BENCHMARK_STAT_FIELDS:
            metric_name = _benchmark_metric_name(metric_key, stat_field)
            metrics.append((metric_name, _benchmark_metric_label(metric_name)))
    return metrics


def _values_match(left: Any, right: Any) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def _numeric_diff(left: int | float, right: int | float) -> float:
    return float(right) - float(left)


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


def _percent_diff(anylogic_value: int | float, simpy_value: int | float) -> float | None:
    baseline = abs(float(anylogic_value))
    if baseline < 1e-12:
        return None
    return ((float(simpy_value) - float(anylogic_value)) / baseline) * 100.0


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    text = f"{value:+.2f}%"
    if "." in text:
        text = text.replace(".00%", "%")
    return text


def _status(anylogic_value: int | float, simpy_value: int | float) -> str:
    if _values_match(anylogic_value, simpy_value):
        return "MATCH"

    baseline = abs(float(anylogic_value))
    if baseline < 1e-12:
        return "DIFF"
    pct = abs(float(simpy_value) - float(anylogic_value)) / baseline * 100.0
    if pct < 1.0:
        return "CLOSE"
    return "DIFF"


def _format_case(key: tuple[float, int, float, float, float] | None) -> str:
    if key is None:
        return "n/a"
    (
        arrival_rate_s,
        forklift_capacity,
        forklift_max_speed,
        forklift_acceleration,
        displacement_m,
    ) = key
    return (
        f"a={_format_value(arrival_rate_s)} "
        f"f={forklift_capacity} "
        f"v={_format_value(forklift_max_speed)} "
        f"acc={_format_value(forklift_acceleration)} "
        f"disp={_format_value(displacement_m)}"
    )


def _truncate(text: str, max_width: int) -> str:
    if max_width < 4 or len(text) <= max_width:
        return text
    return text[: max_width - 3] + "..."


def _matrix_cell(anylogic_value: int | float, simpy_value: int | float) -> str:
    status = _status(anylogic_value, simpy_value)
    if status == "MATCH":
        return "MATCH"
    prefix = "C" if status == "CLOSE" else "D"
    return f"{prefix} {_format_percent(_percent_diff(anylogic_value, simpy_value))}"


def _print_table(header: list[str], rows: list[list[str]], *, indent: str = "") -> None:
    if not rows:
        print(f"{indent}<no rows>")
        return

    max_width_by_header = {
        "Metric": 52,
        "Case": 18,
    }
    widths = [
        min(len(column), max_width_by_header.get(column, len(column)))
        for column in header
    ]
    display_rows: list[list[str]] = []
    for row in rows:
        display_row: list[str] = []
        for index, value in enumerate(row):
            max_width = max_width_by_header.get(header[index], len(value))
            display_value = _truncate(value, max_width)
            widths[index] = max(widths[index], len(display_value))
            display_row.append(display_value)
        display_rows.append(display_row)

    display_header = [
        _truncate(column, max_width_by_header.get(column, len(column)))
        for column in header
    ]

    header_line = indent + "  ".join(
        value.ljust(widths[index]) for index, value in enumerate(display_header)
    )
    divider = indent + "  ".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in display_rows:
        print(
            indent
            + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 1 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        default="logs/anylogic_model_1_parameter_variation_range.txt",
        help="AnyLogic console output text file.",
    )
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_1_parameter_variation_range_runs.csv",
        help="SimPy per-run CSV file.",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_1_parameter_variation_range_summary.csv",
        help="SimPy summary CSV file.",
    )
    parser.add_argument(
        "--view",
        choices=("full", "overview", "matrix", "offenders", "report", "all"),
        default="overview",
        help="Console view to print. Default prints the overview report.",
    )
    parser.add_argument(
        "--metric",
        default="all",
        help=(
            "Metric filter for matrix/offenders views. Supports summary metrics "
            "plus benchmark metric names like "
            "'benchmark_move_seize_to_loading_start_s__average', "
            "or the shortcut 'benchmark_avg_only' for all forklift average-duration metrics."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many rows to print in offenders view.",
    )
    parser.add_argument(
        "--output",
        help="Optional report output path. Prints only a confirmation when set.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "html"),
        help=(
            "Output format when --output is set. Defaults to html for .html/.htm "
            "paths and text otherwise."
        ),
    )
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_range_output(args.anylogic)
    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs)
    context = build_comparison_context(anylogic_rows, simpy_summary_rows, simpy_run_rows)

    if args.output:
        output_path = Path(args.output)
        output_format = _infer_output_format(output_path, args.format)
        if output_format == "html":
            content = render_html_report(
                context,
                metric_name=args.metric,
                top=args.top,
            )
        else:
            content = render_comparison_report_text(
                context,
                view=args.view,
                metric_name=args.metric,
                top=args.top,
            )
        if output_path.parent != Path(""):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        print(f"Wrote report: {output_path}")
    else:
        _print_report_header(context)
        _print_unmatched(context)

        if not context.common_keys:
            print("\nNo common parameter combinations found.")
            return

        if args.view == "full":
            _print_full_view(context)
        elif args.view == "overview":
            _print_overview_view(context)
        elif args.view == "matrix":
            _print_matrix_view(context, metric_name=args.metric)
        elif args.view == "offenders":
            _print_offenders_view(context, metric_name=args.metric, top=args.top)
        elif args.view == "report":
            _print_report_view(context, metric_name=args.metric, top=args.top)
        elif args.view == "all":
            _print_overview_view(context)
            _print_matrix_view(context, metric_name=args.metric)
            _print_offenders_view(context, metric_name=args.metric, top=args.top)
            _print_full_view(context)
        else:
            raise ValueError(f"Unsupported view: {args.view}")


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


if __name__ == "__main__":
    main()
