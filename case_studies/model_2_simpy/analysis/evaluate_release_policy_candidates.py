#!/usr/bin/env python3
"""Evaluate Model 2 block-specific release-policy candidate outputs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from mhsim_analysis.range_comparison import _format_percent, _format_value

from .compare_benchmark_results import (
    _status,
    parse_anylogic_benchmark_output,
    run_simpy_benchmark,
)
from .compare_parameter_variation_range import (
    BENCHMARK_AVG_ONLY,
    build_comparison_context,
    load_simpy_run_rows,
    load_simpy_summary_rows,
    parse_anylogic_range_output,
)
from .compare_parity_step import _overview_for_metric
from ..params import Model2Params


DEFAULT_CANDIDATES = (
    ("storage_return_outbound_return", True, True),
    ("storage_stay_outbound_return", False, True),
    ("storage_stay_outbound_stay", False, False),
    ("storage_return_outbound_stay", True, False),
)


@dataclass(frozen=True)
class CandidateResult:
    name: str
    storage_returns: bool
    outbound_returns: bool
    benchmark_match: int
    benchmark_close: int
    benchmark_diff: int
    benchmark_worst_pct: float | None
    avg_cycle_close: int
    default_avg_cycle_status: str
    default_utilization_status: str
    rejected: bool

    @property
    def sort_key(self) -> tuple[bool, int, float, int]:
        worst_pct = (
            abs(self.benchmark_worst_pct)
            if self.benchmark_worst_pct is not None
            else float("inf")
        )
        return (self.rejected, self.benchmark_diff, worst_pct, -self.avg_cycle_close)


def _policy_label(value: bool) -> str:
    return "return" if value else "stay"


def _load_candidate_result(
    *,
    candidate_root: Path,
    anylogic_range_rows,
    anylogic_benchmark_row,
    name: str,
    storage_returns: bool,
    outbound_returns: bool,
) -> CandidateResult:
    candidate_dir = candidate_root / name
    context = build_comparison_context(
        anylogic_range_rows,
        load_simpy_summary_rows(
            candidate_dir / "model_2_parameter_variation_range_summary.csv"
        ),
        load_simpy_run_rows(candidate_dir / "model_2_parameter_variation_range_runs.csv"),
    )
    benchmark_overview = _overview_for_metric(context, BENCHMARK_AVG_ONLY)
    avg_cycle_overview = _overview_for_metric(context, "avg_time_in_system_s")

    params = Model2Params()
    params.move_to_storage_apply_post_task_policy = storage_returns
    params.move_to_outbound_apply_post_task_policy = outbound_returns
    simpy_default = run_simpy_benchmark(
        anylogic_benchmark_row,
        sim_time=18000.0,
        base_params=params,
    )
    default_avg_cycle_status = _status(
        anylogic_benchmark_row.avg_time_in_system_s,
        simpy_default.avg_time_in_system_s,
    )
    default_utilization_status = _status(
        anylogic_benchmark_row.forklift_utilization,
        simpy_default.forklift_utilization,
    )
    rejected = (
        default_avg_cycle_status == "DIFF"
        or default_utilization_status == "DIFF"
    )

    return CandidateResult(
        name=name,
        storage_returns=storage_returns,
        outbound_returns=outbound_returns,
        benchmark_match=benchmark_overview.match_count,
        benchmark_close=benchmark_overview.close_count,
        benchmark_diff=benchmark_overview.diff_count,
        benchmark_worst_pct=benchmark_overview.worst_pct,
        avg_cycle_close=avg_cycle_overview.close_count,
        default_avg_cycle_status=default_avg_cycle_status,
        default_utilization_status=default_utilization_status,
        rejected=rejected,
    )


def _render_table(rows: list[CandidateResult]) -> str:
    headers = [
        "Candidate",
        "Storage",
        "Outbound",
        "Bench M/C/D",
        "Worst %",
        "Avg-cycle CLOSE",
        "Default avg",
        "Default util",
        "Rejected",
    ]
    body = [
        [
            row.name,
            _policy_label(row.storage_returns),
            _policy_label(row.outbound_returns),
            f"{row.benchmark_match}/{row.benchmark_close}/{row.benchmark_diff}",
            _format_percent(row.benchmark_worst_pct),
            _format_value(row.avg_cycle_close),
            row.default_avg_cycle_status,
            row.default_utilization_status,
            "yes" if row.rejected else "no",
        ]
        for row in rows
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in body))
        for index in range(len(headers))
    ]
    lines = [
        "  " + "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
        "  " + "  ".join("-" * width for width in widths),
    ]
    for row in body:
        lines.append(
            "  " + "  ".join(row[index].ljust(widths[index]) for index in range(len(row)))
        )
    return "\n".join(lines)


def evaluate_candidates(
    *,
    candidate_root: Path,
    anylogic_range_path: Path,
    anylogic_benchmark_path: Path,
) -> tuple[list[CandidateResult], CandidateResult | None]:
    anylogic_range_rows = parse_anylogic_range_output(anylogic_range_path)
    benchmark_rows = parse_anylogic_benchmark_output(anylogic_benchmark_path)
    if not benchmark_rows:
        raise ValueError(f"No AnyLogic benchmark rows found in {anylogic_benchmark_path}")
    anylogic_benchmark_row = benchmark_rows[0]

    results = [
        _load_candidate_result(
            candidate_root=candidate_root,
            anylogic_range_rows=anylogic_range_rows,
            anylogic_benchmark_row=anylogic_benchmark_row,
            name=name,
            storage_returns=storage_returns,
            outbound_returns=outbound_returns,
        )
        for name, storage_returns, outbound_returns in DEFAULT_CANDIDATES
    ]
    eligible = [row for row in results if not row.rejected]
    selected = min(eligible, key=lambda row: row.sort_key) if eligible else None
    return sorted(results, key=lambda row: row.sort_key), selected


def render_evaluation(
    *,
    candidate_root: Path,
    anylogic_range_path: Path,
    anylogic_benchmark_path: Path,
) -> str:
    results, selected = evaluate_candidates(
        candidate_root=candidate_root,
        anylogic_range_path=anylogic_range_path,
        anylogic_benchmark_path=anylogic_benchmark_path,
    )
    selected_line = (
        "Selected candidate: none"
        if selected is None
        else (
            "Selected candidate: "
            f"{selected.name} "
            f"(storage={_policy_label(selected.storage_returns)}, "
            f"outbound={_policy_label(selected.outbound_returns)})"
        )
    )
    return "\n\n".join(
        [
            "Model 2 release-policy candidate evaluation",
            _render_table(results),
            selected_line,
            (
                "Selection rule: lowest benchmark_avg_only DIFF count, then lowest "
                "worst offender percent, then highest avg-cycle CLOSE count; reject "
                "candidates whose default avg cycle or utilization is DIFF."
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Model 2 release-policy candidate step directories."
    )
    parser.add_argument(
        "--candidate-root",
        default="logs/model_2_parity_steps/02_release_policy_candidates",
        help="Directory containing release-policy candidate output directories.",
    )
    parser.add_argument(
        "--anylogic-range",
        default="logs/anylogic_model_2_parameter_variation_range.txt",
        help="AnyLogic parameter variation range output.",
    )
    parser.add_argument(
        "--anylogic-benchmark",
        default="logs/anylogic_model_2_forklift_timing.txt",
        help="AnyLogic default benchmark output.",
    )
    parser.add_argument("--output", help="Optional text output path.")
    args = parser.parse_args()

    text = render_evaluation(
        candidate_root=Path(args.candidate_root),
        anylogic_range_path=Path(args.anylogic_range),
        anylogic_benchmark_path=Path(args.anylogic_benchmark),
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
        print(f"Wrote release-policy evaluation: {output_path}")
    print(text)


if __name__ == "__main__":
    main()
