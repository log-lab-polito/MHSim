from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .experiments import (
    MetricCollector,
    ParameterVariationExperiment,
    ParameterVariationResult,
    RangeVariation,
)


@dataclass(frozen=True)
class StochasticReplicationOptions:
    replications: int
    run_until: float | None
    base_random_seed: int = 1
    random_arrival_times: bool = True
    random_service_times: bool = True
    arrival_time_distribution: str = "exponential"
    service_time_distribution: str = "triangular"
    service_time_triangular_spread: float = 0.5


@dataclass(frozen=True)
class StochasticReplicationSpec:
    model_name: str
    experiment_name: str
    model_cls: type[Any]
    params_factory: Callable[[StochasticReplicationOptions], Any]
    metrics_factory: Callable[[], Mapping[str, MetricCollector]]
    default_run_until_s: float
    default_replications: int
    runs_filename: str
    summary_filename: str


def build_stochastic_replication_experiment(
    spec: StochasticReplicationSpec,
    options: StochasticReplicationOptions,
) -> ParameterVariationExperiment:
    return ParameterVariationExperiment(
        experiment_name=spec.experiment_name,
        model_cls=spec.model_cls,
        base_params=spec.params_factory(options),
        variation=RangeVariation(),
        metrics=spec.metrics_factory(),
        replications=options.replications,
        random_seed_mode="fixed",
        base_random_seed=options.base_random_seed,
        run_until=options.run_until,
        compact_numeric_summary=False,
    )


def write_stochastic_replication_outputs(
    result: ParameterVariationResult,
    spec: StochasticReplicationSpec,
    *,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    output = Path(output_dir)
    runs_path = output / spec.runs_filename
    summary_path = output / spec.summary_filename
    result.write_run_csv(runs_path)
    result.write_summary_csv(summary_path)
    return runs_path, summary_path
