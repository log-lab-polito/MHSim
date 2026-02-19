#!/usr/bin/env python3
"""Animate Model 1 warehouse simulation with forklift paths and metrics."""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    # Allow running as a script from the repo root without package context.
    package_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), ".."))
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    __package__ = "model_1_simpy"

from .visualization import MovementRecorder, create_recording_process
from .setup import create_warehouse_with_standard_config
from .params import Model1Params
from .model import Model1SimModel
from matplotlib.patches import Rectangle
from matplotlib import animation
import numpy as np
import matplotlib.pyplot as plt
import time

import argparse
from dataclasses import dataclass
from typing import List, Tuple

import matplotlib

matplotlib.use("TkAgg")


@dataclass
class Snapshot:
    t: float
    # Source block
    source_out: int
    # Service1 block
    service1_in: int
    service1_out: int
    service1_queue: int
    service1_delay: int
    # Store block
    store_in: int
    store_out: int
    store_contains: int
    # Delay block (storage)
    delay_in: int
    delay_out: int
    delay_contains: int
    # Retrieve block
    retrieve_in: int
    retrieve_out: int
    retrieve_contains: int
    # Service2 block
    service2_in: int
    service2_out: int
    service2_queue: int
    service2_delay: int
    # Sink
    sink_in: int
    # Legacy fields for time series
    storage_level: int
    created: int
    completed: int
    rack_occupancy: List[List[str]]


def _build_snapshot(env, model, s1, s2, fleet, storage) -> Snapshot:
    return Snapshot(
        t=env.now,
        # Source
        source_out=model.stats.created,
        # Service1
        service1_in=getattr(s1, "entered_count", 0),
        service1_out=getattr(s1, "finished_count", 0),
        service1_queue=len(s1.resource.queue),
        service1_delay=s1.resource.count,
        # Store
        store_in=getattr(model.store, "entered_count", 0),
        store_out=getattr(model.store, "finished_count", 0),
        store_contains=getattr(model.store, "entered_count", 0)
        - getattr(model.store, "completed_count", 0),
        # Delay
        delay_in=getattr(model.delay, "entered_count", 0),
        delay_out=getattr(model.delay, "finished_count", 0),
        delay_contains=getattr(model.delay, "entered_count", 0)
        - getattr(model.delay, "completed_count", 0),
        # Retrieve
        retrieve_in=getattr(model.retrieve, "entered_count", 0),
        retrieve_out=getattr(model.retrieve, "finished_count", 0),
        retrieve_contains=getattr(model.retrieve, "entered_count", 0)
        - getattr(model.retrieve, "completed_count", 0),
        # Service2
        service2_in=getattr(s2, "entered_count", 0),
        service2_out=getattr(s2, "finished_count", 0),
        service2_queue=len(s2.resource.queue),
        service2_delay=s2.resource.count,
        # Sink
        sink_in=getattr(model.sink, "entered_count", model.stats.completed),
        # Legacy fields for time series
        storage_level=int(storage.level),
        created=model.stats.created,
        completed=model.stats.completed,
        rack_occupancy=model.slot_manager.occupancy_grid(model.layout.storage),
    )


def run_and_record(
    params: Model1Params | None = None,
    sample_dt: float = 2.0,
    recording_interval: float = 1.0,
    sim_time_override: float | None = None,
) -> Tuple[List[Snapshot], Model1SimModel, MovementRecorder]:
    """Run the model and collect state snapshots plus forklift trajectories."""
    active_params = params or Model1Params()
    model = Model1SimModel(params=active_params)

    if sim_time_override is not None:
        model.params.sim_time = sim_time_override

    env = model.env
    s1 = model.service1
    s2 = model.service2
    fleet = model.fleet
    storage = model.storage

    snapshots: List[Snapshot] = []

    recorder = MovementRecorder()
    env.process(
        create_recording_process(
            env, fleet.forklifts, recorder, recording_interval=recording_interval
        )
    )

    def sampler():
        while True:
            snap = _build_snapshot(env, model, s1, s2, fleet, storage)
            snapshots.append(snap)
            yield env.timeout(sample_dt)

    env.process(sampler())
    model.source.start()

    stop_time = model.params.sim_time
    chunk = max(sample_dt, 5.0)
    last_report = 0.0
    while env.now < stop_time:
        env.run(until=min(stop_time, env.now + chunk))
        if env.now - last_report >= 10.0 or env.now >= stop_time:
            pct = (env.now / stop_time) * 100.0
            print(
                f"   ... model progress {env.now:.0f}/{stop_time:.0f}s ({pct:.0f}%) created={model.stats.created} completed={model.stats.completed} storage={int(storage.level)}"
            )
            last_report = env.now

    if not snapshots or snapshots[-1].t < env.now:
        snapshots.append(_build_snapshot(env, model, s1, s2, fleet, storage))

    return snapshots, model, recorder


