#!/usr/bin/env python3
"""Animate a Model 1 cyclic trace against an AnyLogic cyclic log."""

from __future__ import annotations

import argparse
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from mhsim.spatial import PointNode, RectangularNode

from .analysis.compare_movement_trace import (
    POSITION_RE,
    TRACE_LINE_RE,
    TracePhases,
    TraceSample,
    infer_trace_phases,
)
from .model import Model1SimModel
from .params import Model1Params
from .setup import create_model1_warehouse


TRACE_TO_MODEL_SCALE = 0.1


@dataclass(frozen=True)
class ForkliftTrace:
    forklift_index: int
    times: np.ndarray
    positions_m: np.ndarray
    velocity_mps: np.ndarray
    speed_mps: np.ndarray
    acceleration_mps2: np.ndarray
    acceleration_magnitude_mps2: np.ndarray
    signed_tangential_acceleration_mps2: np.ndarray


@dataclass(frozen=True)
class CyclicTrace:
    label: str
    path: Path
    forklifts: dict[int, ForkliftTrace]
    expected_dt_s: float | None
    phases: TracePhases

    @property
    def max_time(self) -> float:
        return max(
            (float(trace.times[-1]) for trace in self.forklifts.values() if len(trace.times)),
            default=0.0,
        )


def build_params_from_args(
    args: argparse.Namespace,
    *,
    inferred_n_forklifts: int | None,
) -> Model1Params:
    params = Model1Params()
    params.arrival_rate_s = args.arrival_rate_s
    params.n_forklifts = (
        inferred_n_forklifts
        if inferred_n_forklifts is not None
        else params.n_forklifts
    )
    params.forklift_max_speed = args.forklift_max_speed
    params.forklift_acceleration = args.forklift_acceleration
    params.displacement_m = args.displacement_m
    params.apply_displacement_geometry = args.apply_displacement_geometry
    params.log_filename_prefix = "simpy_model1_range_trace"
    if args.sim_time is not None:
        params.sim_time = args.sim_time
    return params


def _finite_difference(
    values: np.ndarray,
    times: np.ndarray,
    *,
    expected_dt_s: float | None,
    gap_tolerance_multiplier: float = 1.5,
) -> np.ndarray:
    result = np.full(values.shape, np.nan, dtype=float)
    if len(times) < 2:
        return result

    max_gap = (
        expected_dt_s * gap_tolerance_multiplier
        if expected_dt_s is not None and expected_dt_s > 0
        else math.inf
    )

    def usable(left: int, right: int) -> bool:
        dt = times[right] - times[left]
        return dt > 0 and dt <= max_gap

    for index in range(len(times)):
        if 0 < index < len(times) - 1 and usable(index - 1, index) and usable(index, index + 1):
            left = index - 1
            right = index + 1
        elif index == 0 and usable(0, 1):
            left = 0
            right = 1
        elif index == len(times) - 1 and usable(index - 1, index):
            left = index - 1
            right = index
        elif index > 0 and usable(index - 1, index):
            left = index - 1
            right = index
        elif index < len(times) - 1 and usable(index, index + 1):
            left = index
            right = index + 1
        else:
            continue

        result[index] = (values[right] - values[left]) / (times[right] - times[left])

    return result


def _expected_dt(times: Iterable[float]) -> float | None:
    values = np.asarray(list(times), dtype=float)
    if len(values) < 2:
        return None
    diffs = np.diff(values)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return None
    return float(np.median(diffs))


def _smooth(values: np.ndarray, window_samples: int) -> np.ndarray:
    if window_samples <= 1 or len(values) == 0:
        return values
    window_samples = max(1, int(window_samples))
    smoothed = np.full(values.shape, np.nan, dtype=float)
    half = window_samples // 2
    for index in range(len(values)):
        left = max(0, index - half)
        right = min(len(values), index + half + 1)
        segment = values[left:right]
        if np.isfinite(segment).any():
            smoothed[index] = float(np.nanmean(segment))
    return smoothed


