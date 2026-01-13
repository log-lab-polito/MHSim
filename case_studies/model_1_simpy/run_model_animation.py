#!/usr/bin/env python3
"""Animate Model 1 warehouse simulation with forklift paths and metrics."""

from __future__ import annotations
from .visualization import MovementRecorder, create_recording_process
from .setup import create_warehouse_with_standard_config
from .params import Model1Params
from .model import Model1SimModel
from matplotlib.patches import Rectangle
from matplotlib import animation
import numpy as np
import matplotlib.pyplot as plt

import argparse
from dataclasses import dataclass
from typing import List, Tuple

import matplotlib

matplotlib.use("TkAgg")


@dataclass
class Snapshot:
    t: float
    storage_level: int
    service1_queue: int
    service1_busy: int
    store_in_flight: int
    delay_in_system: int
    retrieve_in_flight: int
    service2_queue: int
    service2_busy: int
    forklifts_busy: int
    forklifts_total: int
    created: int
    completed: int


def run_and_record(
    sample_dt: float = 2.0,
    recording_interval: float = 1.0,
    sim_time_override: float | None = None,
) -> Tuple[List[Snapshot], Model1SimModel, MovementRecorder]:
    """Run the model and collect state snapshots plus forklift trajectories."""
    model = Model1SimModel()

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
            snap = Snapshot(
                t=env.now,
                storage_level=int(storage.level),
                service1_queue=len(s1.resource.queue),
                service1_busy=s1.resource.count,
                store_in_flight=0,
                delay_in_system=0,
                retrieve_in_flight=0,
                service2_queue=len(s2.resource.queue),
                service2_busy=s2.resource.count,
                forklifts_busy=fleet.resource.count if hasattr(
                    fleet, "resource") else 0,
                forklifts_total=int(fleet.resource.capacity)
                if hasattr(fleet, "resource")
                else int(fleet.count_total()),
                created=model.stats.created,
                completed=model.stats.completed,
            )
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
        snapshots.append(
            Snapshot(
                t=env.now,
                storage_level=int(storage.level),
                service1_queue=len(s1.resource.queue),
                service1_busy=s1.resource.count,
                store_in_flight=0,
                delay_in_system=0,
                retrieve_in_flight=0,
                service2_queue=len(s2.resource.queue),
                service2_busy=s2.resource.count,
                forklifts_busy=fleet.resource.count if hasattr(
                    fleet, "resource") else 0,
                forklifts_total=int(fleet.resource.capacity)
                if hasattr(fleet, "resource")
                else int(fleet.count_total()),
                created=model.stats.created,
                completed=model.stats.completed,
            )
        )

    return snapshots, model, recorder


