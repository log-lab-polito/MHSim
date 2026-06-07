#!/usr/bin/env python3
"""Evaluate Model 1 forklift return-home policy candidate outputs."""

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
from ..params import Model1Params


DEFAULT_CANDIDATE_ROOT = Path("logs")
DEFAULT_ANYLOGIC_RANGE = Path("anylogic/Model 1/log_file.txt")
DEFAULT_ANYLOGIC_BENCHMARK = Path("anylogic/Model 1/log_file.txt")
ARTIFACT_REFRESH_NOTE = (
    "Refresh release-policy candidate artifacts by running the Model 1 "
    "parameter-variation command for each return-home policy, then writing the "
    "range run/summary CSVs to "
    "logs/model_1_release_policy_<policy>_parameter_variation_range_*.csv."
)
DEFAULT_CANDIDATES = ("idle", "stay", "always")


@dataclass(frozen=True)
class CandidateResult:
    name: str
    benchmark_match: int
    benchmark_close: int
    benchmark_diff: int
    benchmark_worst_pct: float | None
    avg_cycle_close: int
    return_home_match: int
    return_home_close: int
    return_home_diff: int
    implied_return_home_match: int
    implied_return_home_close: int
    implied_return_home_diff: int
    default_avg_cycle_status: str
    default_utilization_status: str
    rejected: bool

    @property
    def sort_key(self) -> tuple[bool, int, int, int, float, int]:
        worst_pct = (
            abs(self.benchmark_worst_pct)
            if self.benchmark_worst_pct is not None
            else float("inf")
        )
        return (
            self.rejected,
            self.benchmark_diff,
            self.return_home_diff,
            self.implied_return_home_diff,
            worst_pct,
            -self.avg_cycle_close,
        )


def _candidate_artifact_path(candidate_root: Path, name: str, suffix: str) -> Path:
    path = candidate_root / name
    if path.exists() and path.is_dir():
        return path / f"model_1_parameter_variation_range_{suffix}.csv"
    return (
        candidate_root
        / f"model_1_release_policy_{name}_parameter_variation_range_{suffix}.csv"
    )


def _load_candidate_result(
    *,
    candidate_root: Path,
    anylogic_range_rows,
    anylogic_benchmark_row,
    name: str,
) -> CandidateResult:
    summary_path = _candidate_artifact_path(candidate_root, name, "summary")
    runs_path = _candidate_artifact_path(candidate_root, name, "runs")
    _require_file(
        summary_path,
        f"Model 1 release-policy candidate summary CSV for {name}",
    )
    _require_file(
        runs_path,
        f"Model 1 release-policy candidate run CSV for {name}",
    )
    context = build_comparison_context(
        anylogic_range_rows,
        load_simpy_summary_rows(summary_path),
        load_simpy_run_rows(runs_path),
    )
    benchmark_overview = _overview_for_metric(context, BENCHMARK_AVG_ONLY)
    avg_cycle_overview = _overview_for_metric(context, "avg_time_in_system_s")
    return_home_overview = _overview_for_metric(context, "return_home_busy_s")
    implied_return_home_overview = _overview_for_metric(
        context,
        "implied_return_home_busy_s",
    )

    params = Model1Params()
    params.forklift_return_home_policy = name
    simpy_default = run_simpy_benchmark(
        anylogic_benchmark_row,
        sim_time=3600.0,
        base_params=params,
    )
    default_avg_cycle_status = _status(
        anylogic_benchmark_row.avg_time_in_system_s,
        simpy_default.avg_time_in_system_s,
    )
    if anylogic_benchmark_row.forklift_utilization is None:
        default_utilization_status = "n/a"
    else:
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
        benchmark_match=benchmark_overview.match_count,
        benchmark_close=benchmark_overview.close_count,
        benchmark_diff=benchmark_overview.diff_count,
        benchmark_worst_pct=benchmark_overview.worst_pct,
        avg_cycle_close=avg_cycle_overview.close_count,
        return_home_match=return_home_overview.match_count,
        return_home_close=return_home_overview.close_count,
        return_home_diff=return_home_overview.diff_count,
        implied_return_home_match=implied_return_home_overview.match_count,
        implied_return_home_close=implied_return_home_overview.close_count,
        implied_return_home_diff=implied_return_home_overview.diff_count,
        default_avg_cycle_status=default_avg_cycle_status,
        default_utilization_status=default_utilization_status,
        rejected=rejected,
    )


def _require_file(path: Path, description: str) -> None:
    if path.exists():
        return
    raise FileNotFoundError(f"Missing {description}: {path}\n{ARTIFACT_REFRESH_NOTE}")


def _mcd(match: int, close: int, diff: int) -> str:
    return f"{match}/{close}/{diff}"


def _render_table(rows: list[CandidateResult]) -> str:
    headers = [
        "Policy",
        "Bench M/C/D",
        "Worst %",
        "Avg-cycle CLOSE",
        "Return M/C/D",
        "Implied M/C/D",
        "Default avg",
        "Default util",
        "Rejected",
    ]
    body = [
        [
            row.name,
            _mcd(row.benchmark_match, row.benchmark_close, row.benchmark_diff),
            _format_percent(row.benchmark_worst_pct),
            _format_value(row.avg_cycle_close),
            _mcd(row.return_home_match, row.return_home_close, row.return_home_diff),
            _mcd(
                row.implied_return_home_match,
                row.implied_return_home_close,
                row.implied_return_home_diff,
            ),
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
    _require_file(anylogic_range_path, "AnyLogic Model 1 parameter-variation output")
    _require_file(anylogic_benchmark_path, "AnyLogic Model 1 benchmark output")
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
        )
        for name in DEFAULT_CANDIDATES
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
        else f"Selected candidate: {selected.name}"
    )
    return "\n\n".join(
        [
            "Model 1 return-home policy candidate evaluation",
            _render_table(results),
            selected_line,
            (
                "Selection rule: lowest benchmark_avg_only DIFF count, then "
                "lowest return-home DIFF counts, then lowest worst offender "
                "percent, then highest avg-cycle CLOSE count; reject candidates "
                "whose default avg cycle or utilization is DIFF."
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Model 1 return-home policy candidate outputs."
    )
    parser.add_argument(
        "--candidate-root",
        default=str(DEFAULT_CANDIDATE_ROOT),
        help="Directory containing release-policy candidate output CSV files.",
    )
    parser.add_argument(
        "--anylogic-range",
        default=str(DEFAULT_ANYLOGIC_RANGE),
        help="AnyLogic parameter variation range output.",
    )
    parser.add_argument(
        "--anylogic-benchmark",
        default=str(DEFAULT_ANYLOGIC_BENCHMARK),
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
