#!/usr/bin/env python3
"""
Analyze SimPy Model 1 forklift movement to extract speed and acceleration.
Generates plots for trajectory, position, speed, and acceleration.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
CASE_STUDIES = ROOT / "case_studies"
if str(CASE_STUDIES) not in sys.path:
    sys.path.insert(0, str(CASE_STUDIES))

from model_1_simpy.model import Model1SimModel
from model_1_simpy.visualization import MovementRecorder, create_recording_process

Position = Tuple[float, float, float, float]  # t, x, y, z


def run_simulation(recording_interval: float, sim_time: float) -> MovementRecorder:
    model = Model1SimModel(enable_logging=False, console_logging=False)
    recorder = MovementRecorder()

    model.env.process(
        create_recording_process(
            model.env, model.fleet.forklifts, recorder, recording_interval=recording_interval
        )
    )
    model.source.start()
    model.env.run(until=sim_time)
    return recorder


def trajectory_to_positions(trajectory) -> List[Position]:
    return [
        (record.time, record.position.x, record.position.y, record.position.z)
        for record in trajectory.records
    ]


def select_trajectory(trajectories: Dict[str, object], forklift_id: str | None):
    if not trajectories:
        raise RuntimeError("No trajectories recorded. Try increasing sim time.")
    if forklift_id:
        if forklift_id not in trajectories:
            available = ", ".join(sorted(trajectories.keys()))
            raise KeyError(f"Forklift '{forklift_id}' not found. Available: {available}")
        return trajectories[forklift_id]
    return trajectories[sorted(trajectories.keys())[0]]


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
        if dt <= 0:
            continue
        accels.append((t2, (v2 - v1) / dt, v2))
    return accels


def summarize_movement(
    speeds: List[Tuple[float, float]],
    accels: List[Tuple[float, float, float]],
) -> Dict[str, float]:
    summary: Dict[str, float] = {}
    if speeds:
        speed_vals = [v for _, v in speeds if v > 1e-6]
        if speed_vals:
            summary["max_speed"] = float(np.percentile(speed_vals, 95))

    accel_eps = max(0.05, summary.get("max_speed", 0.0) * 0.05)
    if accels:
        pos_accels = [a for _, a, _ in accels if a > accel_eps]
        neg_accels = [a for _, a, _ in accels if a < -accel_eps]
        if pos_accels:
            summary["accel"] = float(np.median(pos_accels))
        if neg_accels:
            summary["decel"] = float(np.median([abs(a) for a in neg_accels]))
    return summary


def plot_results(
    positions: List[Position],
    speeds: List[Tuple[float, float]],
    accels: List[Tuple[float, float, float]],
    summary: Dict[str, float],
    max_time: float,
    output: str,
    recording_interval: float,
) -> None:
    pos_f = [(t, x, y, z) for t, x, y, z in positions if t <= max_time]
    if len(pos_f) < 2:
        raise RuntimeError("Not enough recorded positions to plot.")

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
    fig.suptitle(
        f"SimPy Model 1 Forklift Movement Analysis ({recording_interval:.2f}s resolution)",
        fontsize=16,
        fontweight="bold",
    )

    ax = axes[0]
    ax.plot(xs, ys, "b-", lw=1.3, alpha=0.75)
    ax.scatter(xs[0], ys[0], c="green", s=70, label="Start", zorder=5)
    ax.scatter(xs[-1], ys[-1], c="red", s=70, marker="s", label="End", zorder=5)
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
        ax.axhline(exact_v, color="orange", ls="--", lw=1.5, label=f"Max speed {exact_v:.2f} m/s")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (m/s)")
    ax.set_title("Speed vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim(bottom=-0.1)

    ax = axes[3]
    ax.plot(accel_times, accel_vals, color="purple", lw=1.1, alpha=0.8)
    ax.axhline(0, color="black", lw=0.8, alpha=0.5)
    if exact_a:
        ax.axhline(exact_a, color="green", ls="--", lw=1.3, label=f"Accel {exact_a:.2f} m/s²")
    if exact_d:
        ax.axhline(-exact_d, color="red", ls="--", lw=1.3, label=f"Decel {-exact_d:.2f} m/s²")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Acceleration (m/s²)")
    ax.set_title("Acceleration vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved plot to {output}")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze SimPy Model 1 forklift movement and generate charts."
    )
    parser.add_argument("--forklift-id", default=None, help="Forklift ID to plot (default: first).")
    parser.add_argument("--recording-interval", type=float, default=0.2, help="Sampling interval (s).")
    parser.add_argument("--sim-time", type=float, default=200.0, help="Simulation time to run (s).")
    parser.add_argument("--max-time", type=float, default=200.0, help="Max time shown on plots (s).")
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
    parser.add_argument("--output", default="simpy_movement_analysis.png", help="Output image filename.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 70)
    print("SIMPY MODEL 1 FORKLIFT MOVEMENT ANALYSIS")
    print("=" * 70)
    print(
        f"Running sim for {args.sim_time:.2f}s, recording every {args.recording_interval:.2f}s..."
    )

    recorder = run_simulation(args.recording_interval, args.sim_time)
    trajectories = recorder.get_all_trajectories()
    trajectory = select_trajectory(trajectories, args.forklift_id)

    positions = trajectory_to_positions(trajectory)
    if len(positions) < 2:
        raise RuntimeError("Not enough recorded positions for analysis.")

    print(
        f"Raw samples: {len(positions)} from {positions[0][0]:.2f}s to {positions[-1][0]:.2f}s"
    )
    positions = smooth_positions(positions, window=args.smooth_window)
    positions = downsample_positions(positions, interval=args.downsample_interval)
    if len(positions) < 2:
        raise RuntimeError("Not enough recorded positions after smoothing/downsampling.")

    max_time = args.timeframe if args.timeframe is not None else args.max_time
    positions = apply_time_window(positions, max_time)
    if len(positions) < 2:
        raise RuntimeError("Not enough recorded positions within the max time window.")

    speeds = compute_speeds(positions)
    accels = compute_accelerations(speeds)
    summary = summarize_movement(speeds, accels)

    print(
        f"Parsed {len(positions)} samples from {positions[0][0]:.2f}s to {positions[-1][0]:.2f}s"
    )
    if args.smooth_window > 1:
        print(f"Smoothing: trailing average window = {args.smooth_window} samples")
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
        recording_interval=args.recording_interval,
    )


if __name__ == "__main__":
    main()
