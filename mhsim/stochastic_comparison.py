from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str


@dataclass(frozen=True)
class ReplicationRow:
    iteration: int
    replication: int
    metrics: dict[str, float]
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricComparison:
    metric_name: str
    label: str
    anylogic_n: int
    simpy_n: int
    anylogic_mean: float
    simpy_mean: float
    anylogic_std: float
    simpy_std: float
    diff: float
    diff_ci_low: float
    diff_ci_high: float
    t_stat: float
    df: float
    p_value: float | None


@dataclass(frozen=True)
class StochasticComparisonGroup:
    scope: str
    iteration: int | None
    parameter_values: Mapping[str, object]
    anylogic_rows: int
    simpy_rows: int
    comparisons: tuple[MetricComparison, ...]


@dataclass(frozen=True)
class StochasticComparisonSpec:
    title: str
    description: str
    metrics: Sequence[MetricSpec]
    anylogic_key_map: Mapping[str, str]
    default_anylogic_path: str
    default_simpy_runs_path: str
    anylogic_parameter_key_map: Mapping[str, str] = field(default_factory=dict)
    default_replications_per_iteration: int | None = None
    default_expected_iterations: int | None = None


def parse_anylogic_replication_log(
    path: str | Path,
    *,
    metrics: Sequence[MetricSpec],
    anylogic_key_map: Mapping[str, str],
    anylogic_parameter_key_map: Mapping[str, str] | None = None,
) -> list[ReplicationRow]:
    iteration_re = re.compile(
        r"^ITERATION #(?P<iteration>\d+)(?:,\s*REPLICATION #(?P<replication>\d+))?\s*$"
    )
    key_value_re = re.compile(r"^\s*([^:]+):\s*(.+?)\s*$")
    metric_names = [metric.name for metric in metrics]
    rows: list[ReplicationRow] = []
    current_iteration: int | None = None
    current_replication: int | None = None
    current_section: str | None = None
    current_parameters: dict[str, object] = {}
    current_values: dict[str, float] = {}
    next_replication_by_iteration: dict[int, int] = {}
    parameter_key_map = anylogic_parameter_key_map or {}

    def finalize_current() -> None:
        nonlocal current_iteration, current_replication, current_section
        nonlocal current_parameters, current_values
        if current_iteration is None:
            return
        missing = [metric for metric in metric_names if metric not in current_values]
        if missing:
            raise ValueError(
                f"AnyLogic iteration {current_iteration} replication "
                f"{current_replication} is missing fields: {', '.join(missing)}"
            )
        if current_replication is None:
            current_replication = next_replication_by_iteration.get(
                current_iteration,
                1,
            )
        rows.append(
            ReplicationRow(
                iteration=current_iteration,
                replication=current_replication,
                metrics={metric: current_values[metric] for metric in metric_names},
                parameters=dict(current_parameters),
            )
        )
        next_replication_by_iteration[current_iteration] = current_replication + 1
        current_iteration = None
        current_replication = None
        current_section = None
        current_parameters = {}
        current_values = {}

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            iteration_match = iteration_re.match(stripped)
            if iteration_match:
                finalize_current()
                current_iteration = int(iteration_match.group("iteration"))
                replication_text = iteration_match.group("replication")
                current_replication = (
                    int(replication_text) if replication_text is not None else None
                )
                current_section = None
                continue

            if current_iteration is None or not stripped:
                continue
            if stripped == "PARAMETERS":
                current_section = "parameters"
                continue
            if stripped == "RESULTS":
                current_section = "results"
                continue

            key_value_match = key_value_re.match(line)
            if key_value_match is None:
                continue
            raw_key, raw_value = key_value_match.groups()
            if current_section == "parameters":
                parameter_name = parameter_key_map.get(raw_key.strip())
                if parameter_name is not None:
                    current_parameters[parameter_name] = _parse_scalar(raw_value)
                continue

            if current_section == "results":
                metric_name = anylogic_key_map.get(raw_key.strip())
                if metric_name is not None:
                    current_values[metric_name] = float(raw_value)

    finalize_current()
    return rows


