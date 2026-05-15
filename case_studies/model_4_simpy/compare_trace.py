from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from .model import Model4SimModel
from .params import Model4Params


PARAMETER_KEY_MAP = {
    "Arrival rate (s)": "main_arrival_time_s",
    "Main arrival rate (s)": "main_arrival_time_s",
    "Branch arrival rate (s)": "branch_arrival_time_s",
    "Conveyor Speed (m/s)": "conveyor_speed_mps",
    "Conveyor Gap (m)": "conveyor_gap_m",
}
DIAGNOSTIC_EVENT_PREFIXES = ("diag_",)


def _is_diagnostic_event(event_name: str) -> bool:
    return event_name.startswith(DIAGNOSTIC_EVENT_PREFIXES)


@dataclass(frozen=True)
class TraceEvent:
    time_s: float
    event: str
    pallet_id: int
    origin: str
    cycle_time_s: float | None = None
    origin_seq: int | None = None


@dataclass(frozen=True)
class AnyLogicTrace:
    iteration: int | None
    params: dict[str, float]
    events: list[TraceEvent]


def _parse_number(value: str) -> float:
    return float(value.strip())


def parse_anylogic_trace(
    path: str | Path,
    *,
    selected_iteration: int | None = None,
) -> AnyLogicTrace:
    current_iteration: int | None = None
    current_params: dict[str, float] = {}
    params_by_iteration: dict[int, dict[str, float]] = {}
    events_by_iteration: defaultdict[int, list[TraceEvent]] = defaultdict(list)

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if stripped.startswith("ITERATION #"):
                # Handle both "ITERATION #N" and "ITERATION #N, REPLICATION #M"
                iteration_token = stripped.removeprefix("ITERATION #").split(",")[0]
                current_iteration = int(iteration_token)
                current_params = {}
                continue

            if line.startswith("TRACE\t"):
                parts = line.split("\t")
                if len(parts) < 6:
                    continue
                trace_iteration = int(parts[1])
                cycle_time = None
                if len(parts) >= 7 and parts[6] != "":
                    cycle_time = _parse_number(parts[6])
                events_by_iteration[trace_iteration].append(
                    TraceEvent(
                        time_s=_parse_number(parts[2]),
                        event=parts[3],
                        pallet_id=int(parts[4]),
                        origin=parts[5],
                        cycle_time_s=cycle_time,
                    )
                )
                continue

            if ":" in line and not stripped.startswith("TRACE_HEADER"):
                key, value = line.split(":", 1)
                field_name = PARAMETER_KEY_MAP.get(key.strip())
                if field_name is not None:
                    current_params[field_name] = _parse_number(value)
                    if current_iteration is not None:
                        params_by_iteration[current_iteration] = dict(current_params)

    if not events_by_iteration:
        raise ValueError(f"No TRACE rows found in {path}")

    trace_iterations = sorted(events_by_iteration)
    iteration = selected_iteration if selected_iteration is not None else trace_iterations[0]
    if iteration not in events_by_iteration:
        raise ValueError(
            f"No TRACE rows found for iteration #{iteration}. "
            f"Available traced iterations: {', '.join(str(i) for i in trace_iterations)}"
        )
    params = params_by_iteration.get(iteration, {})

    return AnyLogicTrace(
        iteration=iteration,
        params=params,
        events=_with_origin_sequences(events_by_iteration[iteration]),
    )


