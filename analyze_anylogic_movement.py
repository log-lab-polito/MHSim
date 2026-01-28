"""
Analyze AnyLogic forklift movement to extract exact acceleration, deceleration, and max speed.
Generates plots for trajectory, position, speed, and acceleration.
"""

from __future__ import annotations

import math
import re
import argparse
from collections import deque
from pathlib import Path
from typing import List, Tuple, Dict

import matplotlib.pyplot as plt
import numpy as np

LOG_PATH = Path("anylogic/Model 1/log_file.txt")

Position = Tuple[float, float, float, float]  # t, x, y, z


def parse_log_file(path: Path, max_lines: int | None = None) -> List[Position]:
    """Parse AnyLogic log lines into (t, x, y, z) in meters."""
    positions: List[Position] = []
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    with path.open() as f:
        for i, line in enumerate(f):
            if max_lines and i >= max_lines:
                break
            m = re.match(
                r"\[(\d+\.\d+)s\] Forklift position: \(([-\d\.]+), ([-\d\.]+), ([-\d\.]+),",
                line.strip(),
            )
            if m:
                t = float(m.group(1))
                # AnyLogic positions are in 10*m; scale to meters.
                x = float(m.group(2)) / 10.0
                y = float(m.group(3)) / 10.0
                z = float(m.group(4)) / 10.0
                positions.append((t, x, y, z))
    return positions


def compute_speeds(positions: List[Position]) -> List[Tuple[float, float]]:
    speeds: List[Tuple[float, float]] = []
    for i in range(1, len(positions)):
        t1, x1, y1, _ = positions[i - 1]
        t2, x2, y2, _ = positions[i]
        dt = t2 - t1
        if dt <= 0:
            continue
        dist = math.hypot(x2 - x1, y2 - y1)
        speeds.append((t2, dist / dt))
    return speeds


def smooth_positions(positions: List[Position], window: int) -> List[Position]:
    if window <= 1:
        return positions
    window = int(window)
    if window <= 1:
        return positions

    smoothed: List[Position] = []
    xs: deque[float] = deque()
    ys: deque[float] = deque()
    zs: deque[float] = deque()
    sum_x = 0.0
    sum_y = 0.0
    sum_z = 0.0

    for t, x, y, z in positions:
        xs.append(x)
        ys.append(y)
        zs.append(z)
        sum_x += x
        sum_y += y
        sum_z += z
        if len(xs) > window:
            sum_x -= xs.popleft()
            sum_y -= ys.popleft()
            sum_z -= zs.popleft()
        count = len(xs)
        smoothed.append((t, sum_x / count, sum_y / count, sum_z / count))
    return smoothed


def downsample_positions(positions: List[Position], interval: float | None) -> List[Position]:
    if interval is None or interval <= 0:
        return positions
    sampled = [positions[0]]
    last_t = positions[0][0]
    for pos in positions[1:]:
        if pos[0] - last_t >= interval - 1e-9:
            sampled.append(pos)
            last_t = pos[0]
    return sampled


def apply_time_window(positions: List[Position], max_time: float | None) -> List[Position]:
    if max_time is None:
        return positions
    return [p for p in positions if p[0] <= max_time]


def describe_values(values: List[float]) -> Dict[str, float] | None:
    if not values:
        return None
    arr = np.array(values, dtype=float)
    return {
        "count": float(len(values)),
        "raw_max": float(np.max(arr)),
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
    }


def print_stats(label: str, values: List[float], unit: str) -> None:
    stats = describe_values(values)
    if stats is None:
        print(f"{label}: no samples")
        return
    print(
        f"{label}: count {int(stats['count'])}, raw max {stats['raw_max']:.2f} {unit}, "
        f"median {stats['median']:.2f}, 95th pct {stats['p95']:.2f}"
    )


