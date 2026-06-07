from __future__ import annotations

import argparse
import os
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
    workers: int = 1
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
    variation_factory: Callable[[], RangeVariation] = RangeVariation


def build_stochastic_replication_experiment(
    spec: StochasticReplicationSpec,
    options: StochasticReplicationOptions,
) -> ParameterVariationExperiment:
    return ParameterVariationExperiment(
        experiment_name=spec.experiment_name,
        model_cls=spec.model_cls,
        base_params=spec.params_factory(options),
        variation=spec.variation_factory(),
        metrics_factory=spec.metrics_factory,
        replications=options.replications,
        random_seed_mode="fixed",
        base_random_seed=options.base_random_seed,
        run_until=options.run_until,
        compact_numeric_summary=False,
        workers=options.workers,
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


def run_stochastic_replications_cli(
    spec: StochasticReplicationSpec,
    *,
    verbose: bool = False,
    summary_callback: Callable[[ParameterVariationResult], None] | None = None,
) -> None:
    """Standard argparse CLI entry point for per-model stochastic replication scripts."""
    parser = argparse.ArgumentParser(
        description=(
            f"Run stochastic {spec.model_name} replications and write per-run CSV output."
        )
    )
    parser.add_argument("--output-dir", default="logs")
    parser.add_argument("--run-until", type=float, default=spec.default_run_until_s)
    parser.add_argument("--replications", type=int, default=spec.default_replications)
    parser.add_argument("--base-seed", type=int, default=1)
    parser.add_argument(
        "--workers",
        default="1",
        help=(
            "Parallel worker processes to use. Use an integer or 'auto'. "
            "Default: 1 (sequential)."
        ),
    )
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

    workers = _parse_workers(args.workers)
    options = StochasticReplicationOptions(
        replications=args.replications,
        run_until=args.run_until,
        base_random_seed=args.base_seed,
        workers=workers,
        random_arrival_times=not args.deterministic_arrivals,
        random_service_times=not args.deterministic_services,
        arrival_time_distribution=args.arrival_distribution,
        service_time_distribution=args.service_distribution,
        service_time_triangular_spread=args.service_triangular_spread,
    )
    result = build_stochastic_replication_experiment(spec, options).run(verbose=verbose)
    run_csv, summary_csv = write_stochastic_replication_outputs(
        result, spec, output_dir=Path(args.output_dir)
    )
    if summary_callback is not None:
        summary_callback(result)
    print(f"Wrote run CSV: {run_csv}")
    print(f"Wrote summary CSV: {summary_csv}")


def _parse_workers(value: str) -> int:
    if value == "auto":
        return max(1, os.cpu_count() or 1)
    try:
        workers = int(value)
    except ValueError as exc:
        raise SystemExit("--workers must be a positive integer or 'auto'") from exc
    if workers < 1:
        raise SystemExit("--workers must be >= 1")
    return workers
