from __future__ import annotations

import argparse
from pathlib import Path

from mhsim.experiments import (
    ChoiceParameter,
    ParameterVariationExperiment,
    ParameterVariationResult,
    RangeVariation,
)
from mhsim.stochastic_replications import (
    StochasticReplicationOptions,
    StochasticReplicationSpec,
    build_stochastic_replication_experiment as _build_stochastic_replication_experiment,
    write_stochastic_replication_outputs,
)

from .model import Model5SimModel
from .params import Model5Params
from .run_parameter_variation import _metrics


DEFAULT_RUN_UNTIL_S = 18000.0
DEFAULT_REPLICATIONS = 50


def _params(options: StochasticReplicationOptions) -> Model5Params:
    return Model5Params(
        sim_time=(
            options.run_until
            if options.run_until is not None
            else DEFAULT_RUN_UNTIL_S
        ),
        random_arrival_times=options.random_arrival_times,
        random_service_times=options.random_service_times,
        arrival_time_distribution=options.arrival_time_distribution,
        service_time_distribution=options.service_time_distribution,
        service_time_triangular_spread=options.service_time_triangular_spread,
    )


def _variation() -> RangeVariation:
    # Match the three arrival-rate values used by SensitivityAnalysis in AnyLogic
    # Model 5 (arrival_rate_s = 96, 120, 144 → arrival_rate_per_min = 60/96, …).
    return RangeVariation(
        parameters=[
            ChoiceParameter("n_forklifts", [1, 2, 3, 4]),
            ChoiceParameter("delay_time_s", [180.0, 300.0, 420.0]),
            ChoiceParameter(
                "arrival_rate_per_min",
                [60.0 / 96.0, 60.0 / 120.0, 60.0 / 144.0],
            ),
        ],
    )


STOCHASTIC_REPLICATION_SPEC = StochasticReplicationSpec(
    model_name="Model 5",
    experiment_name="model_5_stochastic_replications",
    model_cls=Model5SimModel,
    params_factory=_params,
    metrics_factory=_metrics,
    default_run_until_s=DEFAULT_RUN_UNTIL_S,
    default_replications=DEFAULT_REPLICATIONS,
    runs_filename="model_5_stochastic_replications_runs.csv",
    summary_filename="model_5_stochastic_replications_summary.csv",
    variation_factory=_variation,
)


def build_stochastic_replication_experiment(
    *,
    replications: int = DEFAULT_REPLICATIONS,
    run_until: float | None = DEFAULT_RUN_UNTIL_S,
    base_random_seed: int = 1,
    random_arrival_times: bool = True,
    random_service_times: bool = True,
    arrival_time_distribution: str = "exponential",
    service_time_distribution: str = "triangular",
    service_time_triangular_spread: float = 0.5,
) -> ParameterVariationExperiment:
    return _build_stochastic_replication_experiment(
        STOCHASTIC_REPLICATION_SPEC,
        StochasticReplicationOptions(
            replications=replications,
            run_until=run_until,
            base_random_seed=base_random_seed,
            random_arrival_times=random_arrival_times,
            random_service_times=random_service_times,
            arrival_time_distribution=arrival_time_distribution,
            service_time_distribution=service_time_distribution,
            service_time_triangular_spread=service_time_triangular_spread,
        ),
    )


def _write_outputs(
    result: ParameterVariationResult,
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    return write_stochastic_replication_outputs(
        result,
        STOCHASTIC_REPLICATION_SPEC,
        output_dir=output_dir,
    )


def _metric(row: dict[str, object], name: str) -> float:
    return float(row[f"metric_{name}"])


def _print_summary(result: ParameterVariationResult) -> None:
    print("\n--- Model 5 Stochastic Replications ---")
    print(
        f"Iterations: {result.total_iterations}  "
        f"Replications/iteration: {len(result.runs) // result.total_iterations}  "
        f"Total runs: {result.total_runs}"
    )
    completed = [_metric(row, "completed") for row in result.run_rows()]
    avg_wip = [_metric(row, "avg_wip") for row in result.run_rows()]
    avg_cycle = [_metric(row, "avg_time_in_system_s") for row in result.run_rows()]
    throughput = [_metric(row, "throughput_per_hour") for row in result.run_rows()]
    print(
        f"completed range={min(completed):.0f}..{max(completed):.0f}  "
        f"avg_wip mean={sum(avg_wip) / len(avg_wip):.2f}  "
        f"avg_cycle mean={sum(avg_cycle) / len(avg_cycle):.2f}s  "
        f"throughput mean={sum(throughput) / len(throughput):.2f}/h"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stochastic Model 5 replications and write per-run CSV output."
    )
    parser.add_argument("--output-dir", default="logs")
    parser.add_argument(
        "--run-until",
        type=float,
        default=STOCHASTIC_REPLICATION_SPEC.default_run_until_s,
    )
    parser.add_argument(
        "--replications",
        type=int,
        default=STOCHASTIC_REPLICATION_SPEC.default_replications,
    )
    parser.add_argument("--base-seed", type=int, default=1)
    parser.add_argument(
        "--arrival-distribution",
        choices=("deterministic", "exponential", "triangular"),
        default="exponential",
    )
    parser.add_argument(
        "--service-distribution",
        choices=("deterministic", "exponential", "triangular"),
        default="triangular",
    )
    parser.add_argument("--service-triangular-spread", type=float, default=0.5)
    parser.add_argument(
        "--deterministic-arrivals",
        action="store_true",
        help="Keep arrivals deterministic while allowing stochastic services.",
    )
    parser.add_argument(
        "--deterministic-services",
        action="store_true",
        help="Keep services deterministic while allowing stochastic arrivals.",
    )
    args = parser.parse_args()

    result = build_stochastic_replication_experiment(
        replications=args.replications,
        run_until=args.run_until,
        base_random_seed=args.base_seed,
        random_arrival_times=not args.deterministic_arrivals,
        random_service_times=not args.deterministic_services,
        arrival_time_distribution=args.arrival_distribution,
        service_time_distribution=args.service_distribution,
        service_time_triangular_spread=args.service_triangular_spread,
    ).run(verbose=True)
    run_csv, summary_csv = _write_outputs(result, output_dir=Path(args.output_dir))
    _print_summary(result)
    print(f"Wrote run CSV: {run_csv}")
    print(f"Wrote summary CSV: {summary_csv}")


if __name__ == "__main__":
    main()
