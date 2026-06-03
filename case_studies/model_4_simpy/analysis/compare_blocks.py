#!/usr/bin/env python3
"""Block-by-block comparison support for Model 4."""

from __future__ import annotations

import argparse

from ..model import Model4SimModel
from ..params import Model4Params


# Transcribed AnyLogic Model 4 reference block counts, kept here like the
# Model 3 block baseline so the comparison can run without parsing the .alp.
ANYLOGIC_BLOCKS = {
    "mainSource": 1200,
    "branchSource": 1200,
    "mainService": 1199,
    "branchService": 1199,
    "mainConvey": 1197,
    "branchConvey": 1197,
    "downstreamService": 2393,
    "sink": 2393,
}

BLOCK_MAPPING = [
    ("main_source", "mainSource", "MAIN SOURCE"),
    ("branch_source", "branchSource", "BRANCH SOURCE"),
    ("main_service", "mainService", "MAIN SERVICE"),
    ("branch_service", "branchService", "BRANCH SERVICE"),
    ("main_convey", "mainConvey", "MAIN CONVEY"),
    ("branch_convey", "branchConvey", "BRANCH CONVEY"),
    ("downstream_service", "downstreamService", "DOWNSTREAM SERVICE"),
    ("sink", "sink", "SINK"),
]


def _block_count(model: Model4SimModel, simpy_name: str) -> int:
    if simpy_name == "main_source":
        return model.main_source.emitted_count
    if simpy_name == "branch_source":
        return model.branch_source.emitted_count
    block = getattr(model, simpy_name)
    if simpy_name == "sink":
        return int(getattr(block, "entered_count", 0))
    return int(getattr(block, "finished_count", getattr(block, "completed_count", 0)))


def collect_block_counts(params: Model4Params | None = None) -> dict[str, int]:
    """Run Model 4 and return SimPy block counts keyed by AnyLogic block name."""
    active_params = params or Model4Params()
    model = Model4SimModel(params=active_params, console_logging=False)
    model.run()
    return {
        anylogic_name: _block_count(model, simpy_name)
        for simpy_name, anylogic_name, _label in BLOCK_MAPPING
    }


def compare_blocks(
    params: Model4Params | None = None,
    *,
    simpy_only: bool = False,
):
    """Run Model 4 and compare block counts with the transcribed AnyLogic baseline."""
    anylogic_blocks = None if simpy_only else _validated_anylogic_blocks()
    active_params = params or Model4Params()
    model = Model4SimModel(params=active_params, console_logging=False)
    stats = model.run()
    simpy_counts = {
        anylogic_name: _block_count(model, simpy_name)
        for simpy_name, anylogic_name, _label in BLOCK_MAPPING
    }

    print("\n" + "=" * 92)
    if simpy_only:
        print("BLOCK SUMMARY: SIMPY MODEL 4")
    else:
        print("BLOCK COMPARISON: ANYLOGIC vs SIMPY (MODEL 4)")
    print("=" * 92)

    if simpy_only:
        print(f"{'BLOCK':<28} {'SIMPY':>10}")
        print("-" * 92)
        for _simpy_name, anylogic_name, label in BLOCK_MAPPING:
            print(f"{label:<28} {simpy_counts[anylogic_name]:>10}")
    else:
        print(
            f"{'BLOCK':<28} {'ANYLOGIC':>10} {'SIMPY':>10} "
            f"{'DIFF':>8} {'%':>8} {'STATUS':>8}"
        )
        print("-" * 92)
        for _simpy_name, anylogic_name, label in BLOCK_MAPPING:
            anylogic_count = int(anylogic_blocks[anylogic_name])
            simpy_count = simpy_counts[anylogic_name]
            diff = simpy_count - anylogic_count
            pct = (abs(diff) / anylogic_count * 100.0) if anylogic_count else 0.0
            status = _status(pct)
            print(
                f"{label:<28} {anylogic_count:>10} {simpy_count:>10} "
                f"{diff:>+8} {pct:>7.1f}% {status:>8}"
            )

    print("-" * 92)
    print(
        f"Created: {stats.created}  Completed: {stats.completed}  "
        f"In-flight: {stats.created - stats.completed}"
    )
    print(
        "Completed by origin: "
        f"main={model.sink.completed_by_origin.get('main', 0)} "
        f"branch={model.sink.completed_by_origin.get('branch', 0)}"
    )
    print(
        "Conveyors: "
        f"main_occ={model.main_conveyor.occupancy} "
        f"branch_occ={model.branch_conveyor.occupancy} "
        f"spur_transferred={model.spur.total_transferred}"
    )
    print(f"Avg cycle: {stats.avg_time_in_system:.2f}s")
    print("=" * 92)

    return stats, model, simpy_counts


def _status(pct: float) -> str:
    if pct < 1:
        return "MATCH"
    if pct < 2:
        return "CLOSE"
    return "DIFF"


def _validated_anylogic_blocks() -> dict[str, int]:
    expected = {anylogic_name for _simpy, anylogic_name, _label in BLOCK_MAPPING}
    missing = sorted(expected - set(ANYLOGIC_BLOCKS))
    if missing:
        raise ValueError(
            "ANYLOGIC_BLOCKS is missing required keys: "
            + ", ".join(missing)
        )
    unset = sorted(key for key, value in ANYLOGIC_BLOCKS.items() if value is None)
    if unset:
        raise ValueError(
            "Fill ANYLOGIC_BLOCKS in case_studies/model_4_simpy/analysis/compare_blocks.py "
            "with the transcribed AnyLogic Model 4 block counts before running "
            "the comparison. Unset keys: "
            + ", ".join(unset)
        )
    return {key: int(value) for key, value in ANYLOGIC_BLOCKS.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print or compare Model 4 block counts."
    )
    parser.add_argument(
        "--simpy-only",
        action="store_true",
        help="Print SimPy block counts without comparing against ANYLOGIC_BLOCKS.",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Optional simulation stop time override in seconds.",
    )
    args = parser.parse_args()

    params = Model4Params()
    if args.sim_time is not None:
        params.sim_time = args.sim_time

    try:
        compare_blocks(params=params, simpy_only=args.simpy_only)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
