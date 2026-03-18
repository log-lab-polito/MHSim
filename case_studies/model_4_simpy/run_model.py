from __future__ import annotations

from .model import Model4SimModel
from .params import Model4Params


def main():
    params = Model4Params()
    model = Model4SimModel(params=params, console_logging=True)
    stats = model.run()

    print("--- Model 4 (SimPy Conveyor Spur Test) ---")
    print(f"Simulated time: {params.sim_time:.1f} s")
    print(
        f"Pallets created: total={stats.created} "
        f"main={model.main_source.emitted_count} "
        f"branch={model.branch_source.emitted_count}"
    )
    print(f"Pallets completed: {stats.completed}")
    print(
        "Completed by origin: "
        f"main={model.sink.completed_by_origin.get('main', 0)} "
        f"branch={model.sink.completed_by_origin.get('branch', 0)}"
    )
    print(f"Average time in system: {stats.avg_time_in_system:.2f} s")
    print(
        "Main conveyor: "
        f"entered={model.main_conveyor.total_entered} "
        f"exited={model.main_conveyor.total_exited} "
        f"occupancy_end={model.main_conveyor.occupancy}"
    )
    print(
        "Branch conveyor: "
        f"entered={model.branch_conveyor.total_entered} "
        f"exited={model.branch_conveyor.total_exited} "
        f"occupancy_end={model.branch_conveyor.occupancy}"
    )
    print(
        "Spur: "
        f"transferred={model.spur.total_transferred} "
        f"remaining_main_distance={model.spur.remaining_target_distance_m():.2f} m"
    )


if __name__ == "__main__":
    main()
