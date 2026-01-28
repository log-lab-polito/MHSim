#!/usr/bin/env python3
"""
Analyze forklift dwell periods using AnyLogic movement + event logs.

Finds intervals where the forklift is stationary and correlates those
intervals with pallet block-enter events.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple, Dict, Optional

Position = Tuple[float, float, float, float]  # t, x, y, rot


@dataclass
class DwellInterval:
    start: float
    end: float
    x: float
    y: float
    z: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Event:
    time: float
    pallet_id: str
    block: str


def parse_movement_positions(path: Path) -> Iterable[Position]:
    pattern = re.compile(r"^\[(\d+\.?\d*)s\].*Forklift position:\s*\(([^)]*)\)")
    with path.open() as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m:
                continue
            t = float(m.group(1))
            parts = [p.strip() for p in m.group(2).split(",") if p.strip()]
            if len(parts) < 4:
                continue
            x, y, z, rot = (float(parts[i]) for i in range(4))
            yield (t, x / 10.0, y / 10.0, rot)


def detect_dwells(
    positions: Iterable[Position],
    move_eps: float = 1e-3,
    rot_eps: float = 1e-3,
    min_dwell: float = 0.5,
) -> List[DwellInterval]:
    dwells: List[DwellInterval] = []

    prev = None
    state_moving = None
    dwell_start = None
    dwell_pos = None

    for pos in positions:
        if prev is None:
            prev = pos
            continue

        t0, x0, y0, r0 = prev
        t1, x1, y1, r1 = pos
        dt = t1 - t0
        if dt <= 0:
            prev = pos
            continue

        dist = math.hypot(x1 - x0, y1 - y0)
        speed = dist / dt
        rot_rate = abs(r1 - r0) / dt
        moving = speed > move_eps or rot_rate > rot_eps

        if state_moving is None:
            state_moving = moving
            if not moving:
                dwell_start = t0
                dwell_pos = (x0, y0, 0.0)
        elif state_moving and not moving:
            dwell_start = t0
            dwell_pos = (x0, y0, 0.0)
            state_moving = False
        elif not state_moving and moving:
            dwell_end = t0
            if dwell_start is not None and dwell_end - dwell_start >= min_dwell:
                x, y, z = dwell_pos if dwell_pos else (x0, y0, 0.0)
                dwells.append(DwellInterval(dwell_start, dwell_end, x, y, z))
            dwell_start = None
            dwell_pos = None
            state_moving = True

        prev = pos

    if not state_moving and dwell_start is not None and prev is not None:
        t_last = prev[0]
        if t_last - dwell_start >= min_dwell:
            x, y, z = dwell_pos if dwell_pos else (prev[1], prev[2], 0.0)
            dwells.append(DwellInterval(dwell_start, t_last, x, y, z))

    return dwells


def parse_events(path: Path) -> List[Event]:
    pattern = re.compile(r"^Pallet\s+(\d+)\s+entering\s+(\w+)\s+block\s+at\s+([\d\.]+)")
    events: List[Event] = []
    with path.open() as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m:
                continue
            pallet_id, block, t = m.group(1), m.group(2), float(m.group(3))
            events.append(Event(time=t, pallet_id=pallet_id, block=block))
    return sorted(events, key=lambda e: e.time)

def build_pallet_timelines(events: List[Event]) -> Dict[str, List[Event]]:
    pallets: Dict[str, List[Event]] = {}
    for ev in events:
        pallets.setdefault(ev.pallet_id, []).append(ev)
    for pallet_id, evs in pallets.items():
        evs.sort(key=lambda e: e.time)
    return pallets


def compute_block_durations(
    pallets: Dict[str, List[Event]],
    block_order: List[str],
) -> Dict[str, List[float]]:
    durations: Dict[str, List[float]] = {b: [] for b in block_order}
    for _, evs in pallets.items():
        for i in range(len(evs) - 1):
            cur = evs[i]
            nxt = evs[i + 1]
            if cur.block not in durations:
                continue
            if nxt.time <= cur.time:
                continue
            durations[cur.block].append(nxt.time - cur.time)
    return durations


def summarize_block_durations(durations: List[float]) -> Dict[str, float]:
    if not durations:
        return {}
    vals = sorted(durations)
    n = len(vals)
    p50 = vals[n // 2]
    p90 = vals[int(n * 0.9)]
    return {
        "count": n,
        "median": p50,
        "p90": p90,
        "max": vals[-1],
        "mean": sum(vals) / n,
    }


def parse_expected_durations(args: argparse.Namespace) -> Dict[str, Optional[float]]:
    return {
        "service1": args.expected_service1,
        "store": args.expected_store,
        "delay": args.expected_delay,
        "retrieve": args.expected_retrieve,
        "service2": args.expected_service2,
    }

def count_block_entries(events: List[Event]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for ev in events:
        counts[ev.block] = counts.get(ev.block, 0) + 1
    return counts


def correlate(dwells: List[DwellInterval], events: List[Event]) -> List[Dict[str, object]]:
    results = []
    if not dwells:
        return results

    dwells_sorted = sorted(dwells, key=lambda d: d.start)
    i = 0
    for dwell in dwells_sorted:
        dwell_events: List[Event] = []
        while i < len(events) and events[i].time < dwell.start:
            i += 1
        j = i
        while j < len(events) and events[j].time <= dwell.end:
            dwell_events.append(events[j])
            j += 1
        results.append(
            {
                "dwell": dwell,
                "events": dwell_events,
            }
        )
    return results


def dwell_block_overlap(
    dwells: List[DwellInterval],
    pallets: Dict[str, List[Event]],
) -> List[Dict[str, object]]:
    results = []
    for dwell in dwells:
        block_counts: Dict[str, int] = {}
        for _, evs in pallets.items():
            for i in range(len(evs) - 1):
                cur = evs[i]
                nxt = evs[i + 1]
                if nxt.time <= cur.time:
                    continue
                if cur.time <= dwell.end and nxt.time >= dwell.start:
                    block_counts[cur.block] = block_counts.get(cur.block, 0) + 1
        results.append({"dwell": dwell, "blocks": block_counts})
    return results


def summarize(dwells: List[DwellInterval]) -> Dict[str, float]:
    if not dwells:
        return {}
    durations = [d.duration for d in dwells]
    durations.sort()
    total = sum(durations)
    p50 = durations[len(durations) // 2]
    p90 = durations[int(len(durations) * 0.9)]
    return {
        "count": len(dwells),
        "total": total,
        "median": p50,
        "p90": p90,
        "max": max(durations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze AnyLogic forklift dwell periods.")
    parser.add_argument("--movement-log", default="anylogic/Model 1/log_file.txt")
    parser.add_argument("--event-log", default="logs/anylogic_model_1.txt")
    parser.add_argument("--label", default="AnyLogic")
    parser.add_argument("--skip-dwell", action="store_true")
    parser.add_argument("--move-eps", type=float, default=1e-3)
    parser.add_argument("--rot-eps", type=float, default=1e-3)
    parser.add_argument("--min-dwell", type=float, default=0.5)
    parser.add_argument("--max-dwells", type=int, default=20)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--expected-service1", type=float, default=30.0)
    parser.add_argument("--expected-store", type=float, default=None)
    parser.add_argument("--expected-delay", type=float, default=300.0)
    parser.add_argument("--expected-retrieve", type=float, default=None)
    parser.add_argument("--expected-service2", type=float, default=30.0)
    args = parser.parse_args()

    movement_log = Path(args.movement_log)
    event_log = Path(args.event_log)

    if args.skip_dwell:
        dwells: List[DwellInterval] = []
    else:
        dwells = detect_dwells(
            parse_movement_positions(movement_log),
            move_eps=args.move_eps,
            rot_eps=args.rot_eps,
            min_dwell=args.min_dwell,
        )
    events = parse_events(event_log)
    entry_counts = count_block_entries(events)
    pallets = build_pallet_timelines(events)
    block_order = ["service1", "store", "delay", "retrieve", "service2", "sink"]
    durations_by_block = compute_block_durations(pallets, block_order)
    expected = parse_expected_durations(args)
    summary = summarize(dwells)

    print("=" * 70)
    print(f"{args.label.upper()} DWELL ANALYSIS")
    print("=" * 70)
    if args.skip_dwell:
        print("Dwells: skipped")
    elif summary:
        print(
            f"Dwells: {summary['count']} | total {summary['total']:.1f}s | "
            f"median {summary['median']:.2f}s | p90 {summary['p90']:.2f}s | max {summary['max']:.2f}s"
        )
    else:
        print("No dwells detected.")

    if not args.skip_dwell:
        combined = correlate(dwells, events)
        overlap = dwell_block_overlap(dwells, pallets)
        shown = 0
        for item in combined:
            if shown >= args.max_dwells:
                break
            dwell = item["dwell"]
            evs = item["events"]
            if not evs:
                continue
            block_counts: Dict[str, int] = {}
            for ev in evs:
                block_counts[ev.block] = block_counts.get(ev.block, 0) + 1
            blocks = ", ".join(f"{k}:{v}" for k, v in sorted(block_counts.items()))
            print(
                f"Dwell {dwell.start:.2f}-{dwell.end:.2f} ({dwell.duration:.2f}s) "
                f"at ({dwell.x:.2f},{dwell.y:.2f}) -> {blocks}"
            )
            shown += 1

    print(f"\nBlock duration summary ({args.label} log):")
    for block in block_order:
        stats = summarize_block_durations(durations_by_block.get(block, []))
        entries = entry_counts.get(block, 0)
        if not stats:
            if entries:
                print(f"- {block}: no duration samples (entries={entries})")
            else:
                print(f"- {block}: no samples")
            continue
        exp = expected.get(block)
        exp_str = f"{exp:.2f}s" if exp is not None else "n/a"
        print(
            f"- {block}: n={stats['count']} median={stats['median']:.2f}s "
            f"p90={stats['p90']:.2f}s max={stats['max']:.2f}s mean={stats['mean']:.2f}s "
            f"entries={entries} "
            f"(expected {exp_str})"
        )

    if not args.skip_dwell:
        print("\nDwells overlapped by block (first shown):")
        shown = 0
        for item in overlap:
            if shown >= args.max_dwells:
                break
            dwell = item["dwell"]
            blocks = item["blocks"]
            if not blocks:
                continue
            blocks_str = ", ".join(f"{k}:{v}" for k, v in sorted(blocks.items()))
            print(
                f"Dwell {dwell.start:.2f}-{dwell.end:.2f} ({dwell.duration:.2f}s) "
                f"-> {blocks_str}"
            )
            shown += 1

    if args.csv:
        out = Path(args.csv)
        with out.open("w") as f:
            f.write("dwell_start,dwell_end,duration,x,y,z,blocks\n")
            for item in combined:
                dwell = item["dwell"]
                evs = item["events"]
                block_counts: Dict[str, int] = {}
                for ev in evs:
                    block_counts[ev.block] = block_counts.get(ev.block, 0) + 1
                blocks = ";".join(f"{k}:{v}" for k, v in sorted(block_counts.items()))
                f.write(
                    f"{dwell.start:.4f},{dwell.end:.4f},{dwell.duration:.4f},"
                    f"{dwell.x:.4f},{dwell.y:.4f},{dwell.z:.4f},{blocks}\n"
                )
        print(f"Saved CSV to {out}")


if __name__ == "__main__":
    main()