def parse_cyclic_trace(path: str | Path, *, label: str) -> CyclicTrace:
    trace_path = Path(path)
    rows: list[tuple[float, tuple[tuple[float, float], ...]]] = []
    with trace_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            if raw_line.strip().startswith("ITERATION #"):
                rows.clear()
                continue
            time_match = TRACE_LINE_RE.search(raw_line)
            if time_match is None:
                continue
            positions = tuple(
                (float(x) * TRACE_TO_MODEL_SCALE, float(y) * TRACE_TO_MODEL_SCALE)
                for x, y in POSITION_RE.findall(raw_line)
            )
            if positions:
                rows.append((float(time_match.group(1)), positions))

    by_forklift: dict[int, list[tuple[float, tuple[float, float]]]] = {}
    for time_s, positions in rows:
        for index, position in enumerate(positions, start=1):
            by_forklift.setdefault(index, []).append((time_s, position))

    all_times = [time_s for time_s, _positions in rows]
    expected_dt_s = _expected_dt(all_times)
    forklifts: dict[int, ForkliftTrace] = {}
    for index, samples in sorted(by_forklift.items()):
        times = np.asarray([sample[0] for sample in samples], dtype=float)
        positions = np.asarray([sample[1] for sample in samples], dtype=float)
        velocity = _finite_difference(
            positions,
            times,
            expected_dt_s=expected_dt_s,
        )
        speed = np.linalg.norm(velocity, axis=1)
        acceleration = _finite_difference(
            velocity,
            times,
            expected_dt_s=expected_dt_s,
        )
        acceleration_magnitude = np.linalg.norm(acceleration, axis=1)
        signed_tangential_acceleration = _finite_difference(
            speed,
            times,
            expected_dt_s=expected_dt_s,
        )
        forklifts[index] = ForkliftTrace(
            forklift_index=index,
            times=times,
            positions_m=positions,
            velocity_mps=velocity,
            speed_mps=speed,
            acceleration_mps2=acceleration,
            acceleration_magnitude_mps2=acceleration_magnitude,
            signed_tangential_acceleration_mps2=signed_tangential_acceleration,
        )

    phase_samples = [
        TraceSample(time=time_s, positions=positions)
        for time_s, positions in rows
    ]
    return CyclicTrace(
        label=label,
        path=trace_path,
        forklifts=forklifts,
        expected_dt_s=expected_dt_s,
        phases=infer_trace_phases(phase_samples),
    )


def generate_simpy_trace(params: Model1Params) -> tuple[Path, object]:
    model = Model1SimModel(params=params, console_logging=False, enable_logging=True)
    model.run(until=params.sim_time)
    if model.logger is None:
        raise RuntimeError("Model 1 trace logging was not enabled")
    return model.logger.log_file, model.layout


def _create_layout(params: Model1Params):
    import simpy

    env = simpy.Environment()
    layout, _router, _fleet = create_model1_warehouse(env, params)
    return layout


def _axis_limits(layout, traces: Iterable[CyclicTrace]) -> tuple[tuple[float, float], tuple[float, float]]:
    xs: list[float] = []
    ys: list[float] = []

    if layout is not None:
        for node in [layout.inbound_area, layout.outbound_area, layout.forklifts_home]:
            if node is None:
                continue
            if isinstance(node, RectangularNode):
                xs.extend([node.position.x, node.position.x + node.width])
                ys.extend([node.position.y, node.position.y + node.depth])
            elif isinstance(node, PointNode):
                xs.append(node.position.x)
                ys.append(node.position.y)
        for node in getattr(layout, "extra_nodes", []):
            xs.append(node.position.x)
            ys.append(node.position.y)
        for path in getattr(layout, "paths", []) or []:
            for point in path.waypoints:
                xs.append(point.x)
                ys.append(point.y)

    for trace in traces:
        for forklift in trace.forklifts.values():
            if len(forklift.positions_m):
                xs.extend(forklift.positions_m[:, 0].tolist())
                ys.extend(forklift.positions_m[:, 1].tolist())

    if not xs or not ys:
        return (45.0, 75.0), (25.0, 45.0)

    x_span = max(1.0, max(xs) - min(xs))
    y_span = max(1.0, max(ys) - min(ys))
    margin = max(2.0, x_span * 0.12, y_span * 0.12)
    return (min(xs) - margin, max(xs) + margin), (min(ys) - margin, max(ys) + margin)