def compute_accelerations(speeds: List[Tuple[float, float]]) -> List[Tuple[float, float, float]]:
    accels: List[Tuple[float, float, float]] = []
    for i in range(1, len(speeds)):
        t1, v1 = speeds[i - 1]
        t2, v2 = speeds[i]
        dt = t2 - t1
        if 0 < dt < 0.6:
            accels.append((t2, (v2 - v1) / dt, v2))
    return accels


def detect_phases(accels: List[Tuple[float, float, float]]) -> Dict[str, List[Tuple[float, float, float]]]:
    accel_phase = [(t, a, v) for t, a, v in accels if a > 1.0]
    cruise_phase = [(t, a, v)
                    for t, a, v in accels if abs(a) < 0.5 and v > 8.0]
    decel_phase = [(t, a, v) for t, a, v in accels if a < -1.0]
    return {
        "acceleration": accel_phase,
        "cruise": cruise_phase,
        "deceleration": decel_phase,
        "all": accels,
    }


def summarize_phases(phases: Dict[str, List[Tuple[float, float, float]]]) -> Dict[str, float]:
    summary: Dict[str, float] = {}
    if phases["acceleration"]:
        acc_vals = [a for _, a, _ in phases["acceleration"]]
        summary["accel"] = float(np.median(acc_vals))
    if phases["cruise"]:
        cruise_vals = [v for _, _, v in phases["cruise"]]
        summary["max_speed"] = float(np.median(cruise_vals))
    if phases["deceleration"]:
        decel_vals = [abs(a) for _, a, _ in phases["deceleration"]]
        summary["decel"] = float(np.median(decel_vals))
    return summary


