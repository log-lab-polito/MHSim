from __future__ import annotations

import argparse
from pathlib import Path

from .compare_trace import run_simpy_trace
from .range_config import range_values_for_iteration


DEFAULT_RANGE_TRACE_UNTIL_S = 18000.0


def _params_for_iteration(iteration: int) -> dict[str, float]:
    values = range_values_for_iteration(iteration)
    return {
        "main_arrival_time_s": values.main_arrival_time_s,
        "branch_arrival_time_s": values.branch_arrival_time_s,
        "conveyor_speed_mps": values.conveyor_speed_mps,
        "conveyor_gap_m": values.conveyor_gap_m,
    }


def _default_output(iteration: int) -> Path:
    return Path("logs") / f"model_4_iteration_{iteration}_simpy_trace.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a traced SimPy Model 4 range-grid iteration."
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
        help="1-based Model 4 range iteration to trace. Default: 1.",
    )
    parser.add_argument(
        "--until",
        type=float,
        default=DEFAULT_RANGE_TRACE_UNTIL_S,
        help="Simulation stop time in seconds. Default matches the Model 4 range run.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Trace CSV output path. Defaults to logs/model_4_iteration_N_simpy_trace.csv.",
    )
    args = parser.parse_args()

    params = _params_for_iteration(args.iteration)
    output_path = Path(args.output) if args.output else _default_output(args.iteration)
    events = run_simpy_trace(
        params=params,
        until=args.until,
        output_path=output_path,
    )

    print(f"Model 4 SimPy trace iteration: {args.iteration}")
    print(f"Stop time: {args.until:g}s")
    print(
        "Parameters: "
        f"main_arrival_s={params['main_arrival_time_s']:g} "
        f"branch_arrival_s={params['branch_arrival_time_s']:g} "
        f"speed={params['conveyor_speed_mps']:g} "
        f"gap={params['conveyor_gap_m']:g}"
    )
    print(f"Events written: {len(events)}")
    print(f"Trace CSV: {output_path}")


if __name__ == "__main__":
    main()