def build_animation(
    snapshots: List[Snapshot],
    recorder: MovementRecorder,
    layout,
    fps: int = 6,
):
    if not snapshots:
        raise ValueError("No snapshots to animate")

    times = [s.t for s in snapshots]
    created = [s.created for s in snapshots]
    completed = [s.completed for s in snapshots]
    storage_level = [s.storage_level for s in snapshots]
    max_time = max(times) if times else 1.0

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(
        3, 2, width_ratios=[1.2, 1], height_ratios=[1, 1, 1.1], hspace=0.35, wspace=0.3
    )
    ax_warehouse = fig.add_subplot(gs[0:2, 0])
    ax_flow = fig.add_subplot(gs[0, 1])
    ax_metrics = fig.add_subplot(gs[1, 1])
    ax_ts = fig.add_subplot(gs[2, :])

    ax_warehouse.set_xlim(50, 480)
    ax_warehouse.set_ylim(240, 480)
    ax_warehouse.set_aspect("equal")
    ax_warehouse.set_xlabel("X Position (m)", fontsize=11)
    ax_warehouse.set_ylabel("Y Position (m)", fontsize=11)
    ax_warehouse.set_title(
        "Warehouse Map with Forklift Movements", fontsize=12, fontweight="bold")
    ax_warehouse.grid(True, alpha=0.2)

    if layout is not None:
        areas = [
            (layout.inbound_area, {"edgecolor": "#388E3C"}),
            (layout.outbound_area, {"edgecolor": "#1976D2"}),
            (layout.forklifts_home, {"edgecolor": "#6A1B9A"}),
        ]
        for area, style in areas:
            if area is None:
                continue
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
                area.position.y + area.depth + 3,
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
                    shelf.position.y - shelf.cell_depth - 3,
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
                                  color="#90CAF9", linewidth=1.2, alpha=0.9)
                ax_warehouse.scatter(xs, ys, s=8, color="#2196F3", alpha=0.8)

    lines = {}
    scatters = {}
    colors = plt.cm.tab10(np.linspace(0, 1, len(recorder.trajectories)))
    line_styles = ["-", "--", "-.", ":", "-", "--"]
    for (fl_id, trajectory), color, linestyle in zip(
        recorder.get_all_trajectories().items(
        ), colors, line_styles[: len(recorder.trajectories)]
    ):
        line, = ax_warehouse.plot(
            [], [], linestyle=linestyle, label=fl_id, color=color, linewidth=2.5)
        lines[fl_id] = line
        scatter = ax_warehouse.scatter(
            [], [], s=100, color=color, edgecolors="black", linewidth=1.5)
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

    nodes = {
        "service1": (0.2, 0.7),
        "store": (0.35, 0.7),
        "delay": (0.5, 0.7),
        "retrieve": (0.65, 0.7),
        "service2": (0.8, 0.7),
        "storage": (0.5, 0.4),
        "fleet": (0.5, 0.15),
    }

    def draw_box(ax, center, label):
        x, y = center
        w, h = 0.15, 0.12
        rect = Rectangle((x - w / 2, y - h / 2), w, h, fill=False, lw=1.5)
        ax.add_patch(rect)
        text = ax.text(x, y + h / 2 + 0.03, label,
                       ha="center", va="bottom", fontsize=10)
        return rect, text

    ax_flow.set_xlim(0, 1)
    ax_flow.set_ylim(0, 1)
    ax_flow.axis("off")
    ax_flow.set_title("Pipeline State", fontsize=11, fontweight="bold")
    ax_metrics.axis("off")

    boxes = {}
    labels = {}
    for name, pos in nodes.items():
        rect, text = draw_box(ax_flow, pos, name)
        boxes[name] = rect
        labels[name] = text

    txt = {
        "service1_queue": ax_flow.text(nodes["service1"][0], nodes["service1"][1], "", ha="center", va="center", fontsize=11),
        "service1_busy": ax_flow.text(nodes["service1"][0], nodes["service1"][1] - 0.12, "", ha="center", va="center", fontsize=10, color="tab:blue"),
        "service2_queue": ax_flow.text(nodes["service2"][0], nodes["service2"][1], "", ha="center", va="center", fontsize=11),
        "service2_busy": ax_flow.text(nodes["service2"][0], nodes["service2"][1] - 0.12, "", ha="center", va="center", fontsize=10, color="tab:blue"),
        "storage_level": ax_flow.text(nodes["storage"][0], nodes["storage"][1], "", ha="center", va="center", fontsize=12, color="tab:green"),
        "fleet_busy": ax_flow.text(nodes["fleet"][0], nodes["fleet"][1], "", ha="center", va="center", fontsize=11, color="tab:purple"),
    }

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

    def update(frame_idx):
        if frame_idx >= len(snapshots):
            frame_idx = len(snapshots) - 1
        s = snapshots[frame_idx]
        current_time = s.t

        txt["service1_queue"].set_text(f"Q: {s.service1_queue}")
        txt["service1_busy"].set_text(f"Busy: {s.service1_busy}")
        txt["service2_queue"].set_text(f"Q: {s.service2_queue}")
        txt["service2_busy"].set_text(f"Busy: {s.service2_busy}")
        txt["storage_level"].set_text(f"{s.storage_level}")
        txt["fleet_busy"].set_text(
            f"Busy: {s.forklifts_busy}/{s.forklifts_total}")

        for fl_id, trajectory in recorder.get_all_trajectories().items():
            times_traj = trajectory.get_times()
            positions_all = trajectory.get_positions_xy()

            mask = times_traj <= current_time
            if mask.any():
                positions = positions_all[mask]

                if len(positions) > 0:
                    lines[fl_id].set_data(positions[:, 0], positions[:, 1])

                    idx = np.searchsorted(times_traj, current_time)
                    if 0 < idx < len(times_traj):
                        t0, t1 = times_traj[idx - 1], times_traj[idx]
                        p0, p1 = positions_all[idx - 1], positions_all[idx]
                        alpha = (current_time - t0) / \
                            (t1 - t0) if t1 > t0 else 0
                        current_pos = p0 + alpha * (p1 - p0)
                        scatters[fl_id].set_offsets([current_pos])
                    else:
                        scatters[fl_id].set_offsets(positions[-1:])

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

        return list(lines.values()) + list(scatters.values()) + [
            time_text_warehouse,
            created_text,
            completed_text,
            storage_text,
        ] + list(txt.values()) + [line_created, line_completed, line_storage]

    interval_ms = 1000 / fps
    anim = animation.FuncAnimation(
        fig,
        update,
        frames=len(snapshots),
        interval=interval_ms,
        blit=False,
        repeat=True,
    )

    fig.tight_layout()
    return fig, anim


def main():
    parser = argparse.ArgumentParser(
        description="Animate Model 1 warehouse simulation")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full-length simulation with finer sampling",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("DISCRETE-EVENT MODEL WITH WAREHOUSE ANIMATION")
    print("=" * 70)

    if args.full:
        sample_dt = 1.0
        recording_interval = 0.5
        sim_time_override = None
        snapshot_stride = 1
        fps = 10
        print("\nMode: FULL (long run, finer sampling)")
    else:
        sample_dt = 2.0
        recording_interval = 1.0
        sim_time_override = 1200.0
        snapshot_stride = 2
        fps = 6
        print("\nMode: FAST (shorter run, coarser sampling)")

    print("Running model and recording forklift movements ...")
    snapshots, model, recorder = run_and_record(
        sample_dt=sample_dt,
        recording_interval=recording_interval,
        sim_time_override=sim_time_override,
    )
    print(
        f"\n✅ Collected {len(snapshots)} snapshots over {snapshots[-1].t:.1f}s")
    print(f"   Recorded {len(recorder.trajectories)} forklifts")

    layout, _, _ = create_warehouse_with_standard_config(
        model.env, Model1Params())

    snapshots_for_anim = snapshots[::snapshot_stride]

    fig, anim = build_animation(snapshots_for_anim, recorder, layout, fps=fps)

    print("\n" + "=" * 70)
    print("ANIMATION READY")
    print("=" * 70)
    print("\nShowing:")
    print("  Left:  Warehouse map with forklift movements and paths")
    print("  Top Right: Pipeline state (queue lengths, busy forklifts)")
    print("  Bottom: Time-series metrics (throughput & storage level)")
    print("\nClose window when done viewing.")
    print("=" * 70 + "\n")

    plt.show()


if __name__ == "__main__":
    main()
