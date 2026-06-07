#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy outputs for Model 5 parameter-variation range runs.

Model 5 keeps SimPy arrivals in the experiment CSV as rates per minute, while
AnyLogic exports the cyclic arrival interval in seconds. The comparison rows
therefore normalize SimPy parameters to the AnyLogic-style interval before
matching and rendering reports.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from mhsim_analysis.range_comparison import (
    RangeComparisonSpec,
    RangeRow,
    build_comparison_context,
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
    ("storage_level", "Storage level"),
    ("throughput_per_hour", "Throughput (/h)"),
)
OPTIONAL_METRICS = (
    ("forklift_utilization", "Forklifts Utilization (%)"),
)

MODEL5_RANGE_SPEC = RangeComparisonSpec(
    model_label="Model 5",
    parameter_fields=("arrival_rate_s", "n_forklifts", "delay_time_s"),
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
    header_note=(
        "Arrival mapping used for SimPy: arrival_rate_s = "
        "60 / param_arrival_rate_per_min"
    ),
)

ANYLOGIC_KEY_MAP = {
    "Arrival rate (s)": "arrival_rate_s",
    "Forklift capacity": "n_forklifts",
    "Delay time (s)": "delay_time_s",
    "Created": "created",
    "Completed": "completed",
    "Avg WIP": "avg_wip",
    "Avg cycle (s)": "avg_time_in_system_s",
    "Storage level": "storage_level",
    "Throughput (/h)": "throughput_per_hour",
    "Forklifts Utilization (%)": "forklift_utilization",
}


def parse_anylogic_range_output(path: str | Path) -> list[RangeRow]:
    return parse_anylogic_summary_log(
        path,
        key_map=ANYLOGIC_KEY_MAP,
        parameter_fields=MODEL5_RANGE_SPEC.parameter_fields,
        metric_fields=[name for name, _label in METRICS],
        optional_metric_fields=[name for name, _label in OPTIONAL_METRICS],
    )


def load_simpy_summary_rows(path: str | Path) -> list[RangeRow]:
    rows: list[RangeRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                RangeRow(
                    iteration=_int_field(record, "iteration"),
                    replications=_int_field(record, "replications"),
                    params=_simpy_params(record),
                    metrics={
                        name: _metric_number_field(record, name)
                        for name, _label in (*METRICS, *OPTIONAL_METRICS)
                    },
                )
            )
    return rows


def load_simpy_run_rows(path: str | Path) -> list[RangeRow]:
    rows: list[RangeRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                RangeRow(
                    iteration=_int_field(record, "iteration"),
                    replication=_int_field(record, "replication"),
                    params=_simpy_params(record),
                    metrics={
                        name: _number_field(record, f"metric_{name}")
                        for name, _label in (*METRICS, *OPTIONAL_METRICS)
                    },
                )
            )
    return rows


def _simpy_params(record: dict[str, str]) -> dict[str, int | float]:
    arrival_rate_per_min = _float_field(record, "param_arrival_rate_per_min")
    return {
        "arrival_rate_s": 60.0 / arrival_rate_per_min,
        "n_forklifts": _int_field(record, "param_n_forklifts"),
        "delay_time_s": _float_field(record, "param_delay_time_s"),
    }


def _infer_output_format(output_path: Path, requested_format: str | None) -> str:
    if requested_format is not None:
        return requested_format
    if output_path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "text"


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


def _number_field(record: dict[str, str], field_name: str) -> int | float | None:
    value = record.get(field_name)
    if value in (None, ""):
        return None
    numeric = float(value)
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _metric_number_field(record: dict[str, str], metric_name: str) -> int | float | None:
    direct = _number_field(record, f"metric_{metric_name}")
    if direct is not None:
        return direct
    return _number_field(record, f"metric_{metric_name}_mean")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 5 range-experiment outputs."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 5/log_file.txt",
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
        help=(
            "Output format when --output is set. Defaults to html for .html/.htm "
            "paths and text otherwise."
        ),
    )
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_range_output(args.anylogic)
    simpy_summary_rows = load_simpy_summary_rows(args.simpy_summary)
    simpy_run_rows = load_simpy_run_rows(args.simpy_runs)
    context = build_comparison_context(
        anylogic_rows,
        simpy_summary_rows,
        simpy_run_rows,
        spec=MODEL5_RANGE_SPEC,
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
