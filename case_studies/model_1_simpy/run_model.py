from __future__ import annotations

from .model import Model1SimModel
from .params import Model1Params


def main():
    params = Model1Params()
    model = Model1SimModel(params=params, console_logging=True)
    stats = model.run()
    print("--- Model 1 (SimPy) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    print(f"Storage level at end: {model.storage.level}")


if __name__ == "__main__":
    main()
