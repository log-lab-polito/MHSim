from __future__ import annotations

from typing import Any

DEFAULT_BLOCK_MAPPING = [
    ("service1", "service1", "SERVICE1 (upstream)"),
    ("store", "store", "STORE"),
    ("delay", "delay", "DELAY"),
    ("retrieve", "retrieve", "RETRIEVE"),
    ("service2", "service2", "SERVICE2 (downstream)"),
]


def run_model_and_print_summary(
    *,
    model_cls: type[Any],
    params: Any,
    model_label: str,
    console_logging: bool = True,
):
    model = model_cls(params=params, console_logging=console_logging)
    stats = model.run()
    print(f"--- {model_label} (SimPy) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    print(f"Storage level at end: {model.storage.level}")
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
    model = model_cls(params=params, console_logging=console_logging)
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
    print(
        f"Storage: {model.storage.level}/{model.storage.capacity}  Avg cycle: {stats.avg_time_in_system:.2f}s"
    )
    print(f"Throughput: {throughput_per_hour:.1f} pallets/hour")
    print("=" * 78)

    return stats, model, block_stats
