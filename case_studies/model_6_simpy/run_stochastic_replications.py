from __future__ import annotations

from mhsim.experiments import RangeVariation
from mhsim.stochastic_replications import (
    StochasticReplicationOptions,
    StochasticReplicationSpec,
    run_stochastic_replications_cli,
)

from .anylogic_range import fixed_range_parameters, range_variation_parameters
from .model import Model6SimModel
from .params import Model6Params
from .run_parameter_variation import _metrics


DEFAULT_RUN_UNTIL_S = 3600.0
DEFAULT_REPLICATIONS = 50


def _params(options: StochasticReplicationOptions) -> Model6Params:
    return Model6Params(
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
    return RangeVariation(
        parameters=range_variation_parameters(),
        fixed_parameters=fixed_range_parameters(),
    )


STOCHASTIC_REPLICATION_SPEC = StochasticReplicationSpec(
    model_name="Model 6",
    experiment_name="model_6_stochastic_replications",
    model_cls=Model6SimModel,
    params_factory=_params,
    metrics_factory=_metrics,
    default_run_until_s=DEFAULT_RUN_UNTIL_S,
    default_replications=DEFAULT_REPLICATIONS,
    runs_filename="model_6_stochastic_replications_runs.csv",
    summary_filename="model_6_stochastic_replications_summary.csv",
    variation_factory=_variation,
)


def _metric(row: dict[str, object], name: str) -> float:
    return float(row[f"metric_{name}"])


def _print_summary(result) -> None:
    print("\n--- Model 6 Stochastic Replications ---")
    print(
        f"Iterations: {result.total_iterations}  "
        f"Replications/iteration: {len(result.runs) // result.total_iterations}  "
        f"Total runs: {result.total_runs}"
    )
    completed = [_metric(row, "completed") for row in result.run_rows()]
    avg_cycle = [_metric(row, "avg_time_in_system_s") for row in result.run_rows()]
    throughput = [_metric(row, "throughput_per_hour") for row in result.run_rows()]
    print(
        f"completed range={min(completed):.0f}..{max(completed):.0f}  "
        f"avg_cycle mean={sum(avg_cycle) / len(avg_cycle):.2f}s  "
        f"throughput mean={sum(throughput) / len(throughput):.2f}/h"
    )


def main() -> None:
    run_stochastic_replications_cli(
        STOCHASTIC_REPLICATION_SPEC,
        verbose=True,
        summary_callback=_print_summary,
    )


if __name__ == "__main__":
    main()