def plot_results(
    positions: List[Position],
    speeds: List[Tuple[float, float]],
    accels: List[Tuple[float, float, float]],
    summary: Dict[str, float],
    max_time: float = 200.0,
    output: str = "anylogic_movement_analysis.png",
    sampling_interval: float | None = None,
) -> None:
    pos_f = [(t, x, y, z) for t, x, y, z in positions if t <= max_time]
    times = [p[0] for p in pos_f]
    xs = [p[1] for p in pos_f]
    ys = [p[2] for p in pos_f]

    speed_times = [t for t, _ in speeds if t <= max_time]
    speed_vals = [v for t, v in speeds if t <= max_time]

    accel_times = [t for t, _, _ in accels if t <= max_time]
    accel_vals = [a for t, a, _ in accels if t <= max_time]

    exact_v = summary.get("max_speed", 0.0)
    exact_a = summary.get("accel", 0.0)
    exact_d = summary.get("decel", 0.0)

    fig, axes = plt.subplots(4, 1, figsize=(14, 12))
    if sampling_interval is not None:
        title = f"AnyLogic Forklift Movement Analysis ({sampling_interval:.2f}s resolution)"
    else:
        title = "AnyLogic Forklift Movement Analysis"
    fig.suptitle(title, fontsize=16, fontweight="bold")

    ax = axes[0]
    ax.plot(xs, ys, "b-", lw=1.3, alpha=0.75)
    ax.scatter(xs[0], ys[0], c="green", s=70, label="Start", zorder=5)
    ax.scatter(xs[-1], ys[-1], c="red", s=70,
               marker="s", label="End", zorder=5)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_title("Trajectory")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_aspect("equal", adjustable="datalim")

    ax = axes[1]
    ax.plot(times, xs, "r-", lw=1.1, label="X")
    ax.plot(times, ys, "b-", lw=1.1, label="Y")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Position (m)")
    ax.set_title("Position vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()

    ax = axes[2]
    ax.plot(speed_times, speed_vals, "g-", lw=1.3, alpha=0.8)
    if exact_v:
        ax.axhline(exact_v, color="orange", ls="--", lw=1.5,
                   label=f"Max speed {exact_v:.2f} m/s")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (m/s)")
    ax.set_title("Speed vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim(bottom=-0.5)

    ax = axes[3]
    ax.plot(accel_times, accel_vals, color="purple", lw=1.1, alpha=0.8)
    ax.axhline(0, color="black", lw=0.8, alpha=0.5)
    if exact_a:
        ax.axhline(exact_a, color="green", ls="--", lw=1.3,
                   label=f"Accel {exact_a:.2f} m/s²")
    if exact_d:
        ax.axhline(-exact_d, color="red", ls="--", lw=1.3,
                   label=f"Decel {-exact_d:.2f} m/s²")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Acceleration (m/s²)")
    ax.set_title("Acceleration vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim([-10, 10])

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved plot to {output}")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze AnyLogic forklift movement and generate charts."
    )
    parser.add_argument("--max-time", type=float, default=200.0,
                        help="Max time shown on plots (s).")
    parser.add_argument(
        "--timeframe",
        type=float,
        default=None,
        help="Time window shown on plots (s). Overrides --max-time if set.",
    )
    parser.add_argument(
        "--smooth-window",
        type=int,
        default=1,
        help="Trailing moving-average window in samples (1 disables).",
    )
    parser.add_argument(
        "--downsample-interval",
        type=float,
        default=None,
        help="Downsample to at least this interval in seconds (disabled if unset).",
    )
    parser.add_argument(
        "--output",
        default="anylogic_movement_analysis.png",
        help="Output image filename.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("=" * 70)
    print("ANYLOGIC FORKLIFT MOVEMENT ANALYSIS")
    print("=" * 70)

    raw_positions = parse_log_file(LOG_PATH)
    if not raw_positions:
        raise RuntimeError("No positions parsed from log file")

    print(
        f"Raw samples: {len(raw_positions)} from {raw_positions[0][0]:.2f}s to {raw_positions[-1][0]:.2f}s"
    )

    positions = smooth_positions(raw_positions, window=args.smooth_window)
    positions = downsample_positions(positions, interval=args.downsample_interval)
    if len(positions) < 2:
        raise RuntimeError("Not enough positions after smoothing/downsampling.")

    max_time = args.timeframe if args.timeframe is not None else args.max_time
    positions = apply_time_window(positions, max_time)
    if len(positions) < 2:
        raise RuntimeError("Not enough positions within the max time window.")

    speeds = compute_speeds(positions)
    accels = compute_accelerations(speeds)
    phases = detect_phases(accels)
    summary = summarize_phases(phases)
    speed_vals = [v for _, v in speeds if v > 1e-6]
    if speed_vals:
        summary["max_speed"] = float(np.percentile(speed_vals, 95))

    print(
        f"Parsed {len(positions)} samples from {positions[0][0]:.2f}s to {positions[-1][0]:.2f}s")
    if len(positions) >= 2:
        deltas = [positions[i][0] - positions[i - 1][0]
                  for i in range(1, len(positions))]
        sampling_interval = float(np.median([dt for dt in deltas if dt > 0]))
        print(f"Sampling interval (median): {sampling_interval:.2f}s")
    else:
        sampling_interval = None
    if args.smooth_window > 1:
        print(
            f"Smoothing: trailing average window = {args.smooth_window} samples")
    if args.downsample_interval is not None and args.downsample_interval > 0:
        print(f"Downsampling: min interval = {args.downsample_interval:.2f}s")
    print_stats("Speed (m/s)", [v for _, v in speeds], "m/s")
    accel_vals = [a for _, a, _ in accels]
    print_stats("Acceleration (m/s^2)", [a for a in accel_vals if a > 0], "m/s^2")
    print_stats("Deceleration (m/s^2)", [abs(a) for a in accel_vals if a < 0], "m/s^2")

    print("\nGenerating plots...")
    max_time = args.timeframe if args.timeframe is not None else args.max_time
    plot_results(
        positions,
        speeds,
        accels,
        summary,
        max_time=max_time,
        output=args.output,
        sampling_interval=sampling_interval,
    )


if __name__ == "__main__":
    main()
