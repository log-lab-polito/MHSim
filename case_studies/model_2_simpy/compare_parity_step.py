#!/usr/bin/env python3
"""Compare two Model 2 parity-step output directories.

The parity-step workflow keeps each behavior change in its own output directory
under ``logs/model_2_parity_steps``. This helper summarizes what changed from
one step to the next without replacing the canonical Model 2 comparison CSVs.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mhsim.range_comparison import (
    ComparisonContext,
    MetricComparisonRow,
    RangeRow,
    _build_metric_comparison_row,
    _comparison_metrics,
    _format_case,
    _format_diff,
    _format_percent,
    _format_value,
)

from case_studies.model_2_simpy.compare_parameter_variation_range import (
    BENCHMARK_AVG_ONLY,
    MODEL2_RANGE_SPEC,
    build_comparison_context,
    load_simpy_run_rows,
    load_simpy_summary_rows,
    parse_anylogic_range_output,
)


STEP_ROOT = Path("logs/model_2_parity_steps")
DEFAULT_ANYLOGIC_RANGE = Path("logs/anylogic_model_2_parameter_variation_range.txt")
SUMMARY_RANGE_METRICS = (
    "avg_time_in_system_s",
    "forklift_utilization",
    BENCHMARK_AVG_ONLY,
)


@dataclass(frozen=True)
class CsvComparisonRow:
    section: str
    metric_key: str
    metric_label: str
    stat: str
    anylogic_value: float
    simpy_value: float
    diff: float
    diff_pct: float | None
    status: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.section, self.metric_key, self.stat)


@dataclass(frozen=True)
class OverviewSummary:
    metric_name: str
    label: str
    match_count: int
    close_count: int
    diff_count: int
    worst_diff: float
    worst_pct: float | None
    worst_case: tuple[int | float, ...] | None


def _step_dir(value: str) -> Path:
    path = Path(value)
    if path.exists() or path.is_absolute() or "/" in value:
        return path
    return STEP_ROOT / value


def _float_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _read_benchmark_comparison(path: Path) -> dict[tuple[str, str, str], CsvComparisonRow]:
    rows: dict[tuple[str, str, str], CsvComparisonRow] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            row = CsvComparisonRow(
                section=record["section"],
                metric_key=record["metric_key"],
                metric_label=record["metric"],
                stat=record["stat"],
                anylogic_value=float(record["anylogic_value"]),
                simpy_value=float(record["simpy_value"]),
                diff=float(record["diff"]),
                diff_pct=_float_or_none(record.get("diff_pct")),
                status=record["status"],
            )
            rows[row.key] = row
    return rows


def _load_range_context(step_dir: Path, anylogic_range: Path) -> ComparisonContext:
    anylogic_rows = parse_anylogic_range_output(anylogic_range)
    simpy_summary_rows = load_simpy_summary_rows(
        step_dir / "model_2_parameter_variation_range_summary.csv"
    )
    simpy_run_rows = load_simpy_run_rows(
        step_dir / "model_2_parameter_variation_range_runs.csv"
    )
    return build_comparison_context(anylogic_rows, simpy_summary_rows, simpy_run_rows)


def _matched_rows(context: ComparisonContext) -> Iterable[tuple[RangeRow, RangeRow]]:
    for key in context.common_keys:
        yield context.anylogic_by_key[key], context.simpy_by_key[key]


def _benchmark_average_metrics(context: ComparisonContext) -> list[tuple[str, str]]:
    return [
        (field_name, label)
        for field_name, label in _comparison_metrics(context)
        if field_name.startswith("benchmark_") and field_name.endswith("__average")
    ]


def _overview_for_metric(
    context: ComparisonContext,
    metric_name: str,
) -> OverviewSummary:
    if metric_name == BENCHMARK_AVG_ONLY:
        metrics = _benchmark_average_metrics(context)
        label = "Benchmark averages"
    else:
        metrics = [
            (field_name, label)
            for field_name, label in _comparison_metrics(context)
            if field_name == metric_name
        ]
        label = metrics[0][1] if metrics else metric_name

    counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
    worst_diff: tuple[float, float, tuple[int | float, ...]] | None = None
    worst_pct: tuple[float, float | None, tuple[int | float, ...]] | None = None

    for anylogic, simpy in _matched_rows(context):
        for field_name, metric_label in metrics:
            row = _build_metric_comparison_row(anylogic, simpy, field_name, metric_label)
            counts[row.status] += 1
            key = anylogic.match_key(context.spec)
            diff_rank = abs(row.diff)
            pct_rank = abs(row.diff_pct) if row.diff_pct is not None else -1.0
            if worst_diff is None or diff_rank > worst_diff[0]:
                worst_diff = (diff_rank, row.diff, key)
            if worst_pct is None or pct_rank > worst_pct[0]:
                worst_pct = (pct_rank, row.diff_pct, key)

    return OverviewSummary(
        metric_name=metric_name,
        label=label,
        match_count=counts["MATCH"],
        close_count=counts["CLOSE"],
        diff_count=counts["DIFF"],
        worst_diff=0.0 if worst_diff is None else worst_diff[1],
        worst_pct=None if worst_pct is None else worst_pct[1],
        worst_case=None if worst_pct is None else worst_pct[2],
    )


def _range_rows_by_key(
    context: ComparisonContext,
    metrics: list[tuple[str, str]],
) -> dict[tuple[str, tuple[int | float, ...]], MetricComparisonRow]:
    rows: dict[tuple[str, tuple[int | float, ...]], MetricComparisonRow] = {}
    for anylogic, simpy in _matched_rows(context):
        case_key = anylogic.match_key(context.spec)
        for field_name, label in metrics:
            rows[(field_name, case_key)] = _build_metric_comparison_row(
                anylogic,
                simpy,
                field_name,
                label,
            )
    return rows


def _benchmark_offenders(
    context: ComparisonContext,
    *,
    top: int,
) -> list[tuple[MetricComparisonRow, tuple[int | float, ...]]]:
    rows: list[tuple[float, MetricComparisonRow, tuple[int | float, ...]]] = []
    for anylogic, simpy in _matched_rows(context):
        case_key = anylogic.match_key(context.spec)
        for field_name, label in _benchmark_average_metrics(context):
            row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            severity = abs(row.diff_pct) if row.diff_pct is not None else abs(row.diff)
            rows.append((severity, row, case_key))
    rows.sort(key=lambda item: (item[0], abs(item[1].diff), item[2]), reverse=True)
    return [(row, key) for _severity, row, key in rows[:top]]


def _improved(old_diff: float, new_diff: float) -> str:
    old_abs = abs(old_diff)
    new_abs = abs(new_diff)
    if math.isclose(old_abs, new_abs, rel_tol=1e-9, abs_tol=1e-9):
        return "same"
    return "yes" if new_abs < old_abs else "no"


def _range_improved(old: OverviewSummary, new: OverviewSummary) -> str:
    if new.diff_count != old.diff_count:
        return "yes" if new.diff_count < old.diff_count else "no"
    if new.match_count != old.match_count:
        return "yes" if new.match_count > old.match_count else "no"
    old_pct = abs(old.worst_pct) if old.worst_pct is not None else abs(old.worst_diff)
    new_pct = abs(new.worst_pct) if new.worst_pct is not None else abs(new.worst_diff)
    if math.isclose(old_pct, new_pct, rel_tol=1e-9, abs_tol=1e-9):
        return "same"
    return "yes" if new_pct < old_pct else "no"


def _format_simpy_value(row: CsvComparisonRow | None) -> str:
    return "missing" if row is None else _format_value(row.simpy_value)


def _format_status(row: CsvComparisonRow | MetricComparisonRow | None) -> str:
    return "missing" if row is None else row.status


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        rows = [["n/a" for _ in headers]]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [
        "  " + "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
        "  " + "  ".join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(
            "  " + "  ".join(row[index].ljust(widths[index]) for index in range(len(row)))
        )
    return "\n".join(lines)


def _render_default_delta(
    title: str,
    old_rows: dict[tuple[str, str, str], CsvComparisonRow],
    new_rows: dict[tuple[str, str, str], CsvComparisonRow],
    *,
    section: str,
    stat: str,
) -> str:
    table_rows: list[list[str]] = []
    ordered_keys = [
        key
        for key, row in old_rows.items()
        if row.section == section and row.stat == stat
    ]
    for key in ordered_keys:
        old = old_rows[key]
        new = new_rows.get(key)
        if new is None:
            table_rows.append(
                [
                    old.metric_label,
                    _format_simpy_value(old),
                    "missing",
                    old.status,
                    "missing",
                    "no",
                ]
            )
            continue
        table_rows.append(
            [
                old.metric_label,
                _format_simpy_value(old),
                _format_simpy_value(new),
                old.status,
                new.status,
                _improved(old.diff, new.diff),
            ]
        )
    return "\n".join(
        [
            title,
            _render_table(
                ["Metric", "Old SimPy", "New SimPy", "Old status", "New status", "Improved"],
                table_rows,
            ),
        ]
    )


def _render_range_delta(
    old_context: ComparisonContext,
    new_context: ComparisonContext,
) -> str:
    rows: list[list[str]] = []
    for metric_name in SUMMARY_RANGE_METRICS:
        old = _overview_for_metric(old_context, metric_name)
        new = _overview_for_metric(new_context, metric_name)
        rows.append(
            [
                new.label,
                f"{old.match_count}/{old.close_count}/{old.diff_count}",
                f"{new.match_count}/{new.close_count}/{new.diff_count}",
                _format_percent(old.worst_pct),
                _format_percent(new.worst_pct),
                _format_case(old.worst_case, MODEL2_RANGE_SPEC),
                _format_case(new.worst_case, MODEL2_RANGE_SPEC),
                _range_improved(old, new),
            ]
        )
    return "\n".join(
        [
            "Range overview deltas",
            _render_table(
                [
                    "Metric",
                    "Old M/C/D",
                    "New M/C/D",
                    "Old worst %",
                    "New worst %",
                    "Old worst case",
                    "New worst case",
                    "Improved",
                ],
                rows,
            ),
        ]
    )


def _render_offender_delta(
    old_context: ComparisonContext,
    new_context: ComparisonContext,
    *,
    top: int,
) -> str:
    old_metric_rows = _range_rows_by_key(
        old_context,
        _benchmark_average_metrics(old_context),
    )
    rows: list[list[str]] = []
    for index, (new, case_key) in enumerate(_benchmark_offenders(new_context, top=top), start=1):
        old = old_metric_rows.get((new.metric_name, case_key))
        rows.append(
            [
                str(index),
                new.label,
                _format_case(case_key, MODEL2_RANGE_SPEC),
                _format_diff(old.diff) if old else "missing",
                _format_percent(old.diff_pct) if old else "missing",
                _format_status(old),
                _format_diff(new.diff),
                _format_percent(new.diff_pct),
                new.status,
                "n/a" if old is None else _improved(old.diff, new.diff),
            ]
        )
    return "\n".join(
        [
            f"Top {top} benchmark average offenders",
            _render_table(
                [
                    "#",
                    "Metric",
                    "Case",
                    "Old diff",
                    "Old %",
                    "Old status",
                    "New diff",
                    "New %",
                    "New status",
                    "Improved",
                ],
                rows,
            ),
        ]
    )


def render_step_delta(
    previous_dir: Path,
    current_dir: Path,
    *,
    anylogic_range: Path,
    top: int,
) -> str:
    old_default = _read_benchmark_comparison(previous_dir / "benchmark_comparison.csv")
    new_default = _read_benchmark_comparison(current_dir / "benchmark_comparison.csv")
    old_context = _load_range_context(previous_dir, anylogic_range)
    new_context = _load_range_context(current_dir, anylogic_range)

    return "\n\n".join(
        [
            f"Model 2 parity step delta: {previous_dir.name} -> {current_dir.name}",
            _render_default_delta(
                "Default benchmark summary deltas",
                old_default,
                new_default,
                section="summary",
                stat="value",
            ),
            _render_default_delta(
                "Default phase benchmark avg deltas",
                old_default,
                new_default,
                section="benchmark",
                stat="avg",
            ),
            _render_range_delta(old_context, new_context),
            _render_offender_delta(old_context, new_context, top=top),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two Model 2 parity-step output directories."
    )
    parser.add_argument("previous", help="Previous step name or directory.")
    parser.add_argument("current", help="Current step name or directory.")
    parser.add_argument(
        "--anylogic-range",
        default=str(DEFAULT_ANYLOGIC_RANGE),
        help="AnyLogic parameter variation range output.",
    )
    parser.add_argument("--top", type=int, default=10, help="Top offender count.")
    parser.add_argument("--output", help="Optional text report path.")
    args = parser.parse_args()

    text = render_step_delta(
        _step_dir(args.previous),
        _step_dir(args.current),
        anylogic_range=Path(args.anylogic_range),
        top=args.top,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
        print(f"Wrote step delta report: {output_path}")
    print(text)


if __name__ == "__main__":
    main()
