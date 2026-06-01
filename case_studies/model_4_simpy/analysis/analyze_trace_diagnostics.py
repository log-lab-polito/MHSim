from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Iterable


BRANCH_TIMING_PAIRS = (
    ("branch_service_exit", "branch_convey_enter", "service_to_convey"),
    ("branch_convey_enter", "branch_conveyor_leading_edge_enter", "convey_to_leading_enter"),
    (
        "branch_conveyor_leading_edge_enter",
        "branch_conveyor_trailing_edge_enter",
        "leading_to_trailing_enter",
    ),
    (
        "branch_conveyor_leading_edge_enter",
        "branch_conveyor_leading_edge_exit",
        "leading_enter_to_exit",
    ),
    (
        "branch_conveyor_trailing_edge_enter",
        "branch_conveyor_leading_edge_exit",
        "trailing_enter_to_leading_exit",
    ),
    (
        "branch_conveyor_leading_edge_exit",
        "branch_conveyor_trailing_edge_exit",
        "leading_to_trailing_exit",
    ),
    ("branch_convey_enter", "branch_convey_at_exit", "convey_enter_to_at_exit"),
    (
        "branch_conveyor_leading_edge_exit",
        "branch_convey_at_exit",
        "leading_exit_to_at_exit",
    ),
    (
        "branch_conveyor_trailing_edge_exit",
        "branch_convey_at_exit",
        "trailing_exit_to_at_exit",
    ),
)
BRANCH_COMPARISON_EVENTS = (
    "branch_service_exit",
    "branch_convey_enter",
    "branch_conveyor_leading_edge_enter",
    "branch_conveyor_trailing_edge_enter",
    "branch_conveyor_leading_edge_exit",
    "branch_conveyor_trailing_edge_exit",
    "branch_convey_at_exit",
)
BRANCH_ANCHOR_EVENT = "branch_convey_at_exit"
BRANCH_ANCHORED_EVENTS = tuple(
    event for event in BRANCH_COMPARISON_EVENTS if event != BRANCH_ANCHOR_EVENT
)


def _format_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _parse_detail_fields(parts: list[str]) -> dict[str, float | str]:
    details: dict[str, float | str] = {}
    for field in parts[7:]:
        if "=" not in field:
            continue
        key, value = field.split("=", 1)
        try:
            details[key] = float(value)
        except ValueError:
            details[key] = value
    return details


def _parse_csv_detail_fields(row: dict[str, str]) -> dict[str, float | str]:
    details: dict[str, float | str] = {}
    for field_name, field in row.items():
        if not field_name.startswith("detail_") or not field or "=" not in field:
            continue
        key, value = field.split("=", 1)
        try:
            details[key] = float(value)
        except ValueError:
            details[key] = value
    return details


def _summarize(values: Iterable[float]) -> str:
    observed = list(values)
    if not observed:
        return "count=0"
    return (
        f"count={len(observed)} "
        f"min={_format_number(min(observed))} "
        f"mean={_format_number(mean(observed))} "
        f"max={_format_number(max(observed))}"
    )


def _summarize_diffs(values: Iterable[float]) -> str:
    observed = list(values)
    if not observed:
        return "count=0"
    abs_values = [abs(value) for value in observed]
    return (
        f"count={len(observed)} "
        f"mean_abs={_format_number(mean(abs_values))} "
        f"max_abs={_format_number(max(abs_values))} "
        f"mean={_format_number(mean(observed))}"
    )


