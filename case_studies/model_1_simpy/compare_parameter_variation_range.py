#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 1 parameter-variation range runs.

This comparison focuses on summary metrics and forklift movement benchmarks.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mhsim.range_comparison import (
    RangeComparisonSpec,
    RangeRow,
    build_comparison_context as _build_comparison_context,
    load_simpy_run_rows as _load_simpy_run_rows,
    load_simpy_summary_rows as _load_simpy_summary_rows,
    print_comparison_report,
    render_comparison_report_text as _render_comparison_report_text,
    render_html_report,
)

from case_studies.model_1_simpy.anylogic_range import range_values_for_iteration
from case_studies.model_1_simpy.benchmark_labels import (
    MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
)
from case_studies.model_1_simpy.compare_benchmark_results import (
    BENCHMARK_STAT_FIELDS,
    BenchmarkStats,
    parse_anylogic_benchmark_output,
)


METRICS = (
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    ("forklift_utilization", "Forklifts Utilization (%)"),
)
BENCHMARK_METRIC_PREFIX = "benchmark_"
BENCHMARK_STAT_LABELS = {field_name: label for field_name, label in BENCHMARK_STAT_FIELDS}
BENCHMARK_STAT_DISPLAY_LABELS = {
    "average": "avg",
    "minimum": "min",
    "maximum": "max",
    "std_dev_pop": "std",
}
BENCHMARK_AVG_ONLY = "benchmark_avg_only"


MODEL1_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 1",
    parameter_fields=(
        "arrival_rate_s",
        "n_forklifts",
        "forklift_max_speed",
        "forklift_acceleration",
        "displacement_m",
    ),
    parameter_labels={
        "arrival_rate_s": "Arrival rate (s)",
        "n_forklifts": "Forklift capacity",
        "forklift_max_speed": "Forklift max speed (m/s)",
        "forklift_acceleration": "Forklift acceleration (m/s/s)",
        "displacement_m": "Displacement (m)",
    },
    parameter_short_labels={
        "arrival_rate_s": "a",
        "n_forklifts": "f",
        "forklift_max_speed": "v",
        "forklift_acceleration": "acc",
        "displacement_m": "disp",
    },
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    benchmark_metric_labels=MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
    benchmark_stat_fields=tuple(BENCHMARK_STAT_FIELDS),
    benchmark_stat_display_labels=BENCHMARK_STAT_DISPLAY_LABELS,
    benchmark_avg_only_name=BENCHMARK_AVG_ONLY,
    header_note="Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval",
)


def parse_anylogic_range_output(path: str | Path) -> list[RangeRow]:
    rows: list[RangeRow] = []
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
            RangeRow(
                iteration=row.iteration,
                params={
                    "arrival_rate_s": row.arrival_rate_s,
                    "n_forklifts": row.forklift_capacity,
                    "forklift_max_speed": forklift_max_speed,
                    "forklift_acceleration": forklift_acceleration,
                    "displacement_m": displacement_m,
                },
                metrics={
                    "created": row.created,
                    "completed": row.completed,
                    "in_flight": row.in_flight,
                    "avg_time_in_system_s": row.avg_time_in_system_s,
                    "throughput_per_hour": row.throughput_per_hour,
                    "forklift_utilization": row.forklift_utilization,
                },
                benchmarks=row.benchmarks,
            )
        )
    return rows


def load_simpy_summary_rows(path: str | Path) -> list[RangeRow]:
    return _load_simpy_summary_rows(path, MODEL1_RANGE_SPEC)


def load_simpy_run_rows(path: str | Path) -> list[RangeRow]:
    return _load_simpy_run_rows(path, MODEL1_RANGE_SPEC)


def build_comparison_context(
    anylogic_rows: list[RangeRow],
    simpy_summary_rows: list[RangeRow],
    simpy_run_rows: list[RangeRow],
):
    return _build_comparison_context(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL1_RANGE_SPEC,
    )


def render_comparison_report_text(
    context,
    *,
    view: str,
    metric_name: str,
    top: int,
) -> str:
    return _render_comparison_report_text(
        context,
        view=view,
        metric_name=metric_name,
        top=top,
    )


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        print(f"Wrote report: {output_path}")
    else:
        print_comparison_report(
            context,
            view=args.view,
            metric_name=args.metric,
            top=args.top,
        )


if __name__ == "__main__":
    main()
