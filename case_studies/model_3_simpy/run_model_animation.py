#!/usr/bin/env python3
"""Animate Model 3 conveyor simulation to inspect conveyor behavior."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Tuple

import matplotlib

matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import animation
from matplotlib.patches import Circle, Rectangle

if __package__ in (None, ""):
    package_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    __package__ = "model_3_simpy"

from .model import Model3SimModel
from .params import Model3Params
from mhsim.movement import Position3D
from mhsim.spatial import Path, PointNode, RectangularNode, Shelf, Storage, WarehouseLayout


@dataclass
class ConveyorItemTrace:
    item_id: int
    entered_t: float
    exited_t: float | None = None


@dataclass
class Snapshot:
    t: float
    source_out: int
    service1_in: int
    service1_out: int
    service1_queue: int
    service1_busy: int
    conveyor_enter_in: int
    conveyor_enter_out: int
    conveyor_enter_wip: int
    convey_in: int
    convey_out: int
    convey_wip: int
    conveyor_exit_in: int
    conveyor_exit_out: int
    conveyor_exit_wip: int
    service2_in: int
    service2_out: int
    service2_queue: int
    service2_busy: int
    sink_in: int
    created: int
    completed: int
    conveyor_occ: int
    conveyor_entered: int
    conveyor_exited: int


def _attach_conveyor_trace(model: Model3SimModel) -> List[ConveyorItemTrace]:
    traces: List[ConveyorItemTrace] = []
    active_ids: Deque[int] = deque()
    next_id = 1

    original_enter = model.conveyor.enter
    original_leave = model.conveyor.leave

    def traced_enter():
        nonlocal next_id
        yield from original_enter()
        traces.append(ConveyorItemTrace(item_id=next_id, entered_t=model.env.now))
        active_ids.append(next_id)
        next_id += 1

    def traced_leave():
        if active_ids:
            leaving_id = active_ids.popleft()
            traces[leaving_id - 1].exited_t = model.env.now
        return original_leave()

    model.conveyor.enter = traced_enter
    model.conveyor.leave = traced_leave
    return traces


def _build_snapshot(model: Model3SimModel) -> Snapshot:
    s1 = model.service1
    c_in = model.conveyor_enter
    c_move = model.convey
    c_out = model.conveyor_exit
    s2 = model.service2

    return Snapshot(
        t=model.env.now,
        source_out=model.stats.created,
        service1_in=s1.entered_count,
        service1_out=s1.finished_count,
        service1_queue=len(s1.resource.queue),
        service1_busy=s1.resource.count,
        conveyor_enter_in=c_in.entered_count,
        conveyor_enter_out=c_in.finished_count,
        conveyor_enter_wip=c_in.entered_count - c_in.finished_count,
        convey_in=c_move.entered_count,
        convey_out=c_move.finished_count,
        convey_wip=c_move.entered_count - c_move.finished_count,
        conveyor_exit_in=c_out.entered_count,
        conveyor_exit_out=c_out.finished_count,
        conveyor_exit_wip=c_out.entered_count - c_out.finished_count,
        service2_in=s2.entered_count,
        service2_out=s2.finished_count,
        service2_queue=len(s2.resource.queue),
        service2_busy=s2.resource.count,
        sink_in=model.sink.entered_count,
        created=model.stats.created,
        completed=model.stats.completed,
        conveyor_occ=model.conveyor.occupancy,
        conveyor_entered=model.conveyor.total_entered,
        conveyor_exited=model.conveyor.total_exited,
    )


def run_and_record(
    params: Model3Params | None = None,
    sample_dt: float = 0.1,
    sim_time_override: float | None = None,
) -> Tuple[List[Snapshot], Model3SimModel, List[ConveyorItemTrace]]:
    active_params = params or Model3Params()
    model = Model3SimModel(params=active_params)

    if sim_time_override is not None:
        model.params.sim_time = sim_time_override

    traces = _attach_conveyor_trace(model)
    snapshots: List[Snapshot] = []

    def sampler():
        while True:
            snapshots.append(_build_snapshot(model))
            yield model.env.timeout(sample_dt)

    model.env.process(sampler())
    model.source.start()

    stop_time = model.params.sim_time
    chunk = max(sample_dt, 5.0)
    last_report = -10.0
    while model.env.now < stop_time:
        model.env.run(until=min(stop_time, model.env.now + chunk))
        if model.env.now - last_report >= 10.0 or model.env.now >= stop_time:
            pct = (model.env.now / stop_time) * 100.0 if stop_time > 0 else 100.0
            print(
                f"   ... model progress {model.env.now:.0f}/{stop_time:.0f}s ({pct:.0f}%) "
                f"created={model.stats.created} completed={model.stats.completed} conveyor_occ={model.conveyor.occupancy}"
            )
            last_report = model.env.now

    if not snapshots or snapshots[-1].t < model.env.now:
        snapshots.append(_build_snapshot(model))

    return snapshots, model, traces


def _active_pallet_positions(
    traces: List[ConveyorItemTrace],
    current_time: float,
    speed_mps: float,
    length_m: float,
) -> Tuple[np.ndarray, np.ndarray]:
    ids: List[int] = []
    positions: List[float] = []
    for trace in traces:
        if trace.entered_t > current_time:
            break
        if trace.exited_t is not None and trace.exited_t <= current_time:
            continue
        distance = (current_time - trace.entered_t) * speed_mps
        positions.append(max(0.0, min(length_m, distance)))
        ids.append(trace.item_id)
    return np.asarray(ids, dtype=int), np.asarray(positions, dtype=float)


def _build_reference_warehouse_layout() -> WarehouseLayout:
    storage = Storage()
    storage.add_shelf(
        Shelf(
            id="rack_1",
            position=Position3D(34, 38, 0),
            levels=6,
            positions_per_level=10,
            cell_depth=0.24,
            level_height=0.1,
            position_spacing=0.1,
        )
    )
    storage.add_shelf(
        Shelf(
            id="rack_2",
            position=Position3D(34, 41, 0),
            levels=6,
            positions_per_level=10,
            cell_depth=0.24,
            level_height=0.1,
            position_spacing=0.1,
        )
    )

    paths = [
        Path(
            "path_top",
            [Position3D(23, 35.5, 0), Position3D(29, 35.5, 0), Position3D(35, 35.5, 0)],
        ),
        Path(
            "path_bottom",
            [Position3D(23, 45.3, 0), Position3D(29, 45.3, 0), Position3D(35, 45.3, 0)],
        ),
        Path(
            "left_vertical",
            [Position3D(23, 35.5, 0), Position3D(23, 40.5, 0), Position3D(23, 45.3, 0)],
        ),
        Path(
            "right_vertical",
            [Position3D(35, 35.5, 0), Position3D(35, 40.5, 0), Position3D(35, 45.3, 0)],
        ),
        Path(
            "center_vertical",
            [Position3D(29, 35.5, 0), Position3D(29, 40.5, 0), Position3D(29, 45.3, 0)],
        ),
        Path(
            "inbound_connector",
            [Position3D(16, 40.5, 0), Position3D(23, 40.5, 0)],
        ),
        Path(
            "outbound_connector",
            [Position3D(35, 40.5, 0), Position3D(43, 40.5, 0)],
        ),
        Path(
            "home_connector",
            [Position3D(29, 28, 0), Position3D(29, 35.5, 0)],
        ),
        Path(
            "rack1_connector",
            [Position3D(34.45, 37.76, 0), Position3D(35, 37.76, 0), Position3D(35, 35.5, 0)],
        ),
        Path(
            "rack2_connector",
            [Position3D(34.45, 40.76, 0), Position3D(35, 40.76, 0), Position3D(35, 40.5, 0)],
        ),
    ]

    return WarehouseLayout(
        inbound_area=PointNode("inbound", Position3D(16, 40.5, 0)),
        outbound_area=PointNode("outbound", Position3D(43, 40.5, 0)),
        forklifts_home=RectangularNode("home", Position3D(24, 26, 0), width=10, depth=4, height=2.5),
        storage=storage,
        paths=paths,
    )


def _draw_warehouse_map(ax, layout: WarehouseLayout, conveyor_length_m: float):
    ax.set_xlim(12, 45)
    ax.set_ylim(24, 48)
    ax.set_aspect("equal")
    ax.set_xlabel("X position (m)")
    ax.set_ylabel("Y position (m)")
    ax.set_title("Warehouse Map", fontweight="bold")
    ax.grid(True, alpha=0.2)

    areas = [
        (layout.inbound_area, {"edgecolor": "#388E3C"}),
        (layout.outbound_area, {"edgecolor": "#1976D2"}),
        (layout.forklifts_home, {"edgecolor": "#6A1B9A"}),
    ]
    for area, style in areas:
        if isinstance(area, PointNode):
            circle = Circle(
                (area.position.x, area.position.y),
                radius=1.0,
                fill=False,
                lw=1.5,
                linestyle="--",
                edgecolor=style["edgecolor"],
                alpha=0.9,
            )
            ax.add_patch(circle)
            ax.text(
                area.position.x,
                area.position.y + 1.4,
                area.id,
                color=style["edgecolor"],
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
                edgecolor=style["edgecolor"],
                alpha=0.9,
            )
            ax.add_patch(rect)
            ax.text(
                area.position.x + area.width / 2,
                area.position.y + area.depth + 0.3,
                area.id,
                color=style["edgecolor"],
                ha="center",
                va="bottom",
                fontsize=9,
            )

    for shelf in layout.storage.shelves:
        shelf_rect = Rectangle(
            (shelf.position.x, shelf.position.y - shelf.cell_depth),
            shelf.positions_per_level * shelf.position_spacing,
            shelf.cell_depth,
            fill=False,
            lw=1.2,
            edgecolor="#455A64",
            alpha=0.9,
        )
        ax.add_patch(shelf_rect)
        ax.text(
            shelf.position.x,
            shelf.position.y - shelf.cell_depth - 0.25,
            shelf.id,
            color="#455A64",
            ha="left",
            va="top",
            fontsize=8,
        )

    for path in layout.paths:
        if not path.waypoints:
            continue
        xs = [p.x for p in path.waypoints]
        ys = [p.y for p in path.waypoints]
        ax.plot(xs, ys, linestyle="-", color="#90CAF9", linewidth=0.8, alpha=0.9)
        ax.scatter(xs, ys, s=4, color="#2196F3", alpha=0.8)

    conveyor_y = 40.5
    conveyor_start = layout.inbound_area.position.x
    conveyor_end = min(layout.outbound_area.position.x, conveyor_start + conveyor_length_m)
    ax.plot(
        [conveyor_start, conveyor_end],
        [conveyor_y, conveyor_y],
        linestyle="-",
        color="#EF6C00",
        linewidth=2.2,
        alpha=0.9,
        label="Model 3 conveyor",
    )
    ax.legend(loc="upper right", fontsize=8)


def build_animation(
    snapshots: List[Snapshot],
    traces: List[ConveyorItemTrace],
    model: Model3SimModel,
    layout: WarehouseLayout,
    fps: float = 10.0,
    playback_speed: float = 5.0,
):
    if not snapshots:
        raise ValueError("No snapshots to animate.")

    times = [s.t for s in snapshots]
    times_arr = np.asarray(times, dtype=float)
    max_time = times[-1] if times else 1.0

    created = [s.created for s in snapshots]
    completed = [s.completed for s in snapshots]
    occupancy = [s.conveyor_occ for s in snapshots]
    max_occ = max(occupancy) if occupancy else 1

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[1.2, 1.0],
        height_ratios=[1.05, 1.0],
        hspace=0.34,
        wspace=0.25,
    )
    ax_warehouse = fig.add_subplot(gs[0, 0])
    ax_conveyor = fig.add_subplot(gs[0, 1])
    ax_pipeline = fig.add_subplot(gs[1, 0])
    ax_counts = fig.add_subplot(gs[1, 1])

    conveyor_length = model.params.conveyor_length_m
    _draw_warehouse_map(ax_warehouse, layout=layout, conveyor_length_m=conveyor_length)
    map_status_text = ax_warehouse.text(0.02, 0.98, "", transform=ax_warehouse.transAxes, va="top", fontsize=10)

    ax_conveyor.set_xlim(-1.0, conveyor_length + 1.0)
    ax_conveyor.set_ylim(0.0, 1.0)
    ax_conveyor.set_yticks([])
    ax_conveyor.set_xlabel("Conveyor position (m)")
    ax_conveyor.set_title("Conveyor State", fontweight="bold")
    ax_conveyor.grid(True, axis="x", alpha=0.25)

    belt = Rectangle((0.0, 0.35), conveyor_length, 0.3, facecolor="#CFD8DC", edgecolor="#455A64", lw=1.2)
    ax_conveyor.add_patch(belt)
    ax_conveyor.text(0.0, 0.75, "Enter", ha="left", va="bottom", fontsize=9, color="#2E7D32")
    ax_conveyor.text(conveyor_length, 0.75, "Exit", ha="right", va="bottom", fontsize=9, color="#1565C0")

    pallet_scatter = ax_conveyor.scatter([], [], s=120, color="#FB8C00", edgecolors="black", linewidths=1.0, zorder=3)
    summary_text = ax_conveyor.text(0.01, 0.98, "", transform=ax_conveyor.transAxes, va="top", fontsize=10)

    ax_pipeline.set_xlim(0.0, 1.0)
    ax_pipeline.set_ylim(0.0, 1.0)
    ax_pipeline.axis("off")
    ax_pipeline.set_title("Pipeline State", fontweight="bold")

    node_names = ["source", "service1", "conv_enter", "convey", "conv_exit", "service2", "sink"]
    x_positions = np.linspace(0.08, 0.92, len(node_names))
    stat_texts = {}
    for name, x in zip(node_names, x_positions):
        rect = Rectangle((x - 0.06, 0.38), 0.12, 0.24, fill=False, lw=1.2)
        ax_pipeline.add_patch(rect)
        ax_pipeline.text(x, 0.67, name, ha="center", va="bottom", fontsize=8)
        stat_texts[name] = ax_pipeline.text(
            x,
            0.50,
            "",
            ha="center",
            va="center",
            fontsize=7,
            family="monospace",
        )
    for i in range(len(x_positions) - 1):
        ax_pipeline.annotate(
            "",
            xy=(x_positions[i + 1] - 0.07, 0.50),
            xytext=(x_positions[i] + 0.07, 0.50),
            arrowprops={"arrowstyle": "->", "lw": 1.0, "color": "#607D8B"},
        )

    (line_created,) = ax_counts.plot([], [], color="#2E7D32", lw=2.0, label="Created")
    (line_completed,) = ax_counts.plot([], [], color="#1565C0", lw=2.0, linestyle="--", label="Completed")
    ax_counts_occ = ax_counts.twinx()
    (line_occ,) = ax_counts_occ.plot(
        [], [], color="#EF6C00", lw=2.0, linestyle="-.", label="Conveyor occupancy"
    )

    ax_counts.set_xlim(times[0], max_time)
    ax_counts.set_ylim(0, max(max(created), max(completed)) * 1.2 + 1)
    ax_counts_occ.set_ylim(0, max_occ * 1.2 + 1)
    ax_counts.set_xlabel("Time (s)")
    ax_counts.set_ylabel("Throughput count")
    ax_counts_occ.set_ylabel("Conveyor occupancy", color="#EF6C00")
    ax_counts_occ.tick_params(axis="y", colors="#EF6C00")
    ax_counts.set_title("Throughput and Conveyor Occupancy", fontweight="bold")
    ax_counts.grid(True, alpha=0.3)
    legend_lines = [line_created, line_completed, line_occ]
    legend_labels = [line.get_label() for line in legend_lines]
    ax_counts.legend(legend_lines, legend_labels, loc="upper left", fontsize=9)

    def update(frame_idx: int):
        if frame_idx >= len(snapshots):
            frame_idx = len(snapshots) - 1
        snap = snapshots[frame_idx]
        current_time = snap.t

        _, positions = _active_pallet_positions(
            traces=traces,
            current_time=current_time,
            speed_mps=model.params.conveyor_speed_mps,
            length_m=conveyor_length,
        )
        if len(positions) > 0:
            points = np.column_stack([positions, np.full(len(positions), 0.5)])
        else:
            points = np.empty((0, 2))
        pallet_scatter.set_offsets(points)

        map_status_text.set_text(
            f"t={current_time:.1f}s\ncreated={snap.created} completed={snap.completed}\nconveyor_occ={snap.conveyor_occ}"
        )
        summary_text.set_text(
            f"t={current_time:.1f}s / {max_time:.1f}s\n"
            f"occ={snap.conveyor_occ} entered={snap.conveyor_entered} exited={snap.conveyor_exited}"
        )

        stat_texts["source"].set_text(f"out:{snap.source_out}")
        stat_texts["service1"].set_text(
            f"in:{snap.service1_in}\nq:{snap.service1_queue}\nb:{snap.service1_busy}\nout:{snap.service1_out}"
        )
        stat_texts["conv_enter"].set_text(
            f"in:{snap.conveyor_enter_in}\nout:{snap.conveyor_enter_out}\nwip:{snap.conveyor_enter_wip}"
        )
        stat_texts["convey"].set_text(
            f"in:{snap.convey_in}\nout:{snap.convey_out}\nwip:{snap.convey_wip}"
        )
        stat_texts["conv_exit"].set_text(
            f"in:{snap.conveyor_exit_in}\nout:{snap.conveyor_exit_out}\nwip:{snap.conveyor_exit_wip}"
        )
        stat_texts["service2"].set_text(
            f"in:{snap.service2_in}\nq:{snap.service2_queue}\nb:{snap.service2_busy}\nout:{snap.service2_out}"
        )
        stat_texts["sink"].set_text(f"in:{snap.sink_in}")

        line_created.set_data(times[: frame_idx + 1], created[: frame_idx + 1])
        line_completed.set_data(times[: frame_idx + 1], completed[: frame_idx + 1])
        line_occ.set_data(times[: frame_idx + 1], occupancy[: frame_idx + 1])

        return [
            pallet_scatter,
            map_status_text,
            summary_text,
            *stat_texts.values(),
            line_created,
            line_completed,
            line_occ,
        ]

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
        interval=1000.0 / fps,
        blit=False,
        repeat=False,
    )

    fig.tight_layout()
    return fig, anim


def run_animation_cli():
    parser = argparse.ArgumentParser(description="Animate Model 3 conveyor simulation.")
    parser.add_argument(
        "--speed",
        type=float,
        default=5.0,
        help="Animation speed multiplier (sim seconds per wall second). Default: 5",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=20.0,
        help="Animation frame rate. Default: 20",
    )
    parser.add_argument(
        "--record-fps",
        type=float,
        default=20.0,
        help="Simulation snapshot resolution. Default: 20",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=None,
        help="Override simulation time in seconds.",
    )
    args = parser.parse_args()

    speed = args.speed
    playback_fps = args.fps
    if args.record_fps and args.record_fps > 0:
        sample_dt = 1.0 / args.record_fps
        record_fps = args.record_fps
    else:
        sample_dt = speed / playback_fps
        record_fps = 1.0 / sample_dt if sample_dt > 0 else 0.0

    print("\n" + "=" * 70)
    print("MODEL 3 CONVEYOR ANIMATION")
    print("=" * 70)
    print(f"Mode: FULL ({speed}x speed)")
    print(f"  - Snapshot resolution: {record_fps:.2f} fps ({sample_dt:.3f}s per snapshot)")
    print(f"  - Target render rate: {playback_fps:.1f} fps")

    params = Model3Params()
    snapshots, model, traces = run_and_record(
        params=params,
        sample_dt=sample_dt,
        sim_time_override=args.sim_time,
    )

    total_sim_time = snapshots[-1].t
    expected_playback_time = total_sim_time / speed if speed > 0 else 0.0
    print(f"\nCollected {len(snapshots)} snapshots over {total_sim_time:.1f}s")
    print(f"Tracked {len(traces)} conveyor pallets")
    print(f"Expected playback duration: {expected_playback_time:.1f}s")

    layout = _build_reference_warehouse_layout()

    fig, anim = build_animation(
        snapshots=snapshots,
        traces=traces,
        model=model,
        layout=layout,
        fps=playback_fps,
        playback_speed=speed,
    )

    _ = (fig, anim)  # keep references alive for matplotlib
    print("Showing:")
    print("  Top Left:  Warehouse map reference (with conveyor path)")
    print("  Top Right: Conveyor occupancy and moving pallets")
    print("  Bottom Left: Pipeline block counters")
    print("  Bottom Right: Throughput and occupancy time series")
    print("\nClose the window when done.")
    print("=" * 70 + "\n")
    plt.show()


def main():
    run_animation_cli()


if __name__ == "__main__":
    main()