def _parse_simpy_branch_trace(
    path: Path,
) -> tuple[
    dict[int, dict[str, float]],
    Counter[str],
    defaultdict[str, defaultdict[str, list[float]]],
]:
    next_seq_by_origin: defaultdict[str, int] = defaultdict(int)
    seq_by_pallet_id: dict[int, int] = {}
    events_by_seq: defaultdict[int, dict[str, float]] = defaultdict(dict)
    diag_counts: Counter[str] = Counter()
    diag_details: defaultdict[str, defaultdict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            time_s = float(row["time_s"])
            event = row["event"]
            pallet_id = int(row["pallet_id"])
            origin = row["origin"]

            if event.endswith("_source_exit"):
                next_seq_by_origin[origin] += 1
                seq_by_pallet_id[pallet_id] = next_seq_by_origin[origin]

            if origin != "branch":
                continue
            seq = seq_by_pallet_id.get(pallet_id)
            if seq is None:
                continue
            events_by_seq[seq][event] = time_s
            if event.startswith("diag_"):
                diag_counts[event] += 1
                for key, value in _parse_csv_detail_fields(row).items():
                    if isinstance(value, float):
                        diag_details[event][key].append(value)

    return dict(events_by_seq), diag_counts, diag_details


def _print_diagnostic_summary(
    *,
    title: str,
    diag_counts: Counter[str],
    diag_details: defaultdict[str, defaultdict[str, list[float]]],
) -> None:
    if not diag_counts:
        print(f"\nNo {title} diag_ rows found.")
        return

    print(f"\n{title} diagnostic event counts:")
    for event, count in sorted(diag_counts.items()):
        print(f"  {event}: {count}")

    print(f"\n{title} diagnostic detail summaries:")
    for event in sorted(diag_details):
        print(f"  {event}:")
        for field_name, values in sorted(diag_details[event].items()):
            print(f"    {field_name}: {_summarize(values)}")


def _print_simpy_comparison(
    *,
    anylogic_events_by_seq: dict[int, dict[str, float]],
    simpy_events_by_seq: dict[int, dict[str, float]],
    seq_from: int,
    seq_to: int,
) -> None:
    print("\nSimPy comparison by branch event:")
    for event in BRANCH_COMPARISON_EVENTS:
        diffs = [
            simpy_events_by_seq[seq][event] - anylogic_events_by_seq[seq][event]
            for seq in sorted(anylogic_events_by_seq)
            if event in anylogic_events_by_seq[seq]
            and event in simpy_events_by_seq.get(seq, {})
        ]
        print(f"  {event}: {_summarize_diffs(diffs)}")

    print("\nSimPy comparison by branch event and sequence phase:")
    for event in BRANCH_COMPARISON_EVENTS:
        print(f"  {event}:")
        for phase in range(5):
            diffs = [
                simpy_events_by_seq[seq][event] - anylogic_events_by_seq[seq][event]
                for seq in sorted(anylogic_events_by_seq)
                if seq % 5 == phase
                and event in anylogic_events_by_seq[seq]
                and event in simpy_events_by_seq.get(seq, {})
            ]
            print(f"    seq%5={phase}: {_summarize_diffs(diffs)}")

    print(f"\nSimPy diff window: {seq_from}..{seq_to}")
    print("  seq " + " ".join(f"{event:>37}" for event in BRANCH_COMPARISON_EVENTS))
    for seq in range(seq_from, seq_to + 1):
        anylogic_row = anylogic_events_by_seq.get(seq)
        simpy_row = simpy_events_by_seq.get(seq)
        if not anylogic_row or not simpy_row:
            continue
        values = []
        for event in BRANCH_COMPARISON_EVENTS:
            if event not in anylogic_row or event not in simpy_row:
                values.append(" " * 37)
            else:
                diff = simpy_row[event] - anylogic_row[event]
                values.append(f"{_format_number(diff):>37}")
        print(f"  {seq:>3} " + " ".join(values))


def _anchored_interval(
    row: dict[str, float],
    event: str,
    anchor_event: str = BRANCH_ANCHOR_EVENT,
) -> float | None:
    if event not in row or anchor_event not in row:
        return None
    return row[event] - row[anchor_event]


def _print_anchored_callback_comparison(
    *,
    anylogic_events_by_seq: dict[int, dict[str, float]],
    simpy_events_by_seq: dict[int, dict[str, float]],
    seq_from: int,
    seq_to: int,
) -> None:
    print(f"\nBranch callback intervals relative to {BRANCH_ANCHOR_EVENT}:")
    for event in BRANCH_ANCHORED_EVENTS:
        anylogic_intervals: list[float] = []
        simpy_intervals: list[float] = []
        interval_diffs: list[float] = []
        for seq in sorted(anylogic_events_by_seq):
            anylogic_interval = _anchored_interval(anylogic_events_by_seq[seq], event)
            simpy_interval = _anchored_interval(simpy_events_by_seq.get(seq, {}), event)
            if anylogic_interval is None or simpy_interval is None:
                continue
            anylogic_intervals.append(anylogic_interval)
            simpy_intervals.append(simpy_interval)
            interval_diffs.append(simpy_interval - anylogic_interval)

        print(f"  {event}:")
        print(f"    AnyLogic event-anchor: {_summarize(anylogic_intervals)}")
        print(f"    SimPy event-anchor:    {_summarize(simpy_intervals)}")
        print(f"    SimPy-AnyLogic delta:  {_summarize_diffs(interval_diffs)}")

    print("\nBranch callback relative interval delta by sequence phase:")
    for event in BRANCH_ANCHORED_EVENTS:
        print(f"  {event}:")
        for phase in range(5):
            interval_diffs: list[float] = []
            for seq in sorted(anylogic_events_by_seq):
                if seq % 5 != phase:
                    continue
                anylogic_interval = _anchored_interval(anylogic_events_by_seq[seq], event)
                simpy_interval = _anchored_interval(
                    simpy_events_by_seq.get(seq, {}), event
                )
                if anylogic_interval is None or simpy_interval is None:
                    continue
                interval_diffs.append(simpy_interval - anylogic_interval)
            print(f"    seq%5={phase}: {_summarize_diffs(interval_diffs)}")

    print(f"\nRelative interval delta window: {seq_from}..{seq_to}")
    print("  seq " + " ".join(f"{event:>37}" for event in BRANCH_ANCHORED_EVENTS))
    for seq in range(seq_from, seq_to + 1):
        anylogic_row = anylogic_events_by_seq.get(seq)
        simpy_row = simpy_events_by_seq.get(seq)
        if not anylogic_row or not simpy_row:
            continue
        values = []
        for event in BRANCH_ANCHORED_EVENTS:
            anylogic_interval = _anchored_interval(anylogic_row, event)
            simpy_interval = _anchored_interval(simpy_row, event)
            if anylogic_interval is None or simpy_interval is None:
                values.append(" " * 37)
            else:
                values.append(f"{_format_number(simpy_interval - anylogic_interval):>37}")
        print(f"  {seq:>3} " + " ".join(values))


def analyze_trace(
    path: Path,
    *,
    iteration: int,
    seq_from: int,
    seq_to: int,
    simpy_trace: Path | None = None,
) -> None:
    next_seq_by_origin: defaultdict[str, int] = defaultdict(int)
    seq_by_pallet_id: dict[int, int] = {}
    events_by_seq: defaultdict[int, dict[str, float]] = defaultdict(dict)
    diag_counts: Counter[str] = Counter()
    diag_details: defaultdict[str, defaultdict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    with path.open() as handle:
        for raw_line in handle:
            if not raw_line.startswith("TRACE\t"):
                continue
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) < 6 or int(parts[1]) != iteration:
                continue

            time_s = float(parts[2])
            event = parts[3]
            pallet_id = int(parts[4])
            origin = parts[5]

            if event.startswith("diag_"):
                diag_counts[event] += 1
                for key, value in _parse_detail_fields(parts).items():
                    if isinstance(value, float):
                        diag_details[event][key].append(value)

            if event.endswith("_source_exit"):
                next_seq_by_origin[origin] += 1
                seq_by_pallet_id[pallet_id] = next_seq_by_origin[origin]

            if origin != "branch":
                continue
            seq = seq_by_pallet_id.get(pallet_id)
            if seq is None:
                continue

            events_by_seq[seq][event] = time_s

    print("AnyLogic Model 4 diagnostic trace")
    print(f"Iteration: {iteration}")
    print(f"Branch sequences observed: {len(events_by_seq)}")

    if diag_counts:
        _print_diagnostic_summary(
            title="AnyLogic",
            diag_counts=diag_counts,
            diag_details=diag_details,
        )
    else:
        print("\nNo diag_ TRACE rows found.")

    print("\nBranch timing summaries:")
    for start_event, end_event, label in BRANCH_TIMING_PAIRS:
        values = [
            row[end_event] - row[start_event]
            for row in events_by_seq.values()
            if start_event in row and end_event in row
        ]
        print(f"  {label}: {_summarize(values)}")

    print(f"\nBranch sequence window: {seq_from}..{seq_to}")
    labels = [label for _start, _end, label in BRANCH_TIMING_PAIRS]
    print("  seq " + " ".join(f"{label:>27}" for label in labels))
    for seq in range(seq_from, seq_to + 1):
        row = events_by_seq.get(seq)
        if not row:
            continue
        values = []
        for start_event, end_event, _label in BRANCH_TIMING_PAIRS:
            if start_event not in row or end_event not in row:
                values.append(" " * 27)
            else:
                values.append(f"{_format_number(row[end_event] - row[start_event]):>27}")
        print(f"  {seq:>3} " + " ".join(values))

    if simpy_trace is not None:
        simpy_events_by_seq, simpy_diag_counts, simpy_diag_details = (
            _parse_simpy_branch_trace(simpy_trace)
        )
        _print_diagnostic_summary(
            title="SimPy",
            diag_counts=simpy_diag_counts,
            diag_details=simpy_diag_details,
        )
        _print_simpy_comparison(
            anylogic_events_by_seq=dict(events_by_seq),
            simpy_events_by_seq=simpy_events_by_seq,
            seq_from=seq_from,
            seq_to=seq_to,
        )
        _print_anchored_callback_comparison(
            anylogic_events_by_seq=dict(events_by_seq),
            simpy_events_by_seq=simpy_events_by_seq,
            seq_from=seq_from,
            seq_to=seq_to,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize AnyLogic Model 4 diagnostic TRACE rows."
    )
    parser.add_argument(
        "--anylogic",
        default="anylogic/Model 4/log_file.txt",
        help="AnyLogic Model 4 log file containing TRACE rows.",
    )
    parser.add_argument(
        "--trace-iteration",
        type=int,
        default=5,
        help="Iteration containing diagnostic TRACE rows.",
    )
    parser.add_argument(
        "--seq-from",
        type=int,
        default=45,
        help="First branch origin sequence to print in the detailed window.",
    )
    parser.add_argument(
        "--seq-to",
        type=int,
        default=60,
        help="Last branch origin sequence to print in the detailed window.",
    )
    parser.add_argument(
        "--simpy-trace",
        type=Path,
        help="Optional SimPy Model 4 trace CSV to compare by branch sequence.",
    )
    args = parser.parse_args()

    analyze_trace(
        Path(args.anylogic),
        iteration=args.trace_iteration,
        seq_from=args.seq_from,
        seq_to=args.seq_to,
        simpy_trace=args.simpy_trace,
    )


if __name__ == "__main__":
    main()
