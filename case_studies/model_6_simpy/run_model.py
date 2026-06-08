from __future__ import annotations

import argparse

from .model import Model6SimModel
from .params import Model6Params


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AnyLogic-mirrored SimPy Model 6.")
    parser.add_argument("--sim-time", type=float, default=None)
    args = parser.parse_args()

    params = Model6Params(sim_time=args.sim_time) if args.sim_time is not None else Model6Params()
    model = Model6SimModel(params=params, console_logging=True)
    stats = model.run()
    print("--- Model 6 (SimPy) ---")
    print(f"Simulated time: {model.env.now:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    print(f"Pallets in flight: {stats.created - stats.completed}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    avg_wip = (
        stats.avg_time_in_system * (stats.completed / model.env.now)
        if model.env.now
        else 0.0
    )
    print(f"Avg WIP: {avg_wip:.2f}")
    print(f"Throughput (/h): {(stats.completed / model.env.now) * 3600.0:.2f}")
    print(f"Main conveyor occupancy: {model.conveyor.occupancy}")
    print(f"Storage conveyor occupancy: {model.storage_conveyor.occupancy}")
    print(f"Empty pallets completed: {model.empty_pallets_completed}")
    print(f"Loose items created: {model.loose_items_created}")
    print(f"Batches created: {model.batch.batches_created}")


if __name__ == "__main__":
    main()

