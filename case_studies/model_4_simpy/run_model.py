from __future__ import annotations

import argparse
from pathlib import Path

from case_studies.model_5_simpy.reporting import run_model_and_print_summary

from .model import Model4SimModel
from .params import Model4Params


def main():
    parser = argparse.ArgumentParser(
        description="Run Model 4 and print conveyor spur summary stats."
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Optional simulation stop time override in seconds.",
    )
    parser.add_argument(
        "--main-arrival-time-s",
        type=float,
        default=None,
        help="Override the main source interarrival time in seconds.",
    )
    parser.add_argument(
        "--branch-arrival-time-s",
        type=float,
        default=None,
        help="Override the branch source interarrival time in seconds.",
    )
    parser.add_argument(
        "--conveyor-speed-mps",
        type=float,
        default=None,
        help="Override the conveyor speed in m/s.",
    )
    parser.add_argument(
        "--conveyor-gap-m",
        type=float,
        default=None,
        help="Override the conveyor minimum gap in meters.",
    )
    parser.add_argument(
        "--trace-csv",
        default=None,
        help="Optional CSV path for detailed Model 4 event trace output.",
    )
    args = parser.parse_args()

    params = Model4Params()
    if args.sim_time is not None:
        params.sim_time = args.sim_time
    for attr_name in (
        "main_arrival_time_s",
        "branch_arrival_time_s",
        "conveyor_speed_mps",
        "conveyor_gap_m",
    ):
        value = getattr(args, attr_name)
        if value is not None:
            setattr(params, attr_name, value)

    trace_path = Path(args.trace_csv) if args.trace_csv else None

    stats, model = run_model_and_print_summary(
        model_cls=Model4SimModel,
        params=params,
        model_label="Model 4",
        console_logging=False,
        include_avg_wip=True,
        trace_enabled=trace_path is not None,
    )
    print(
        f"Pallets created: total={stats.created} "
        f"main={model.main_source.emitted_count} "
        f"branch={model.branch_source.emitted_count}"
    )
    print(
        "Completed by origin: "
        f"main={model.sink.completed_by_origin.get('main', 0)} "
        f"branch={model.sink.completed_by_origin.get('branch', 0)}"
    )
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
    if trace_path is not None:
        output_path = model.write_trace_csv(trace_path)
        print(f"Trace CSV: {output_path}")


if __name__ == "__main__":
    main()
