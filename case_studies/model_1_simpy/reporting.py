from __future__ import annotations

import csv
import inspect
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


def build_forklift_movement_benchmark_rows(stats: Any) -> list[dict[str, Any]]:
    summaries_fn = getattr(stats, "forklift_movement_summaries", None)
    if not callable(summaries_fn):
        return []

    summaries = summaries_fn()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for metric_name, label in FORKLIFT_MOVEMENT_BENCHMARK_LABELS.items():
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


def write_forklift_movement_benchmark_csv(
    stats: Any,
    output_path: str | Path,
) -> Path:
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
):
    model = model_cls(params=params, console_logging=console_logging)
    stats = model.run()
    print(f"--- {model_label} (SimPy) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    print(f"Storage level at end: {model.storage.level}")
    if include_forklift_utilization:
        fleet = getattr(model, "fleet", None)
        utilization = getattr(fleet, "utilization", None)
        if utilization is not None:
            print(f"Forklifts utilization (%): {utilization:.6f}")
    if include_forklift_benchmarks:
        print_forklift_movement_benchmarks(stats)
    return stats, model


def _status(pct: float) -> str:
    if pct < 1:
        return "MATCH"
    if pct < 2:
        return "CLOSE"
    return "DIFF"


def compare_blocks_with_anylogic(
    *,
    model_cls: type[Any],
    params: Any,
    anylogic_blocks: dict[str, int],
    block_mapping: list[tuple[str, str, str]] | None = None,
    console_logging: bool = False,
):
    mapping = block_mapping or DEFAULT_BLOCK_MAPPING
    model_kwargs = {
        "params": params,
        "console_logging": console_logging,
    }
    if "enable_logging" in inspect.signature(model_cls).parameters:
        model_kwargs["enable_logging"] = False
    model = model_cls(**model_kwargs)
    stats = model.run()
    block_stats = {}
    for name, _, _ in mapping:
        block = getattr(model, name)
        block_stats[name] = {
            "entries": getattr(block, "entered_count", 0),
            "exits": getattr(
                block, "finished_count", getattr(block, "completed_count", 0)
            ),
        }

    print("\n" + "=" * 78)
    print("BLOCK COMPARISON: ANYLOGIC vs SIMPY")
    print("=" * 78)
    print(
        f"{'BLOCK':<22} {'ANYLOGIC':<10} {'SIMPY':<10} {'DIFF':<8} {'%':<8} {'STATUS':<8}"
    )
    print("-" * 78)

    def row(label: str, anylogic: int, simpy: int):
        diff = simpy - anylogic
        pct = (abs(diff) / anylogic * 100) if anylogic else 0.0
        status = _status(pct)
        print(
            f"{label:<22} {anylogic:<10} {simpy:<10} {diff:+7} {pct:>6.1f}% {status:<8}"
        )

    row("SOURCE (created)", anylogic_blocks["source"], stats.created)
    for simpy_name, anylogic_name, label in mapping:
        row(label, anylogic_blocks[anylogic_name], block_stats[simpy_name]["exits"])
    row("SINK (completed)", anylogic_blocks["sink"], stats.completed)

    print("-" * 78)
    in_flight = stats.created - stats.completed
    throughput_per_hour = (stats.completed / params.sim_time) * 3600
    print(f"Created: {stats.created}  Completed: {stats.completed}  In-flight: {in_flight}")
    summary_parts = [f"Avg cycle: {stats.avg_time_in_system:.2f}s"]

    storage = getattr(model, "storage", None)
    if storage is not None and hasattr(storage, "level") and hasattr(storage, "capacity"):
        summary_parts.insert(0, f"Storage: {storage.level}/{storage.capacity}")

    conveyor = getattr(model, "conveyor", None)
    if conveyor is not None and hasattr(conveyor, "occupancy"):
        capacity = getattr(conveyor, "max_items", "?")
        summary_parts.insert(0, f"Conveyor occ: {conveyor.occupancy}/{capacity}")

    print("  ".join(summary_parts))
    print(f"Throughput: {throughput_per_hour:.1f} pallets/hour")
    print("=" * 78)

    return stats, model, block_stats
