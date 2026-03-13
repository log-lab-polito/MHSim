from __future__ import annotations

from .model import Model3SimModel
from .params import Model3Params


def main():
    params = Model3Params()
    model = Model3SimModel(params=params, console_logging=True)
    stats = model.run()

    print("--- Model 3 (SimPy Conveyor Test) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(f"Pallets created: {stats.created}")
    print(f"Pallets completed: {stats.completed}")
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    print(
        "Conveyor: "
        f"entered={model.conveyor.total_entered} "
        f"exited={model.conveyor.total_exited} "
        f"occupancy_end={model.conveyor.occupancy}"
    )


if __name__ == "__main__":
    main()
