from __future__ import annotations

import argparse
from jobshop_salabim import JobShopParams, JobShopModel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Job Shop (Salabim) with textual/CSV logging."
    )
    parser.add_argument(
        "--hours", type=float, default=8.0, help="Simulation horizon in hours"
    )
    parser.add_argument("--seed", type=int, default=1, help="Random seed")
    parser.add_argument(
        "--report-every",
        type=float,
        default=60.0,
        help="Report interval in simulated seconds",
    )
    parser.add_argument(
        "--log-file", type=str, default=None, help="Write CSV trace rows to this file"
    )
    parser.add_argument(
        "--log-append",
        action="store_true",
        help="Append to the log instead of overwriting it",
    )
    parser.add_argument(
        "--console-level",
        choices=["full", "summary", "silent"],
        default="full",
        help="Control console verbosity",
    )
    parser.add_argument(
        "--animate",
        action="store_true",
        help="Enable Salabim's 2D animation (opens a UI window)",
    )
    parser.add_argument(
        "--animation-speed",
        type=float,
        default=1.0,
        help="Animation speed multiplier (1.0 = simulate seconds in real time)",
    )
    args = parser.parse_args()

    params = JobShopParams(
        random_seed=args.seed,
        sim_time=args.hours * 3600,
        enable_animation=args.animate,
        animation_speed=args.animation_speed,
    )
    model = JobShopModel(
        params,
        report_interval_s=args.report_every,
        trace_log_file=args.log_file,
        trace_log_append=args.log_append,
        console_level=args.console_level,
    )
    try:
        model.run()
        model.report()
    finally:
        model.close_tracer()


if __name__ == "__main__":
    main()
