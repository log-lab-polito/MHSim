from __future__ import annotations

import argparse
from pathlib import Path

from case_studies.model_1_simpy.reporting import build_forklift_movement_benchmark_rows
from mhsim.experiments import (
    ChoiceParameter,
    ParameterVariationExperiment,
    ParameterVariationResult,
    RangeVariation,
    model_attr_metric,
    stats_attr_metric,
)

from .compare_benchmark_results import (
    ANYLOGIC_BENCHMARK_KEY_MAP,
    BENCHMARK_STAT_FIELDS,
    BenchmarkStats,
)
from .model import Model6SimModel
from .params import Model6Params


def _build_benchmark_stats_map(stats: object) -> dict[str, BenchmarkStats]:
    cached = getattr(stats, "_model6_range_benchmark_cache", None)
    if cached is not None:
        return cached

    benchmarks: dict[str, BenchmarkStats] = {}
    for row in build_forklift_movement_benchmark_rows(stats):
        benchmarks[row["metric_key"]] = BenchmarkStats(
            average=float(row["avg_s"]),
            minimum=float(row["min_s"]),
            maximum=float(row["max_s"]),
            std_dev_pop=float(row["std_dev_s"]),
            count=int(row["count"]),
        )

    setattr(stats, "_model6_range_benchmark_cache", benchmarks)
    return benchmarks


def _benchmark_metric_name(metric_key: str, stat_field: str) -> str:
    return f"benchmark_{metric_key}__{stat_field}"


def _benchmark_metric(metric_key: str, stat_field: str):
    def collector(_ctx, _model, stats):
        benchmarks = _build_benchmark_stats_map(stats)
        benchmark = benchmarks.get(metric_key)
        if benchmark is None:
            raise KeyError(f"Missing benchmark '{metric_key}' in Model 6 run")
        return getattr(benchmark, stat_field)

    return collector


def _metrics():
    metrics = {
        "created": stats_attr_metric("created"),
        "completed": stats_attr_metric("completed"),
        "avg_time_in_system_s": stats_attr_metric("avg_time_in_system"),
        "in_flight": lambda _ctx, _model, stats: stats.created - stats.completed,
        "storage_level": lambda _ctx, model, _stats: int(model.get_storage_level()),
        "throughput_per_hour": lambda _ctx, model, stats: (
            (stats.completed / model.env.now) * 3600.0 if model.env.now else 0.0
        ),
        "forklift_utilization": model_attr_metric("fleet.utilization"),
    }
    benchmark_metric_keys = tuple(dict.fromkeys(ANYLOGIC_BENCHMARK_KEY_MAP.values()))
    for metric_key in benchmark_metric_keys:
        for stat_field, _stat_label in BENCHMARK_STAT_FIELDS:
            metrics[_benchmark_metric_name(metric_key, stat_field)] = _benchmark_metric(
                metric_key,
                stat_field,
            )
    return metrics


def build_range_validation_experiment(
    *,
    replications: int = 2,
    run_until: float | None = None,
) -> ParameterVariationExperiment:
    return ParameterVariationExperiment(
        experiment_name="model_6_range_validation",
        model_cls=Model6SimModel,
        base_params=Model6Params(),
        variation=RangeVariation(
            parameters=[
                ChoiceParameter("n_forklifts", [1, 2, 3, 4]),
                ChoiceParameter("delay_time_s", [180.0, 300.0, 420.0]),
                # AnyLogic Model 6 varies the interarrival time in seconds.
                ChoiceParameter(
                    "arrival_rate_per_min",
                    [
                        60.0 / 48.0,
                        60.0 / 60.0,
                        60.0 / 72.0,
                    ],
                ),
            ],
        ),
        metrics=_metrics(),
        replications=replications,
        random_seed_mode="fixed",
        base_random_seed=1,
        run_until=run_until,
        compact_numeric_summary=True,
    )


def _write_outputs(
    result: ParameterVariationResult,
    *,
    output_dir: Path,
    prefix: str,
) -> tuple[Path, Path]:
    runs_path = output_dir / f"{prefix}_runs.csv"
    summary_path = output_dir / f"{prefix}_summary.csv"
    result.write_run_csv(runs_path)
    result.write_summary_csv(summary_path)
    return runs_path, summary_path


def _format_number(value: float) -> str:
    formatted = f"{value:.2f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _print_summary(title: str, result: ParameterVariationResult) -> None:
    rows = result.iteration_rows()
    print(f"\n--- {title} ---")
    print(f"Iterations: {result.total_iterations}  Total runs: {result.total_runs}")
    for row in rows:
        arrival = row.get("param_arrival_rate_per_min", "")
        forklifts = row.get("param_n_forklifts", "")
        delay = row.get("param_delay_time_s", "")
        throughput = row.get(
            "metric_throughput_per_hour",
            row.get("metric_throughput_per_hour_mean"),
        )
        avg_cycle = row.get(
            "metric_avg_time_in_system_s",
            row.get("metric_avg_time_in_system_s_mean"),
        )
        forklift_utilization = row.get(
            "metric_forklift_utilization",
            row.get("metric_forklift_utilization_mean"),
        )
        parts = [f"iter={row['iteration']}"]
        if arrival != "":
            parts.append(f"arrival_per_min={arrival}")
            parts.append(f"arrival_s={_format_number(60.0 / float(arrival))}")
        if forklifts != "":
            parts.append(f"forklifts={forklifts}")
        if delay != "":
            parts.append(f"delay_s={delay}")
        if throughput is not None:
            parts.append(f"throughput/h={_format_number(throughput)}")
        if avg_cycle is not None:
            parts.append(f"avg_cycle_s={_format_number(avg_cycle)}")
        if forklift_utilization is not None:
            parts.append(f"forklift_util={_format_number(forklift_utilization)}")
        print("  ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Model 6 ranged parameter-variation validation experiment."
    )
    parser.add_argument(
        "--output-dir",
        default="logs",
        help="Directory where per-run and summary CSV files are written.",
    )
    parser.add_argument(
        "--run-until",
        type=float,
        default=None,
        help="Optional stop time override passed to model.run(until=...).",
    )
    parser.add_argument(
        "--range-replications",
        type=int,
        default=2,
        help="Replications per ranged iteration.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    range_result = build_range_validation_experiment(
        replications=args.range_replications,
        run_until=args.run_until,
    ).run()
    run_csv, summary_csv = _write_outputs(
        range_result,
        output_dir=output_dir,
        prefix="model_6_parameter_variation_range",
    )
    _print_summary("Model 6 Range Validation", range_result)
    print(f"Wrote run CSV: {run_csv}")
    print(f"Wrote summary CSV: {summary_csv}")


if __name__ == "__main__":
    main()
