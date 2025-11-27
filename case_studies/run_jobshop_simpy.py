from __future__ import annotations

import argparse
from jobshop_simpy import JobShopParams, JobShopModel


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run Job Shop (SimPy) with live textual updates."
    )
    ap.add_argument(
        "--hours",
        type=float,
        default=8.0,
        help="Simulation horizon in hours (default: 8)",
    )
    ap.add_argument("--seed", type=int, default=1,
                    help="Random seed (default: 1)")
    ap.add_argument(
        "--report-every",
        type=float,
        default=60.0,
        help="Report interval in simulated seconds (default: 60)",
    )
    ap.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Mirror colored console output to this text file",
    )
    ap.add_argument(
        "--log-append",
        action="store_true",
        help="Append to the log file instead of overwriting it",
    )
    ap.add_argument(
        "--console-level",
        choices=["full", "summary", "silent"],
        default="full",
        help="How chatty the console output should be",
    )
    args = ap.parse_args()

    params = JobShopParams(
        random_seed=args.seed,
        sim_time=args.hours * 3600.0,
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
