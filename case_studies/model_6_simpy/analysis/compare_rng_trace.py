#!/usr/bin/env python3
"""Compare Model 6 AnyLogic and SimPy random sampled values."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from case_studies.model_6_simpy.model import Model6SimModel
from case_studies.model_6_simpy.params import Model6Params


@dataclass(frozen=True)
class SamplePair:
    current_nof_items: int
    items_count: int


@dataclass(frozen=True)
class AnyLogicIterationTrace:
    pairs: list[SamplePair]
    source_item_counts: list[int]


def parse_anylogic_trace(path: str | Path) -> dict[int, AnyLogicIterationTrace]:
    sections: dict[int, list[list[int | None]]] = {}
    source_counts: dict[int, list[int]] = {}
    current_iteration: int | None = None
    for line in Path(path).read_text().splitlines():
        iteration_match = re.match(r"ITERATION #(\d+)", line)
        if iteration_match:
            current_iteration = int(iteration_match.group(1))
            sections[current_iteration] = []
            source_counts[current_iteration] = []
            continue
        if current_iteration is None:
            continue
        if "event=source_item_count" in line:
            source_counts[current_iteration].append(
                _extract_int(line, "current_nof_items")
            )
        elif "event=unbatch_started" in line:
            value = _extract_int(line, "current_nof_items")
            sections[current_iteration].append([value, None])
        elif "event=loose_items_injected" in line:
            if not sections[current_iteration]:
                raise ValueError(
                    f"loose_items_injected appeared before unbatch_started: {line}"
                )
            sections[current_iteration][-1][1] = _extract_int(line, "items_count")

    parsed: dict[int, AnyLogicIterationTrace] = {}
    for iteration, pairs in sections.items():
        parsed_pairs = [
            SamplePair(current_nof_items=int(current), items_count=int(items))
            for current, items in pairs
            if current is not None and items is not None
        ]
        parsed[iteration] = AnyLogicIterationTrace(
            pairs=parsed_pairs,
            source_item_counts=source_counts.get(iteration) or [
                pair.current_nof_items for pair in parsed_pairs
            ],
        )
    return parsed


def _extract_int(line: str, name: str) -> int:
    match = re.search(rf"{re.escape(name)}=(\d+)", line)
    if match is None:
        raise ValueError(f"Missing {name} in trace line: {line}")
    return int(match.group(1))


def run_simpy_pairs(
    *,
    max_items_per_pallet: int,
    run_until_s: float,
    trace_limit: int,
    replay_pairs: Iterable[SamplePair] | None = None,
    replay_source_counts: Iterable[int] | None = None,
) -> tuple[list[SamplePair], Model6SimModel]:
    replay_tuple = tuple(replay_pairs) if replay_pairs is not None else None
    source_replay_tuple = (
        tuple(replay_source_counts) if replay_source_counts is not None else None
    )
    params = Model6Params(
        sim_time=run_until_s,
        max_items_per_pallet=max_items_per_pallet,
        diagnostic_trace_limit=trace_limit,
        item_count_replay=(
            source_replay_tuple
            if source_replay_tuple is not None
            else tuple(pair.current_nof_items for pair in replay_tuple)
            if replay_tuple is not None
            else None
        ),
        unbatch_count_replay=(
            tuple(pair.items_count for pair in replay_tuple)
            if replay_tuple is not None
            else None
        ),
        random_replay_strict=False,
    )
    model = Model6SimModel(params)
    model.run(until=run_until_s)
    return _parse_simpy_pairs(model.diagnostic_events), model


def _parse_simpy_pairs(lines: Iterable[str]) -> list[SamplePair]:
    pairs: list[list[int | None]] = []
    for line in lines:
        if "event=unbatch_started" in line:
            pairs.append([_extract_int(line, "current_nof_items"), None])
        elif "event=loose_items_injected" in line:
            if not pairs:
                raise ValueError(
                    f"loose_items_injected appeared before unbatch_started: {line}"
                )
            pairs[-1][1] = _extract_int(line, "items_count")
    return [
        SamplePair(current_nof_items=int(current), items_count=int(items))
        for current, items in pairs
        if current is not None and items is not None
    ]


def _parse_simpy_rng_values(lines: Iterable[str], event: str) -> list[int]:
    return [
        _extract_int(line, "value")
        for line in lines
        if f"event={event}" in line
    ]


def compare_pairs(
    anylogic: list[SamplePair],
    simpy: list[SamplePair],
    *,
    limit: int,
) -> tuple[int, int, int | None]:
    compared = min(len(anylogic), len(simpy), limit)
    first_mismatch: int | None = None
    mismatches = 0
    for index in range(compared):
        if anylogic[index] != simpy[index]:
            mismatches += 1
            if first_mismatch is None:
                first_mismatch = index
    return compared, mismatches, first_mismatch


def compare_values(
    anylogic: list[int],
    simpy: list[int],
    *,
    limit: int,
) -> tuple[int, int, int | None]:
    compared = min(len(anylogic), len(simpy), limit)
    first_mismatch: int | None = None
    mismatches = 0
    for index in range(compared):
        if anylogic[index] != simpy[index]:
            mismatches += 1
            if first_mismatch is None:
                first_mismatch = index
    return compared, mismatches, first_mismatch


def _format_pair(pair: SamplePair) -> str:
    return f"({pair.current_nof_items}, {pair.items_count})"


def _print_value_comparison(
    label: str,
    anylogic: list[int],
    simpy: list[int],
    *,
    limit: int,
) -> None:
    compared, mismatches, first_mismatch = compare_values(
        anylogic,
        simpy,
        limit=limit,
    )
    print(f"  {label}: compared={compared} mismatches={mismatches}")
    if first_mismatch is None:
        print("    sampled values match for compared prefix")
        return
    index = first_mismatch
    print(
        f"    first mismatch #{index + 1}: "
        f"AnyLogic={anylogic[index]} SimPy={simpy[index]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 6 random sampled values."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 6/model_6_diagnostic_trace.txt",
    )
    parser.add_argument("--run-until", type=float, default=300.0)
    parser.add_argument("--trace-limit", type=int, default=200)
    parser.add_argument("--compare-limit", type=int, default=25)
    parser.add_argument(
        "--max-items",
        default="10,20",
        help="Comma-separated max_items_per_pallet values by iteration.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Force SimPy to replay AnyLogic sampled values for a same-randoms smoke check.",
    )
    args = parser.parse_args()

    anylogic_sections = parse_anylogic_trace(args.anylogic)
    max_items_by_iteration = {
        index + 1: int(value)
        for index, value in enumerate(args.max_items.split(","))
        if value.strip()
    }

    print("\n--- Model 6 RNG Trace Comparison ---")
    print(f"AnyLogic trace: {args.anylogic}")
    print(f"Replay mode: {args.replay}")

    for iteration in sorted(anylogic_sections):
        if iteration not in max_items_by_iteration:
            print(f"\nITERATION {iteration}: skipped, no --max-items entry")
            continue
        anylogic_trace = anylogic_sections[iteration]
        anylogic_pairs = anylogic_trace.pairs
        simpy_pairs, model = run_simpy_pairs(
            max_items_per_pallet=max_items_by_iteration[iteration],
            run_until_s=args.run_until,
            trace_limit=args.trace_limit,
            replay_pairs=anylogic_pairs if args.replay else None,
            replay_source_counts=(
                anylogic_trace.source_item_counts if args.replay else None
            ),
        )
        simpy_source_counts = _parse_simpy_rng_values(
            model.rng_events,
            "source_item_count",
        )
        simpy_unbatch_counts = _parse_simpy_rng_values(
            model.rng_events,
            "unbatch_items_count",
        )
        anylogic_unbatch_counts = [pair.items_count for pair in anylogic_pairs]
        compared, mismatches, first_mismatch = compare_pairs(
            anylogic_pairs,
            simpy_pairs,
            limit=args.compare_limit,
        )
        print(
            f"\nITERATION {iteration} max_items={max_items_by_iteration[iteration]}: "
            f"unbatch_pairs_compared={compared} "
            f"unbatch_pair_mismatches={mismatches}"
        )
        if first_mismatch is None:
            print("  unbatch context/value pairs match for compared prefix")
        else:
            index = first_mismatch
            print(
                f"  first mismatch #{index + 1}: "
                f"AnyLogic={_format_pair(anylogic_pairs[index])} "
                f"SimPy={_format_pair(simpy_pairs[index])}"
            )
        _print_value_comparison(
            "source_item_count sequence",
            anylogic_trace.source_item_counts,
            simpy_source_counts,
            limit=args.compare_limit,
        )
        _print_value_comparison(
            "unbatch_items_count sequence",
            anylogic_unbatch_counts,
            simpy_unbatch_counts,
            limit=args.compare_limit,
        )
        print("  first SimPy RNG events:")
        for line in model.rng_events[:8]:
            print(f"    {line}")


if __name__ == "__main__":
    main()
