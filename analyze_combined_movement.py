#!/usr/bin/env python3
"""
Compare AnyLogic and SimPy forklift movement in a shared set of plots.
Plots trajectory, position, speed, and acceleration for the full available time range.
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

LOG_PATH = ROOT / "anylogic" / "Model 1" / "log_file.txt"

Position = Tuple[float, float, float, float]  # t, x, y, z


def parse_anylogic_log(path: Path) -> List[Position]:
    """Parse AnyLogic log lines into (t, x, y, z) in meters."""
    positions: List[Position] = []
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    with path.open() as f:
        for line in f:
            match = _match_anylogic_line(line)
            if match:
                positions.append(match)
    return positions


def _match_anylogic_line(line: str) -> Position | None:
    line = line.strip()
    if not line.startswith("["):
        return None
    if "Forklift position" not in line:
        return None
    parts = line.split("Forklift position:")
    if len(parts) < 2:
        return None
    time_part = parts[0].strip().strip("[]")
    if not time_part.endswith("s"):
        return None
    try:
        t = float(time_part[:-1])
    except ValueError:
        return None

    coords_part = parts[1].strip()
    if not coords_part.startswith("("):
        return None
    coords_part = coords_part[1:]
    coord_values = []
    for token in coords_part.split(",")[:3]:
        token = token.strip()
        try:
            coord_values.append(float(token))
        except ValueError:
            return None
    if len(coord_values) != 3:
        return None

    x, y, z = (value / 10.0 for value in coord_values)
    return (t, x, y, z)


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


def compute_accelerations(
    speeds: List[Tuple[float, float]], max_dt: float | None = None
) -> List[Tuple[float, float]]:
    accels: List[Tuple[float, float]] = []
    for i in range(1, len(speeds)):
        t1, v1 = speeds[i - 1]
        t2, v2 = speeds[i]
        dt = t2 - t1
        if dt <= 0:
            continue
        if max_dt is not None and dt >= max_dt:
            continue
        accels.append((t2, (v2 - v1) / dt))
    return accels


def plot_combined(
    anylogic_positions: List[Position],
    anylogic_speeds: List[Tuple[float, float]],
    anylogic_accels: List[Tuple[float, float]],
    sim_positions: List[Position],
    sim_speeds: List[Tuple[float, float]],
    sim_accels: List[Tuple[float, float]],
    output: str,
    recording_interval: float,
    max_time: float,
) -> None:
    any_times = [p[0] for p in anylogic_positions]
    any_xs = [p[1] for p in anylogic_positions]
    any_ys = [p[2] for p in anylogic_positions]

    sim_times = [p[0] for p in sim_positions]
    sim_xs = [p[1] for p in sim_positions]
    sim_ys = [p[2] for p in sim_positions]

    any_speed_times = [t for t, _ in anylogic_speeds]
    any_speed_vals = [v for _, v in anylogic_speeds]

    sim_speed_times = [t for t, _ in sim_speeds]
    sim_speed_vals = [v for _, v in sim_speeds]

    any_accel_times = [t for t, _ in anylogic_accels]
    any_accel_vals = [a for _, a in anylogic_accels]

    sim_accel_times = [t for t, _ in sim_accels]
    sim_accel_vals = [a for _, a in sim_accels]

    fig, axes = plt.subplots(4, 1, figsize=(14, 12))
    fig.suptitle(
        f"AnyLogic vs SimPy Forklift Movement (first {max_time:.2f}s, {recording_interval:.2f}s SimPy sampling)",
        fontsize=16,
        fontweight="bold",
    )

    ax = axes[0]
    ax.plot(any_xs, any_ys, color="tab:blue", lw=1.3, alpha=0.75, label="AnyLogic")
    ax.plot(sim_xs, sim_ys, color="tab:orange", lw=1.3, alpha=0.75, label="SimPy")
    ax.scatter(any_xs[0], any_ys[0], c="tab:blue", s=60, marker="o", label="AnyLogic start")
    ax.scatter(any_xs[-1], any_ys[-1], c="tab:blue", s=60, marker="s", label="AnyLogic end")
    ax.scatter(sim_xs[0], sim_ys[0], c="tab:orange", s=60, marker="o", label="SimPy start")
    ax.scatter(sim_xs[-1], sim_ys[-1], c="tab:orange", s=60, marker="s", label="SimPy end")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_title("Trajectory")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2)
    ax.set_aspect("equal", adjustable="datalim")

    ax = axes[1]
    ax.plot(any_times, any_xs, color="tab:blue", lw=1.1, label="AnyLogic X")
    ax.plot(any_times, any_ys, color="tab:blue", lw=1.1, ls="--", label="AnyLogic Y")
    ax.plot(sim_times, sim_xs, color="tab:orange", lw=1.1, label="SimPy X")
    ax.plot(sim_times, sim_ys, color="tab:orange", lw=1.1, ls="--", label="SimPy Y")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Position (m)")
    ax.set_title("Position vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2)
    ax.set_xlim(0, max_time)

    ax = axes[2]
    ax.plot(any_speed_times, any_speed_vals, color="tab:blue", lw=1.3, alpha=0.8, label="AnyLogic")
    ax.plot(sim_speed_times, sim_speed_vals, color="tab:orange", lw=1.3, alpha=0.8, label="SimPy")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (m/s)")
    ax.set_title("Speed vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_xlim(0, max_time)

    ax = axes[3]
    ax.plot(any_accel_times, any_accel_vals, color="tab:blue", lw=1.1, alpha=0.8, label="AnyLogic")
    ax.plot(sim_accel_times, sim_accel_vals, color="tab:orange", lw=1.1, alpha=0.8, label="SimPy")
    ax.axhline(0, color="black", lw=0.8, alpha=0.5)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Acceleration (m/s^2)")
    ax.set_title("Acceleration vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_xlim(0, max_time)

    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"Saved plot to {output}")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot AnyLogic and SimPy forklift movement on the same charts."
    )
    parser.add_argument("--forklift-id", default=None, help="Forklift ID to plot (default: first).")
    parser.add_argument("--recording-interval", type=float, default=0.2, help="Sampling interval (s).")
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="SimPy simulation time (s). Defaults to min(AnyLogic duration, max-time).",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=600.0,
        help="Max time shown on plots (s).",
    )
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
        "--anylogic-log",
        default=str(LOG_PATH),
        help="Path to AnyLogic log file.",
    )
    parser.add_argument(
        "--output",
        default="combined_movement_analysis.png",
        help="Output image filename.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    anylogic_log = Path(args.anylogic_log)

    print("=" * 70)
    print("ANYLOGIC VS SIMPY FORKLIFT MOVEMENT ANALYSIS")
    print("=" * 70)

    anylogic_positions = parse_anylogic_log(anylogic_log)
    if len(anylogic_positions) < 2:
        raise RuntimeError("Not enough AnyLogic positions for analysis.")

    anylogic_duration = anylogic_positions[-1][0]
    max_time = args.timeframe if args.timeframe is not None else args.max_time
    sim_time = (
        args.sim_time
        if args.sim_time is not None
        else min(anylogic_duration, max_time)
    )

    print(
        f"AnyLogic samples: {len(anylogic_positions)} from {anylogic_positions[0][0]:.2f}s to {anylogic_positions[-1][0]:.2f}s"
    )
    if args.smooth_window > 1:
        print(f"Smoothing: trailing average window = {args.smooth_window} samples")
    if args.downsample_interval is not None and args.downsample_interval > 0:
        print(f"Downsampling: min interval = {args.downsample_interval:.2f}s")
    print(
        f"Running SimPy for {sim_time:.2f}s, recording every {args.recording_interval:.2f}s..."
    )

    anylogic_positions = smooth_positions(anylogic_positions, window=args.smooth_window)
    anylogic_positions = downsample_positions(anylogic_positions, interval=args.downsample_interval)
    if len(anylogic_positions) < 2:
        raise RuntimeError("Not enough AnyLogic positions after smoothing/downsampling.")
    print(
        f"AnyLogic samples (processed): {len(anylogic_positions)} from {anylogic_positions[0][0]:.2f}s to {anylogic_positions[-1][0]:.2f}s"
    )

    recorder = run_simulation(args.recording_interval, sim_time)
    trajectories = recorder.get_all_trajectories()
    trajectory = select_trajectory(trajectories, args.forklift_id)
    sim_positions = trajectory_to_positions(trajectory)

    if len(sim_positions) < 2:
        raise RuntimeError("Not enough SimPy positions for analysis.")

    print(
        f"SimPy raw samples: {len(sim_positions)} from {sim_positions[0][0]:.2f}s to {sim_positions[-1][0]:.2f}s"
    )
    sim_positions = smooth_positions(sim_positions, window=args.smooth_window)
    sim_positions = downsample_positions(sim_positions, interval=args.downsample_interval)
    if len(sim_positions) < 2:
        raise RuntimeError("Not enough SimPy positions after smoothing/downsampling.")

    sim_duration = sim_positions[-1][0]
    print(
        f"SimPy samples: {len(sim_positions)} from {sim_positions[0][0]:.2f}s to {sim_duration:.2f}s"
    )

    plot_max_time = min(max_time, anylogic_duration, sim_duration)

    anylogic_positions = [p for p in anylogic_positions if p[0] <= plot_max_time]
    sim_positions = [p for p in sim_positions if p[0] <= plot_max_time]

    if len(anylogic_positions) < 2:
        raise RuntimeError("Not enough AnyLogic positions within the max time window.")
    if len(sim_positions) < 2:
        raise RuntimeError("Not enough SimPy positions within the max time window.")

    anylogic_speeds = compute_speeds(anylogic_positions)
    sim_speeds = compute_speeds(sim_positions)

    anylogic_accels = compute_accelerations(anylogic_speeds, max_dt=0.6)
    sim_accels = compute_accelerations(sim_speeds)

    print("\nAnyLogic stats (windowed):")
    print_stats("Speed (m/s)", [v for _, v in anylogic_speeds], "m/s")
    any_accel_vals = [a for _, a in anylogic_accels]
    print_stats("Acceleration (m/s^2)", [a for a in any_accel_vals if a > 0], "m/s^2")
    print_stats("Deceleration (m/s^2)", [abs(a) for a in any_accel_vals if a < 0], "m/s^2")

    print("\nSimPy stats (windowed):")
    print_stats("Speed (m/s)", [v for _, v in sim_speeds], "m/s")
    sim_accel_vals = [a for _, a in sim_accels]
    print_stats("Acceleration (m/s^2)", [a for a in sim_accel_vals if a > 0], "m/s^2")
    print_stats("Deceleration (m/s^2)", [abs(a) for a in sim_accel_vals if a < 0], "m/s^2")

    print(f"\nGenerating combined plots (first {plot_max_time:.2f}s)...")
    plot_combined(
        anylogic_positions,
        anylogic_speeds,
        anylogic_accels,
        sim_positions,
        sim_speeds,
        sim_accels,
        output=args.output,
        recording_interval=args.recording_interval,
        max_time=plot_max_time,
    )


if __name__ == "__main__":
    main()
