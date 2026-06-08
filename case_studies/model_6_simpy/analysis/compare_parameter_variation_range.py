#!/usr/bin/env python3
"""Compare AnyLogic and SimPy outputs for Model 6 range runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from mhsim_analysis.range_comparison import (
    RangeComparisonSpec,
    RangeRow,
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
    ("avg_wip", "Avg WIP"),
    ("avg_time_in_system_s", "Avg cycle (s)"),
    ("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    ("main_conveyor_occupancy_end", "Main conveyor occupancy end"),
    ("storage_conveyor_occupancy_end", "Storage conveyor occupancy end"),
    ("empty_pallets_completed", "Empty pallets completed"),
    ("loose_items_created", "Loose items created"),
    ("batches_created", "Batches created"),
)

MODEL6_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 6",
    parameter_fields=(
        "arrival_rate_s",
        "conveyor_speed_mps",
        "conveyor_gap_m",
        "min_items_per_pallet",
        "max_items_per_pallet",
    ),
    parameter_labels={
        "arrival_rate_s": "Arrival rate (s)",
        "conveyor_speed_mps": "Conveyor Speed (m/s)",
        "conveyor_gap_m": "Conveyor Gap (m)",
        "min_items_per_pallet": "Min items per pallet",
        "max_items_per_pallet": "Max items per pallet",
    },
    parameter_short_labels={
        "arrival_rate_s": "a",
        "conveyor_speed_mps": "v",
        "conveyor_gap_m": "gap",
        "min_items_per_pallet": "min_items",
        "max_items_per_pallet": "max_items",
    },
    metrics=METRICS,
    optional_metrics=OPTIONAL_METRICS,
    header_note=(
        "Model 6 uses AnyLogic manual Source.inject() flows for inbound pallets "
        "and loose items; arrival_rate_s is the cyclic inbound inject interval."
    ),
)

ANYLOGIC_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Conveyor Speed (m/s)": "conveyor_speed_mps",
    "Conveyor Gap (m)": "conveyor_gap_m",
    "Min items per pallet": "min_items_per_pallet",
    "Max items per pallet": "max_items_per_pallet",
    "Created": "created",
    "Completed": "completed",
    "Avg WIP": "avg_wip",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Throughput (/h)": "throughput_per_hour",
}


def parse_anylogic_range_output(path: str | Path):
    try:
        return parse_anylogic_summary_log(
            path,
            key_map=ANYLOGIC_KEY_MAP,
            parameter_fields=MODEL6_RANGE_SPEC.parameter_fields,
            metric_fields=[name for name, _label in METRICS],
        )
    except ValueError as exc:
        message = str(exc)
        missing_item_params = (
            "min_items_per_pallet" in message
            or "max_items_per_pallet" in message
        )
        if not missing_item_params:
            raise
        legacy_rows = parse_anylogic_summary_log(
            path,
            key_map=ANYLOGIC_KEY_MAP,
            parameter_fields=(
                "arrival_rate_s",
                "conveyor_speed_mps",
                "conveyor_gap_m",
            ),
            metric_fields=[name for name, _label in METRICS],
        )
        return [
            RangeRow(
                iteration=row.iteration,
                params={
                    **row.params,
                    "min_items_per_pallet": 5.0,
                    "max_items_per_pallet": 20.0,
                },
                metrics=row.metrics,
                benchmarks=row.benchmarks,
                replications=row.replications,
                replication=row.replication,
            )
            for row in legacy_rows
        ]


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 6 range-experiment outputs."
    )
    parser.add_argument("--anylogic", default="anylogic/Model 6/log_file.txt")
    parser.add_argument(
        "--simpy-runs",
        default="logs/model_6_parameter_variation_range_runs.csv",
    )
    parser.add_argument(
        "--simpy-summary",
        default="logs/model_6_parameter_variation_range_summary.csv",
    )
    parser.add_argument(
        "--view",
        choices=("full", "overview", "matrix", "offenders", "report", "all"),
        default="overview",
    )
    parser.add_argument("--metric", default="all")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("text", "html"))
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_range_output(args.anylogic)
    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary, MODEL6_RANGE_SPEC)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs, MODEL6_RANGE_SPEC)
    context = build_comparison_context(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL6_RANGE_SPEC,
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
