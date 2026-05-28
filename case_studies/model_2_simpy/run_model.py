from __future__ import annotations

import argparse

from case_studies.model_5_simpy.reporting import (
    run_model_and_print_summary,
    write_forklift_movement_benchmark_csv,
)

from .model import Model2SimModel
from .params import Model2Params


def main():
    parser = argparse.ArgumentParser(
        description="Run Model 2 and print forklift movement benchmark stats."
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Optional simulation stop time override in seconds.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV output path for the forklift movement benchmark table.",
    )
    args = parser.parse_args()

    params = Model2Params()
    if args.sim_time is not None:
        params.sim_time = args.sim_time

    stats, _model = run_model_and_print_summary(
        model_cls=Model2SimModel,
        params=params,
        model_label="Model 2",
        console_logging=False,
        include_avg_wip=True,
        include_forklift_utilization=True,
        include_forklift_benchmarks=True,
    )
    if args.csv:
        output_path = write_forklift_movement_benchmark_csv(stats, args.csv)
        print(f"Forklift benchmark CSV: {output_path}")


if __name__ == "__main__":
    main()
