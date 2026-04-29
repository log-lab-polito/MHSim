#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 5 parameter-variation range runs.

This script is intentionally tolerant of:
- AnyLogic iteration order differing from SimPy iteration order
- deterministic SimPy summaries that use either scalar metric columns or
  older mean/min/max columns
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ANYLOGIC_KEY_MAP = {
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

METRICS = [
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("storage_level", "Storage level"),
    ("throughput_per_hour", "Throughput (/h)"),
]
OPTIONAL_METRICS = [
    ("forklift_utilization", "Forklifts Utilization (%)"),
]


@dataclass(frozen=True)
class AnyLogicRangeRow:
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

    @property
    def match_key(self) -> tuple[float, int, float]:
        return (self.arrival_rate_s, self.forklift_capacity, self.delay_time_s)


@dataclass(frozen=True)
class SimPyRangeSummaryRow:
    iteration: int
    replications: int
    arrival_rate_per_min: float
    arrival_rate_s: float
    forklift_capacity: int
    delay_time_s: float | None
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    storage_level: int
    throughput_per_hour: float
    forklift_utilization: float | None

    @property
    def match_key(self) -> tuple[float, int, float | None]:
        return (self.arrival_rate_s, self.forklift_capacity, self.delay_time_s)


@dataclass(frozen=True)
class SimPyRangeRunRow:
    iteration: int
    replication: int
    arrival_rate_per_min: float
    arrival_rate_s: float
    forklift_capacity: int
    delay_time_s: float | None
    created: int
    completed: int
    in_flight: int
    avg_time_in_system_s: float
    storage_level: int
    throughput_per_hour: float
    forklift_utilization: float | None


@dataclass(frozen=True)
class ComparisonContext:
    validation_issues: list[str]
    anylogic_by_key: dict[tuple[float, int, float], AnyLogicRangeRow]
    simpy_by_key: dict[tuple[float, int, float | None], SimPyRangeSummaryRow]
    common_keys: list[tuple[float, int, float]]
    anylogic_only: list[tuple[float, int, float]]
    simpy_only: list[tuple[float, int, float | None]]


def parse_anylogic_range_output(path: str | Path) -> list[AnyLogicRangeRow]:
    iteration_re = re.compile(r"^ITERATION #(\d+)\s*$")
    key_value_re = re.compile(r"^\s*([^:]+):\s*(.+?)\s*$")
    rows: list[AnyLogicRangeRow] = []

    current_iteration: int | None = None
    values: dict[str, Any] = {}

    def finalize_current() -> None:
        nonlocal current_iteration, values
        if current_iteration is None:
            return
        required = [
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
        missing = [name for name in required if name not in values]
        if missing:
            raise ValueError(
                f"AnyLogic iteration #{current_iteration} is missing fields: {', '.join(missing)}"
            )
        rows.append(
            AnyLogicRangeRow(
                iteration=current_iteration,
                arrival_rate_s=float(values["arrival_rate_s"]),
                forklift_capacity=int(values["forklift_capacity"]),
                delay_time_s=float(values["delay_time_s"]),
                created=int(values["created"]),
                completed=int(values["completed"]),
                in_flight=int(values["in_flight"]),
                avg_time_in_system_s=float(values["avg_time_in_system_s"]),
                storage_level=int(values["storage_level"]),
                throughput_per_hour=float(values["throughput_per_hour"]),
                forklift_utilization=(
                    None
                    if "forklift_utilization" not in values
                    else float(values["forklift_utilization"])
                ),
            )
        )
        current_iteration = None
        values = {}

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line.strip():
                finalize_current()
                continue

            iteration_match = iteration_re.match(line)
            if iteration_match:
                finalize_current()
                current_iteration = int(iteration_match.group(1))
                values = {}
                continue

            if line.startswith("PARAMETERS") or line.startswith("RESULTS"):
                continue
            if line.startswith("WARNING"):
                continue

            match = key_value_re.match(line)
            if not match or current_iteration is None:
                continue

            label, raw_value = match.groups()
            normalized_key = ANYLOGIC_KEY_MAP.get(label)
            if normalized_key is None:
                continue
            values[normalized_key] = _parse_number(raw_value)

    finalize_current()
    return rows


def load_simpy_summary_rows(path: str | Path) -> list[SimPyRangeSummaryRow]:
    rows: list[SimPyRangeSummaryRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            arrival_rate_per_min = _float_field(record, "param_arrival_rate_per_min")
            rows.append(
                SimPyRangeSummaryRow(
                    iteration=_int_field(record, "iteration"),
                    replications=_int_field(record, "replications"),
                    arrival_rate_per_min=arrival_rate_per_min,
                    arrival_rate_s=60.0 / arrival_rate_per_min,
                    forklift_capacity=_int_field(record, "param_n_forklifts"),
                    delay_time_s=_optional_float_field(record, "param_delay_time_s"),
                    created=_metric_int_field(record, "created"),
                    completed=_metric_int_field(record, "completed"),
                    in_flight=_metric_int_field(record, "in_flight"),
                    avg_time_in_system_s=_metric_float_field(
                        record, "avg_time_in_system_s"
                    ),
                    storage_level=_metric_int_field(record, "storage_level"),
                    throughput_per_hour=_metric_float_field(
                        record, "throughput_per_hour"
                    ),
                    forklift_utilization=_optional_metric_float_field(
                        record, "forklift_utilization"
                    ),
                )
            )
    return rows


def load_simpy_run_rows(path: str | Path) -> list[SimPyRangeRunRow]:
    rows: list[SimPyRangeRunRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            arrival_rate_per_min = _float_field(record, "param_arrival_rate_per_min")
            rows.append(
                SimPyRangeRunRow(
                    iteration=_int_field(record, "iteration"),
                    replication=_int_field(record, "replication"),
                    arrival_rate_per_min=arrival_rate_per_min,
                    arrival_rate_s=60.0 / arrival_rate_per_min,
                    forklift_capacity=_int_field(record, "param_n_forklifts"),
                    delay_time_s=_optional_float_field(record, "param_delay_time_s"),
                    created=_int_field(record, "metric_created"),
                    completed=_int_field(record, "metric_completed"),
                    in_flight=_int_field(record, "metric_in_flight"),
                    avg_time_in_system_s=_float_field(
                        record, "metric_avg_time_in_system_s"
                    ),
                    storage_level=_int_field(record, "metric_storage_level"),
                    throughput_per_hour=_float_field(
                        record, "metric_throughput_per_hour"
                    ),
                    forklift_utilization=_optional_float_field(
                        record, "metric_forklift_utilization"
                    ),
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
                    getattr(first, field_name),
                    getattr(other, field_name),
                ):
                    issues.append(
                        f"SimPy iteration {iteration} differs across replications "
                        f"for '{field_name}': replication {first.replication}="
                        f"{getattr(first, field_name)} vs replication {other.replication}="
                        f"{getattr(other, field_name)}"
                    )
        summary = summary_by_iteration.get(iteration)
        if summary is None:
            issues.append(f"SimPy summary is missing iteration {iteration}")
            continue
        for field_name, _ in metrics:
            if not _values_match(
                getattr(first, field_name),
                getattr(summary, field_name),
            ):
                issues.append(
                    f"SimPy summary mismatch for iteration {iteration} field '{field_name}': "
                    f"summary={getattr(summary, field_name)} runs={getattr(first, field_name)}"
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
    print("Arrival conversion used for SimPy: arrival_rate_s = 60 / param_arrival_rate_per_min")


def _print_unmatched(context: ComparisonContext) -> None:
    if context.anylogic_only:
        print("\nAnyLogic combinations without a matching SimPy summary row:")
        for arrival_rate_s, forklift_capacity, delay_time_s in context.anylogic_only:
            anylogic = context.anylogic_by_key[(arrival_rate_s, forklift_capacity, delay_time_s)]
            print(
                f"  arrival_s={arrival_rate_s:g}  forklifts={forklift_capacity}  "
                f"delay_s={anylogic.delay_time_s:g}"
            )

    if context.simpy_only:
        print("\nSimPy combinations without a matching AnyLogic row:")
        for arrival_rate_s, forklift_capacity, delay_time_s in context.simpy_only:
            print(
                f"  arrival_s={arrival_rate_s:g}  forklifts={forklift_capacity}  "
                f"delay_s={_format_optional(delay_time_s)}"
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
    return metrics


def _selected_metrics(
    metric_name: str,
    available_metrics: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    if metric_name == "all":
        return available_metrics
    for field_name, label in available_metrics:
        if field_name == metric_name:
            return [(field_name, label)]
    raise ValueError(f"Unsupported metric: {metric_name}")


def _print_full_view(context: ComparisonContext) -> None:
    metrics = _comparison_metrics(context)
    print("\nMatched comparisons:")
    for anylogic, simpy in _matched_rows(context):
        print(
            f"\narrival_s={anylogic.arrival_rate_s:g}  "
            f"forklifts={anylogic.forklift_capacity}  "
            f"delay_s={_format_optional(anylogic.delay_time_s)}  "
            f"AnyLogic iteration={anylogic.iteration}  SimPy iteration={simpy.iteration}"
        )
        print(
            f"  {'Metric':<26} {'AnyLogic':>14} {'SimPy':>14} "
            f"{'Diff':>14} {'Diff %':>10} {'Status':>8}"
        )
        print(f"  {'-' * 88}")
        for field_name, label in metrics:
            anylogic_value = getattr(anylogic, field_name)
            simpy_value = getattr(simpy, field_name)
            diff = _numeric_diff(anylogic_value, simpy_value)
            diff_pct = _percent_diff(anylogic_value, simpy_value)
            print(
                f"  {label:<26} "
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
        f"  {'Metric':<26} {'Match':>7} {'Close':>7} {'Diff':>7} "
        f"{'Worst Diff':>14} {'Worst %':>10} {'Worst Case':>22}"
    )
    print(f"  {'-' * 100}")

    for field_name, label in metrics:
        counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
        worst_diff: tuple[float, float, tuple[float, int, float]] | None = None
        worst_pct: tuple[float, float | None, tuple[float, int, float]] | None = None

        for anylogic, simpy in _matched_rows(context):
            anylogic_value = getattr(anylogic, field_name)
            simpy_value = getattr(simpy, field_name)
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
            f"  {label:<26} "
            f"{counts['MATCH']:>7} {counts['CLOSE']:>7} {counts['DIFF']:>7} "
            f"{_format_diff(worst_diff_value):>14} "
            f"{_format_percent(worst_pct_value):>10} "
            f"{_format_case(worst_case_key):>22}"
        )

    print("\nStatus thresholds: MATCH = exact, CLOSE = <1% difference, DIFF = >=1% difference")


def _print_matrix_view(context: ComparisonContext, *, metric_name: str) -> None:
    matched = _matched_rows(context)
    arrivals = sorted({row.arrival_rate_s for row, _ in matched})
    delays = sorted({row.delay_time_s for row, _ in matched})
    forklifts = sorted({row.forklift_capacity for row, _ in matched})
    metric_items = _selected_metrics(metric_name, _comparison_metrics(context))

    print("\nHotspot matrices:")
    print("Cells show status and percent difference relative to AnyLogic.")
    print("Legend: MATCH = exact, C = close (<1%), D = diff (>=1%)")

    for field_name, label in metric_items:
        for forklift_capacity in forklifts:
            print(f"\n{label} | forklifts={forklift_capacity}")
            header = ["arrival\\delay"] + [f"d={delay:g}" for delay in delays]
            rows: list[list[str]] = []
            for arrival_rate_s in arrivals:
                row_cells = [f"a={arrival_rate_s:g}"]
                for delay_time_s in delays:
                    key = (arrival_rate_s, forklift_capacity, delay_time_s)
                    anylogic = context.anylogic_by_key.get(key)
                    simpy = context.simpy_by_key.get(key)
                    if anylogic is None or simpy is None:
                        row_cells.append("---")
                        continue
                    row_cells.append(_matrix_cell(getattr(anylogic, field_name), getattr(simpy, field_name)))
                rows.append(row_cells)
            _print_table(header, rows, indent="  ")


def _print_offenders_view(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> None:
    offenders: list[tuple[float, str, tuple[float, int, float], int, int | float, int | float, float, float | None, str]] = []
    for anylogic, simpy in _matched_rows(context):
        for field_name, label in _selected_metrics(metric_name, _comparison_metrics(context)):
            anylogic_value = getattr(anylogic, field_name)
            simpy_value = getattr(simpy, field_name)
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
        _, label, key, anylogic_iteration, simpy_iteration, _anylogic_value, _simpy_value, diff, diff_pct, status = offender
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


def _parse_number(raw_value: str) -> int | float:
    value = raw_value.strip()
    if re.search(r"[.eE]", value):
        return float(value)
    return int(value)


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


def _format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_value(value)


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


def _format_case(key: tuple[float, int, float] | tuple[float, int, float | None] | None) -> str:
    if key is None:
        return "n/a"
    arrival_rate_s, forklift_capacity, delay_time_s = key
    return (
        f"a={_format_value(arrival_rate_s)} "
        f"f={forklift_capacity} "
        f"d={_format_optional(delay_time_s)}"
    )


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

    widths = [len(column) for column in header]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    header_line = indent + "  ".join(
        value.ljust(widths[index]) for index, value in enumerate(header)
    )
    divider = indent + "  ".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in rows:
        print(
            indent
            + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 5 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        default="logs/anylogic_model_5_parameter_variation_range.txt",
        help="AnyLogic console output text file.",
    )
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_5_parameter_variation_range_runs.csv",
        help="SimPy per-run CSV file.",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_5_parameter_variation_range_summary.csv",
        help="SimPy summary CSV file.",
    )
    parser.add_argument(
        "--view",
        choices=("full", "overview", "matrix", "offenders", "all"),
        default="full",
        help="Console view to print. Default keeps the existing detailed full report.",
    )
    parser.add_argument(
        "--metric",
        choices=("all",) + tuple(
            field_name for field_name, _ in (METRICS + OPTIONAL_METRICS)
        ),
        default="all",
        help="Metric filter for matrix/offenders views.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many rows to print in offenders view.",
    )
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_range_output(args.anylogic)
    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs)
    print_comparison_report(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        view=args.view,
        metric_name=args.metric,
        top=args.top,
    )


if __name__ == "__main__":
    main()