def load_simpy_replication_csv(
    path: str | Path,
    *,
    metrics: Sequence[MetricSpec],
) -> list[ReplicationRow]:
    rows: list[ReplicationRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            parameters = {
                name.removeprefix("param_"): _parse_scalar(value)
                for name, value in record.items()
                if name.startswith("param_") and value != ""
            }
            rows.append(
                ReplicationRow(
                    iteration=int(record["iteration"]),
                    replication=int(record["replication"]),
                    metrics={
                        metric.name: float(record[f"metric_{metric.name}"])
                        for metric in metrics
                    },
                    parameters=parameters,
                )
            )
    return rows


def _parse_scalar(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return ""
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return float(stripped)
    except ValueError:
        return stripped


def compare_metric(
    metric_name: str,
    label: str,
    anylogic_values: list[float],
    simpy_values: list[float],
    *,
    alpha: float,
) -> MetricComparison:
    if len(anylogic_values) < 2 or len(simpy_values) < 2:
        raise ValueError(f"Metric '{metric_name}' needs at least two samples per side")

    anylogic_mean = statistics.fmean(anylogic_values)
    simpy_mean = statistics.fmean(simpy_values)
    anylogic_std = statistics.stdev(anylogic_values)
    simpy_std = statistics.stdev(simpy_values)
    diff = simpy_mean - anylogic_mean

    n_a = len(anylogic_values)
    n_s = len(simpy_values)
    var_a = anylogic_std**2
    var_s = simpy_std**2
    se2 = var_a / n_a + var_s / n_s
    if se2 <= 0:
        t_stat = 0.0 if diff == 0 else math.copysign(math.inf, diff)
        df = math.inf
        p_value = 1.0 if diff == 0 else 0.0
        margin = 0.0
    else:
        se = math.sqrt(se2)
        t_stat = diff / se
        df = _welch_df(var_a, n_a, var_s, n_s)
        p_value = _two_sided_t_p_value(t_stat, df)
        critical = _t_critical(1.0 - alpha / 2.0, df)
        margin = critical * se

    return MetricComparison(
        metric_name=metric_name,
        label=label,
        anylogic_n=n_a,
        simpy_n=n_s,
        anylogic_mean=anylogic_mean,
        simpy_mean=simpy_mean,
        anylogic_std=anylogic_std,
        simpy_std=simpy_std,
        diff=diff,
        diff_ci_low=diff - margin,
        diff_ci_high=diff + margin,
        t_stat=t_stat,
        df=df,
        p_value=p_value,
    )


def compare_replication_samples(
    anylogic_rows: Iterable[ReplicationRow],
    simpy_rows: Iterable[ReplicationRow],
    *,
    metrics: Sequence[MetricSpec],
    metric_filter: str = "all",
    alpha: float,
) -> list[MetricComparison]:
    anylogic_rows_list = list(anylogic_rows)
    simpy_rows_list = list(simpy_rows)
    selected_metrics = select_metric_specs(metrics, metric_filter)
    return [
        compare_metric(
            metric.name,
            metric.label,
            values_for(anylogic_rows_list, metric.name),
            values_for(simpy_rows_list, metric.name),
            alpha=alpha,
        )
        for metric in selected_metrics
    ]


def compare_replication_sample_groups(
    anylogic_rows: Iterable[ReplicationRow],
    simpy_rows: Iterable[ReplicationRow],
    *,
    metrics: Sequence[MetricSpec],
    metric_filter: str = "all",
    alpha: float,
    include_overall: bool = True,
    include_iterations: bool = True,
) -> list[StochasticComparisonGroup]:
    anylogic_rows_list = list(anylogic_rows)
    simpy_rows_list = list(simpy_rows)
    selected_metrics = select_metric_specs(metrics, metric_filter)

    groups: list[StochasticComparisonGroup] = []
    if include_overall:
        groups.append(
            _build_comparison_group(
                scope="overall",
                iteration=None,
                anylogic_rows=anylogic_rows_list,
                simpy_rows=simpy_rows_list,
                selected_metrics=selected_metrics,
                alpha=alpha,
            )
        )

    if include_iterations:
        anylogic_by_iteration = _group_rows_by_iteration(anylogic_rows_list)
        simpy_by_iteration = _group_rows_by_iteration(simpy_rows_list)
        anylogic_iterations = set(anylogic_by_iteration)
        simpy_iterations = set(simpy_by_iteration)
        if anylogic_iterations != simpy_iterations:
            only_anylogic = sorted(anylogic_iterations - simpy_iterations)
            only_simpy = sorted(simpy_iterations - anylogic_iterations)
            details = []
            if only_anylogic:
                details.append(f"AnyLogic only: {_format_iteration_list(only_anylogic)}")
            if only_simpy:
                details.append(f"SimPy only: {_format_iteration_list(only_simpy)}")
            raise ValueError("Mismatched stochastic iterations. " + "; ".join(details))

        for iteration in sorted(anylogic_by_iteration):
            groups.append(
                _build_comparison_group(
                    scope="iteration",
                    iteration=iteration,
                    anylogic_rows=anylogic_by_iteration[iteration],
                    simpy_rows=simpy_by_iteration[iteration],
                    selected_metrics=selected_metrics,
                    alpha=alpha,
                )
            )

    return groups


def select_metric_specs(
    metrics: Sequence[MetricSpec],
    metric_filter: str,
) -> list[MetricSpec]:
    selected = [
        metric
        for metric in metrics
        if metric_filter == "all" or metric_filter == metric.name
    ]
    if not selected:
        valid = ", ".join(metric.name for metric in metrics)
        raise ValueError(f"Unknown metric '{metric_filter}'. Valid metrics: {valid}")
    return selected


def values_for(rows: Iterable[ReplicationRow], metric_name: str) -> list[float]:
    return [row.metrics[metric_name] for row in rows]


def _build_comparison_group(
    *,
    scope: str,
    iteration: int | None,
    anylogic_rows: list[ReplicationRow],
    simpy_rows: list[ReplicationRow],
    selected_metrics: Sequence[MetricSpec],
    alpha: float,
) -> StochasticComparisonGroup:
    return StochasticComparisonGroup(
        scope=scope,
        iteration=iteration,
        parameter_values=(
            {}
            if scope == "overall"
            else _parameter_values_for_group(anylogic_rows, simpy_rows)
        ),
        anylogic_rows=len(anylogic_rows),
        simpy_rows=len(simpy_rows),
        comparisons=tuple(
            compare_metric(
                metric.name,
                metric.label,
                values_for(anylogic_rows, metric.name),
                values_for(simpy_rows, metric.name),
                alpha=alpha,
            )
            for metric in selected_metrics
        ),
    )


def _parameter_values_for_group(
    anylogic_rows: Sequence[ReplicationRow],
    simpy_rows: Sequence[ReplicationRow],
) -> Mapping[str, object]:
    for rows in (simpy_rows, anylogic_rows):
        for row in rows:
            if row.parameters:
                return dict(row.parameters)
    return {}


def _group_rows_by_iteration(
    rows: Iterable[ReplicationRow],
) -> dict[int, list[ReplicationRow]]:
    grouped: dict[int, list[ReplicationRow]] = {}
    for row in rows:
        grouped.setdefault(row.iteration, []).append(row)
    return grouped


def _format_iteration_list(iterations: Sequence[int]) -> str:
    if len(iterations) <= 10:
        return ", ".join(str(iteration) for iteration in iterations)
    head = ", ".join(str(iteration) for iteration in iterations[:5])
    tail = ", ".join(str(iteration) for iteration in iterations[-3:])
    return f"{head}, ..., {tail}"


def _format_parameters(parameters: Mapping[str, object]) -> str:
    if not parameters:
        return "-"
    return ", ".join(
        f"{name}={_format_parameter_value(value)}"
        for name, value in sorted(parameters.items())
    )


def _format_parameter_value(value: object) -> str:
    if isinstance(value, float):
        text = f"{value:.6g}"
        return text
    return str(value)


def print_stochastic_comparison_report(
    title: str,
    comparisons: list[MetricComparison],
    *,
    alpha: float,
) -> None:
    print(f"\n{title}")
    print("=" * 110)
    print(
        "Welch two-sample t-test compares means; a large p-value is not proof of parity."
    )
    print(f"Confidence level: {(1.0 - alpha) * 100:.1f}%")
    print("-" * 110)
    print(
        f"{'Metric':<22} {'n AL/SP':>8} {'AL mean':>12} {'SP mean':>12} "
        f"{'Diff SP-AL':>12} {'Diff CI':>25} {'p-value':>10} {'Status':>10}"
    )
    print("-" * 110)
    for item in comparisons:
        p_value_text = "n/a" if item.p_value is None else f"{item.p_value:.4f}"
        status = (
            "DIFF"
            if item.p_value is not None and item.p_value < alpha
            else "NO_SIG_DIFF"
        )
        print(
            f"{item.label:<22} "
            f"{item.anylogic_n:>3}/{item.simpy_n:<3} "
            f"{item.anylogic_mean:>12.4f} "
            f"{item.simpy_mean:>12.4f} "
            f"{item.diff:>12.4f} "
            f"[{item.diff_ci_low:>9.4f}, {item.diff_ci_high:>9.4f}] "
            f"{p_value_text:>10} "
            f"{status:>10}"
        )


def print_stochastic_group_report(
    title: str,
    groups: Sequence[StochasticComparisonGroup],
    *,
    alpha: float,
    show_iteration_details: bool = False,
) -> None:
    overall_groups = [group for group in groups if group.scope == "overall"]
    for group in overall_groups:
        print_stochastic_comparison_report(
            f"{title} - OVERALL",
            list(group.comparisons),
            alpha=alpha,
        )

    iteration_groups = [group for group in groups if group.scope == "iteration"]
    if not iteration_groups:
        return

    print("\nPER-ITERATION STOCHASTIC COMPARISONS")
    print("=" * 110)
    print(
        f"{'Iter':>4} {'n AL/SP':>8} {'Status':>10} {'Diff metrics':<42} Parameters"
    )
    print("-" * 110)
    for group in iteration_groups:
        significant = [
            item.label
            for item in group.comparisons
            if item.p_value is not None and item.p_value < alpha
        ]
        status = "DIFF" if significant else "NO_SIG_DIFF"
        diff_text = ", ".join(significant) if significant else "-"
        if len(diff_text) > 40:
            diff_text = diff_text[:37] + "..."
        print(
            f"{group.iteration:>4} "
            f"{group.anylogic_rows:>3}/{group.simpy_rows:<3} "
            f"{status:>10} "
            f"{diff_text:<42} "
            f"{_format_parameters(group.parameter_values)}"
        )

    if show_iteration_details:
        for group in iteration_groups:
            print_stochastic_comparison_report(
                f"{title} - ITERATION {group.iteration}",
                list(group.comparisons),
                alpha=alpha,
            )


def write_stochastic_comparison_csv(
    comparisons: list[MetricComparison],
    output_path: str | Path,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "metric",
                "anylogic_n",
                "simpy_n",
                "anylogic_mean",
                "simpy_mean",
                "anylogic_std",
                "simpy_std",
                "diff_simpy_minus_anylogic",
                "diff_ci_low",
                "diff_ci_high",
                "t_stat",
                "df",
                "p_value",
            ],
        )
        writer.writeheader()
        for item in comparisons:
            writer.writerow(
                {
                    "metric": item.metric_name,
                    "anylogic_n": item.anylogic_n,
                    "simpy_n": item.simpy_n,
                    "anylogic_mean": item.anylogic_mean,
                    "simpy_mean": item.simpy_mean,
                    "anylogic_std": item.anylogic_std,
                    "simpy_std": item.simpy_std,
                    "diff_simpy_minus_anylogic": item.diff,
                    "diff_ci_low": item.diff_ci_low,
                    "diff_ci_high": item.diff_ci_high,
                    "t_stat": item.t_stat,
                    "df": item.df,
                    "p_value": item.p_value if item.p_value is not None else "",
                }
            )
    return output


def write_stochastic_comparison_groups_csv(
    groups: Sequence[StochasticComparisonGroup],
    output_path: str | Path,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    parameter_names = sorted(
        {
            name
            for group in groups
            for name in group.parameter_values
        }
    )
    fieldnames = [
        "scope",
        "iteration",
        "metric",
        "anylogic_n",
        "simpy_n",
        "anylogic_mean",
        "simpy_mean",
        "anylogic_std",
        "simpy_std",
        "diff_simpy_minus_anylogic",
        "diff_ci_low",
        "diff_ci_high",
        "t_stat",
        "df",
        "p_value",
    ] + [f"param_{name}" for name in parameter_names]

    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for group in groups:
            for item in group.comparisons:
                row = {
                    "scope": group.scope,
                    "iteration": group.iteration if group.iteration is not None else "",
                    "metric": item.metric_name,
                    "anylogic_n": item.anylogic_n,
                    "simpy_n": item.simpy_n,
                    "anylogic_mean": item.anylogic_mean,
                    "simpy_mean": item.simpy_mean,
                    "anylogic_std": item.anylogic_std,
                    "simpy_std": item.simpy_std,
                    "diff_simpy_minus_anylogic": item.diff,
                    "diff_ci_low": item.diff_ci_low,
                    "diff_ci_high": item.diff_ci_high,
                    "t_stat": item.t_stat,
                    "df": item.df,
                    "p_value": item.p_value if item.p_value is not None else "",
                }
                for name in parameter_names:
                    row[f"param_{name}"] = group.parameter_values.get(name, "")
                writer.writerow(row)
    return output


def run_stochastic_comparison_cli(spec: StochasticComparisonSpec) -> None:
    parser = argparse.ArgumentParser(description=spec.description)
    parser.add_argument(
        "--anylogic",
        default=spec.default_anylogic_path,
        help="AnyLogic stochastic replication log.",
    )
    parser.add_argument(
        "--simpy-runs",
        default=spec.default_simpy_runs_path,
        help="SimPy stochastic per-run CSV.",
    )
    parser.add_argument(
        "--metric",
        default="all",
        help="Metric to compare, or 'all'.",
    )
    parser.add_argument(
        "--comparison-scope",
        choices=("all", "overall", "iterations"),
        default="all",
        help="Compare all rows, each ranged iteration, or both.",
    )
    parser.add_argument(
        "--replications-per-iteration",
        default=(
            str(spec.default_replications_per_iteration)
            if spec.default_replications_per_iteration is not None
            else "all"
        ),
        help=(
            "Limit each ranged iteration to this many replications before comparing; "
            "use 'all' to compare every available row."
        ),
    )
    parser.add_argument(
        "--expected-iterations",
        type=int,
        default=spec.default_expected_iterations,
        help="Expected ranged-iteration count; pass 0 to disable this check.",
    )
    parser.add_argument(
        "--show-iteration-details",
        action="store_true",
        help="Print full metric tables for every ranged iteration.",
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--output-csv", help="Optional CSV output path.")
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_replication_log(
        args.anylogic,
        metrics=spec.metrics,
        anylogic_key_map=spec.anylogic_key_map,
        anylogic_parameter_key_map=spec.anylogic_parameter_key_map,
    )
    simpy_rows = load_simpy_replication_csv(args.simpy_runs, metrics=spec.metrics)
    if not anylogic_rows:
        raise SystemExit(f"No AnyLogic replication rows found: {args.anylogic}")
    if not simpy_rows:
        raise SystemExit(f"No SimPy replication rows found: {args.simpy_runs}")

    try:
        replication_limit = _parse_replication_limit(args.replications_per_iteration)
        anylogic_rows = limit_replications_per_iteration(
            anylogic_rows,
            replication_limit,
            label="AnyLogic",
        )
        simpy_rows = limit_replications_per_iteration(
            simpy_rows,
            replication_limit,
            label="SimPy",
        )
        expected_iterations = (
            args.expected_iterations
            if args.expected_iterations is not None and args.expected_iterations > 0
            else None
        )
        if expected_iterations is not None:
            validate_expected_iterations(
                anylogic_rows,
                expected_iterations,
                label="AnyLogic",
            )
            validate_expected_iterations(
                simpy_rows,
                expected_iterations,
                label="SimPy",
            )

        groups = compare_replication_sample_groups(
            anylogic_rows,
            simpy_rows,
            metrics=spec.metrics,
            metric_filter=args.metric,
            alpha=args.alpha,
            include_overall=args.comparison_scope in {"all", "overall"},
            include_iterations=args.comparison_scope in {"all", "iterations"},
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print_stochastic_group_report(
        spec.title,
        groups,
        alpha=args.alpha,
        show_iteration_details=args.show_iteration_details,
    )

    compared_replications = (
        "all" if replication_limit is None else str(replication_limit)
    )
    print(
        f"\nAnyLogic rows compared: {len(anylogic_rows)} from {args.anylogic}\n"
        f"SimPy rows compared: {len(simpy_rows)} from {args.simpy_runs}\n"
        f"Replications per iteration compared: {compared_replications}"
    )
    if args.output_csv:
        output_path = write_stochastic_comparison_groups_csv(groups, args.output_csv)
        print(f"Wrote CSV: {output_path}")


def _parse_replication_limit(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "all", "none"}:
        return None
    limit = int(text)
    if limit < 2:
        raise ValueError("replications-per-iteration must be at least 2")
    return limit


def limit_replications_per_iteration(
    rows: Iterable[ReplicationRow],
    limit: int | None,
    *,
    label: str,
) -> list[ReplicationRow]:
    rows_list = list(rows)
    if limit is None:
        return rows_list

    limited: list[ReplicationRow] = []
    grouped = _group_rows_by_iteration(rows_list)
    for iteration in sorted(grouped):
        iteration_rows = sorted(grouped[iteration], key=lambda row: row.replication)
        if len(iteration_rows) < limit:
            raise ValueError(
                f"{label} iteration {iteration} has {len(iteration_rows)} "
                f"replications, expected at least {limit}"
            )
        limited.extend(iteration_rows[:limit])
    return limited


def validate_expected_iterations(
    rows: Iterable[ReplicationRow],
    expected_iterations: int,
    *,
    label: str,
) -> None:
    actual_iterations = sorted(_group_rows_by_iteration(rows))
    if len(actual_iterations) != expected_iterations:
        raise ValueError(
            f"{label} has {len(actual_iterations)} stochastic iterations, "
            f"expected {expected_iterations}: "
            f"{_format_iteration_list(actual_iterations)}"
        )


def _welch_df(var_a: float, n_a: int, var_s: float, n_s: int) -> float:
    term_a = var_a / n_a
    term_s = var_s / n_s
    numerator = (term_a + term_s) ** 2
    denominator = 0.0
    if n_a > 1:
        denominator += (term_a**2) / (n_a - 1)
    if n_s > 1:
        denominator += (term_s**2) / (n_s - 1)
    return numerator / denominator if denominator else math.inf


def _two_sided_t_p_value(t_stat: float, df: float) -> float | None:
    try:
        from scipy import stats
    except ModuleNotFoundError:
        return None
    return float(2.0 * stats.t.sf(abs(t_stat), df))


def _t_critical(probability: float, df: float) -> float:
    try:
        from scipy import stats
    except ModuleNotFoundError:
        return 1.959963984540054
    return float(stats.t.ppf(probability, df))
