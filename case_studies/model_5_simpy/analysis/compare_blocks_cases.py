#!/usr/bin/env python3
"""
Run a parameter sweep of Model 5 SimPy scenarios and export block/summary metrics to CSV.
"""

from __future__ import annotations

import argparse
import csv
from typing import Dict, List

from .compare_blocks import ANYLOGIC_BLOCKS, BLOCK_MAPPING
from ..model import Model5SimModel
from ..params import Model5Params


PRIORITY_MODES = [
    ("same", 1, 1),
    ("retrieve_high", 1, 0),
]

STORE_POLICIES = ["FIRST", "BEST"]
RETRIEVE_POLICIES = ["FIFO", "LIFO", "BEST"]
RETURN_HOME_POLICIES = ["stay", "always", "idle"]


def _case_id(
    priority_label: str,
    store_policy: str,
    retrieve_policy: str,
    return_home_policy: str,
) -> str:
    return (
        f"prio_{priority_label}"
        f"__store_{store_policy}"
        f"__retrieve_{retrieve_policy}"
        f"__return_{return_home_policy}"
    )


def _collect_metrics(params: Model5Params) -> Dict[str, str | int | float]:
    model = Model5SimModel(
        params=params,
        console_logging=False,
        enable_logging=False,
    )
    stats = model.run()

    block_stats: Dict[str, Dict[str, int]] = {}
    for name, _, _ in BLOCK_MAPPING:
        block = getattr(model, name)
        block_stats[name] = {
            "entries": getattr(block, "entered_count", 0),
            "exits": getattr(
                block,
                "finished_count",
                getattr(block, "completed_count", 0),
            ),
        }

    throughput_per_hour = (stats.completed / params.sim_time) * 3600
    return {
        "source_created": stats.created,
        "service1": block_stats["service1"]["exits"],
        "store": block_stats["store"]["exits"],
        "delay": block_stats["delay"]["exits"],
        "retrieve": block_stats["retrieve"]["exits"],
        "service2": block_stats["service2"]["exits"],
        "sink_completed": stats.completed,
        "created": stats.created,
        "completed": stats.completed,
        "in_flight": stats.created - stats.completed,
        "storage": int(model.storage.level),
        "avg_cycle_s": stats.avg_time_in_system,
        "throughput_per_hour": throughput_per_hour,
    }


def _metric_rows(base_params: Model5Params) -> List[tuple[str, str, str | int | float]]:
    throughput_anylogic = (ANYLOGIC_BLOCKS["sink"] / base_params.sim_time) * 3600
    return [
        ("source_created", "SOURCE (created)", ANYLOGIC_BLOCKS["source"]),
        ("service1", "SERVICE1 (upstream)", ANYLOGIC_BLOCKS["service1"]),
        ("store", "STORE", ANYLOGIC_BLOCKS["store"]),
        ("delay", "DELAY", ANYLOGIC_BLOCKS["delay"]),
        ("retrieve", "RETRIEVE", ANYLOGIC_BLOCKS["retrieve"]),
        ("service2", "SERVICE2 (downstream)", ANYLOGIC_BLOCKS["service2"]),
        ("sink_completed", "SINK (completed)", ANYLOGIC_BLOCKS["sink"]),
        ("created", "Created", ANYLOGIC_BLOCKS["source"]),
        ("completed", "Completed", ANYLOGIC_BLOCKS["sink"]),
        ("in_flight", "In-flight", ANYLOGIC_BLOCKS["source"] - ANYLOGIC_BLOCKS["sink"]),
        ("storage", "Storage", ""),
        ("avg_cycle_s", "Avg cycle (s)", ""),
        ("throughput_per_hour", "Throughput (pallets/hour)", throughput_anylogic),
    ]


def _trim_float(value: float, decimals: int) -> str:
    formatted = f"{value:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _format_metric_value(key: str, value: str | int | float) -> str:
    if value == "" or value is None:
        return ""
    if key == "avg_cycle_s":
        return _trim_float(float(value), 2)
    if key == "throughput_per_hour":
        return _trim_float(float(value), 1)
    return str(value)


def write_csv(
    output_path: str,
    cases: List[Dict[str, str]],
    results: Dict[str, Dict[str, str | int | float]],
    base_params: Model5Params,
) -> None:
    with open(output_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        case_ids = [case["id"] for case in cases]
        header_priority = ["Store vs Retrieve Priority", "AnyLogic"] + [
            case["priority_label"] for case in cases
        ]
        header_store = ["Store Policy", ""] + [case["store_policy"] for case in cases]
        header_retrieve = ["Retrieve Policy", ""] + [
            case["retrieve_policy"] for case in cases
        ]
        header_return = ["Forklift Return-Home Policy", ""] + [
            case["return_home_policy"] for case in cases
        ]
        writer.writerow(header_priority)
        writer.writerow(header_store)
        writer.writerow(header_retrieve)
        writer.writerow(header_return)
        for key, label, anylogic_value in _metric_rows(base_params):
            row = [label, _format_metric_value(key, anylogic_value)]
            for case_id in case_ids:
                row.append(_format_metric_value(key, results[case_id].get(key, "")))
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Model 5 SimPy sweep and export block stats to CSV."
    )
    parser.add_argument(
        "--output",
        default="case_studies/model_5_simpy/compare_blocks_cases.csv",
        help="CSV output path.",
    )
    args = parser.parse_args()

    base_params = Model5Params()
    cases: List[Dict[str, str]] = []
    results: Dict[str, Dict[str, str | int | float]] = {}

    for priority_label, store_prio, retrieve_prio in PRIORITY_MODES:
        for store_policy in STORE_POLICIES:
            for retrieve_policy in RETRIEVE_POLICIES:
                for return_home_policy in RETURN_HOME_POLICIES:
                    params = Model5Params(
                        storage_store_policy=store_policy,
                        storage_retrieve_policy=retrieve_policy,
                        forklift_return_home_policy=return_home_policy,
                        forklift_store_priority=store_prio,
                        forklift_retrieve_priority=retrieve_prio,
                    )
                    case_id = _case_id(
                        priority_label,
                        store_policy,
                        retrieve_policy,
                        return_home_policy,
                    )
                    cases.append(
                        {
                            "id": case_id,
                            "priority_label": priority_label,
                            "store_policy": store_policy,
                            "retrieve_policy": retrieve_policy,
                            "return_home_policy": return_home_policy,
                        }
                    )
                    results[case_id] = _collect_metrics(params)

    write_csv(args.output, cases, results, base_params)
    print(f"Wrote CSV to {args.output}")


if __name__ == "__main__":
    main()