def _draw_layout(ax, layout) -> None:
    if layout is None:
        return

    from matplotlib.patches import Circle, Rectangle

    for path in getattr(layout, "paths", []) or []:
        if not path.waypoints:
            continue
        xs = [point.x for point in path.waypoints]
        ys = [point.y for point in path.waypoints]
        ax.plot(xs, ys, color="#90A4AE", linewidth=1.0, alpha=0.8)
        ax.scatter(xs, ys, s=8, color="#546E7A", alpha=0.8)

    nodes = [
        layout.inbound_area,
        layout.outbound_area,
        layout.forklifts_home,
        *getattr(layout, "extra_nodes", []),
    ]
    seen: set[str] = set()
    for node in nodes:
        if node is None or node.id in seen:
            continue
        seen.add(node.id)
        if isinstance(node, RectangularNode):
            rect = Rectangle(
                (node.position.x, node.position.y),
                node.width,
                node.depth,
                fill=False,
                edgecolor="#455A64",
                linewidth=1.4,
                linestyle="--",
            )
            ax.add_patch(rect)
            x = node.position.x + node.width / 2
            y = node.position.y + node.depth + 0.5
        else:
            circle = Circle(
                (node.position.x, node.position.y),
                radius=0.8,
                fill=False,
                edgecolor="#455A64",
                linewidth=1.4,
                linestyle="--",
            )
            ax.add_patch(circle)
            x = node.position.x
            y = node.position.y + 1.2
        ax.text(x, y, node.id, ha="center", va="bottom", fontsize=8, color="#455A64")


def _phase_items(phases: TracePhases) -> list[tuple[str, float]]:
    raw = [
        ("move", phases.movement_start),
        ("load start", phases.loading_start),
        ("load finish", phases.loading_finish),
        ("unload start", phases.unloading_start),
        ("unload finish", phases.unloading_finish),
    ]
    return [(label, value) for label, value in raw if value is not None]


