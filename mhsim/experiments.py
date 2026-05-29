from __future__ import annotations

import copy
import csv
import inspect
import math
import statistics
import sys
import time
from dataclasses import dataclass, field, is_dataclass, replace
from itertools import product
from numbers import Number
from pathlib import Path
from random import SystemRandom
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ExperimentIterationContext:
    """Context available while calculating parameter values for an iteration."""

    iteration_index: int
    iteration_number: int
    parameter_values: Mapping[str, Any]
    base_params: Any

    def get_current_iteration(self) -> int:
        """Return the current iteration index (0-based)."""
        return self.iteration_index


@dataclass(frozen=True)
class ExperimentRunContext(ExperimentIterationContext):
    """Context available while collecting outputs for a finished simulation run."""

    replication_index: int
    replication_number: int
    run_index: int
    run_number: int
    seed: int | None = None

    def get_current_replication(self) -> int:
        """Return the current replication index (0-based)."""
        return self.replication_index


MetricCollector = Callable[[ExperimentRunContext, Any, Any], Any]


@dataclass(frozen=True)
class RangeParameter:
    """Numeric parameter varied from start to stop using the given step."""

    name: str
    start: int | float
    stop: int | float
    step: int | float
    include_stop: bool = True

    def values(self) -> list[int | float]:
        if self.step == 0:
            raise ValueError(f"Range parameter '{self.name}' cannot use step=0")

        increasing = self.stop >= self.start
        if increasing and self.step < 0:
            raise ValueError(
                f"Range parameter '{self.name}' requires a positive step for an increasing range"
            )
        if not increasing and self.step > 0:
            raise ValueError(
                f"Range parameter '{self.name}' requires a negative step for a decreasing range"
            )

        integer_mode = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (self.start, self.stop, self.step)
        )
        tolerance = abs(float(self.step)) * 1e-12 + 1e-12
        compare = (
            (lambda value: value <= self.stop + tolerance)
            if self.step > 0
            else (lambda value: value >= self.stop - tolerance)
        )

        values: list[int | float] = []
        current = self.start
        while compare(current):
            value = int(current) if integer_mode else round(float(current), 12)
            values.append(value)
            current = self.start + (len(values) * self.step)

        if not self.include_stop and values:
            last = values[-1]
            if math.isclose(
                float(last),
                float(self.stop),
                rel_tol=0.0,
                abs_tol=tolerance,
            ):
                values.pop()

        if not values:
            raise ValueError(
                f"Range parameter '{self.name}' expands to no values: "
                f"start={self.start}, stop={self.stop}, step={self.step}"
            )
        return values


@dataclass(frozen=True)
class ChoiceParameter:
    """Discrete parameter varied over an explicit list of values."""

    name: str
    values_list: Sequence[Any]

    def values(self) -> list[Any]:
        values = list(self.values_list)
        if not values:
            raise ValueError(f"Choice parameter '{self.name}' must define at least one value")
        return values


@dataclass(frozen=True)
class RangeVariation:
    """
    Cartesian-product parameter variation, similar to AnyLogic's ranged mode.

    `fixed_parameters` may use constants, iteration-indexed sequences, or callables
    that receive `ExperimentIterationContext`.
    """

    parameters: Sequence[RangeParameter | ChoiceParameter] = field(default_factory=tuple)
    fixed_parameters: Mapping[str, Any] = field(default_factory=dict)

    def build_iterations(self, base_params: Any) -> list[dict[str, Any]]:
        dimensions = [(parameter.name, parameter.values()) for parameter in self.parameters]
        combinations = (
            product(*(values for _, values in dimensions))
            if dimensions
            else [()]
        )

        iterations: list[dict[str, Any]] = []
        for iteration_index, combination in enumerate(combinations):
            parameter_values = {
                name: value
                for (name, _), value in zip(dimensions, combination)
            }
            iterations.append(
                _resolve_iteration_values(
                    iteration_index=iteration_index,
                    base_params=base_params,
                    initial_values=parameter_values,
                    dynamic_values=self.fixed_parameters,
                )
            )
        return iterations


@dataclass(frozen=True)
class ParameterVariationRun:
    iteration_index: int
    iteration_number: int
    replication_index: int
    replication_number: int
    run_index: int
    run_number: int
    seed: int | None
    parameter_values: Mapping[str, Any]
    metrics: Mapping[str, Any]

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "iteration": self.iteration_number,
            "replication": self.replication_number,
            "run_number": self.run_number,
            "seed": self.seed,
        }
        for name, value in self.parameter_values.items():
            row[f"param_{name}"] = value
        for name, value in self.metrics.items():
            row[f"metric_{name}"] = value
        return row


