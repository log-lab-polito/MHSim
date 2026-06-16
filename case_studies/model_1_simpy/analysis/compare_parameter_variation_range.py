#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 1 parameter-variation range runs.

This comparison focuses on summary metrics and forklift movement benchmarks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from mhsim_analysis.range_comparison import (
    RangeComparisonSpec,
    RangeRow,
    build_comparison_context as _build_comparison_context,
    collect_parity_offenders,
    format_parity_offenders,
    load_simpy_run_rows as _load_simpy_run_rows,
    load_simpy_summary_rows as _load_simpy_summary_rows,
    print_comparison_report,
    render_comparison_report_text as _render_comparison_report_text,
    render_html_report,
)

from case_studies.model_1_simpy.anylogic_range import range_values_for_iteration
from case_studies.model_1_simpy.benchmark_labels import (
    ANYLOGIC_BENCHMARK_KEY_MAP,
    BENCHMARK_AVG_ONLY,
    BENCHMARK_METRIC_PREFIX,
    BENCHMARK_STAT_DISPLAY_LABELS,
    BENCHMARK_STAT_FIELDS,
    BenchmarkStats,
    MODEL1_FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
    SUMMARY_METRICS as METRICS,
)
from case_studies.model_1_simpy.analysis.compare_benchmark_results import (
    parse_anylogic_benchmark_output,
)


OPTIONAL_METRICS = (
    ("forklift_utilization", "Forklifts Utilization (%)"),
    ("return_home_busy_s", "Return-home busy (s)"),
    ("implied_return_home_busy_s", "Implied return-home busy (s)"),
)
CSV_OPTIONAL_METRICS = (
    ("forklift_utilization", "Forklifts Utilization (%)"),
    ("return_home_busy_s", "Return-home busy (s)"),
)
BENCHMARK_STAT_LABELS = {field_name: label for field_name, label in BENCHMARK_STAT_FIELDS}


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
_MODEL1_CSV_LOAD_SPEC = replace(
    MODEL1_RANGE_SPEC,
    optional_metrics=CSV_OPTIONAL_METRICS,
)

_MOVE_BUSY_BENCHMARKS = tuple(ANYLOGIC_BENCHMARK_KEY_MAP.values())


def _implied_return_home_busy_s(row: RangeRow) -> float | None:
    """Infer post-release transporter busy time from utilization.

    AnyLogic's `ReleaseTransporter` sends the item downstream at unload
    completion, then accounts the transporter return as a busy ResourcePool
    wrap-up task. The range export does not print that wrap-up duration
    directly, so derive it from utilization minus the exported move windows.
    """
    utilization = row.metrics.get("forklift_utilization")
    completed = row.metrics.get("completed")
    throughput_per_hour = row.metrics.get("throughput_per_hour")
    n_forklifts = row.params.get("n_forklifts")
    if (
        utilization is None
        or completed is None
        or completed <= 0
        or throughput_per_hour is None
        or throughput_per_hour <= 0
        or n_forklifts is None
    ):
        return None

    task_busy_time = 0.0
    for metric_key in _MOVE_BUSY_BENCHMARKS:
        benchmark = row.benchmarks.get(metric_key)
        if benchmark is None or benchmark.average is None:
            return None
        task_busy_time += float(benchmark.average)

    sim_time_s = (float(completed) / float(throughput_per_hour)) * 3600.0
    busy_time_per_completed_move = (
        float(utilization) * float(n_forklifts) * sim_time_s / float(completed)
    )
    return busy_time_per_completed_move - task_busy_time


def _with_return_home_busy_metrics(rows: list[RangeRow]) -> list[RangeRow]:
    updated_rows: list[RangeRow] = []
    for row in rows:
        implied_return_home_busy_s = _implied_return_home_busy_s(row)
        return_home_busy_s = row.metrics.get("return_home_busy_s")
        if return_home_busy_s is None:
            return_home_busy_s = implied_return_home_busy_s
        updated_rows.append(
            RangeRow(
                iteration=row.iteration,
                params=row.params,
                metrics={
                    **row.metrics,
                    # AnyLogic does not export wrap-up duration directly, so
                    # its value here is utilization-implied. SimPy writes this
                    # metric from ForkliftFleet.return_home_time_s.
                    "return_home_busy_s": return_home_busy_s,
                    "implied_return_home_busy_s": implied_return_home_busy_s,
                },
                benchmarks=row.benchmarks,
                replications=row.replications,
                replication=row.replication,
            )
        )
    return updated_rows


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
                    "avg_wip": row.avg_wip,
                    "avg_time_in_system_s": row.avg_time_in_system_s,
                    "throughput_per_hour": row.throughput_per_hour,
                    "forklift_utilization": row.forklift_utilization,
                },
                benchmarks=row.benchmarks,
            )
        )
    return _with_return_home_busy_metrics(rows)


def load_simpy_summary_rows(path: str | Path) -> list[RangeRow]:
    return _with_return_home_busy_metrics(
        _load_simpy_summary_rows(path, _MODEL1_CSV_LOAD_SPEC)
    )


def load_simpy_run_rows(path: str | Path) -> list[RangeRow]:
    return _with_return_home_busy_metrics(
        _load_simpy_run_rows(path, _MODEL1_CSV_LOAD_SPEC)
    )


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
        default="anylogic/Model 1/log_file.txt",
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
    parser.add_argument(
        "--fail-over-abs-s",
        type=float,
        default=None,
        help=(
            "Regression gate: exit non-zero if any benchmark movement-timing "
            "metric (seconds) diverges from AnyLogic by more than this many "
            "seconds. Use in CI to catch sub-0.1%% movement-parity regressions."
        ),
    )
    parser.add_argument(
        "--fail-over-pct",
        type=float,
        default=None,
        help=(
            "Regression gate: exit non-zero if any gated metric diverges by more "
            "than this percent. Applies to the same metric scope as "
            "--gate-metric-prefix."
        ),
    )
    parser.add_argument(
        "--gate-metric-prefix",
        default="benchmark_",
        help=(
            "Restrict the regression gate to metrics whose field name starts "
            "with this prefix. Default 'benchmark_' gates only the second-valued "
            "movement-timing windows; pass an empty string to gate all metrics."
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

    if args.fail_over_abs_s is not None or args.fail_over_pct is not None:
        offenders = collect_parity_offenders(
            context,
            max_abs_diff=args.fail_over_abs_s,
            max_pct=args.fail_over_pct,
            metric_name_prefix=args.gate_metric_prefix or None,
        )
        gate_parts = []
        if args.fail_over_abs_s is not None:
            gate_parts.append(f"abs>{args.fail_over_abs_s:g}s")
        if args.fail_over_pct is not None:
            gate_parts.append(f"pct>{args.fail_over_pct:g}%")
        scope = args.gate_metric_prefix or "all"
        gate_desc = " or ".join(gate_parts)
        if offenders:
            print(
                f"\nPARITY GATE FAILED ({gate_desc}, scope='{scope}'): "
                f"{len(offenders)} offending metric/case row(s):"
            )
            print(format_parity_offenders(offenders, context.spec, limit=25))
            sys.exit(1)
        print(f"\nPARITY GATE PASSED ({gate_desc}, scope='{scope}').")


if __name__ == "__main__":
    main()
