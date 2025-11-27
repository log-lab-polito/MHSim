from __future__ import annotations
from jobshop_simpy import JobShopParams as SimPyParams
from jobshop_simpy import JobShopModel as SimPyModel
from jobshop_salabim import JobShopParams as SalabimParams
from jobshop_salabim import JobShopModel as SalabimModel
from typing import Any, Dict
from dataclasses import asdict, fields
import argparse
import sys
from pathlib import Path
workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))


def _shared_kwargs(s_params: SalabimParams) -> Dict[str, Any]:
    salabim_dict = asdict(s_params)
    simpy_field_names = {f.name for f in fields(SimPyParams)}
    return {name: v for name, v in salabim_dict.items() if name in simpy_field_names}


def _format_value(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _collect_metrics(stats, params) -> Dict[str, float]:
    return {
        "Completed parts": stats.completed_parts,
        "Avg part time (s)": stats.avg_time_in_system,
        "Throughput (parts/h)": stats.throughput_per_hour(params.sim_time),
        "Completed pallets": getattr(stats, "completed_pallets", 0),
        "Pallets shipped": getattr(stats, "pallets_shipped", 0),
        "Avg pallet wait (s)": getattr(stats, "avg_pallet_wait", 0.0),
        "Shipping trucks": getattr(stats, "shipping_trucks_arrived", 0),
        "Forklift tasks": getattr(stats, "forklift_tasks_completed", 0),
        "Forklift distance (m)": getattr(stats, "forklift_distance_m", 0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SimPy vs Salabim job shop benchmark."
    )
    parser.add_argument(
        "--hours", type=float, default=8.0, help="Simulation horizon in hours"
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="Random seed for both models"
    )
    parser.add_argument(
        "--report-every",
        type=float,
        default=60.0,
        help="Report interval in simulated seconds",
    )
    parser.add_argument(
        "--salabim-console",
        choices=["full", "summary", "silent"],
        default="summary",
        help="Salabim console verbosity",
    )
    parser.add_argument(
        "--simpy-console",
        choices=["full", "summary", "silent"],
        default="summary",
        help="SimPy console verbosity",
    )
    parser.add_argument(
        "--animate-salabim",
        action="store_true",
        help="Enable animation when running the Salabim model",
    )
    args = parser.parse_args()

    print("Step 1/4: preparing shared parameters")
    salabim_params = SalabimParams(
        random_seed=args.seed,
        sim_time=args.hours * 3600.0,
        enable_animation=args.animate_salabim,
    )
    simpy_params = SimPyParams(**_shared_kwargs(salabim_params))

    print("Step 2/4: running SimPy baseline model ...")
    simpy_model = SimPyModel(
        simpy_params,
        report_interval_s=args.report_every,
        console_level=args.simpy_console,
    )
    simpy_stats = simpy_model.run()
    simpy_model.report()
    simpy_model.close_tracer()

    print("Step 3/4: running Salabim forklift + shipping model ...")
    salabim_model = SalabimModel(
        salabim_params,
        report_interval_s=args.report_every,
        console_level=args.salabim_console,
    )
    try:
        salabim_stats = salabim_model.run()
        salabim_model.report()
    finally:
        salabim_model.close_tracer()

    print("Step 4/4: comparison")
    simpy_metrics = _collect_metrics(simpy_stats, simpy_params)
    salabim_metrics = _collect_metrics(salabim_stats, salabim_params)
    header = f"{'Metric':<28}{'SimPy':>14}{'Salabim':>14}"
    print()
    print(header)
    print("-" * len(header))
    for metric in simpy_metrics.keys():
        simpy_val = _format_value(simpy_metrics[metric])
        salabim_val = _format_value(salabim_metrics.get(metric, 0))
        print(f"{metric:<28}{simpy_val:>14}{salabim_val:>14}")


if __name__ == "__main__":
    main()
