from __future__ import annotations

import argparse

from case_studies.model_5_simpy.reporting import run_model_and_print_summary

from .model import Model3SimModel
from .params import Model3Params


def main():
    parser = argparse.ArgumentParser(
        description="Run Model 3 and print conveyor flow summary stats."
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Optional simulation stop time override in seconds.",
    )
    args = parser.parse_args()

    params = Model3Params()
    if args.sim_time is not None:
        params.sim_time = args.sim_time

    _stats, model = run_model_and_print_summary(
        model_cls=Model3SimModel,
        params=params,
        model_label="Model 3",
        console_logging=False,
        include_avg_wip=True,
    )
    print(
        "Conveyor: "
        f"entered={model.conveyor.total_entered} "
        f"exited={model.conveyor.total_exited} "
        f"occupancy_end={model.conveyor.occupancy}"
    )


if __name__ == "__main__":
    main()
