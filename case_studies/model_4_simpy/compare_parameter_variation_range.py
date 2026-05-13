#!/usr/bin/env python3
"""Compare AnyLogic and SimPy outputs for Model 4 range runs."""

from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

from mhsim.range_comparison import (
    RangeRow,
    RangeComparisonSpec,
    build_comparison_context,
    load_simpy_run_rows,
    load_simpy_summary_rows,
    parse_anylogic_summary_log,
    print_comparison_report,
    render_comparison_report_text,
    render_html_report,
    validate_simpy_runs,
)

from .range_config import RANGE_VALUES, range_values_for_iteration


METRICS = (
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    ("main_created", "Main created"),
    ("branch_created", "Branch created"),
    ("main_completed", "Main completed"),
    ("branch_completed", "Branch completed"),
    ("main_conveyor_entered", "Main conveyor entered"),
    ("main_conveyor_exited", "Main conveyor exited"),
    ("main_conveyor_occupancy_end", "Main conveyor occupancy end"),
    ("branch_conveyor_entered", "Branch conveyor entered"),
    ("branch_conveyor_exited", "Branch conveyor exited"),
    ("branch_conveyor_occupancy_end", "Branch conveyor occupancy end"),
    ("spur_transferred", "Spur transferred"),
    ("spur_remaining_main_distance_m", "Spur remaining main distance (m)"),
)

MODEL4_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 4",
    parameter_fields=(
        "main_arrival_time_s",
        "conveyor_speed_mps",
        "conveyor_gap_m",
        "branch_arrival_time_s",
    ),
    parameter_labels={
        "main_arrival_time_s": "Arrival rate (s)",
        "conveyor_speed_mps": "Conveyor Speed (m/s)",
        "conveyor_gap_m": "Conveyor Gap (m)",
        "branch_arrival_time_s": "Branch arrival rate (s)",
    },
    parameter_short_labels={
        "main_arrival_time_s": "main_a",
        "conveyor_speed_mps": "v",
        "conveyor_gap_m": "gap",
        "branch_arrival_time_s": "branch_a",
    },
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    header_note=(
        "Model 4 is the conveyor spur/merge scenario. Older AnyLogic summary "
        "logs omit branch arrival, so branch arrival is inferred from the "
        "AnyLogic ranged-experiment iteration order when needed."
    ),
)

ANYLOGIC_KEY_MAP = {
    "Arrival rate (s)": "main_arrival_time_s",
    "Main arrival rate (s)": "main_arrival_time_s",
    "Branch arrival rate (s)": "branch_arrival_time_s",
    "Conveyor Speed (m/s)": "conveyor_speed_mps",
    "Conveyor Gap (m)": "conveyor_gap_m",
    "Created": "created",
    "Completed": "completed",
    "Main completed": "main_completed",
    "Branch completed": "branch_completed",
    "In flight": "in_flight",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
}


def parse_anylogic_range_output(path: str | Path):
    metric_fields = [name for name, _label in METRICS]
    optional_metric_fields = [name for name, _label in OPTIONAL_METRICS]
    try:
        rows = parse_anylogic_summary_log(
            path,
            key_map=ANYLOGIC_KEY_MAP,
            parameter_fields=(
                "main_arrival_time_s",
                "branch_arrival_time_s",
                "conveyor_speed_mps",
                "conveyor_gap_m",
            ),
            metric_fields=metric_fields,
            optional_metric_fields=optional_metric_fields,
        )
        return _filter_to_model4_range_grid(rows)
    except ValueError as exc:
        if "branch_arrival_time_s" not in str(exc):
            raise

    rows = parse_anylogic_summary_log(
        path,
        key_map=ANYLOGIC_KEY_MAP,
        parameter_fields=(
            "main_arrival_time_s",
            "conveyor_speed_mps",
            "conveyor_gap_m",
        ),
        metric_fields=metric_fields,
        optional_metric_fields=optional_metric_fields,
    )
    enriched_rows: list[RangeRow] = []
    for row in rows:
        params = dict(row.params)
        if "branch_arrival_time_s" not in params:
            params["branch_arrival_time_s"] = (
                range_values_for_iteration(row.iteration).branch_arrival_time_s
            )
        enriched_rows.append(
            RangeRow(
                iteration=row.iteration,
                params=params,
                metrics=row.metrics,
                benchmarks=row.benchmarks,
                replications=row.replications,
                replication=row.replication,
            )
        )
    return _filter_to_model4_range_grid(enriched_rows)


def _filter_to_model4_range_grid(rows: list[RangeRow]) -> list[RangeRow]:
    expected_keys = set(product(*(RANGE_VALUES[name] for name in MODEL4_RANGE_SPEC.parameter_fields)))
    return [row for row in rows if row.match_key(MODEL4_RANGE_SPEC) in expected_keys]


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


def _render_simpy_validation(
    *,
    simpy_summary_rows,
    simpy_run_rows,
) -> str:
    issues = validate_simpy_runs(
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL4_RANGE_SPEC,
    )
    lines = [
        "SIMPY PARAMETER VARIATION OUTPUT VALIDATION (Model 4)",
        "=" * 58,
        f"Summary iterations: {len(simpy_summary_rows)}",
        f"Run rows: {len(simpy_run_rows)}",
        "SimPy consistency check: " + ("FAIL" if issues else "PASS"),
    ]
    lines.extend(f"  - {issue}" for issue in issues)
    lines.append("")
    lines.append("Pass --anylogic PATH to run an AnyLogic vs SimPy comparison.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 4 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        help=(
            "AnyLogic console output text file. Optional; when omitted, only "
            "the SimPy CSV consistency check is run."
        ),
    )
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_4_parameter_variation_range_runs.csv",
        help="SimPy per-run CSV file.",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_4_parameter_variation_range_summary.csv",
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
        help="Metric filter for matrix/offenders views.",
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
        help="Output format when --output is set.",
    )
    args = parser.parse_args()

    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary, MODEL4_RANGE_SPEC)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs, MODEL4_RANGE_SPEC)

    if args.anylogic:
        anylogic_rows = parse_anylogic_range_output(args.anylogic)
        context = build_comparison_context(
            anylogic_rows,
            simpy_summary_rows,
            simpy_run_rows,
            spec=MODEL4_RANGE_SPEC,
        )
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
    else:
        content = _render_simpy_validation(
            simpy_summary_rows=simpy_summary_rows,
            simpy_run_rows=simpy_run_rows,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            print(f"Wrote report: {output_path}")
        else:
            print(content)


if __name__ == "__main__":
    main()
