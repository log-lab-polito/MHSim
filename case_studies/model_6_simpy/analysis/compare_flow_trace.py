#!/usr/bin/env python3
"""Compare Model 6 AnyLogic and SimPy flow-event timing traces."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from case_studies.model_6_simpy.analysis.compare_rng_trace import (
    parse_anylogic_trace as parse_anylogic_rng_trace,
)
from case_studies.model_6_simpy.model import Model6SimModel
from case_studies.model_6_simpy.params import Model6Params


TRACE_EVENTS = (
    "unbatch_started",
    "loose_items_injected",
    "empty_pallet_sink_enter",
    "batch_released",
    "completed_pallet_sink_enter",
)

DEBUG_EVENTS = (
    "pallet_conveyor_enter",
    "item_conveyor_enter",
    "item_convey_to_batch_enter",
    "item_convey_to_batch_at_exit",
    "item_convey_to_batch_exit",
    "loaded_pallet_convey_enter",
    "loaded_pallet_conveyor_exit",
    "unbatch_station_process_started",
    "unbatch_station_process_finished",
    "batch_station_process_started",
    "batch_station_process_finished",
    "batch_add",
    "batch_released",
    "empty_pallet_transfer_enter",
    "empty_pallet_transfer_at_exit",
    "empty_pallet_storage_conveyor_enter",
    "empty_pallet_storage_conveyor_exit",
    "empty_pallet_transfer_exit",
    "empty_pallet_sink_enter",
    "unbatch_station_released",
    "batch_station_released",
)


@dataclass(frozen=True)
class FlowEvent:
    time_s: float
    event: str
    line: str


def parse_anylogic_flow_trace(
    path: str | Path,
    *,
    events: Iterable[str] = TRACE_EVENTS,
) -> dict[int, list[FlowEvent]]:
    wanted = set(events)
    sections: dict[int, list[FlowEvent]] = {}
    current_iteration: int | None = None
    for line in Path(path).read_text().splitlines():
        iteration_match = re.match(r"ITERATION #(\d+)", line)
        if iteration_match:
            current_iteration = int(iteration_match.group(1))
            sections[current_iteration] = []
            continue
        if current_iteration is None:
            continue
        event = _extract_field(line, "event")
        if event not in wanted:
            continue
        sections[current_iteration].append(
            FlowEvent(
                time_s=float(_extract_field(line, "t")),
                event=event,
                line=line,
            )
        )
    return sections


def run_simpy_flow_trace(
    *,
    max_items_per_pallet: int,
    run_until_s: float,
    trace_limit: int,
    replay_source_counts: Iterable[int] | None = None,
    replay_unbatch_counts: Iterable[int] | None = None,
    events: Iterable[str] = TRACE_EVENTS,
    include_debug: bool = False,
) -> tuple[list[FlowEvent], Model6SimModel]:
    params = Model6Params(
        sim_time=run_until_s,
        max_items_per_pallet=max_items_per_pallet,
        diagnostic_trace_limit=trace_limit,
        item_count_replay=(
            tuple(replay_source_counts)
            if replay_source_counts is not None
            else None
        ),
        unbatch_count_replay=(
            tuple(replay_unbatch_counts)
            if replay_unbatch_counts is not None
            else None
        ),
        random_replay_strict=False,
    )
    model = Model6SimModel(params)
    model.run(until=run_until_s)
    lines = list(model.diagnostic_events)
    if include_debug:
        lines.extend(model.debug_events)
    flow_events = parse_simpy_flow_trace(lines, events=events)
    flow_events.sort(key=lambda event: event.time_s)
    return flow_events, model


def parse_simpy_flow_trace(
    lines: Iterable[str],
    *,
    events: Iterable[str] = TRACE_EVENTS,
) -> list[FlowEvent]:
    wanted = set(events)
    parsed: list[FlowEvent] = []
    for line in lines:
        event = _extract_field(line, "event")
        if event not in wanted:
            continue
        parsed.append(
            FlowEvent(
                time_s=float(_extract_field(line, "t")),
                event=event,
                line=line,
            )
        )
    return parsed


def _extract_field(line: str, name: str) -> str:
    match = re.search(rf"(?:^|,){re.escape(name)}=([^,]+)", line)
    return match.group(1) if match is not None else ""


def _parse_event_filter(value: str, *, include_debug: bool) -> tuple[str, ...]:
    normalized = value.strip().lower()
    if normalized in {"", "primary"}:
        return TRACE_EVENTS
    if normalized == "debug":
        return DEBUG_EVENTS
    if normalized == "all":
        return TRACE_EVENTS + (DEBUG_EVENTS if include_debug else ())
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _compare_sequence(
    anylogic: list[FlowEvent],
    simpy: list[FlowEvent],
    *,
    limit: int,
    time_tolerance_s: float,
) -> tuple[int, int, int | None]:
    compared = min(len(anylogic), len(simpy), limit)
    mismatches = 0
    first_mismatch: int | None = None
    for index in range(compared):
        anylogic_event = anylogic[index]
        simpy_event = simpy[index]
        mismatch = (
            anylogic_event.event != simpy_event.event
            or abs(anylogic_event.time_s - simpy_event.time_s) > time_tolerance_s
        )
        if mismatch:
            mismatches += 1
            if first_mismatch is None:
                first_mismatch = index
    return compared, mismatches, first_mismatch


def _events_by_name(events: list[FlowEvent], event_name: str) -> list[FlowEvent]:
    return [event for event in events if event.event == event_name]


def _print_first_mismatch(
    anylogic: list[FlowEvent],
    simpy: list[FlowEvent],
    first_mismatch: int | None,
) -> None:
    if first_mismatch is None:
        print("  event sequence/timestamps match for compared prefix")
        return
    index = first_mismatch
    anylogic_event = anylogic[index]
    simpy_event = simpy[index]
    print(
        f"  first mismatch #{index + 1}: "
        f"AnyLogic={anylogic_event.event}@{anylogic_event.time_s:.6f} "
        f"SimPy={simpy_event.event}@{simpy_event.time_s:.6f} "
        f"delta={simpy_event.time_s - anylogic_event.time_s:+.6f}s"
    )


def _print_event_type_summary(
    event_name: str,
    anylogic: list[FlowEvent],
    simpy: list[FlowEvent],
    *,
    compare_limit: int,
    time_tolerance_s: float,
) -> None:
    anylogic_events = _events_by_name(anylogic, event_name)
    simpy_events = _events_by_name(simpy, event_name)
    compared = min(len(anylogic_events), len(simpy_events), compare_limit)
    first_mismatch: int | None = None
    for index in range(compared):
        if (
            abs(anylogic_events[index].time_s - simpy_events[index].time_s)
            > time_tolerance_s
        ):
            first_mismatch = index
            break
    print(
        f"  {event_name}: AnyLogic={len(anylogic_events)} "
        f"SimPy={len(simpy_events)} compared={compared}"
    )
    if first_mismatch is not None:
        index = first_mismatch
        print(
            f"    first timestamp mismatch #{index + 1}: "
            f"AnyLogic={anylogic_events[index].time_s:.6f} "
            f"SimPy={simpy_events[index].time_s:.6f} "
            f"delta={simpy_events[index].time_s - anylogic_events[index].time_s:+.6f}s"
        )


def _print_debug_context(
    model: Model6SimModel,
    *,
    before_time_s: float | None,
    limit: int,
    events: Iterable[str],
) -> None:
    wanted = set(events)
    debug_events = parse_simpy_flow_trace(model.debug_events, events=wanted)
    if before_time_s is not None:
        debug_events = [
            event for event in debug_events if event.time_s <= before_time_s + 1e-9
        ]
    if not debug_events:
        print("  SimPy debug context: no matching debug events captured")
        return
    print("  SimPy debug context:")
    for event in debug_events[:limit]:
        print(f"    {event.line}")


def _unbatch_counts(anylogic_rng_section) -> tuple[int, ...]:
    return tuple(pair.items_count for pair in anylogic_rng_section.pairs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 6 flow-event timing traces."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 6/model_6_diagnostic_trace.txt",
    )
    parser.add_argument(
        "--rng-anylogic",
        default=None,
        help=(
            "AnyLogic trace used for replay RNG values. Defaults to --anylogic; "
            "use the primary diagnostic trace when --anylogic points at a "
            "debug-only trace."
        ),
    )
    parser.add_argument("--run-until", type=float, default=300.0)
    parser.add_argument("--trace-limit", type=int, default=200)
    parser.add_argument("--compare-limit", type=int, default=50)
    parser.add_argument(
        "--max-items",
        default="10,20",
        help="Comma-separated max_items_per_pallet values by iteration.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Force SimPy to replay AnyLogic sampled values for a same-randoms trace check.",
    )
    parser.add_argument(
        "--include-debug",
        action="store_true",
        help="Include SimPy debug events when --events names debug or all.",
    )
    parser.add_argument(
        "--events",
        default="primary",
        help=(
            "Event filter: primary, debug, all, or comma-separated event names. "
            "Default compares AnyLogic primary flow events."
        ),
    )
    parser.add_argument(
        "--debug-events",
        default="all",
        help="Debug context filter: all or comma-separated SimPy debug event names.",
    )
    parser.add_argument("--debug-limit", type=int, default=20)
    parser.add_argument("--time-tolerance", type=float, default=1e-6)
    args = parser.parse_args()

    events = _parse_event_filter(args.events, include_debug=args.include_debug)
    debug_events = (
        DEBUG_EVENTS
        if args.debug_events.strip().lower() == "all"
        else tuple(
            part.strip()
            for part in args.debug_events.split(",")
            if part.strip()
        )
    )

    rng_trace_path = args.rng_anylogic or args.anylogic
    anylogic_flow_sections = parse_anylogic_flow_trace(args.anylogic, events=events)
    anylogic_rng_sections = parse_anylogic_rng_trace(rng_trace_path)
    max_items_by_iteration = {
        index + 1: int(value)
        for index, value in enumerate(args.max_items.split(","))
        if value.strip()
    }

    print("\n--- Model 6 Flow Trace Comparison ---")
    print(f"AnyLogic trace: {args.anylogic}")
    if rng_trace_path != args.anylogic:
        print(f"AnyLogic RNG trace: {rng_trace_path}")
    print(f"Replay mode: {args.replay}")
    print(f"Events: {', '.join(events)}")

    for iteration in sorted(anylogic_flow_sections):
        if iteration not in max_items_by_iteration:
            print(f"\nITERATION {iteration}: skipped, no --max-items entry")
            continue
        anylogic_flow = anylogic_flow_sections[iteration]
        anylogic_rng = anylogic_rng_sections.get(iteration)
        simpy_flow, _model = run_simpy_flow_trace(
            max_items_per_pallet=max_items_by_iteration[iteration],
            run_until_s=args.run_until,
            trace_limit=args.trace_limit,
            replay_source_counts=(
                anylogic_rng.source_item_counts
                if args.replay and anylogic_rng is not None
                else None
            ),
            replay_unbatch_counts=(
                _unbatch_counts(anylogic_rng)
                if args.replay and anylogic_rng is not None
                else None
            ),
            events=events,
            include_debug=args.include_debug,
        )
        compared, mismatches, first_mismatch = _compare_sequence(
            anylogic_flow,
            simpy_flow,
            limit=args.compare_limit,
            time_tolerance_s=args.time_tolerance,
        )
        print(
            f"\nITERATION {iteration} max_items={max_items_by_iteration[iteration]}: "
            f"sequence_compared={compared} sequence_mismatches={mismatches} "
            f"AnyLogic_events={len(anylogic_flow)} SimPy_events={len(simpy_flow)}"
        )
        _print_first_mismatch(anylogic_flow, simpy_flow, first_mismatch)
        if args.include_debug:
            mismatch_time_s = (
                simpy_flow[first_mismatch].time_s
                if first_mismatch is not None and first_mismatch < len(simpy_flow)
                else None
            )
            _print_debug_context(
                _model,
                before_time_s=mismatch_time_s,
                limit=args.debug_limit,
                events=debug_events,
            )
        for event_name in events:
            _print_event_type_summary(
                event_name,
                anylogic_flow,
                simpy_flow,
                compare_limit=args.compare_limit,
                time_tolerance_s=args.time_tolerance,
            )


if __name__ == "__main__":
    main()
