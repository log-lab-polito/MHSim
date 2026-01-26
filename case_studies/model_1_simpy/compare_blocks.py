#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 1.
"""

from __future__ import annotations

from .model import Model1SimModel
from .params import Model1Params

ANYLOGIC_BLOCKS = {
    "source": 181,
    "service1": 180,  # upstream service
    "store": 126,
    "delay": 124,
    "retrieve": 87,
    "service2": 87,  # downstream service
    "sink": 87,
}

BLOCK_MAPPING = [
    ("service1", "service1", "SERVICE1 (upstream)"),
    ("store", "store", "STORE"),
    ("delay", "delay", "DELAY"),
    ("retrieve", "retrieve", "RETRIEVE"),
    ("service2", "service2", "SERVICE2 (downstream)"),
]


def _status(pct: float) -> str:
    if pct < 1:
        return "MATCH"
    if pct < 2:
        return "CLOSE"
    return "DIFF"


def compare_blocks(params: Model1Params | None = None):
    """Run the model and compare block finished counts with AnyLogic reference."""
    if params is None:
        params = Model1Params()

    model = Model1SimModel(params=params, console_logging=False)
    stats = model.run()
    block_stats = {}
    for name, _, _ in BLOCK_MAPPING:
        block = getattr(model, name)
        block_stats[name] = {
            "entries": getattr(block, "entered_count", 0),
            "exits": getattr(block, "finished_count",
                             getattr(block, "completed_count", 0)),
        }

    print("\n" + "=" * 78)
    print("BLOCK COMPARISON: ANYLOGIC vs SIMPY")
    print("=" * 78)
    print(f"{'BLOCK':<22} {'ANYLOGIC':<10} {'SIMPY':<10} {'DIFF':<8} {'%':<8} {'STATUS':<8}")
    print("-" * 78)

    def row(label: str, anylogic: int, simpy: int):
        diff = simpy - anylogic
        pct = (abs(diff) / anylogic * 100) if anylogic else 0.0
        status = _status(pct)
        print(
            f"{label:<22} {anylogic:<10} {simpy:<10} {diff:+7} {pct:>6.1f}% {status:<8}"
        )

    row("SOURCE (created)", ANYLOGIC_BLOCKS["source"], stats.created)
    for simpy_name, anylogic_name, label in BLOCK_MAPPING:
        row(label, ANYLOGIC_BLOCKS[anylogic_name],
            block_stats[simpy_name]["exits"])
    row("SINK (completed)", ANYLOGIC_BLOCKS["sink"], stats.completed)

    print("-" * 78)
    in_flight = stats.created - stats.completed
    throughput_per_hour = (stats.completed / params.sim_time) * 3600
    print(
        f"Created: {stats.created}  Completed: {stats.completed}  In-flight: {in_flight}")
    print(
        f"Storage: {model.storage.level}/{model.storage.capacity}  Avg cycle: {stats.avg_time_in_system:.2f}s"
    )
    print(f"Throughput: {throughput_per_hour:.1f} pallets/hour")
    print("=" * 78)

    return stats, model, block_stats


if __name__ == "__main__":
    compare_blocks()