@dataclass
class ParameterVariationResult:
    experiment_name: str | None
    runs: list[ParameterVariationRun]
    compact_numeric_summary: bool = False

    @property
    def total_iterations(self) -> int:
        return len({run.iteration_index for run in self.runs})

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    def run_rows(self) -> list[dict[str, Any]]:
        return [run.to_row() for run in self.runs]

    def iteration_rows(self) -> list[dict[str, Any]]:
        grouped: dict[int, list[ParameterVariationRun]] = {}
        for run in self.runs:
            grouped.setdefault(run.iteration_index, []).append(run)

        rows: list[dict[str, Any]] = []
        for iteration_index in sorted(grouped):
            iteration_runs = grouped[iteration_index]
            first_run = iteration_runs[0]
            row: dict[str, Any] = {
                "iteration": first_run.iteration_number,
                "replications": len(iteration_runs),
            }
            for name, value in first_run.parameter_values.items():
                row[f"param_{name}"] = value

            metric_names = {
                metric_name
                for run in iteration_runs
                for metric_name in run.metrics
            }
            for metric_name in sorted(metric_names):
                values = [
                    run.metrics[metric_name]
                    for run in iteration_runs
                    if metric_name in run.metrics
                ]
                if not values:
                    continue
                if _all_numeric(values):
                    if self.compact_numeric_summary and _all_values_equal(values):
                        row[f"metric_{metric_name}"] = values[0]
                    else:
                        row[f"metric_{metric_name}_mean"] = statistics.fmean(values)
                        row[f"metric_{metric_name}_min"] = min(values)
                        row[f"metric_{metric_name}_max"] = max(values)
                elif len(values) == 1 or all(value == values[0] for value in values):
                    row[f"metric_{metric_name}"] = values[0]
            rows.append(row)
        return rows

    def write_run_csv(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        _write_rows_csv(output, self.run_rows())
        return output

    def write_summary_csv(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        _write_rows_csv(output, self.iteration_rows())
        return output


@dataclass
class ParameterVariationExperiment:
    """
    Reusable runner for SimPy-style models with AnyLogic-inspired parameter variation.

    Supports:
    - ranged/cartesian iteration definitions
    - fixed replications per iteration
    - deterministic (`fixed`) or non-reproducible (`random`) seed assignment
    - per-run metric collection
    - CSV export via the returned `ParameterVariationResult`
    """

    base_params: Any
    variation: RangeVariation
    model_cls: type[Any] | None = None
    model_factory: Callable[[Any], Any] | None = None
    metrics: Mapping[str, MetricCollector] | None = None
    replications: int = 1
    random_seed_mode: str = "fixed"
    base_random_seed: int | None = None
    seed_field_name: str = "random_seed"
    run_until: float | None = None
    experiment_name: str | None = None
    compact_numeric_summary: bool = False

    def __post_init__(self) -> None:
        if self.model_cls is None and self.model_factory is None:
            raise ValueError("Provide either model_cls or model_factory")
        if self.model_cls is not None and self.model_factory is not None:
            raise ValueError("Provide model_cls or model_factory, not both")
        if self.replications < 1:
            raise ValueError("replications must be >= 1")
        if self.random_seed_mode not in {"fixed", "random"}:
            raise ValueError("random_seed_mode must be 'fixed' or 'random'")

    def run(self, *, verbose: bool = False) -> ParameterVariationResult:
        iteration_values = self.variation.build_iterations(self.base_params)
        total_iterations = len(iteration_values)
        system_random = SystemRandom()
        runs: list[ParameterVariationRun] = []
        t_start = time.monotonic()

        for iteration_index, values in enumerate(iteration_values):
            iteration_runs: list[ParameterVariationRun] = []
            for replication_index in range(self.replications):
                run_index = len(runs)
                parameter_values = dict(values)
                seed_is_explicit = self.seed_field_name in parameter_values
                seed = self._resolve_seed(
                    run_index=run_index,
                    parameter_values=parameter_values,
                    system_random=system_random,
                )
                output_parameter_values = dict(parameter_values)
                if not seed_is_explicit:
                    output_parameter_values.pop(self.seed_field_name, None)
                params = _clone_with_updates(self.base_params, parameter_values)
                model = self._build_model(params)
                stats = self._run_model(model)
                context = ExperimentRunContext(
                    iteration_index=iteration_index,
                    iteration_number=iteration_index + 1,
                    replication_index=replication_index,
                    replication_number=replication_index + 1,
                    run_index=run_index,
                    run_number=run_index + 1,
                    parameter_values=output_parameter_values,
                    base_params=self.base_params,
                    seed=seed,
                )
                metrics = self._collect_metrics(context, model, stats)
                run = ParameterVariationRun(
                    iteration_index=iteration_index,
                    iteration_number=iteration_index + 1,
                    replication_index=replication_index,
                    replication_number=replication_index + 1,
                    run_index=run_index,
                    run_number=run_index + 1,
                    seed=seed,
                    parameter_values=output_parameter_values,
                    metrics=metrics,
                )
                runs.append(run)
                iteration_runs.append(run)

            if verbose:
                _print_iteration_progress(
                    iteration_index=iteration_index,
                    total_iterations=total_iterations,
                    replications=self.replications,
                    iteration_runs=iteration_runs,
                    t_start=t_start,
                )

        return ParameterVariationResult(
            experiment_name=self.experiment_name,
            runs=runs,
            compact_numeric_summary=self.compact_numeric_summary,
        )

    def _resolve_seed(
        self,
        *,
        run_index: int,
        parameter_values: dict[str, Any],
        system_random: SystemRandom,
    ) -> int | None:
        if self.seed_field_name in parameter_values:
            return parameter_values[self.seed_field_name]

        if not _supports_attr(self.base_params, self.seed_field_name):
            return None

        if self.random_seed_mode == "fixed":
            base_seed = (
                self.base_random_seed
                if self.base_random_seed is not None
                else getattr(self.base_params, self.seed_field_name)
            )
            seed = int(base_seed) + run_index
        else:
            seed = system_random.randrange(1, 2**31)

        parameter_values[self.seed_field_name] = seed
        return seed

    def _build_model(self, params: Any) -> Any:
        if self.model_factory is not None:
            return self.model_factory(params)

        assert self.model_cls is not None
        kwargs: dict[str, Any] = {"params": params}
        signature = inspect.signature(self.model_cls)
        if "console_logging" in signature.parameters:
            kwargs["console_logging"] = False
        if "enable_logging" in signature.parameters:
            kwargs["enable_logging"] = False
        return self.model_cls(**kwargs)

    def _run_model(self, model: Any) -> Any:
        if self.run_until is None:
            return model.run()
        return model.run(until=self.run_until)

    def _collect_metrics(
        self,
        context: ExperimentRunContext,
        model: Any,
        stats: Any,
    ) -> dict[str, Any]:
        if not self.metrics:
            return _collect_default_metrics(stats)
        return {
            metric_name: collector(context, model, stats)
            for metric_name, collector in self.metrics.items()
        }


def attribute_metric(
    path: str,
    *,
    source: str = "model",
    transform: Callable[[Any], Any] | None = None,
) -> MetricCollector:
    if source not in {"model", "stats"}:
        raise ValueError("source must be 'model' or 'stats'")

    def collector(_: ExperimentRunContext, model: Any, stats: Any) -> Any:
        root = model if source == "model" else stats
        value = _resolve_path(root, path)
        if transform is not None:
            return transform(value)
        return value

    return collector


def model_attr_metric(
    path: str,
    *,
    transform: Callable[[Any], Any] | None = None,
) -> MetricCollector:
    return attribute_metric(path, source="model", transform=transform)


def stats_attr_metric(
    path: str,
    *,
    transform: Callable[[Any], Any] | None = None,
) -> MetricCollector:
    return attribute_metric(path, source="stats", transform=transform)


def throughput_per_hour_metric(
    *,
    completed_path: str = "completed",
    sim_time_path: str = "params.sim_time",
) -> MetricCollector:
    def collector(_: ExperimentRunContext, model: Any, stats: Any) -> float:
        completed = _resolve_path(stats, completed_path)
        sim_time = _resolve_path(model, sim_time_path)
        if not sim_time:
            return 0.0
        return (float(completed) / float(sim_time)) * 3600.0

    return collector


def _resolve_iteration_values(
    *,
    iteration_index: int,
    base_params: Any,
    initial_values: Mapping[str, Any],
    dynamic_values: Mapping[str, Any],
) -> dict[str, Any]:
    values = dict(initial_values)
    for name, provider in dynamic_values.items():
        context = ExperimentIterationContext(
            iteration_index=iteration_index,
            iteration_number=iteration_index + 1,
            parameter_values=values,
            base_params=base_params,
        )
        values[name] = _resolve_iteration_provider(provider, context)
    return values


def _resolve_iteration_provider(
    provider: Any,
    context: ExperimentIterationContext,
) -> Any:
    if callable(provider):
        return _call_provider(provider, context)
    if _is_indexed_sequence(provider):
        try:
            return provider[context.iteration_index]
        except IndexError as exc:
            raise IndexError(
                f"Provider sequence is missing a value for iteration {context.iteration_number}"
            ) from exc
    return provider


def _call_provider(provider: Callable[..., Any], context: ExperimentIterationContext) -> Any:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError):
        return provider(context)

    if not signature.parameters:
        return provider()
    return provider(context)


def _clone_with_updates(base_params: Any, updates: Mapping[str, Any]) -> Any:
    if is_dataclass(base_params) and not isinstance(base_params, type):
        return replace(base_params, **updates)

    cloned = copy.copy(base_params)
    for name, value in updates.items():
        if not hasattr(cloned, name):
            raise AttributeError(f"Parameter object has no attribute '{name}'")
        setattr(cloned, name, value)
    return cloned


def _collect_default_metrics(stats: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for name in ("created", "completed", "avg_time_in_system"):
        if hasattr(stats, name):
            metrics[name] = getattr(stats, name)
    return metrics


def _resolve_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current[part]
        else:
            current = getattr(current, part)
    return current


def _supports_attr(obj: Any, name: str) -> bool:
    if is_dataclass(obj) and not isinstance(obj, type):
        return any(field.name == name for field in obj.__dataclass_fields__.values())
    return hasattr(obj, name)


def _is_indexed_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _all_numeric(values: Sequence[Any]) -> bool:
    return all(isinstance(value, Number) and not isinstance(value, bool) for value in values)


def _all_values_equal(values: Sequence[Any]) -> bool:
    return len(values) <= 1 or all(value == values[0] for value in values)


def _print_iteration_progress(
    *,
    iteration_index: int,
    total_iterations: int,
    replications: int,
    iteration_runs: list[ParameterVariationRun],
    t_start: float,
) -> None:
    """Print a one-line iteration summary to stderr."""
    elapsed = time.monotonic() - t_start
    completed_iters = iteration_index + 1
    eta_s = (elapsed / completed_iters) * (total_iterations - completed_iters)

    # Parameter summary (skip internal fields like random_seed)
    _SKIP = {"random_seed", "replication"}
    params = iteration_runs[0].parameter_values if iteration_runs else {}
    param_str = "  ".join(
        f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}"
        for k, v in params.items()
        if k not in _SKIP
    )

    # Key metric means
    metric_parts: list[str] = []
    numeric_metrics: dict[str, list[float]] = {}
    for run in iteration_runs:
        for name, val in run.metrics.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                numeric_metrics.setdefault(name, []).append(float(val))
    _HIGHLIGHT = ["completed", "throughput_per_hour", "avg_time_in_system_s", "avg_wip"]
    for name in _HIGHLIGHT:
        if name in numeric_metrics:
            mean = statistics.fmean(numeric_metrics[name])
            if name in ("avg_time_in_system_s",):
                metric_parts.append(f"cycle={mean:.1f}s")
            elif name == "throughput_per_hour":
                metric_parts.append(f"tput={mean:.1f}/h")
            elif name == "avg_wip":
                metric_parts.append(f"wip={mean:.2f}")
            else:
                metric_parts.append(f"{name}={mean:.1f}")

    eta_str = f"ETA {eta_s:.0f}s" if eta_s > 0 else "done"
    metric_str = "  " + "  ".join(metric_parts) if metric_parts else ""
    print(
        f"[{completed_iters:>3}/{total_iterations}] {param_str}{metric_str}"
        f"  ({elapsed:.0f}s elapsed  {eta_str})",
        file=sys.stderr,
        flush=True,
    )


def _write_rows_csv(output_path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _ordered_fieldnames(rows)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _ordered_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    preferred = ["iteration", "replication", "run_number", "replications", "seed"]
    fieldnames: list[str] = []
    for name in preferred:
        if any(name in row for row in rows):
            fieldnames.append(name)
    for row in rows:
        for name in row:
            if name not in fieldnames:
                fieldnames.append(name)
    return fieldnames
