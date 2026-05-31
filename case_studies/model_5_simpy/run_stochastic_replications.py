from __future__ import annotations

from mhsim.experiments import ChoiceParameter, RangeVariation
from mhsim.stochastic_replications import (
    StochasticReplicationOptions,
    StochasticReplicationSpec,
    run_stochastic_replications_cli,
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


def _metric(row: dict[str, object], name: str) -> float:
    return float(row[f"metric_{name}"])


def _print_summary(result) -> None:
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
    run_stochastic_replications_cli(
        STOCHASTIC_REPLICATION_SPEC, verbose=True, summary_callback=_print_summary
    )


if __name__ == "__main__":
    main()