def build_animation(
    anylogic: CyclicTrace,
    simpy_trace: CyclicTrace,
    layout,
    params: Model1Params,
    *,
    playback_speed: float,
    fps: float,
    trail_seconds: float,
    window_seconds: float,
    smooth_window: int,
):
    import matplotlib.pyplot as plt
    from matplotlib import animation

    max_time = max(anylogic.max_time, simpy_trace.max_time, 1.0)
    x_limits, y_limits = _axis_limits(layout, [anylogic, simpy_trace])
    colors = plt.cm.tab10(np.linspace(0, 1, max(1, params.n_forklifts)))

    fig = plt.figure(figsize=(15, 9))
    grid = fig.add_gridspec(3, 2, height_ratios=[1.2, 0.75, 0.75], hspace=0.42, wspace=0.24)
    ax_anylogic = fig.add_subplot(grid[0, 0])
    ax_simpy = fig.add_subplot(grid[0, 1])
    ax_speed = fig.add_subplot(grid[1, :])
    ax_accel = fig.add_subplot(grid[2, :], sharex=ax_speed)

    fig.suptitle(
        (
            "Model 1 Cyclic Trace Comparison  "
            f"arrival={params.arrival_rate_s:g}s  "
            f"forklifts={params.n_forklifts}  "
            f"speed={params.forklift_max_speed:g}m/s  "
            f"accel={params.forklift_acceleration:g}m/s^2  "
            f"displacement={params.displacement_m:g}m"
        ),
        fontsize=12,
        fontweight="bold",
    )

    map_axes = [(ax_anylogic, anylogic), (ax_simpy, simpy_trace)]
    map_lines: dict[tuple[str, int], object] = {}
    map_points: dict[tuple[str, int], object] = {}
    for ax, trace in map_axes:
        _draw_layout(ax, layout)
        ax.set_xlim(*x_limits)
        ax.set_ylim(*y_limits)
        ax.set_aspect("equal")
        ax.set_title(f"{trace.label} positions", fontsize=11, fontweight="bold")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.grid(True, alpha=0.25)
        for forklift_index, forklift in trace.forklifts.items():
            color = colors[(forklift_index - 1) % len(colors)]
            ax.plot(
                forklift.positions_m[:, 0],
                forklift.positions_m[:, 1],
                color=color,
                linewidth=0.7,
                alpha=0.22,
            )
            (line,) = ax.plot([], [], color=color, linewidth=2.0, label=f"fl{forklift_index}")
            point = ax.scatter([], [], color=color, edgecolor="black", linewidth=0.7, s=42)
            map_lines[(trace.label, forklift_index)] = line
            map_points[(trace.label, forklift_index)] = point
        ax.legend(loc="upper right", fontsize=8)

    speed_lines: dict[tuple[str, int], object] = {}
    accel_lines: dict[tuple[str, int], object] = {}
    chart_speeds: dict[tuple[str, int], np.ndarray] = {}
    chart_accelerations: dict[tuple[str, int], np.ndarray] = {}
    for trace, linestyle in [(anylogic, "-"), (simpy_trace, "--")]:
        for forklift_index, forklift in trace.forklifts.items():
            key = (trace.label, forklift_index)
            color = colors[(forklift_index - 1) % len(colors)]
            label = f"{trace.label} fl{forklift_index}"
            (speed_line,) = ax_speed.plot(
                [],
                [],
                linestyle=linestyle,
                color=color,
                linewidth=1.4,
                label=label,
            )
            (accel_line,) = ax_accel.plot(
                [],
                [],
                linestyle=linestyle,
                color=color,
                linewidth=1.4,
                label=label,
            )
            speed_lines[key] = speed_line
            accel_lines[key] = accel_line
            chart_speeds[key] = _smooth(forklift.speed_mps, smooth_window)
            chart_accelerations[key] = _smooth(
                forklift.signed_tangential_acceleration_mps2,
                smooth_window,
            )

    ax_speed.axhline(
        params.forklift_max_speed,
        color="#263238",
        linewidth=1.0,
        linestyle=":",
        label="configured max speed",
    )
    ax_accel.axhline(params.forklift_acceleration, color="#263238", linewidth=1.0, linestyle=":")
    ax_accel.axhline(-params.forklift_acceleration, color="#263238", linewidth=1.0, linestyle=":")

    phase_color_by_trace = {anylogic.label: "#6A1B9A", simpy_trace.label: "#00838F"}
    for trace in [anylogic, simpy_trace]:
        for label, time_s in _phase_items(trace.phases):
            for ax in [ax_speed, ax_accel]:
                ax.axvline(
                    time_s,
                    color=phase_color_by_trace[trace.label],
                    linewidth=0.8,
                    linestyle="-" if trace is anylogic else "--",
                    alpha=0.45,
                )
            ax_speed.text(
                time_s,
                1.02,
                label,
                transform=ax_speed.get_xaxis_transform(),
                rotation=90,
                va="bottom",
                ha="center",
                fontsize=7,
                color=phase_color_by_trace[trace.label],
            )

    ax_speed.set_title("Sample-derived forklift speed", fontsize=10, fontweight="bold")
    ax_speed.set_ylabel("m/s")
    ax_speed.grid(True, alpha=0.25)
    ax_speed.legend(loc="upper right", fontsize=7, ncol=2)

    ax_accel.set_title(
        "Sample-derived signed tangential acceleration",
        fontsize=10,
        fontweight="bold",
    )
    ax_accel.set_xlabel("Time (s)")
    ax_accel.set_ylabel("m/s^2")
    ax_accel.grid(True, alpha=0.25)
    ax_accel.legend(loc="upper right", fontsize=7, ncol=2)

    finite_speeds = [
        values
        for trace in [anylogic, simpy_trace]
        for forklift in trace.forklifts.values()
        for values in [forklift.speed_mps[np.isfinite(forklift.speed_mps)]]
        if len(values)
    ]
    speed_max = max([params.forklift_max_speed, *(float(np.nanmax(v)) for v in finite_speeds)])
    ax_speed.set_ylim(0.0, max(0.5, speed_max * 1.15))

    accel_limit = max(0.5, params.forklift_acceleration * 1.5)
    ax_accel.set_ylim(-accel_limit, accel_limit)

    time_text = fig.text(0.01, 0.02, "", fontsize=10, family="monospace")

    def _current_position(forklift: ForkliftTrace, current_time: float) -> np.ndarray | None:
        if len(forklift.times) == 0:
            return None
        index = int(np.searchsorted(forklift.times, current_time))
        if 0 < index < len(forklift.times):
            t0 = forklift.times[index - 1]
            t1 = forklift.times[index]
            p0 = forklift.positions_m[index - 1]
            p1 = forklift.positions_m[index]
            alpha = (current_time - t0) / (t1 - t0) if t1 > t0 else 0.0
            return p0 + alpha * (p1 - p0)
        if index <= 0:
            return forklift.positions_m[0]
        return forklift.positions_m[-1]

    def _update_trace(trace: CyclicTrace, current_time: float) -> None:
        for forklift_index, forklift in trace.forklifts.items():
            trail_start = max(0.0, current_time - trail_seconds)
            mask = (forklift.times >= trail_start) & (forklift.times <= current_time)
            key = (trace.label, forklift_index)
            if mask.any():
                positions = forklift.positions_m[mask]
                if len(positions) > 1:
                    map_lines[key].set_data(positions[:, 0], positions[:, 1])
                else:
                    map_lines[key].set_data([], [])
            else:
                map_lines[key].set_data([], [])
            current_position = _current_position(forklift, current_time)
            if current_position is None:
                map_points[key].set_offsets(np.empty((0, 2)))
            else:
                map_points[key].set_offsets([current_position])

            window_start = max(0.0, current_time - window_seconds)
            window_mask = (forklift.times >= window_start) & (forklift.times <= current_time)
            if window_mask.any():
                chart_times = forklift.times[window_mask]
                speed_values = chart_speeds[key][window_mask]
                accel_values = chart_accelerations[key][window_mask]
                speed_lines[key].set_data(chart_times, speed_values)
                accel_lines[key].set_data(chart_times, accel_values)
            else:
                speed_lines[key].set_data([], [])
                accel_lines[key].set_data([], [])

    def update(frame_index: int):
        current_time = min(max_time, frame_index / fps * playback_speed)
        _update_trace(anylogic, current_time)
        _update_trace(simpy_trace, current_time)
        window_start = max(0.0, current_time - window_seconds)
        ax_speed.set_xlim(window_start, max(window_start + 1.0, current_time))
        ax_accel.set_xlim(window_start, max(window_start + 1.0, current_time))
        time_text.set_text(
            f"t={current_time:8.2f}s  AnyLogic dt={anylogic.expected_dt_s or float('nan'):.3f}s  "
            f"SimPy dt={simpy_trace.expected_dt_s or float('nan'):.3f}s"
        )
        return [
            *map_lines.values(),
            *map_points.values(),
            *speed_lines.values(),
            *accel_lines.values(),
            time_text,
        ]

    total_frames = max(1, int(math.ceil((max_time / max(0.001, playback_speed)) * fps)))
    anim = animation.FuncAnimation(
        fig,
        update,
        frames=range(total_frames + 1),
        interval=1000.0 / fps,
        blit=False,
        repeat=False,
    )
    fig._mhsim_animation = anim
    return fig, anim


