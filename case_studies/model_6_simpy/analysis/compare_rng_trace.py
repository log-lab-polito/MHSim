#!/usr/bin/env python3
"""Compare Model 6 AnyLogic and SimPy random sampled values."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypeVar

from case_studies.model_6_simpy.model import Model6SimModel
from case_studies.model_6_simpy.params import Model6Params


_BlockT = TypeVar("_BlockT")


@dataclass(frozen=True)
class SamplePair:
    current_nof_items: int
    items_count: int


@dataclass(frozen=True)
class AnyLogicIterationTrace:
    pairs: list[SamplePair]
    source_item_counts: list[int]


@dataclass(frozen=True)
class TraceBlockKey:
    """Identifies one ``ITERATION`` block inside an AnyLogic trace file.

    ``replication`` is ``None`` for the deterministic single-run block and an
    integer for the per-replication blocks a stochastic experiment appends to
    the same file.
    """

    iteration: int
    replication: int | None

    def label(self) -> str:
        if self.replication is None:
            return f"ITERATION #{self.iteration}"
        return f"ITERATION #{self.iteration}, REPLICATION #{self.replication}"


# A stochastic experiment appends "ITERATION #1, REPLICATION #7" headers next to
# the deterministic "ITERATION #1" block. Anchor the pattern so the two forms
# stay distinguishable instead of collapsing onto the same iteration key.
_ITERATION_HEADER_RE = re.compile(
    r"^ITERATION #(?P<iteration>\d+)"
    r"(?:\s*,\s*REPLICATION #(?P<replication>\d+))?\s*$"
)


def parse_iteration_header(line: str) -> TraceBlockKey | None:
    """Return the block key for an ``ITERATION`` header, or ``None`` for a data line.

    Raises on a line that opens a block but does not match either known header
    form, so an unexpected trace layout fails loudly instead of being folded
    into whichever block came before it.
    """
    if not line.startswith("ITERATION"):
        return None
    header = _ITERATION_HEADER_RE.match(line)
    if header is None:
        raise ValueError(f"Unrecognized iteration header: {line!r}")
    replication = header.group("replication")
    return TraceBlockKey(
        iteration=int(header.group("iteration")),
        replication=int(replication) if replication is not None else None,
    )


def select_iteration_blocks(
    blocks: dict[TraceBlockKey, _BlockT],
    *,
    path: str | Path,
    replication: int | None,
) -> dict[int, _BlockT]:
    """Pick one block per iteration, keyed by iteration number.

    ``replication=None`` selects the deterministic blocks, which are the ones a
    single SimPy comparison run mirrors.
    """
    selected = {
        key.iteration: block
        for key, block in blocks.items()
        if key.replication == replication
    }
    if selected:
        return selected
    if not blocks:
        raise ValueError(f"No ITERATION blocks found in trace: {path}")
    available = sorted(
        {key.replication for key in blocks if key.replication is not None}
    )
    if replication is None:
        raise ValueError(
            f"Trace {path} has no deterministic ITERATION block; it contains "
            f"only {len(available)} replication blocks. Re-export the "
            "deterministic run, or pass --replication to compare against one "
            "of them."
        )
    shown = ", ".join(str(value) for value in available[:10])
    suffix = " ..." if len(available) > 10 else ""
    raise ValueError(
        f"Trace {path} has no REPLICATION #{replication} block. "
        f"Available replications: {shown}{suffix}"
    )


def parse_anylogic_trace_blocks(
    path: str | Path,
) -> dict[TraceBlockKey, AnyLogicIterationTrace]:
    """Parse every iteration and replication block in an AnyLogic trace file."""
    sections: dict[TraceBlockKey, list[list[int | None]]] = {}
    source_counts: dict[TraceBlockKey, list[int]] = {}
    current_key: TraceBlockKey | None = None
    for line in Path(path).read_text().splitlines():
        block_key = parse_iteration_header(line)
        if block_key is not None:
            current_key = block_key
            if current_key in sections:
                raise ValueError(
                    f"Trace contains more than one {current_key.label()} block. "
                    "Regenerate the trace so each block appears once."
                )
            sections[current_key] = []
            source_counts[current_key] = []
            continue
        if current_key is None:
            continue
        if "event=source_item_count" in line:
            source_counts[current_key].append(
                _extract_int(line, "current_nof_items")
            )
        elif "event=unbatch_started" in line:
            value = _extract_int(line, "current_nof_items")
            sections[current_key].append([value, None])
        elif "event=loose_items_injected" in line:
            if not sections[current_key]:
                raise ValueError(
                    f"loose_items_injected appeared before unbatch_started: {line}"
                )
            sections[current_key][-1][1] = _extract_int(line, "items_count")

    parsed: dict[TraceBlockKey, AnyLogicIterationTrace] = {}
    for key, pairs in sections.items():
        parsed_pairs = [
            SamplePair(current_nof_items=int(current), items_count=int(items))
            for current, items in pairs
            if current is not None and items is not None
        ]
        parsed[key] = AnyLogicIterationTrace(
            pairs=parsed_pairs,
            source_item_counts=source_counts.get(key) or [
                pair.current_nof_items for pair in parsed_pairs
            ],
        )
    return parsed


def parse_anylogic_trace(
    path: str | Path,
    *,
    replication: int | None = None,
) -> dict[int, AnyLogicIterationTrace]:
    """Select one block per iteration, keyed by iteration number.

    ``replication=None`` selects the deterministic blocks, which are the ones
    the SimPy comparison run mirrors. Passing an integer selects that
    replication instead, for inspecting a specific stochastic run.
    """
    return select_iteration_blocks(
        parse_anylogic_trace_blocks(path),
        path=path,
        replication=replication,
    )


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
        "--replication",
        type=int,
        default=None,
        help=(
            "Compare against this stochastic REPLICATION block instead of the "
            "deterministic ITERATION block."
        ),
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Force SimPy to replay AnyLogic sampled values for a same-randoms smoke check.",
    )
    args = parser.parse_args()

    anylogic_sections = parse_anylogic_trace(
        args.anylogic,
        replication=args.replication,
    )
    max_items_by_iteration = {
        index + 1: int(value)
        for index, value in enumerate(args.max_items.split(","))
        if value.strip()
    }

    print("\n--- Model 6 RNG Trace Comparison ---")
    print(f"AnyLogic trace: {args.anylogic}")
    block_label = (
        "deterministic ITERATION blocks"
        if args.replication is None
        else f"REPLICATION #{args.replication} blocks"
    )
    print(f"Comparing against: {block_label}")
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
