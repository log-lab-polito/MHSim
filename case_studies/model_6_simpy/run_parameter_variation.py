from __future__ import annotations

import argparse
from pathlib import Path

from mhsim.experiments import (
    ParameterVariationExperiment,
    ParameterVariationResult,
    RangeVariation,
    stats_attr_metric,
)

from .anylogic_range import fixed_range_parameters, range_variation_parameters
from .model import Model6SimModel
from .params import Model6Params


def _metrics():
    return {
        "created": stats_attr_metric("created"),
        "completed": stats_attr_metric("completed"),
        "avg_time_in_system_s": stats_attr_metric("avg_time_in_system"),
        "avg_wip": lambda _ctx, model, stats: (
            stats.avg_time_in_system * (stats.completed / model.env.now)
            if model.env.now
            else 0.0
        ),
        "throughput_per_hour": lambda _ctx, model, stats: (
            (stats.completed / model.env.now) * 3600.0 if model.env.now else 0.0
        ),
        "main_conveyor_occupancy_end": lambda _ctx, model, _stats: model.conveyor.occupancy,
        "storage_conveyor_occupancy_end": lambda _ctx, model, _stats: model.storage_conveyor.occupancy,
        "empty_pallets_completed": lambda _ctx, model, _stats: model.empty_pallets_completed,
        "loose_items_created": lambda _ctx, model, _stats: model.loose_items_created,
        "batches_created": lambda _ctx, model, _stats: model.batch.batches_created,
    }


def build_range_validation_experiment(
    *,
    replications: int = 2,
    run_until: float | None = 3600.0,
) -> ParameterVariationExperiment:
    return ParameterVariationExperiment(
        experiment_name="model_6_range_validation",
        model_cls=Model6SimModel,
        base_params=Model6Params(sim_time=run_until or 3600.0),
        variation=RangeVariation(
            parameters=range_variation_parameters(),
            fixed_parameters=fixed_range_parameters(),
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
            ("param_arrival_rate_s", "arrival_s"),
            ("param_conveyor_speed_mps", "speed"),
            ("param_conveyor_gap_m", "gap"),
            ("param_max_items_per_pallet", "max_items"),
            ("metric_completed", "completed"),
            ("metric_throughput_per_hour", "throughput/h"),
            ("metric_avg_time_in_system_s", "avg_cycle_s"),
        ):
            value = row.get(field_name, row.get(f"{field_name}_mean"))
            if value != "" and value is not None:
                parts.append(f"{label}={_format_number(float(value))}")
        print("  ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Model 6 ranged parameter-variation validation experiment."
    )
    parser.add_argument("--output-dir", default="logs")
    parser.add_argument("--run-until", type=float, default=3600.0)
    parser.add_argument("--range-replications", type=int, default=2)
    args = parser.parse_args()

    range_result = build_range_validation_experiment(
        replications=args.range_replications,
        run_until=args.run_until,
    ).run()
    run_csv, summary_csv = _write_outputs(
        range_result,
        output_dir=Path(args.output_dir),
        prefix="model_6_parameter_variation_range",
    )
    _print_summary("Model 6 Range Validation", range_result)
    print(f"Wrote run CSV: {run_csv}")
    print(f"Wrote summary CSV: {summary_csv}")


if __name__ == "__main__":
    main()
