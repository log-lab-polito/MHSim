#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 2 parameter-variation range runs.

This comparison focuses on summary metrics and phase-level forklift movement
benchmarks. Model 2 now uses the shared range comparison/report renderer also
used by Model 1, including report and HTML output support.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mhsim_analysis.range_comparison import (
    RangeComparisonSpec,
    RangeRow,
    build_comparison_context as _build_comparison_context,
    load_simpy_run_rows as _load_simpy_run_rows,
    load_simpy_summary_rows as _load_simpy_summary_rows,
    print_comparison_report,
    render_comparison_report_text as _render_comparison_report_text,
    render_html_report,
)

from case_studies.model_2_simpy.benchmark_labels import (
    BENCHMARK_AVG_ONLY,
    BENCHMARK_STAT_DISPLAY_LABELS,
    BENCHMARK_STAT_FIELDS,
    MODEL2_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
    SUMMARY_METRICS as METRICS,
)
from .compare_benchmark_results import (
    parse_anylogic_benchmark_output,
)


OPTIONAL_METRICS = (
    ("forklift_utilization", "Forklifts Utilization (%)"),
    # AnyLogic's Model 2 range export does not include enough per-phase counts
    # to derive this safely. SimPy still writes it so run CSVs expose the same
    # return-home diagnostic that Model 1 uses.
    ("return_home_busy_s", "Return-home busy (s)"),
)


MODEL2_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 2",
    parameter_fields=(
        "arrival_rate_s",
        "n_forklifts",
        "delay_time_s",
    ),
    parameter_labels={
        "arrival_rate_s": "Arrival rate (s)",
        "n_forklifts": "Forklift capacity",
        "delay_time_s": "Delay time (s)",
    },
    parameter_short_labels={
        "arrival_rate_s": "a",
        "n_forklifts": "f",
        "delay_time_s": "d",
    },
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    benchmark_metric_labels=MODEL2_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
    benchmark_stat_fields=tuple(BENCHMARK_STAT_FIELDS),
    benchmark_stat_display_labels=BENCHMARK_STAT_DISPLAY_LABELS,
    benchmark_avg_only_name=BENCHMARK_AVG_ONLY,
    header_note="Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval",
)


def parse_anylogic_range_output(path: str | Path) -> list[RangeRow]:
    rows: list[RangeRow] = []
    for row in parse_anylogic_benchmark_output(path):
        rows.append(
            RangeRow(
                iteration=row.iteration,
                params={
                    "arrival_rate_s": row.arrival_rate_s,
                    "n_forklifts": row.forklift_capacity,
                    "delay_time_s": row.delay_time_s,
                },
                metrics={
                    "created": row.created,
                    "completed": row.completed,
                    "avg_wip": row.avg_wip,
                    "avg_time_in_system_s": row.avg_time_in_system_s,
                    "storage_level": row.storage_level,
                    "throughput_per_hour": row.throughput_per_hour,
                    "forklift_utilization": row.forklift_utilization,
                },
                benchmarks=row.benchmarks,
            )
        )
    return rows


def load_simpy_summary_rows(path: str | Path) -> list[RangeRow]:
    return _load_simpy_summary_rows(path, MODEL2_RANGE_SPEC)


def load_simpy_run_rows(path: str | Path) -> list[RangeRow]:
    return _load_simpy_run_rows(path, MODEL2_RANGE_SPEC)


def build_comparison_context(
    anylogic_rows: list[RangeRow],
    simpy_summary_rows: list[RangeRow],
    simpy_run_rows: list[RangeRow],
):
    return _build_comparison_context(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL2_RANGE_SPEC,
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
        description="Compare AnyLogic and SimPy Model 2 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 2/log_file.txt",
        help="AnyLogic console output text file.",
    )
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_2_parameter_variation_range_runs.csv",
        help="SimPy per-run CSV file.",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_2_parameter_variation_range_summary.csv",
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
            "'benchmark_store_seize_to_loading_start_s__average', "
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
