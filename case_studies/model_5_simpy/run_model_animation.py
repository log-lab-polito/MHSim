#!/usr/bin/env python3
"""Animate warehouse simulations with forklift paths and metrics."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import matplotlib
import numpy as np
from matplotlib.patches import Rectangle

from .model import Model5SimModel
from .params import Model5Params
from .spatial import PointNode, RectangularNode
from .visualization import MovementRecorder, create_recording_process

try:
    matplotlib.use("TkAgg")
except Exception:  # pragma: no cover - backend fallback is environment-specific
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import animation


@dataclass
class Snapshot:
    t: float
    created: int
    completed: int
    storage_level: int
    stage_stats: dict[str, str]
    rack_occupancy: list[list[str]] | None = None


SnapshotBuilder = Callable[[Any], Snapshot]
LayoutResolver = Callable[[Any], Any]


def _block_contains(block: Any) -> int:
    return max(
        0,
        getattr(block, "entered_count", 0) - getattr(block, "completed_count", 0),
    )


def build_model5_snapshot(model: Model5SimModel) -> Snapshot:
    service1 = model.service1
    service2 = model.service2
    storage_level = int(model.get_storage_level())

    return Snapshot(
        t=model.env.now,
        created=model.stats.created,
        completed=model.stats.completed,
        storage_level=storage_level,
        stage_stats={
            "source": f"out:{model.stats.created}",
            "service1": (
                f"in:{getattr(service1, 'entered_count', 0)}\n"
                f"queue:{len(service1.resource.queue)}\n"
                f"delay:{service1.resource.count}\n"
                f"out:{getattr(service1, 'finished_count', 0)}"
            ),
            "store": (
                f"in:{getattr(model.store, 'entered_count', 0)}\n"
                f"out:{getattr(model.store, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.store)}"
            ),
            "delay": (
                f"in:{getattr(model.delay, 'entered_count', 0)}\n"
                f"out:{getattr(model.delay, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.delay)}"
            ),
            "retrieve": (
                f"in:{getattr(model.retrieve, 'entered_count', 0)}\n"
                f"out:{getattr(model.retrieve, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.retrieve)}"
            ),
            "service2": (
                f"in:{getattr(service2, 'entered_count', 0)}\n"
                f"queue:{len(service2.resource.queue)}\n"
                f"delay:{service2.resource.count}\n"
                f"out:{getattr(service2, 'finished_count', 0)}"
            ),
            "sink": f"in:{getattr(model.sink, 'entered_count', model.stats.completed)}",
        },
        rack_occupancy=model.slot_manager.occupancy_grid(model.layout.storage),
    )


def run_and_record(
    *,
    params: Any | None = None,
    sample_dt: float = 2.0,
    recording_interval: float = 1.0,
    sim_time_override: float | None = None,
    model_factory: Callable[..., Any] = Model5SimModel,
    snapshot_builder: SnapshotBuilder = build_model5_snapshot,
    storage_metric_label: str = "Storage",
) -> Tuple[List[Snapshot], Any, MovementRecorder]:
    """Run the model and collect state snapshots plus forklift trajectories."""
    active_params = params or Model5Params()
    model = model_factory(params=active_params)

    if sim_time_override is not None:
        model.params.sim_time = sim_time_override

    env = model.env
    fleet = model.fleet
    snapshots: List[Snapshot] = []

    recorder = MovementRecorder()
    env.process(
        create_recording_process(
            env, fleet.forklifts, recorder, recording_interval=recording_interval
        )
    )

    def sampler():
        while True:
            snapshots.append(snapshot_builder(model))
            yield env.timeout(sample_dt)

    env.process(sampler())
    model.source.start()

    stop_time = model.params.sim_time
    chunk = max(sample_dt, 5.0)
    last_report = 0.0
    while env.now < stop_time:
        env.run(until=min(stop_time, env.now + chunk))
        if env.now - last_report >= 10.0 or env.now >= stop_time:
            pct = (env.now / stop_time) * 100.0 if stop_time > 0 else 100.0
            metric_level = (
                snapshots[-1].storage_level
                if snapshots
                else snapshot_builder(model).storage_level
            )
            print(
                f"   ... model progress {env.now:.0f}/{stop_time:.0f}s ({pct:.0f}%) "
                f"created={model.stats.created} completed={model.stats.completed} "
                f"{storage_metric_label}={metric_level}"
            )
            last_report = env.now

    if not snapshots or snapshots[-1].t < env.now:
        snapshots.append(snapshot_builder(model))

    return snapshots, model, recorder


def _iter_layout_nodes(layout: Any) -> list[Any]:
    nodes: list[Any] = []
    seen_ids: set[int] = set()

    for candidate in (
        getattr(layout, "inbound_area", None),
        getattr(layout, "outbound_area", None),
        getattr(layout, "forklifts_home", None),
        getattr(layout, "storage_rack", None),
        *getattr(layout, "extra_nodes", []),
    ):
        if candidate is None:
            continue
        node_id = id(candidate)
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(candidate)

    return nodes


def _warehouse_axis_limits(
    layout: Any, recorder: MovementRecorder
) -> tuple[tuple[float, float], tuple[float, float]]:
    xs: list[float] = []
    ys: list[float] = []

    def add_point(point: Any) -> None:
        xs.append(float(point.x))
        ys.append(float(point.y))

    for node in _iter_layout_nodes(layout) if layout is not None else []:
        if isinstance(node, PointNode):
            add_point(node.position)
        elif isinstance(node, RectangularNode):
            xs.extend([float(node.position.x), float(node.position.x + node.width)])
            ys.extend([float(node.position.y), float(node.position.y + node.depth)])

    if layout is not None and getattr(layout, "storage", None):
        for shelf in getattr(layout.storage, "shelves", []):
            xs.extend(
                [
                    float(shelf.position.x),
                    float(
                        shelf.position.x
                        + shelf.positions_per_level * shelf.position_spacing
                    ),
                ]
            )
            ys.extend(
                [float(shelf.position.y - shelf.cell_depth), float(shelf.position.y)]
            )

    if layout is not None and getattr(layout, "paths", None):
        for path in layout.paths:
            for waypoint in path.waypoints:
                add_point(waypoint)

    for trajectory in recorder.get_all_trajectories().values():
        positions = trajectory.get_positions_xy()
        if len(positions) > 0:
            xs.extend(float(x) for x in positions[:, 0])
            ys.extend(float(y) for y in positions[:, 1])

    if not xs or not ys:
        return (12.0, 45.0), (24.0, 48.0)

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = max(1.0, x_max - x_min)
    y_span = max(1.0, y_max - y_min)
    margin = max(1.0, x_span * 0.12, y_span * 0.12)
    return (x_min - margin, x_max + margin), (y_min - margin, y_max + margin)


def build_animation(
    snapshots: List[Snapshot],
    recorder: MovementRecorder,
    layout: Any,
    *,
    fps: int = 6,
    playback_speed: float = 1.0,
    trail_seconds: float = 10.0,
    pipeline_stage_names: Optional[list[str]] = None,
    storage_metric_label: str = "Storage",
):
    if not snapshots:
        raise ValueError("No snapshots to animate")

    times = [s.t for s in snapshots]
    times_arr = np.asarray(times, dtype=float)
    created = [s.created for s in snapshots]
    completed = [s.completed for s in snapshots]
    storage_level = [s.storage_level for s in snapshots]
    max_time = max(times) if times else 1.0
    pipeline_names = pipeline_stage_names or list(snapshots[0].stage_stats.keys())

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
        3,
        2,
        width_ratios=[1.45, 0.75],
        height_ratios=[1, 1, 1.1],
        hspace=0.55,
        wspace=0.3,
    )
    ax_warehouse = fig.add_subplot(gs[0:2, 0])
    ax_flow = fig.add_subplot(gs[0, 1])
    gs_metrics = gs[1, 1].subgridspec(2, 1, hspace=0.6)
    ax_speed = fig.add_subplot(gs_metrics[0])
    ax_height = fig.add_subplot(gs_metrics[1])
    ax_ts = fig.add_subplot(gs[2, 0])
    ax_rack = fig.add_subplot(gs[2, 1])

    x_limits, y_limits = _warehouse_axis_limits(layout, recorder)
    ax_warehouse.set_xlim(*x_limits)
    ax_warehouse.set_ylim(*y_limits)
    ax_warehouse.set_aspect("equal")
    ax_warehouse.set_xlabel("X Position (m)", fontsize=11)
    ax_warehouse.set_ylabel("Y Position (m)", fontsize=11)
    ax_warehouse.set_title(
        "Warehouse Map with Forklift Movements", fontsize=12, fontweight="bold"
    )
    ax_warehouse.grid(True, alpha=0.2)

    if layout is not None:
        for area in _iter_layout_nodes(layout):
            if isinstance(area, PointNode):
                from matplotlib.patches import Circle

                circle = Circle(
                    (area.position.x, area.position.y),
                    radius=1.0,
                    fill=False,
                    lw=1.5,
                    linestyle="--",
                    edgecolor="#455A64",
                    alpha=0.8,
                )
                ax_warehouse.add_patch(circle)
                ax_warehouse.text(
                    area.position.x,
                    area.position.y + 1.5,
                    area.id,
                    color="#455A64",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )
            elif isinstance(area, RectangularNode):
                rect = Rectangle(
                    (area.position.x, area.position.y),
                    area.width,
                    area.depth,
                    fill=False,
                    lw=1.5,
                    linestyle="--",
                    edgecolor="#455A64",
                    alpha=0.8,
                )
                ax_warehouse.add_patch(rect)
                ax_warehouse.text(
                    area.position.x + area.width / 2,
                    area.position.y + area.depth + 0.3,
                    area.id,
                    color="#455A64",
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
                ax_warehouse.plot(
                    xs, ys, linestyle="-", color="#90CAF9", linewidth=0.8, alpha=0.9
                )
                ax_warehouse.scatter(xs, ys, s=4, color="#2196F3", alpha=0.8)

    lines = {}
    scatters = {}
    colors = plt.cm.tab10(np.linspace(0, 1, len(recorder.trajectories)))
    line_styles = ["-", "--", "-.", ":", "-", "--"]
    for (fl_id, trajectory), color, linestyle in zip(
        recorder.get_all_trajectories().items(),
        colors,
        line_styles[: len(recorder.trajectories)],
    ):
        line, = ax_warehouse.plot(
            [], [], linestyle=linestyle, label=fl_id, color=color, linewidth=2.0
        )
        lines[fl_id] = line
        scatter = ax_warehouse.scatter(
            [], [], s=15, color=color, edgecolors="black", linewidth=1.5
        )
        scatters[fl_id] = scatter

    ax_warehouse.legend(loc="upper right", fontsize=9)
    time_text_warehouse = ax_warehouse.text(
        0.02, 0.98, "", transform=ax_warehouse.transAxes, fontsize=10, va="top"
    )
    created_text = ax_warehouse.text(
        0.02,
        0.93,
        "",
        transform=ax_warehouse.transAxes,
        fontsize=10,
        va="top",
        color="tab:green",
    )
    completed_text = ax_warehouse.text(
        0.02,
        0.88,
        "",
        transform=ax_warehouse.transAxes,
        fontsize=10,
        va="top",
        color="tab:orange",
    )
    storage_text = ax_warehouse.text(
        0.02,
        0.83,
        "",
        transform=ax_warehouse.transAxes,
        fontsize=10,
        va="top",
        color="tab:blue",
    )

    x_positions = np.linspace(0.10, 0.90, len(pipeline_names))
    nodes = {name: (x, 0.76) for name, x in zip(pipeline_names, x_positions)}

    def draw_box(ax, center, label):
        x, y = center
        w, h = 0.14, 0.34
        rect = Rectangle((x - w / 2, y - h / 2), w, h, fill=False, lw=1.5)
        ax.add_patch(rect)
        text = ax.text(x, y + h / 2 + 0.035, label, ha="center", va="bottom", fontsize=8)
        return rect, text

    ax_flow.set_xlim(0, 1)
    ax_flow.set_ylim(0, 1)
    ax_flow.axis("off")
    ax_flow.set_title("Pipeline State", fontsize=11, fontweight="bold")

    window_seconds = min(60.0, max_time)
    trail_seconds = min(trail_seconds, max_time)

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
    ax_speed.tick_params(axis="both", labelsize=8)

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
    ax_height.set_ylim(
        min_height_global - height_margin, max_height_global + height_margin
    )
    ax_height.grid(True, alpha=0.3)
    ax_height.tick_params(axis="both", labelsize=8)

    speed_lines = {}
    height_lines = {}
    for (fl_id, trajectory), color, linestyle in zip(
        recorder.get_all_trajectories().items(),
        colors,
        line_styles[: len(recorder.trajectories)],
    ):
        speed_line, = ax_speed.plot(
            [], [], linestyle=linestyle, color=color, linewidth=1.5, label=fl_id
        )
        speed_lines[fl_id] = speed_line
        height_line, = ax_height.plot(
            [], [], linestyle=linestyle, color=color, linewidth=1.5, label=fl_id
        )
        height_lines[fl_id] = height_line

    ax_speed.legend(loc="upper right", fontsize=7, ncol=2)
    ax_height.legend(loc="upper right", fontsize=7, ncol=2)

    stat_texts = {}
    for name, pos in nodes.items():
        draw_box(ax_flow, pos, name)
        stat_texts[name] = ax_flow.text(
            pos[0],
            pos[1],
            "",
            ha="center",
            va="center",
            fontsize=7,
            family="monospace",
        )

    (line_created,) = ax_ts.plot(
        [], [], linestyle="-", color="tab:green", label="Created", linewidth=2
    )
    (line_completed,) = ax_ts.plot(
        [], [], linestyle="--", color="tab:orange", label="Completed", linewidth=2
    )
    (line_storage,) = ax_ts.plot(
        [], [], linestyle="-.", color="tab:blue", label=storage_metric_label, linewidth=2
    )

    ax_ts.set_xlim(times[0], max_time)
    ax_ts.set_ylim(0, max(max(created), max(completed), max(storage_level)) * 1.2 + 1)
    ax_ts.set_title(
        f"Cumulative Throughput & {storage_metric_label}", fontsize=11, fontweight="bold"
    )
    ax_ts.set_xlabel("Time (s)", fontsize=10)
    ax_ts.legend(loc="upper left", fontsize=9)
    ax_ts.grid(True, alpha=0.3)

    rack_texts: list[list[Any]] = []
    shelves = list(layout.storage.shelves) if layout and layout.storage else []
    max_bays = max((s.positions_per_level for s in shelves), default=0)
    has_rack_panel = bool(shelves and max_bays > 0 and snapshots[0].rack_occupancy is not None)
    if has_rack_panel:
        ax_rack.set_title("Rack Occupancy", fontsize=11, fontweight="bold")
        ax_rack.set_xlim(0, max_bays)
        ax_rack.set_ylim(0, len(shelves))
        ax_rack.set_xticks([i + 0.5 for i in range(max_bays)])
        ax_rack.set_xticklabels([str(i + 1) for i in range(max_bays)], fontsize=7)
        ax_rack.set_yticks([])
        ax_rack.set_xlabel("Bay", fontsize=9)
        ax_rack.grid(False)

        for row_index, shelf in enumerate(shelves):
            y = len(shelves) - row_index - 1
            ax_rack.text(-0.2, y + 0.5, shelf.id, ha="right", va="center", fontsize=8)
            row_texts = []
            for bay in range(shelf.positions_per_level):
                rect = Rectangle((bay, y), 1, 1, fill=False, lw=1.0, edgecolor="#455A64")
                ax_rack.add_patch(rect)
                txt_cell = ax_rack.text(
                    bay + 0.5, y + 0.5, "", ha="center", va="center", fontsize=7
                )
                row_texts.append(txt_cell)
            rack_texts.append(row_texts)
    else:
        ax_rack.set_axis_off()

    def update(frame_idx):
        if frame_idx >= len(snapshots):
            frame_idx = len(snapshots) - 1
        snapshot = snapshots[frame_idx]
        current_time = snapshot.t

        for name, text in stat_texts.items():
            text.set_text(snapshot.stage_stats.get(name, ""))

        for fl_id, trajectory in recorder.get_all_trajectories().items():
            times_traj = trajectory.get_times()
            positions_all = trajectory.get_positions_xy()

            trail_start = max(0.0, current_time - trail_seconds)
            mask_trail = (times_traj >= trail_start) & (times_traj <= current_time)
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
                    alpha = (current_time - t0) / (t1 - t0) if t1 > t0 else 0
                    current_pos = p0 + alpha * (p1 - p0)
                elif idx <= 0:
                    current_pos = positions_all[0]
                else:
                    current_pos = positions_all[-1]
                scatters[fl_id].set_offsets([current_pos])
            else:
                scatters[fl_id].set_offsets([])

        time_text_warehouse.set_text(f"Time: {current_time:.1f}s / {max_time:.0f}s")
        created_text.set_text(f"Created: {snapshot.created}")
        completed_text.set_text(f"Completed: {snapshot.completed}")
        storage_text.set_text(f"{storage_metric_label}: {snapshot.storage_level}")

        line_created.set_data(times[: frame_idx + 1], created[: frame_idx + 1])
        line_completed.set_data(times[: frame_idx + 1], completed[: frame_idx + 1])
        line_storage.set_data(times[: frame_idx + 1], storage_level[: frame_idx + 1])

        window_start = max(0.0, current_time - window_seconds)
        window_span = current_time - window_start
        speed_min = None
        speed_max = None
        height_min = None
        height_max = None
        for fl_id, trajectory in recorder.get_all_trajectories().items():
            times_traj = trajectory.get_times()
            mask = (times_traj >= window_start) & (times_traj <= current_time)
            if mask.any():
                times_filtered = times_traj[mask]

                speeds_all = trajectory.get_speeds_horizontal()
                if len(speeds_all) > 0:
                    speeds_filtered = speeds_all[mask]
                    speed_lines[fl_id].set_data(times_filtered, speeds_filtered)
                    current_min = float(np.min(speeds_filtered))
                    current_max = float(np.max(speeds_filtered))
                    speed_min = current_min if speed_min is None else min(speed_min, current_min)
                    speed_max = current_max if speed_max is None else max(speed_max, current_max)
                else:
                    speed_lines[fl_id].set_data([], [])

                heights_all = trajectory.get_z_coordinates()
                if len(heights_all) > 0:
                    heights_filtered = heights_all[mask]
                    height_lines[fl_id].set_data(times_filtered, heights_filtered)
                    current_min = float(np.min(heights_filtered))
                    current_max = float(np.max(heights_filtered))
                    height_min = current_min if height_min is None else min(height_min, current_min)
                    height_max = current_max if height_max is None else max(height_max, current_max)
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
            ax_speed.set_ylim(max(0.0, speed_min - speed_margin), speed_max + speed_margin)

        if height_min is not None and height_max is not None:
            if height_max <= height_min:
                height_max = height_min + 0.1
            height_margin = max(0.1, (height_max - height_min) * 0.15)
            ax_height.set_ylim(height_min - height_margin, height_max + height_margin)

        if rack_texts and snapshot.rack_occupancy is not None:
            for row_index, row in enumerate(rack_texts):
                if row_index >= len(snapshot.rack_occupancy):
                    break
                for bay_index, txt_cell in enumerate(row):
                    if bay_index < len(snapshot.rack_occupancy[row_index]):
                        txt_cell.set_text(snapshot.rack_occupancy[row_index][bay_index])

        return (
            list(lines.values())
            + list(scatters.values())
            + [time_text_warehouse, created_text, completed_text, storage_text]
            + list(stat_texts.values())
            + [line_created, line_completed, line_storage]
            + list(speed_lines.values())
            + list(height_lines.values())
            + [cell for row in rack_texts for cell in row]
        )

    def frame_generator():
        start = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - start
            target_sim_time = min(elapsed * playback_speed, max_time)
            idx = int(np.searchsorted(times_arr, target_sim_time, side="right") - 1)
            if idx < 0:
                idx = 0
            yield idx
            if target_sim_time >= max_time:
                break

    anim = animation.FuncAnimation(
        fig,
        update,
        frames=frame_generator(),
        interval=1000 / fps,
        blit=False,
        repeat=False,
    )

    fig.tight_layout()
    return fig, anim


def run_animation_cli(
    *,
    model_label: str,
    params_factory: Callable[[], Any] = Model5Params,
    model_factory: Callable[..., Any] = Model5SimModel,
    snapshot_builder: SnapshotBuilder = build_model5_snapshot,
    layout_resolver: LayoutResolver = lambda model: model.layout,
    pipeline_stage_names: Optional[list[str]] = None,
    storage_metric_label: str = "Storage",
):
    parser = argparse.ArgumentParser(
        description=f"Animate {model_label} warehouse simulation"
    )
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

    speed = args.speed
    playback_fps = args.fps

    if args.record_fps is not None and args.record_fps > 0:
        sample_dt = 1.0 / args.record_fps
        record_fps = args.record_fps
    else:
        sample_dt = speed / playback_fps
        record_fps = 1.0 / sample_dt if sample_dt > 0 else 0.0

    recording_interval = 0.1

    print(f"\nMode: FULL ({speed}x speed, full model duration)")
    print(f"  - Snapshot resolution: {record_fps:.2f} fps ({sample_dt:.3f}s per snapshot)")
    print(f"  - Target render rate: {playback_fps:.1f} fps (frame skipping if slow)")
    print(f"  - Recording forklift positions every {recording_interval:.3f}s")
    print(f"  - Trail length: {args.trail_seconds:.0f}s")

    print("Running model and recording forklift movements ...")
    default_params = params_factory()
    snapshots, model, recorder = run_and_record(
        params=default_params,
        sample_dt=sample_dt,
        recording_interval=recording_interval,
        sim_time_override=args.sim_time,
        model_factory=model_factory,
        snapshot_builder=snapshot_builder,
        storage_metric_label=storage_metric_label,
    )
    print(f"\nCollected {len(snapshots)} snapshots over {snapshots[-1].t:.1f}s")
    print(f"   Recorded {len(recorder.trajectories)} forklifts")

    total_sim_time = snapshots[-1].t
    expected_playback_time = total_sim_time / speed if speed > 0 else total_sim_time
    print(f"\nAnimation timing:")
    print(f"   Total simulation time: {total_sim_time:.1f}s")
    print(f"   Expected playback duration: {expected_playback_time:.1f}s (at {speed}x speed)")
    print(f"   Frame interval: {1000 / playback_fps:.1f}ms ({playback_fps} fps)")

    fig, anim = build_animation(
        snapshots,
        recorder,
        layout_resolver(model),
        fps=playback_fps,
        playback_speed=speed,
        trail_seconds=args.trail_seconds,
        pipeline_stage_names=pipeline_stage_names,
        storage_metric_label=storage_metric_label,
    )
    # Keep a strong reference alive until the window closes; otherwise
    # matplotlib may garbage-collect the animation before it ever renders.
    fig._mhsim_animation = anim

    print("\n" + "=" * 70)
    print("ANIMATION READY")
    print("=" * 70)
    print(f"\nAnimation settings:")
    print(f"   Speed: {speed}x")
    print(f"   FPS: {playback_fps}")
    print(f"   Total frames: {len(snapshots)}")
    print(f"   Expected playback time: {expected_playback_time:.1f}s for {total_sim_time:.1f}s of simulation")
    print(f"   Frame interval: {1000 / playback_fps:.1f}ms")
    print("\nClose window when done viewing.")
    print("=" * 70 + "\n")

    plt.show()


def main():
    run_animation_cli(model_label="Model 5", params_factory=Model5Params)


if __name__ == "__main__":
    main()
