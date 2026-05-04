#!/usr/bin/env python3
"""Compare AnyLogic and SimPy outputs for Model 3 range runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from mhsim.range_comparison import (
    RangeComparisonSpec,
    build_comparison_context,
    load_simpy_run_rows,
    load_simpy_summary_rows,
    parse_anylogic_summary_log,
    print_comparison_report,
    render_comparison_report_text,
    render_html_report,
)


METRICS = (
    ("created", "Created"),
    ("completed", "Completed"),
    ("in_flight", "In flight"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    ("conveyor_entered", "Conveyor entered"),
    ("conveyor_exited", "Conveyor exited"),
    ("conveyor_occupancy_end", "Conveyor occupancy end"),
)

MODEL3_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 3",
    parameter_fields=("arrival_rate_s", "conveyor_speed_mps", "conveyor_min_gap_m"),
    parameter_labels={
        "arrival_rate_s": "Arrival rate (s)",
        "conveyor_speed_mps": "Conveyor Speed (m/s)",
        "conveyor_min_gap_m": "Conveyor Gap (m)",
    },
    parameter_short_labels={
        "arrival_rate_s": "a",
        "conveyor_speed_mps": "v",
        "conveyor_min_gap_m": "gap",
    },
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    header_note="Arrival mapping used for SimPy: arrival_rate_s is the cyclic inject interval",
)

ANYLOGIC_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Conveyor Speed (m/s)": "conveyor_speed_mps",
    "Conveyor Gap (m)": "conveyor_min_gap_m",
    "Created": "created",
    "Completed": "completed",
    "In flight": "in_flight",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
}


def parse_anylogic_range_output(path: str | Path):
    return parse_anylogic_summary_log(
        path,
        key_map=ANYLOGIC_KEY_MAP,
        parameter_fields=MODEL3_RANGE_SPEC.parameter_fields,
        metric_fields=[name for name, _label in METRICS],
    )


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 3 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 3/log_file.txt",
        help="AnyLogic console output text file.",
    )
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_3_parameter_variation_range_runs.csv",
        help="SimPy per-run CSV file.",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_3_parameter_variation_range_summary.csv",
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

    anylogic_rows = parse_anylogic_range_output(args.anylogic)
    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary, MODEL3_RANGE_SPEC)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs, MODEL3_RANGE_SPEC)
    context = build_comparison_context(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL3_RANGE_SPEC,
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


if __name__ == "__main__":
    main()