def _warn_trace_count(label: str, trace: CyclicTrace, expected_n_forklifts: int) -> None:
    count = len(trace.forklifts)
    if count != expected_n_forklifts:
        print(
            f"Warning: {label} trace has {count} forklift position columns, "
            f"but SimPy is configured with {expected_n_forklifts} forklifts."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Animate an AnyLogic Model 1 cyclic trace beside a SimPy trace, "
            "including sample-derived speed and acceleration."
        )
    )
    parser.add_argument(
        "--anylogic-trace",
        default="anylogic/Model 1/log_file_movement_trace.txt",
        help="AnyLogic cyclic position log to compare.",
    )
    parser.add_argument(
        "--simpy-trace",
        default=None,
        help="Optional pre-generated SimPy cyclic position log. If omitted, the script runs SimPy.",
    )
    defaults = Model1Params()
    parser.add_argument(
        "--arrival-rate-s",
        type=float,
        default=defaults.arrival_rate_s,
        help=f"SimPy source recurrence in seconds. Default: {defaults.arrival_rate_s:g}.",
    )
    parser.add_argument(
        "--forklift-max-speed",
        type=float,
        default=defaults.forklift_max_speed,
        help=f"SimPy forklift max speed in m/s. Default: {defaults.forklift_max_speed:g}.",
    )
    parser.add_argument(
        "--forklift-acceleration",
        type=float,
        default=defaults.forklift_acceleration,
        help=(
            "SimPy forklift acceleration and deceleration in m/s^2. "
            f"Default: {defaults.forklift_acceleration:g}."
        ),
    )
    parser.add_argument(
        "--displacement-m",
        type=float,
        default=defaults.displacement_m,
        help=f"Model 1 displacement parameter in meters. Default: {defaults.displacement_m:g}.",
    )
    parser.add_argument(
        "--apply-displacement-geometry",
        action=argparse.BooleanOptionalAction,
        default=defaults.apply_displacement_geometry,
        help=(
            "Apply the Simulation experiment A/B displacement geometry. "
            "Use --no-apply-displacement-geometry for parameter-variation logs. "
            f"Default: {defaults.apply_displacement_geometry}."
        ),
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Optional SimPy stop time override. Defaults to Model 1 params.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Animation playback speed multiplier. Default: 1.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=12.0,
        help="Animation render frames per second. Default: 12.",
    )
    parser.add_argument(
        "--trail-seconds",
        type=float,
        default=20.0,
        help="Seconds of recent path to highlight in each warehouse plot. Default: 20.",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=60.0,
        help="Rolling time window for speed and acceleration charts. Default: 60.",
    )
    parser.add_argument(
        "--smooth-window",
        type=int,
        default=1,
        help="Optional moving-average window in samples for charted speed/acceleration. Default: 1.",
    )
    parser.add_argument(
        "--save",
        default=None,
        help="Optional output animation path supported by matplotlib, such as .gif or .mp4.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Build the animation without opening the matplotlib window.",
    )
    args = parser.parse_args()

    if args.fps <= 0:
        raise ValueError("--fps must be positive")
    if args.speed <= 0:
        raise ValueError("--speed must be positive")
    anylogic_trace = parse_cyclic_trace(args.anylogic_trace, label="AnyLogic")
    params = build_params_from_args(
        args,
        inferred_n_forklifts=(
            len(anylogic_trace.forklifts) if anylogic_trace.forklifts else None
        ),
    )
    _warn_trace_count("AnyLogic", anylogic_trace, params.n_forklifts)

    if args.simpy_trace:
        simpy_trace_path = Path(args.simpy_trace)
        layout = _create_layout(params)
    else:
        print(
            f"Running SimPy Model 1 for {params.sim_time:g}s "
            f"with cyclic logger interval {params.log_interval_s:g}s ..."
        )
        print(
            f"SimPy settings: arrival={params.arrival_rate_s:g}s  "
            f"forklifts={params.n_forklifts}  "
            f"speed={params.forklift_max_speed:g}m/s  "
            f"accel={params.forklift_acceleration:g}m/s^2  "
            f"displacement={params.displacement_m:g}m"
        )
        simpy_trace_path, layout = generate_simpy_trace(params)
        print(f"SimPy trace: {simpy_trace_path}")

    simpy_trace = parse_cyclic_trace(simpy_trace_path, label="SimPy")
    _warn_trace_count("SimPy", simpy_trace, params.n_forklifts)

    print(
        "Derived speed and acceleration from cyclic position samples "
        "using timestamp deltas and central differences."
    )
    print(
        f"AnyLogic trace: {anylogic_trace.path}  samples dt~{anylogic_trace.expected_dt_s or float('nan'):.3f}s"
    )
    print(
        f"SimPy trace: {simpy_trace.path}  samples dt~{simpy_trace.expected_dt_s or float('nan'):.3f}s"
    )

    if args.no_show:
        os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())
        import matplotlib

        matplotlib.use("Agg")

    fig, anim = build_animation(
        anylogic_trace,
        simpy_trace,
        layout,
        params,
        playback_speed=args.speed,
        fps=args.fps,
        trail_seconds=args.trail_seconds,
        window_seconds=args.window_seconds,
        smooth_window=args.smooth_window,
    )

    if args.save:
        anim.save(args.save)
        print(f"Saved animation: {args.save}")

    if args.no_show:
        import matplotlib.pyplot as plt

        anim._draw_was_started = True
        plt.close(fig)
    else:
        import matplotlib.pyplot as plt

        plt.show()


if __name__ == "__main__":
    main()