def parse_simpy_trace(path: str | Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            cycle_time = None
            if row.get("cycle_time_s"):
                cycle_time = _parse_number(row["cycle_time_s"])
            events.append(
                TraceEvent(
                    time_s=_parse_number(row["time_s"]),
                    event=row["event"],
                    pallet_id=int(row["pallet_id"]),
                    origin=row["origin"],
                    cycle_time_s=cycle_time,
                )
            )
    if not events:
        raise ValueError(f"No SimPy trace rows found in {path}")
    return _with_origin_sequences(events)


def run_simpy_trace(
    *,
    params: dict[str, float],
    until: float,
    output_path: str | Path | None = None,
) -> list[TraceEvent]:
    model_params = Model4Params()
    model_params.sim_time = until
    for field_name, value in params.items():
        if hasattr(model_params, field_name):
            setattr(model_params, field_name, value)

    model = Model4SimModel(
        params=model_params,
        console_logging=False,
        trace_enabled=True,
    )
    model.run()
    if output_path is not None:
        model.write_trace_csv(output_path)

    events = [
        TraceEvent(
            time_s=float(row["time_s"]),
            event=str(row["event"]),
            pallet_id=int(row["pallet_id"]),
            origin=str(row["origin"]),
            cycle_time_s=(
                float(row["cycle_time_s"]) if row["cycle_time_s"] != "" else None
            ),
        )
        for row in model.trace_events
    ]
    return _with_origin_sequences(events)


def _with_origin_sequences(events: Iterable[TraceEvent]) -> list[TraceEvent]:
    next_seq_by_origin: defaultdict[str, int] = defaultdict(int)
    seq_by_pallet_id: dict[int, int] = {}
    sequenced: list[TraceEvent] = []

    for event in events:
        if event.event.endswith("_source_exit"):
            next_seq_by_origin[event.origin] += 1
            seq_by_pallet_id[event.pallet_id] = next_seq_by_origin[event.origin]
        sequenced.append(
            replace(
                event,
                origin_seq=seq_by_pallet_id.get(event.pallet_id),
            )
        )

    return sequenced


def _event_key(event: TraceEvent) -> tuple[str, int | None, str]:
    return (event.origin, event.origin_seq, event.event)


def _format_params(params: dict[str, float]) -> str:
    labels = (
        ("main_arrival_time_s", "main_arrival_s"),
        ("branch_arrival_time_s", "branch_arrival_s"),
        ("conveyor_speed_mps", "speed"),
        ("conveyor_gap_m", "gap"),
    )
    parts = []
    for field_name, label in labels:
        if field_name in params:
            parts.append(f"{label}={params[field_name]:g}")
    return " ".join(parts)


def compare_traces(
    *,
    anylogic_events: list[TraceEvent],
    simpy_events: list[TraceEvent],
    top: int,
) -> int:
    anylogic_horizon = max(event.time_s for event in anylogic_events)
    simpy_horizon = max(event.time_s for event in simpy_events)
    diagnostic_anylogic_events = [
        event for event in anylogic_events if _is_diagnostic_event(event.event)
    ]
    diagnostic_simpy_events = [
        event for event in simpy_events if _is_diagnostic_event(event.event)
    ]
    comparable_anylogic_events = [
        event for event in anylogic_events if not _is_diagnostic_event(event.event)
    ]
    comparable_simpy_events = [
        event for event in simpy_events if not _is_diagnostic_event(event.event)
    ]
    anylogic_counts = Counter(event.event for event in comparable_anylogic_events)
    simpy_counts = Counter(event.event for event in comparable_simpy_events)
    anylogic_by_key = {
        _event_key(event): event
        for event in comparable_anylogic_events
        if event.origin_seq is not None
    }
    simpy_by_key = {
        _event_key(event): event
        for event in comparable_simpy_events
        if event.origin_seq is not None and event.event in anylogic_counts
    }

    anylogic_keys = set(anylogic_by_key)
    simpy_keys = set(simpy_by_key)
    common_keys = anylogic_keys & simpy_keys
    missing_in_simpy = anylogic_keys - simpy_keys
    extra_in_simpy = simpy_keys - anylogic_keys

    diffs: list[tuple[float, tuple[str, int | None, str], float, float]] = []
    for key in common_keys:
        anylogic_time = anylogic_by_key[key].time_s
        simpy_time = simpy_by_key[key].time_s
        diff = simpy_time - anylogic_time
        if abs(diff) > 1e-9:
            diffs.append((diff, key, anylogic_time, simpy_time))

    print("=" * 92)
    print("TRACE COMPARISON: ANYLOGIC vs SIMPY (MODEL 4)")
    print("=" * 92)
    print(
        f"AnyLogic events: {len(anylogic_events)}  "
        f"SimPy events: {len(simpy_events)}  "
        f"Compared shared events: {len(common_keys)}"
    )
    print(
        f"AnyLogic trace horizon: {anylogic_horizon:g}s  "
        f"SimPy trace horizon: {simpy_horizon:g}s"
    )
    if abs(simpy_horizon - anylogic_horizon) > 1e-9:
        print(
            "WARNING: trace horizons differ; rerun the SimPy trace with "
            f"--until {anylogic_horizon:g} before interpreting timing gaps."
        )
    print(
        f"Missing in SimPy: {len(missing_in_simpy)}  "
        f"Extra shared-event keys in SimPy: {len(extra_in_simpy)}  "
        f"Timestamp differences: {len(diffs)}"
    )
    if diagnostic_anylogic_events:
        diagnostic_counts = Counter(event.event for event in diagnostic_anylogic_events)
        print(
            f"Ignored AnyLogic diagnostic events: {len(diagnostic_anylogic_events)} "
            f"across {len(diagnostic_counts)} event types"
        )
    if diagnostic_simpy_events:
        diagnostic_counts = Counter(event.event for event in diagnostic_simpy_events)
        print(
            f"Ignored SimPy diagnostic events: {len(diagnostic_simpy_events)} "
            f"across {len(diagnostic_counts)} event types"
        )

    event_count_diffs = []
    for event_name in sorted(set(anylogic_counts) | set(simpy_counts)):
        diff = simpy_counts[event_name] - anylogic_counts[event_name]
        if diff and event_name in anylogic_counts:
            event_count_diffs.append((event_name, anylogic_counts[event_name], simpy_counts[event_name]))
    if event_count_diffs:
        print("\nEvent count differences:")
        for event_name, anylogic_count, simpy_count in event_count_diffs[:top]:
            print(
                f"  {event_name}: AnyLogic={anylogic_count} SimPy={simpy_count}"
            )

    if diffs:
        diffs_by_event: defaultdict[str, list[float]] = defaultdict(list)
        for diff, key, _anylogic_time, _simpy_time in diffs:
            diffs_by_event[key[2]].append(diff)

        print("\nTimestamp difference summary by event:")
        print(
            "  "
            f"{'Event':<38} {'Count':>6} {'Mean Abs':>10} "
            f"{'Max Abs':>10} {'Mean':>10}"
        )
        for event_name, event_diffs in sorted(
            diffs_by_event.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )[:top]:
            abs_diffs = [abs(diff) for diff in event_diffs]
            print(
                "  "
                f"{event_name:<38} {len(event_diffs):>6} "
                f"{sum(abs_diffs) / len(abs_diffs):>10.3f} "
                f"{max(abs_diffs):>10.3f} "
                f"{sum(event_diffs) / len(event_diffs):>+10.3f}"
            )

        print("\nFirst timestamp differences:")
        for diff, key, anylogic_time, simpy_time in sorted(
            diffs,
            key=lambda row: (row[2], row[1]),
        )[:top]:
            print(
                f"  {key}: AnyLogic={anylogic_time:.6f} "
                f"SimPy={simpy_time:.6f} diff={diff:+.6f}"
            )

        diffs.sort(
            key=lambda row: (
                abs(row[0]),
                anylogic_by_key[row[1]].time_s,
                row[1],
            ),
            reverse=True,
        )
        print("\nLargest timestamp differences:")
        for diff, key, anylogic_time, simpy_time in diffs[:top]:
            print(
                f"  {key}: AnyLogic={anylogic_time:.6f} "
                f"SimPy={simpy_time:.6f} diff={diff:+.6f}"
            )
    else:
        print("\nAll shared trace events match exactly.")

    if missing_in_simpy:
        print("\nFirst events missing in SimPy:")
        for key in sorted(
            missing_in_simpy,
            key=lambda item: (anylogic_by_key[item].time_s, item),
        )[:top]:
            print(f"  {key}: AnyLogic={anylogic_by_key[key].time_s:.6f}")

    if extra_in_simpy:
        print("\nFirst extra SimPy shared-event keys:")
        for key in sorted(
            extra_in_simpy,
            key=lambda item: (simpy_by_key[item].time_s, item),
        )[:top]:
            print(f"  {key}: SimPy={simpy_by_key[key].time_s:.6f}")

    print("=" * 92)
    return 1 if missing_in_simpy or extra_in_simpy or diffs or event_count_diffs else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 4 TRACE rows."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 4/log_file.txt",
        help="AnyLogic Model 4 log file containing TRACE rows.",
    )
    parser.add_argument(
        "--trace-iteration",
        type=int,
        default=None,
        help=(
            "Specific traced AnyLogic iteration to compare. When omitted, "
            "the first iteration with TRACE rows is used."
        ),
    )
    parser.add_argument(
        "--simpy-trace",
        default=None,
        help="Optional pre-generated SimPy trace CSV. If omitted, SimPy is run.",
    )
    parser.add_argument(
        "--output-simpy-trace",
        default=None,
        help="Optional CSV path for the generated SimPy trace.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=12,
        help="Maximum mismatches to print per section.",
    )
    args = parser.parse_args()

    try:
        anylogic_trace = parse_anylogic_trace(
            args.anylogic,
            selected_iteration=args.trace_iteration,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"AnyLogic iteration: {anylogic_trace.iteration}")
    print(f"Parameters: {_format_params(anylogic_trace.params)}")

    if args.simpy_trace:
        simpy_events = parse_simpy_trace(args.simpy_trace)
    else:
        simpy_events = run_simpy_trace(
            params=anylogic_trace.params,
            until=max(event.time_s for event in anylogic_trace.events),
            output_path=args.output_simpy_trace,
        )

    raise SystemExit(
        compare_traces(
            anylogic_events=anylogic_trace.events,
            simpy_events=simpy_events,
            top=args.top,
        )
    )


if __name__ == "__main__":
    main()