def build_animation(
    snapshots: List[Snapshot],
    recorder: MovementRecorder,
    layout,
    fps: int = 6,
    playback_speed: float = 1.0,
    trail_seconds: float = 10.0,
):
    if not snapshots:
        raise ValueError("No snapshots to animate")

    times = [s.t for s in snapshots]
    times_arr = np.asarray(times, dtype=float)
    created = [s.created for s in snapshots]
    completed = [s.completed for s in snapshots]
    storage_level = [s.storage_level for s in snapshots]
    max_time = max(times) if times else 1.0

    # Pre-calculate max speed and height for fixed axis limits (enables blitting)
    all_speeds_global = []
    all_heights_global = []
    for trajectory in recorder.get_all_trajectories().values():
        speeds = trajectory.get_speeds_horizontal()
        heights = trajectory.get_z_coordinates()
        if len(speeds) > 0:
            all_speeds_global.extend(speeds)
        if len(heights) > 0:
            all_heights_global.extend(heights)

    max_speed_global = max(all_speeds_global) if all_speeds_global else 5.0
    min_height_global = min(all_heights_global) if all_heights_global else 0.0
    max_height_global = max(all_heights_global) if all_heights_global else 10.0

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(
        3, 2, width_ratios=[1.45, 0.75], height_ratios=[1, 1, 1.1], hspace=0.55, wspace=0.3
    )
    ax_warehouse = fig.add_subplot(gs[0:2, 0])
    ax_flow = fig.add_subplot(gs[0, 1])
    # Split the middle-right area into two subplots for speed and height
    gs_metrics = gs[1, 1].subgridspec(2, 1, hspace=0.6)
    ax_speed = fig.add_subplot(gs_metrics[0])
    ax_height = fig.add_subplot(gs_metrics[1])
    ax_ts = fig.add_subplot(gs[2, 0])
    ax_rack = fig.add_subplot(gs[2, 1])

    ax_warehouse.set_xlim(12, 45)
    ax_warehouse.set_ylim(24, 48)
    ax_warehouse.set_aspect("equal")
    ax_warehouse.set_xlabel("X Position (m)", fontsize=11)
    ax_warehouse.set_ylabel("Y Position (m)", fontsize=11)
    ax_warehouse.set_title(
        "Warehouse Map with Forklift Movements", fontsize=12, fontweight="bold")
    ax_warehouse.grid(True, alpha=0.2)

    if layout is not None:
        from .spatial import PointNode, RectangularNode
        areas = [
            (layout.inbound_area, {
             "edgecolor": "#388E3C", "label": "inbound"}),
            (layout.outbound_area, {
             "edgecolor": "#1976D2", "label": "outbound"}),
            (layout.forklifts_home, {"edgecolor": "#6A1B9A", "label": "home"}),
        ]
        for area, style in areas:
            if area is None:
                continue
            if isinstance(area, PointNode):
                # Draw point node as a circle
                from matplotlib.patches import Circle
                circle = Circle(
                    (area.position.x, area.position.y),
                    radius=1.0,  # scaled visualization radius
                    fill=False,
                    lw=1.5,
                    linestyle="--",
                    edgecolor=style["edgecolor"],
                    alpha=0.8,
                )
                ax_warehouse.add_patch(circle)
                ax_warehouse.text(
                    area.position.x,
                    area.position.y + 1.5,
                    area.id,
                    color=style["edgecolor"],
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )
            elif isinstance(area, RectangularNode):
                # Draw rectangular node as a rectangle
                rect = Rectangle(
                    (area.position.x, area.position.y),
                    area.width,
                    area.depth,
                    fill=False,
                    lw=1.5,
                    linestyle="--",
                    edgecolor=style["edgecolor"],
                    alpha=0.8,
                )
                ax_warehouse.add_patch(rect)
                ax_warehouse.text(
                    area.position.x + area.width / 2,
                    area.position.y + area.depth + 0.3,
                    area.id,
                    color=style["edgecolor"],
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

        if layout.storage and getattr(layout.storage, "shelves", None):
            for shelf in layout.storage.shelves:
                shelf_rect = Rectangle(
                    (shelf.position.x, shelf.position.y - shelf.cell_depth),
                    shelf.positions_per_level * shelf.position_spacing,
                    shelf.cell_depth,
                    fill=False,
                    lw=1.2,
                    linestyle="-",
                    edgecolor="#455A64",
                    alpha=0.9,
                )
                ax_warehouse.add_patch(shelf_rect)
                ax_warehouse.text(
                    shelf.position.x,
                    shelf.position.y - shelf.cell_depth - 0.3,
                    shelf.id,
                    color="#455A64",
                    ha="left",
                    va="top",
                    fontsize=8,
                )

        if getattr(layout, "paths", None):
            for path in layout.paths:
                if not path.waypoints:
                    continue
                xs = [p.x for p in path.waypoints]
                ys = [p.y for p in path.waypoints]
                ax_warehouse.plot(xs, ys, linestyle="-",
                                  color="#90CAF9", linewidth=0.8, alpha=0.9)
                ax_warehouse.scatter(xs, ys, s=4, color="#2196F3", alpha=0.8)

    lines = {}
    scatters = {}
    colors = plt.cm.tab10(np.linspace(0, 1, len(recorder.trajectories)))
    line_styles = ["-", "--", "-.", ":", "-", "--"]
    for (fl_id, trajectory), color, linestyle in zip(
        recorder.get_all_trajectories().items(
        ), colors, line_styles[: len(recorder.trajectories)]
    ):
        line, = ax_warehouse.plot(
            [], [], linestyle=linestyle, label=fl_id, color=color, linewidth=2.0)
        lines[fl_id] = line
        scatter = ax_warehouse.scatter(
            [], [], s=15, color=color, edgecolors="black", linewidth=1.5)
        scatters[fl_id] = scatter

    ax_warehouse.legend(loc="upper right", fontsize=9)
    time_text_warehouse = ax_warehouse.text(
        0.02, 0.98, "", transform=ax_warehouse.transAxes, fontsize=10, va="top")
    created_text = ax_warehouse.text(
        0.02, 0.93, "", transform=ax_warehouse.transAxes, fontsize=10, va="top", color="tab:green")
    completed_text = ax_warehouse.text(
        0.02, 0.88, "", transform=ax_warehouse.transAxes, fontsize=10, va="top", color="tab:orange")
    storage_text = ax_warehouse.text(
        0.02, 0.83, "", transform=ax_warehouse.transAxes, fontsize=10, va="top", color="tab:blue")

    node_names = ["source", "service1", "store",
                  "delay", "retrieve", "service2", "sink"]
    x_positions = np.linspace(0.10, 0.90, len(node_names))
    nodes = {name: (x, 0.76) for name, x in zip(node_names, x_positions)}

    def draw_box(ax, center, label):
        x, y = center
        w, h = 0.14, 0.34
        rect = Rectangle((x - w / 2, y - h / 2), w, h, fill=False, lw=1.5)
        ax.add_patch(rect)
        text = ax.text(x, y + h / 2 + 0.035, label,
                       ha="center", va="bottom", fontsize=8)
        return rect, text

    ax_flow.set_xlim(0, 1)
    ax_flow.set_ylim(0, 1)
    ax_flow.axis("off")
    ax_flow.set_title("Pipeline State", fontsize=11, fontweight="bold")

    window_seconds = min(60.0, max_time)
    trail_seconds = min(trail_seconds, max_time)

    # Configure speed chart with fixed limits for a rolling window
    ax_speed.set_title(
        f"Forklift Speed (last {int(window_seconds)}s)",
        fontsize=10,
        fontweight="bold",
        pad=6,
    )
    ax_speed.set_xlabel("", fontsize=9)
    ax_speed.set_ylabel("Speed (m/s)", fontsize=9)
    ax_speed.set_xlim(0, window_seconds)
    ax_speed.set_ylim(0, max_speed_global * 1.15)
    ax_speed.grid(True, alpha=0.3)
    ax_speed.tick_params(axis='both', labelsize=8)

    # Configure height chart with fixed limits for a rolling window
    ax_height.set_title(
        f"Forklift Height (last {int(window_seconds)}s)",
        fontsize=10,
        fontweight="bold",
        pad=6,
    )
    ax_height.set_xlabel("Time (s)", fontsize=9)
    ax_height.set_ylabel("Height (m)", fontsize=9)
    height_margin = max(0.5, (max_height_global - min_height_global) * 0.15)
    ax_height.set_xlim(0, window_seconds)
    ax_height.set_ylim(min_height_global - height_margin,
                       max_height_global + height_margin)
    ax_height.grid(True, alpha=0.3)
    ax_height.tick_params(axis='both', labelsize=8)

    # Create line objects for speed and height charts
    speed_lines = {}
    height_lines = {}
    for (fl_id, trajectory), color, linestyle in zip(
        recorder.get_all_trajectories().items(
        ), colors, line_styles[: len(recorder.trajectories)]
    ):
        speed_line, = ax_speed.plot(
            [], [], linestyle=linestyle, color=color, linewidth=1.5, label=fl_id)
        speed_lines[fl_id] = speed_line
        height_line, = ax_height.plot(
            [], [], linestyle=linestyle, color=color, linewidth=1.5, label=fl_id)
        height_lines[fl_id] = height_line

    ax_speed.legend(loc="upper right", fontsize=7, ncol=2)
    ax_height.legend(loc="upper right", fontsize=7, ncol=2)

    boxes = {}
    labels = {}
    for name, pos in nodes.items():
        rect, text = draw_box(ax_flow, pos, name)
        boxes[name] = rect
        labels[name] = text

    stat_texts = {}
    for name, (x, y) in nodes.items():
        stat_texts[name] = ax_flow.text(
            x,
            y,
            "",
            ha="center",
            va="center",
            fontsize=7,
            family="monospace",
        )

    (line_created,) = ax_ts.plot([], [], linestyle="-",
                                 color="tab:green", label="Created", linewidth=2)
    (line_completed,) = ax_ts.plot([], [], linestyle="--",
                                   color="tab:orange", label="Completed", linewidth=2)
    (line_storage,) = ax_ts.plot([], [], linestyle="-.",
                                 color="tab:blue", label="Storage Level", linewidth=2)

    ax_ts.set_xlim(times[0], max_time)
    ax_ts.set_ylim(0, max(max(created), max(
        completed), max(storage_level)) * 1.2 + 1)
    ax_ts.set_title("Cumulative Throughput & Storage Level",
                    fontsize=11, fontweight="bold")
    ax_ts.set_xlabel("Time (s)", fontsize=10)
    ax_ts.legend(loc="upper left", fontsize=9)
    ax_ts.grid(True, alpha=0.3)

    shelves = list(layout.storage.shelves) if layout and layout.storage else []
    max_bays = max((s.positions_per_level for s in shelves), default=0)
    rack_texts = []
    if shelves and max_bays > 0:
        ax_rack.set_title("Rack Occupancy", fontsize=11, fontweight="bold")
        ax_rack.set_xlim(0, max_bays)
        ax_rack.set_ylim(0, len(shelves))
        ax_rack.set_xticks([i + 0.5 for i in range(max_bays)])
        ax_rack.set_xticklabels([str(i + 1)
                                for i in range(max_bays)], fontsize=7)
        ax_rack.set_yticks([])
        ax_rack.set_xlabel("Bay", fontsize=9)
        ax_rack.grid(False)

        for r, shelf in enumerate(shelves):
            y = len(shelves) - r - 1
            ax_rack.text(-0.2, y + 0.5, shelf.id,
                         ha="right", va="center", fontsize=8)
            row_texts = []
            for b in range(shelf.positions_per_level):
                rect = Rectangle(
                    (b, y), 1, 1, fill=False, lw=1.0, edgecolor="#455A64"
                )
                ax_rack.add_patch(rect)
                txt_cell = ax_rack.text(
                    b + 0.5, y + 0.5, "", ha="center", va="center", fontsize=7
                )
                row_texts.append(txt_cell)
            rack_texts.append(row_texts)
    else:
        ax_rack.set_axis_off()

    def update(frame_idx):
        if frame_idx >= len(snapshots):
            frame_idx = len(snapshots) - 1
        s = snapshots[frame_idx]
        current_time = s.t

        stat_texts["source"].set_text(f"out:{s.source_out}")
        stat_texts["service1"].set_text(
            f"in:{s.service1_in}\nqueue:{s.service1_queue}\ndelay:{s.service1_delay}\nout:{s.service1_out}"
        )
        stat_texts["store"].set_text(
            f"in:{s.store_in}\nout:{s.store_out}\ncont:{s.store_contains}"
        )
        stat_texts["delay"].set_text(
            f"in:{s.delay_in}\nout:{s.delay_out}\ncont:{s.delay_contains}"
        )
        stat_texts["retrieve"].set_text(
            f"in:{s.retrieve_in}\nout:{s.retrieve_out}\ncont:{s.retrieve_contains}"
        )
        stat_texts["service2"].set_text(
            f"in:{s.service2_in}\nqueue:{s.service2_queue}\ndelay:{s.service2_delay}\nout:{s.service2_out}"
        )
        stat_texts["sink"].set_text(f"in:{s.sink_in}")

        for fl_id, trajectory in recorder.get_all_trajectories().items():
            times_traj = trajectory.get_times()
            positions_all = trajectory.get_positions_xy()

            trail_start = max(0.0, current_time - trail_seconds)
            mask_trail = (times_traj >= trail_start) & (
                times_traj <= current_time)
            if mask_trail.any():
                positions = positions_all[mask_trail]
                lines[fl_id].set_data(positions[:, 0], positions[:, 1])
            else:
                lines[fl_id].set_data([], [])

            if len(times_traj) > 0:
                idx = np.searchsorted(times_traj, current_time)
                if 0 < idx < len(times_traj):
                    t0, t1 = times_traj[idx - 1], times_traj[idx]
                    p0, p1 = positions_all[idx - 1], positions_all[idx]
                    alpha = (current_time - t0) / \
                        (t1 - t0) if t1 > t0 else 0
                    current_pos = p0 + alpha * (p1 - p0)
                elif idx <= 0:
                    current_pos = positions_all[0]
                else:
                    current_pos = positions_all[-1]
                scatters[fl_id].set_offsets([current_pos])
            else:
                scatters[fl_id].set_offsets([])

        time_text_warehouse.set_text(
            f"Time: {current_time:.1f}s / {max_time:.0f}s")
        created_text.set_text(f"Created: {s.created}")
        completed_text.set_text(f"Completed: {s.completed}")
        storage_text.set_text(f"Storage: {s.storage_level}")

        line_created.set_data(times[: frame_idx + 1], created[: frame_idx + 1])
        line_completed.set_data(
            times[: frame_idx + 1], completed[: frame_idx + 1])
        line_storage.set_data(times[: frame_idx + 1],
                              storage_level[: frame_idx + 1])

        # Update speed and height charts (rolling window, dynamic axes)
        window_start = max(0.0, current_time - window_seconds)
        window_span = current_time - window_start
        speed_min = None
        speed_max = None
        height_min = None
        height_max = None
        for fl_id, trajectory in recorder.get_all_trajectories().items():
            times_traj = trajectory.get_times()

            # Filter data within the rolling window
            mask = (times_traj >= window_start) & (times_traj <= current_time)
            if mask.any():
                times_filtered = times_traj[mask]

                # Get horizontal (planar) speeds for this forklift
                speeds_all = trajectory.get_speeds_horizontal()
                if len(speeds_all) > 0:
                    speeds_filtered = speeds_all[mask]
                    speed_lines[fl_id].set_data(
                        times_filtered, speeds_filtered)
                    current_min = float(np.min(speeds_filtered))
                    current_max = float(np.max(speeds_filtered))
                    speed_min = current_min if speed_min is None else min(
                        speed_min, current_min)
                    speed_max = current_max if speed_max is None else max(
                        speed_max, current_max)
                else:
                    speed_lines[fl_id].set_data([], [])

                # Get heights for this forklift
                heights_all = trajectory.get_z_coordinates()
                if len(heights_all) > 0:
                    heights_filtered = heights_all[mask]
                    height_lines[fl_id].set_data(
                        times_filtered, heights_filtered)
                    current_min = float(np.min(heights_filtered))
                    current_max = float(np.max(heights_filtered))
                    height_min = current_min if height_min is None else min(
                        height_min, current_min)
                    height_max = current_max if height_max is None else max(
                        height_max, current_max)
                else:
                    height_lines[fl_id].set_data([], [])
            else:
                speed_lines[fl_id].set_data([], [])
                height_lines[fl_id].set_data([], [])

        if window_span > 0:
            ax_speed.set_xlim(window_start, current_time)
            ax_height.set_xlim(window_start, current_time)

        if speed_min is not None and speed_max is not None:
            if speed_max <= speed_min:
                speed_max = speed_min + 0.1
            speed_margin = max(0.1, (speed_max - speed_min) * 0.15)
            ax_speed.set_ylim(max(0.0, speed_min - speed_margin),
                              speed_max + speed_margin)

        if height_min is not None and height_max is not None:
            if height_max <= height_min:
                height_max = height_min + 0.1
            height_margin = max(0.1, (height_max - height_min) * 0.15)
            ax_height.set_ylim(height_min - height_margin,
                               height_max + height_margin)

        if rack_texts:
            rack_grid = s.rack_occupancy
            for r, row in enumerate(rack_texts):
                if r >= len(rack_grid):
                    break
                for b, txt_cell in enumerate(row):
                    if b < len(rack_grid[r]):
                        txt_cell.set_text(rack_grid[r][b])

        return list(lines.values()) + list(scatters.values()) + [
            time_text_warehouse,
            created_text,
            completed_text,
            storage_text,
        ] + list(stat_texts.values()) + [line_created, line_completed, line_storage] + \
            list(speed_lines.values()) + list(height_lines.values()) + \
            [t for row in rack_texts for t in row]

    def frame_generator():
        start = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - start
            target_sim_time = min(elapsed * playback_speed, max_time)
            idx = int(np.searchsorted(
                times_arr, target_sim_time, side="right") - 1)
            if idx < 0:
                idx = 0
            yield idx
            if target_sim_time >= max_time:
                break

    interval_ms = 1000 / fps
    # Dynamic axes for rolling windows require full redraws.
    anim = animation.FuncAnimation(
        fig,
        update,
        frames=frame_generator(),
        interval=interval_ms,
        blit=False,
        repeat=False,
    )

    fig.tight_layout()
    return fig, anim


def run_animation_cli(
    *,
    model_label: str,
    params_factory=Model1Params,
):
    parser = argparse.ArgumentParser(
        description=f"Animate {model_label} warehouse simulation")
    parser.add_argument(
        "--speed",
        type=float,
        default=5.0,
        help="Animation speed multiplier (e.g., 1x for real-time, 10x, 50x, 100x). Default: 5x",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=10.0,
        help="Animation frame rate (frames per second). Higher = smoother. Default: 10",
    )
    parser.add_argument(
        "--record-fps",
        type=float,
        default=10.0,
        help="Snapshot resolution in sim frames per second (e.g., 20). Default: derived from speed/fps",
    )
    parser.add_argument(
        "--trail-seconds",
        type=float,
        default=10.0,
        help="Show forklift path trail for the last N seconds of sim time. Default: 10",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Override simulation time in seconds (e.g., 900)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("DISCRETE-EVENT MODEL WITH WAREHOUSE ANIMATION")
    print("=" * 70)

    # speed controls how fast sim time passes; fps controls render cadence.
    # If record_fps is set, snapshot resolution is fixed and playback skips frames
    # as needed to maintain the target speed.
    speed = args.speed
    playback_fps = args.fps

    if args.record_fps is not None and args.record_fps > 0:
        sample_dt = 1.0 / args.record_fps
        record_fps = args.record_fps
    else:
        # Back-compat: sample rate tied to speed/fps (one snapshot per rendered frame)
        sample_dt = speed / playback_fps
        record_fps = 1.0 / sample_dt if sample_dt > 0 else 0.0

    # Recording interval should match the movement update_interval used in forklift movement (0.05-0.1s)
    # Note: Misalignment between recording and movement update can cause aliasing artifacts in speed calculations
    recording_interval = 0.1
    snapshot_stride = 1  # Show every snapshot

    sim_time_override = None
    print(f"\nMode: FULL ({speed}x speed, full model duration)")

    print(
        f"  - Snapshot resolution: {record_fps:.2f} fps ({sample_dt:.3f}s per snapshot)")
    print(
        f"  - Target render rate: {playback_fps:.1f} fps (frame skipping if slow)")
    print(f"  - Recording forklift positions every {recording_interval:.3f}s")
    print(f"  - Trail length: {args.trail_seconds:.0f}s")

    if args.sim_time is not None:
        sim_time_override = args.sim_time

    print("Running model and recording forklift movements ...")
    default_params = params_factory()
    snapshots, model, recorder = run_and_record(
        params=default_params,
        sample_dt=sample_dt,
        recording_interval=recording_interval,
        sim_time_override=sim_time_override,
    )
    print(
        f"\n✅ Collected {len(snapshots)} snapshots over {snapshots[-1].t:.1f}s")
    print(f"   Recorded {len(recorder.trajectories)} forklifts")
    print(
        f"   Playback: fps={playback_fps}, stride={snapshot_stride}, sample_dt={sample_dt}, record_interval={recording_interval}")

    # Calculate expected playback duration
    total_sim_time = snapshots[-1].t
    expected_playback_time = total_sim_time / speed
    print(f"\n⏱️  Animation timing:")
    print(f"   Total simulation time: {total_sim_time:.1f}s")
    print(
        f"   Expected playback duration: {expected_playback_time:.1f}s (at {speed}x speed)")
    print(f"   Frame interval: {1000/playback_fps:.1f}ms ({playback_fps} fps)")

    layout, _, _ = create_warehouse_with_standard_config(model.env, model.params)

    snapshots_for_anim = snapshots[::snapshot_stride]

    fig, anim = build_animation(
        snapshots_for_anim,
        recorder,
        layout,
        fps=playback_fps,
        playback_speed=speed,
        trail_seconds=args.trail_seconds,
    )

    print("\n" + "=" * 70)
    print("ANIMATION READY")
    print("=" * 70)
    print(f"\n📊 Animation settings:")
    print(f"   Speed: {speed}x")
    print(f"   FPS: {playback_fps}")
    print(f"   Total frames: {len(snapshots_for_anim)}")
    print(
        f"   Expected playback time: {expected_playback_time:.1f}s for {total_sim_time:.1f}s of simulation")
    print(f"   Frame interval: {1000/playback_fps:.1f}ms")
    print("\nShowing:")
    print("  Left:  Warehouse map with forklift movements and paths")
    print("  Top Right: Pipeline state (queue lengths, busy forklifts)")
    print("  Middle Right: Forklift speed & height charts (last 60s)")
    print("  Bottom: Time-series metrics (throughput & storage level)")
    print("\nClose window when done viewing.")
    print("=" * 70 + "\n")

    plt.show()


def main():
    run_animation_cli(model_label="Model 1", params_factory=Model1Params)


if __name__ == "__main__":
    main()
