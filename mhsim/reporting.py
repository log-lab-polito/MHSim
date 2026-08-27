"""Console and CSV reporting helpers shared by the case-study run scripts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .stats import FORKLIFT_MOVEMENT_BENCHMARK_LABELS

DEFAULT_BLOCK_MAPPING = [
    ("service1", "service1", "SERVICE1 (upstream)"),
    ("store", "store", "STORE"),
    ("delay", "delay", "DELAY"),
    ("retrieve", "retrieve", "RETRIEVE"),
    ("service2", "service2", "SERVICE2 (downstream)"),
]


def resolve_model_storage_level(model: Any) -> int | float | None:
    """Read a model's end-of-run storage level, whatever shape it exposes.

    Tries `model.get_storage_level()` first, then `model.storage.level`,
    so warehouse models with a computed level and those holding a plain SimPy
    container both work without the caller knowing which.

    Args:
        model: A model instance, duck-typed.

    Returns:
        The storage level, or `None` if the model does not track one.
    """
    getter = getattr(model, "get_storage_level", None)
    if callable(getter):
        return getter()

    storage = getattr(model, "storage", None)
    if storage is not None and hasattr(storage, "level"):
        return storage.level

    return None


def build_forklift_movement_benchmark_rows(stats: Any) -> list[dict[str, Any]]:
    """Flatten forklift movement summaries into printable, writable rows.

    Args:
        stats: A stats object. Must expose `forklift_movement_summaries()`
            to produce anything; may also expose
            `forklift_movement_benchmark_labels` to override or extend the
            shared labels.

    Returns:
        One row per metric that collected samples, each with `metric_key`,
        `metric`, `count`, `avg_s`, `min_s`, `max_s`, and
        `std_dev_s`. Known metrics come first in label order, then any
        model-specific ones. Returns an empty list for stats that do not track
        movement phases, so callers need not branch on model type.
    """
    summaries_fn = getattr(stats, "forklift_movement_summaries", None)
    if not callable(summaries_fn):
        return []

    summaries = summaries_fn()
    labels = {
        **FORKLIFT_MOVEMENT_BENCHMARK_LABELS,
        **getattr(stats, "forklift_movement_benchmark_labels", {}),
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for metric_name, label in labels.items():
        summary = summaries.get(metric_name)
        seen.add(metric_name)
        if summary is None:
            continue
        rows.append(
            {
                "metric_key": metric_name,
                "metric": label,
                "count": summary.count,
                "avg_s": summary.average,
                "min_s": summary.minimum,
                "max_s": summary.maximum,
                "std_dev_s": summary.std_dev,
            }
        )

    for metric_name, summary in summaries.items():
        if metric_name in seen:
            continue
        rows.append(
            {
                "metric_key": metric_name,
                "metric": metric_name,
                "count": summary.count,
                "avg_s": summary.average,
                "min_s": summary.minimum,
                "max_s": summary.maximum,
                "std_dev_s": summary.std_dev,
            }
        )

    return rows


def print_forklift_movement_benchmarks(stats: Any) -> None:
    """Print the forklift movement benchmark table to stdout.

    Prints nothing at all when no samples were collected, rather than an empty
    table.

    Args:
        stats: A stats object, as accepted by
            `build_forklift_movement_benchmark_rows`.
    """
    rows = build_forklift_movement_benchmark_rows(stats)
    if not rows:
        return

    print("\nForklift movement benchmarks:")
    print(
        f"{'Metric':<54} {'Count':>7} {'Avg (s)':>10} {'Min (s)':>10} "
        f"{'Max (s)':>10} {'Std (s)':>10}"
    )
    print("-" * 108)
    for row in rows:
        print(
            f"{row['metric']:<54} {row['count']:>7} {row['avg_s']:>10.2f} "
            f"{row['min_s']:>10.2f} {row['max_s']:>10.2f} {row['std_dev_s']:>10.2f}"
        )


def print_traffic_wait_summary(stats: Any) -> None:
    """Print accumulated traffic waits to stdout, one row per reason.

    Prints nothing when the model recorded no waits.

    Args:
        stats: A stats object exposing `traffic_wait_summaries()`.
    """
    summaries_fn = getattr(stats, "traffic_wait_summaries", None)
    if not callable(summaries_fn):
        return

    summaries = summaries_fn()
    if not summaries:
        return

    print("\nTraffic waits:")
    print(f"{'Reason':<22} {'Count':>7} {'Total (s)':>12} {'Avg (s)':>10}")
    print("-" * 56)
    for reason, summary in sorted(summaries.items()):
        print(
            f"{reason:<22} {summary.count:>7} {summary.total_s:>12.2f} {summary.average_s:>10.2f}"
        )


def write_forklift_movement_benchmark_csv(
    stats: Any,
    output_path: str | Path,
) -> Path:
    """Write the forklift movement benchmarks to a CSV file.

    Args:
        stats: A stats object, as accepted by
            `build_forklift_movement_benchmark_rows`.
        output_path: Destination file. Parent directories are created.

    Returns:
        The resolved output path. A stats object with no movement samples
        still produces a valid header-only file.
    """
    rows = build_forklift_movement_benchmark_rows(stats)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "metric_key",
                "metric",
                "count",
                "avg_s",
                "min_s",
                "max_s",
                "std_dev_s",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return output


def run_model_and_print_summary(
    *,
    model_cls: type[Any],
    params: Any,
    model_label: str,
    console_logging: bool = True,
    include_forklift_benchmarks: bool = False,
    include_forklift_utilization: bool = False,
    include_in_flight: bool = False,
    include_avg_wip: bool = False,
    storage_level_label: str = "Storage level at end",
    **model_kwargs: Any,
) -> tuple[Any, Any]:
    """Construct a model, run it, and print the standard console summary.

    This is the shared body of the case-study `run_model` entry points, so
    every model reports the same core metrics in the same order.

    Args:
        model_cls: Model class to instantiate.
        params: Parameter record passed to the model.
        model_label: Name shown in the summary header.
        console_logging: Forwarded to the model to enable per-event tracing.
        include_forklift_benchmarks: Also print the movement-phase table.
        include_forklift_utilization: Also print `model.fleet.utilization`,
            skipped silently if the model has no fleet.
        include_in_flight: Also print entities created but not yet completed.
        include_avg_wip: Also print average work in progress, derived from
            Little's law as average time in system times throughput.
        storage_level_label: Caption for the storage level line, which is
            omitted entirely when the model tracks no storage.
        **model_kwargs: Extra keyword arguments forwarded to `model_cls`.

    Returns:
        A `(stats, model)` tuple, so callers can write CSVs or run further
        comparisons against the same run.
    """
    model = model_cls(
        params=params,
        console_logging=console_logging,
        **model_kwargs,
    )
    stats = model.run()
    print(f"--- {model_label} (SimPy) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    if include_in_flight:
        print(f"Pallets in flight: {stats.created - stats.completed}")
    if include_avg_wip:
        avg_wip = (
            stats.avg_time_in_system * (stats.completed / model.env.now)
            if model.env.now else 0.0
        )
        print(f"Avg WIP: {avg_wip:.2f}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    storage_level = resolve_model_storage_level(model)
    if storage_level is not None:
        print(f"{storage_level_label}: {storage_level}")
    if include_forklift_utilization:
        fleet = getattr(model, "fleet", None)
        utilization = getattr(fleet, "utilization", None)
        if utilization is not None:
            print(f"Forklifts utilization (%): {utilization:.6f}")
    if include_forklift_benchmarks:
        print_forklift_movement_benchmarks(stats)
    print_traffic_wait_summary(stats)
    return stats, model


