from __future__ import annotations

import argparse
from pathlib import Path

from mhsim.experiments import (
    ParameterVariationExperiment,
    ParameterVariationResult,
    RangeVariation,
    stats_attr_metric,
)

from .model import Model4SimModel
from .params import Model4Params
from .range_config import range_variation_parameters


def _metrics():
    return {
        "created": stats_attr_metric("created"),
        "completed": stats_attr_metric("completed"),
        "avg_time_in_system_s": stats_attr_metric("avg_time_in_system"),
        "in_flight": lambda _ctx, _model, stats: stats.created - stats.completed,
        "throughput_per_hour": lambda _ctx, model, stats: (
            (stats.completed / model.env.now) * 3600.0 if model.env.now else 0.0
        ),
        "main_created": lambda _ctx, model, _stats: model.main_source.emitted_count,
        "branch_created": lambda _ctx, model, _stats: model.branch_source.emitted_count,
        "main_completed": lambda _ctx, model, _stats: model.sink.completed_by_origin.get(
            "main", 0
        ),
        "branch_completed": lambda _ctx, model, _stats: model.sink.completed_by_origin.get(
            "branch", 0
        ),
        "main_conveyor_entered": lambda _ctx, model, _stats: (
            model.main_conveyor.total_entered
        ),
        "main_conveyor_exited": lambda _ctx, model, _stats: (
            model.main_conveyor.total_exited
        ),
        "main_conveyor_occupancy_end": lambda _ctx, model, _stats: (
            model.main_conveyor.occupancy
        ),
        "branch_conveyor_entered": lambda _ctx, model, _stats: (
            model.branch_conveyor.total_entered
        ),
        "branch_conveyor_exited": lambda _ctx, model, _stats: (
            model.branch_conveyor.total_exited
        ),
        "branch_conveyor_occupancy_end": lambda _ctx, model, _stats: (
            model.branch_conveyor.occupancy
        ),
        "spur_transferred": lambda _ctx, model, _stats: model.spur.total_transferred,
        "spur_remaining_main_distance_m": lambda _ctx, model, _stats: (
            model.spur.remaining_target_distance_m()
        ),
    }


def build_range_validation_experiment(
    *,
    replications: int = 2,
    run_until: float | None = 3600.0,
) -> ParameterVariationExperiment:
    return ParameterVariationExperiment(
        experiment_name="model_4_range_validation",
        model_cls=Model4SimModel,
        base_params=Model4Params(sim_time=3600.0),
        variation=RangeVariation(
            parameters=range_variation_parameters(),
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
    return formatted.rstrip("0").rstrip(".")


def _print_summary(title: str, result: ParameterVariationResult) -> None:
    print(f"\n--- {title} ---")
    print(f"Iterations: {result.total_iterations}  Total runs: {result.total_runs}")
    for row in result.iteration_rows():
        parts = [f"iter={row['iteration']}"]
        for field_name, label in (
            ("param_main_arrival_time_s", "main_arrival_s"),
            ("param_branch_arrival_time_s", "branch_arrival_s"),
            ("param_conveyor_speed_mps", "speed"),
            ("param_conveyor_gap_m", "gap"),
            ("metric_throughput_per_hour", "throughput/h"),
            ("metric_avg_time_in_system_s", "avg_cycle_s"),
            ("metric_spur_transferred", "spur"),
        ):
            value = row.get(field_name, row.get(f"{field_name}_mean"))
            if value != "" and value is not None:
                parts.append(f"{label}={_format_number(float(value))}")
        print("  ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Model 4 ranged parameter-variation experiment."
    )
    parser.add_argument(
        "--output-dir",
        default="logs",
        help="Directory where per-run and summary CSV files are written.",
    )
    parser.add_argument(
        "--run-until",
        type=float,
        default=3600.0,
        help="Optional stop time override passed to model.run(until=...).",
    )
    parser.add_argument(
        "--range-replications",
        type=int,
        default=2,
        help="Replications per ranged iteration.",
    )
    args = parser.parse_args()

    range_result = build_range_validation_experiment(
        replications=args.range_replications,
        run_until=args.run_until,
    ).run()
    run_csv, summary_csv = _write_outputs(
        range_result,
        output_dir=Path(args.output_dir),
        prefix="model_4_parameter_variation_range",
    )
    _print_summary("Model 4 Range Validation", range_result)
    print(f"Wrote run CSV: {run_csv}")
    print(f"Wrote summary CSV: {summary_csv}")


if __name__ == "__main__":
    main()
