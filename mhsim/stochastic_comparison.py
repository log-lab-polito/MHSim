from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from dataclasses import dataclass
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
class StochasticComparisonSpec:
    title: str
    description: str
    metrics: Sequence[MetricSpec]
    anylogic_key_map: Mapping[str, str]
    default_anylogic_path: str
    default_simpy_runs_path: str


def parse_anylogic_replication_log(
    path: str | Path,
    *,
    metrics: Sequence[MetricSpec],
    anylogic_key_map: Mapping[str, str],
) -> list[ReplicationRow]:
    iteration_re = re.compile(
        r"^ITERATION #(?P<iteration>\d+)(?:,\s*REPLICATION #(?P<replication>\d+))?\s*$"
    )
    key_value_re = re.compile(r"^\s*([^:]+):\s*(.+?)\s*$")
    metric_names = [metric.name for metric in metrics]
    rows: list[ReplicationRow] = []
    current_iteration: int | None = None
    current_replication: int | None = None
    current_values: dict[str, float] = {}
    next_replication_by_iteration: dict[int, int] = {}

    def finalize_current() -> None:
        nonlocal current_iteration, current_replication, current_values
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
            )
        )
        next_replication_by_iteration[current_iteration] = current_replication + 1
        current_iteration = None
        current_replication = None
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
                continue

            if current_iteration is None or not stripped:
                continue
            if stripped in {"PARAMETERS", "RESULTS"}:
                continue

            key_value_match = key_value_re.match(line)
            if key_value_match is None:
                continue
            raw_key, raw_value = key_value_match.groups()
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
            rows.append(
                ReplicationRow(
                    iteration=int(record["iteration"]),
                    replication=int(record["replication"]),
                    metrics={
                        metric.name: float(record[f"metric_{metric.name}"])
                        for metric in metrics
                    },
                )
            )
    return rows


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
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--output-csv", help="Optional CSV output path.")
    args = parser.parse_args()

    anylogic_rows = parse_anylogic_replication_log(
        args.anylogic,
        metrics=spec.metrics,
        anylogic_key_map=spec.anylogic_key_map,
    )
    simpy_rows = load_simpy_replication_csv(args.simpy_runs, metrics=spec.metrics)
    if not anylogic_rows:
        raise SystemExit(f"No AnyLogic replication rows found: {args.anylogic}")
    if not simpy_rows:
        raise SystemExit(f"No SimPy replication rows found: {args.simpy_runs}")

    try:
        comparisons = compare_replication_samples(
            anylogic_rows,
            simpy_rows,
            metrics=spec.metrics,
            metric_filter=args.metric,
            alpha=args.alpha,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print_stochastic_comparison_report(spec.title, comparisons, alpha=args.alpha)

    print(
        f"\nAnyLogic rows: {len(anylogic_rows)} from {args.anylogic}\n"
        f"SimPy rows: {len(simpy_rows)} from {args.simpy_runs}"
    )
    if args.output_csv:
        output_path = write_stochastic_comparison_csv(comparisons, args.output_csv)
        print(f"Wrote CSV: {output_path}")


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
