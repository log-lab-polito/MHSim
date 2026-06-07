#!/usr/bin/env python3
"""Animate Model 4 conveyor spur simulation."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Tuple

import matplotlib

if "--no-show" in sys.argv:
    matplotlib.use("Agg")

from matplotlib import animation
from matplotlib.patches import FancyArrowPatch, Rectangle
import matplotlib.pyplot as plt
import numpy as np

from mhsim.pallet import Pallet

from .model import Model4SimModel
from .params import Model4Params


if __package__ in (None, ""):
    package_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    __package__ = "model_4_simpy"


@dataclass
class ConveyorItemTrace:
    pallet_id: int
    origin: str
    conveyor_id: str
    entered_t: float
    start_pos_m: float
    speed_mps: float
    length_m: float
    exited_t: float | None = None


@dataclass
class TransferTrace:
    pallet_id: int
    started_t: float
    completed_t: float | None = None


@dataclass
class Snapshot:
    t: float
    created: int
    completed: int
    main_created: int
    branch_created: int
    main_completed: int
    branch_completed: int
    main_service_in: int
    main_service_out: int
    main_service_queue: int
    main_service_busy: int
    branch_service_in: int
    branch_service_out: int
    branch_service_queue: int
    branch_service_busy: int
    main_enter_in: int
    main_enter_out: int
    branch_enter_in: int
    branch_enter_out: int
    main_convey_in: int
    main_convey_out: int
    branch_convey_in: int
    branch_convey_out: int
    spur_in: int
    spur_out: int
    merge_convey_in: int
    merge_convey_out: int
    main_exit_in: int
    main_exit_out: int
    service2_in: int
    service2_out: int
    service2_queue: int
    service2_busy: int
    sink_in: int
    main_occ: int
    branch_occ: int
    main_entered: int
    main_exited: int
    branch_entered: int
    branch_exited: int
    spur_transferred: int


def _attach_spur_traces(
    model: Model4SimModel,
) -> Tuple[List[ConveyorItemTrace], List[TransferTrace]]:
    conveyor_traces: List[ConveyorItemTrace] = []
    transfer_traces: List[TransferTrace] = []
    trace_by_key: dict[tuple[str, int], ConveyorItemTrace] = {}

    def record_enter(
        *,
        pallet: Pallet,
        conveyor_id: str,
        start_pos_m: float,
        speed_mps: float,
        length_m: float,
    ) -> None:
        trace = ConveyorItemTrace(
            pallet_id=pallet.id,
            origin=str(pallet.attributes.get("origin", "unknown")),
            conveyor_id=conveyor_id,
            entered_t=model.env.now,
            start_pos_m=start_pos_m,
            speed_mps=speed_mps,
            length_m=length_m,
        )
        conveyor_traces.append(trace)
        trace_by_key[(conveyor_id, pallet.id)] = trace

    def record_exit(*, pallet: Pallet, conveyor_id: str) -> None:
        trace = trace_by_key.get((conveyor_id, pallet.id))
        if trace is not None and trace.exited_t is None:
            trace.exited_t = model.env.now

    def main_convey_handle(pallet: Pallet):
        block = model.main_convey
        block.entered_count += 1
        yield from block.conveyor.enter()
        record_enter(
            pallet=pallet,
            conveyor_id="main",
            start_pos_m=0.0,
            speed_mps=model.main_conveyor.speed_mps,
            length_m=model.main_conveyor.length_m,
        )
        yield model.env.timeout(block.conveyor.travel_time_s())
        record_exit(pallet=pallet, conveyor_id="main")
        block.conveyor.leave()
        block.finished_count += 1
        if block.next_block:
            yield from block.next_block.handle(pallet)
        block.completed_count += 1

    def branch_convey_handle(pallet: Pallet):
        block = model.branch_convey
        block.entered_count += 1
        yield from block.branch_conveyor.enter()
        record_enter(
            pallet=pallet,
            conveyor_id="branch",
            start_pos_m=0.0,
            speed_mps=model.branch_conveyor.speed_mps,
            length_m=model.branch_conveyor.length_m,
        )
        yield model.env.timeout(block.branch_conveyor.travel_time_s())
        transfer = TransferTrace(pallet_id=pallet.id, started_t=model.env.now)
        transfer_traces.append(transfer)

        spur = block.spur
        with spur._transfer_mutex.request() as req:
            yield req
            yield from spur.target_conveyor.enter()
            record_enter(
                pallet=pallet,
                conveyor_id="main",
                start_pos_m=spur.target_offset_m,
                speed_mps=model.main_conveyor.speed_mps,
                length_m=model.main_conveyor.length_m,
            )
            record_exit(pallet=pallet, conveyor_id="branch")
            spur.source_conveyor.leave()
            spur.total_transferred += 1
            transfer.completed_t = model.env.now

        yield model.env.timeout(
            spur.target_conveyor.travel_time_s(spur.remaining_target_distance_m())
        )
        record_exit(pallet=pallet, conveyor_id="main")
        spur.target_conveyor.leave()
        block.finished_count += 1
        if block.next_block:
            yield from block.next_block.handle(pallet)
        block.completed_count += 1

    model.main_convey.handle = main_convey_handle
    model.branch_convey.handle = branch_convey_handle

    return conveyor_traces, transfer_traces


def _build_snapshot(model: Model4SimModel) -> Snapshot:
    return Snapshot(
        t=model.env.now,
        created=model.stats.created,
        completed=model.stats.completed,
        main_created=model.main_source.emitted_count,
        branch_created=model.branch_source.emitted_count,
        main_completed=model.sink.completed_by_origin.get("main", 0),
        branch_completed=model.sink.completed_by_origin.get("branch", 0),
        main_service_in=model.main_service1.entered_count,
        main_service_out=model.main_service1.finished_count,
        main_service_queue=len(model.main_service1.resource.queue),
        main_service_busy=model.main_service1.resource.count,
        branch_service_in=model.branch_service1.entered_count,
        branch_service_out=model.branch_service1.finished_count,
        branch_service_queue=len(model.branch_service1.resource.queue),
        branch_service_busy=model.branch_service1.resource.count,
        main_enter_in=model.main_convey.entered_count,
        main_enter_out=model.main_convey.finished_count,
        branch_enter_in=model.branch_convey.entered_count,
        branch_enter_out=model.branch_convey.finished_count,
        main_convey_in=model.main_convey.entered_count,
        main_convey_out=model.main_convey.finished_count,
        branch_convey_in=model.branch_convey.entered_count,
        branch_convey_out=model.branch_convey.finished_count,
        spur_in=model.spur.total_transferred,
        spur_out=model.spur.total_transferred,
        merge_convey_in=model.branch_convey.entered_count,
        merge_convey_out=model.branch_convey.finished_count,
        main_exit_in=model.main_convey.entered_count + model.branch_convey.entered_count,
        main_exit_out=model.main_convey.finished_count + model.branch_convey.finished_count,
        service2_in=model.service2.entered_count,
        service2_out=model.service2.finished_count,
        service2_queue=len(model.service2.resource.queue),
        service2_busy=model.service2.resource.count,
        sink_in=model.sink.entered_count,
        main_occ=model.main_conveyor.occupancy,
        branch_occ=model.branch_conveyor.occupancy,
        main_entered=model.main_conveyor.total_entered,
        main_exited=model.main_conveyor.total_exited,
        branch_entered=model.branch_conveyor.total_entered,
        branch_exited=model.branch_conveyor.total_exited,
        spur_transferred=model.spur.total_transferred,
    )


def run_and_record(
    params: Model4Params | None = None,
    sample_dt: float = 0.1,
    sim_time_override: float | None = None,
) -> Tuple[List[Snapshot], Model4SimModel, List[ConveyorItemTrace], List[TransferTrace]]:
    active_params = params or Model4Params()
    model = Model4SimModel(params=active_params)

    if sim_time_override is not None:
        model.params.sim_time = sim_time_override

    conveyor_traces, transfer_traces = _attach_spur_traces(model)
    snapshots: List[Snapshot] = []

    def sampler():
        while True:
            snapshots.append(_build_snapshot(model))
            yield model.env.timeout(sample_dt)

    model.env.process(sampler())
    model.main_source.start()
    model.branch_source.start()

    stop_time = model.params.sim_time
    chunk = max(sample_dt, 5.0)
    last_report = -10.0
    while model.env.now < stop_time:
        model.env.run(until=min(stop_time, model.env.now + chunk))
        if model.env.now - last_report >= 10.0 or model.env.now >= stop_time:
            pct = (model.env.now / stop_time) * 100.0 if stop_time > 0 else 100.0
            print(
                f"   ... model progress {model.env.now:.0f}/{stop_time:.0f}s ({pct:.0f}%) "
                f"created={model.stats.created} completed={model.stats.completed} "
                f"main_occ={model.main_conveyor.occupancy} branch_occ={model.branch_conveyor.occupancy} "
                f"spur={model.spur.total_transferred}"
            )
            last_report = model.env.now

    if not snapshots or snapshots[-1].t < model.env.now:
        snapshots.append(_build_snapshot(model))

    return snapshots, model, conveyor_traces, transfer_traces


def _active_trace_positions(
    traces: List[ConveyorItemTrace],
    *,
    current_time: float,
    conveyor_id: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    xs: list[float] = []
    ys: list[float] = []
    origins: list[str] = []
    branch_y = -4.0
    main_y = 0.0
    for trace in traces:
        if trace.conveyor_id != conveyor_id:
            continue
        if trace.entered_t > current_time:
            continue
        if trace.exited_t is not None and trace.exited_t <= current_time:
            continue
        distance = trace.start_pos_m + (current_time - trace.entered_t) * trace.speed_mps
        distance = max(0.0, min(trace.length_m, distance))
        if conveyor_id == "branch":
            x = 18.0 - trace.length_m + distance
            y = branch_y
        else:
            x = distance
            y = main_y
        xs.append(x)
        ys.append(y)
        origins.append(trace.origin)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), origins


def _active_transfer_positions(
    transfers: List[TransferTrace],
    *,
    current_time: float,
    transfer_duration_hint_s: float,
) -> np.ndarray:
    points: list[tuple[float, float]] = []
    duration = max(transfer_duration_hint_s, 0.05)
    for trace in transfers:
        if trace.started_t > current_time:
            continue
        end_t = trace.completed_t
        if end_t is not None and end_t <= current_time:
            continue
        elapsed = max(0.0, current_time - trace.started_t)
        progress = min(1.0, elapsed / duration)
        points.append((18.0, -4.0 + 4.0 * progress))
    return np.asarray(points, dtype=float) if points else np.empty((0, 2))


def build_animation(
    snapshots: List[Snapshot],
    conveyor_traces: List[ConveyorItemTrace],
    transfer_traces: List[TransferTrace],
    model: Model4SimModel,
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
    main_occ = [s.main_occ for s in snapshots]
    branch_occ = [s.branch_occ for s in snapshots]
    spur_transferred = [s.spur_transferred for s in snapshots]

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[1.15, 1.0],
        height_ratios=[1.05, 1.0],
        hspace=0.34,
        wspace=0.25,
    )
    ax_layout = fig.add_subplot(gs[0, 0])
    ax_pipeline = fig.add_subplot(gs[0, 1])
    ax_counts = fig.add_subplot(gs[1, 0])
    ax_detail = fig.add_subplot(gs[1, 1])

    ax_layout.set_xlim(-2, model.params.main_conveyor_length_m + 3)
    ax_layout.set_ylim(-6.5, 2.8)
    ax_layout.set_aspect("equal")
    ax_layout.set_xlabel("Conveyor position (m)")
    ax_layout.set_ylabel("Line")
    ax_layout.set_title("Model 4 Spur Merge Layout", fontweight="bold")
    ax_layout.grid(True, alpha=0.2)
    ax_layout.set_yticks([-4, 0])
    ax_layout.set_yticklabels(["branch", "main"])

    main_belt = Rectangle(
        (0, -0.25),
        model.params.main_conveyor_length_m,
        0.5,
        facecolor="#CFD8DC",
        edgecolor="#455A64",
        lw=1.2,
    )
    branch_start_x = model.params.spur_merge_offset_m - model.params.branch_conveyor_length_m
    branch_belt = Rectangle(
        (branch_start_x, -4.25),
        model.params.branch_conveyor_length_m,
        0.5,
        facecolor="#D7CCC8",
        edgecolor="#5D4037",
        lw=1.2,
    )
    ax_layout.add_patch(main_belt)
    ax_layout.add_patch(branch_belt)
    ax_layout.add_patch(
        FancyArrowPatch(
            (model.params.spur_merge_offset_m, -3.75),
            (model.params.spur_merge_offset_m, -0.35),
            arrowstyle="->",
            mutation_scale=18,
            linewidth=2.0,
            color="#6A1B9A",
        )
    )
    ax_layout.axvline(
        model.params.spur_merge_offset_m,
        color="#6A1B9A",
        linestyle=":",
        linewidth=1.2,
    )
    ax_layout.text(0, 0.55, "main source", ha="left", fontsize=9, color="#2E7D32")
    ax_layout.text(
        model.params.main_conveyor_length_m,
        0.55,
        "exit -> service2",
        ha="right",
        fontsize=9,
        color="#1565C0",
    )
    ax_layout.text(
        branch_start_x,
        -3.35,
        "branch source",
        ha="left",
        fontsize=9,
        color="#5D4037",
    )
    ax_layout.text(
        model.params.spur_merge_offset_m + 0.3,
        -2.0,
        "ConveyorSpur",
        ha="left",
        va="center",
        fontsize=9,
        color="#6A1B9A",
    )

    main_scatter = ax_layout.scatter(
        [], [], s=120, color="#FB8C00", edgecolors="black", linewidths=1.0, zorder=3
    )
    branch_scatter = ax_layout.scatter(
        [], [], s=120, color="#8D6E63", edgecolors="black", linewidths=1.0, zorder=3
    )
    transfer_scatter = ax_layout.scatter(
        [], [], s=150, color="#AB47BC", edgecolors="black", linewidths=1.0, zorder=4
    )
    layout_text = ax_layout.text(
        0.02, 0.98, "", transform=ax_layout.transAxes, va="top", fontsize=10
    )

    ax_pipeline.set_xlim(0, 1)
    ax_pipeline.set_ylim(0, 1)
    ax_pipeline.axis("off")
    ax_pipeline.set_title("Block Counters", fontweight="bold")
    pipeline_nodes = [
        ("main_src", 0.08, 0.72),
        ("main_svc", 0.24, 0.72),
        ("main_enter", 0.40, 0.72),
        ("main_convey", 0.56, 0.72),
        ("main_exit", 0.72, 0.72),
        ("service2", 0.86, 0.50),
        ("sink", 0.86, 0.28),
        ("branch_src", 0.08, 0.28),
        ("branch_svc", 0.24, 0.28),
        ("branch_enter", 0.40, 0.28),
        ("branch_convey", 0.56, 0.28),
        ("spur", 0.72, 0.28),
    ]
    stat_texts = {}
    for name, x, y in pipeline_nodes:
        rect = Rectangle((x - 0.055, y - 0.075), 0.11, 0.15, fill=False, lw=1.1)
        ax_pipeline.add_patch(rect)
        ax_pipeline.text(x, y + 0.095, name, ha="center", va="bottom", fontsize=7)
        stat_texts[name] = ax_pipeline.text(
            x,
            y,
            "",
            ha="center",
            va="center",
            fontsize=6.5,
            family="monospace",
        )
    for x0, y0, x1, y1 in [
        (0.135, 0.72, 0.185, 0.72),
        (0.295, 0.72, 0.345, 0.72),
        (0.455, 0.72, 0.505, 0.72),
        (0.615, 0.72, 0.665, 0.72),
        (0.775, 0.70, 0.82, 0.54),
        (0.86, 0.425, 0.86, 0.355),
        (0.135, 0.28, 0.185, 0.28),
        (0.295, 0.28, 0.345, 0.28),
        (0.455, 0.28, 0.505, 0.28),
        (0.615, 0.28, 0.665, 0.28),
        (0.735, 0.355, 0.735, 0.645),
    ]:
        ax_pipeline.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops={"arrowstyle": "->", "lw": 1.0, "color": "#607D8B"},
        )

    (line_created,) = ax_counts.plot([], [], color="#2E7D32", lw=2, label="Created")
    (line_completed,) = ax_counts.plot(
        [], [], color="#1565C0", lw=2, linestyle="--", label="Completed"
    )
    ax_counts_occ = ax_counts.twinx()
    (line_main_occ,) = ax_counts_occ.plot(
        [], [], color="#EF6C00", lw=2, linestyle="-.", label="Main occ"
    )
    (line_branch_occ,) = ax_counts_occ.plot(
        [], [], color="#8D6E63", lw=2, linestyle=":", label="Branch occ"
    )
    ax_counts.set_xlim(times[0], max_time)
    ax_counts.set_ylim(0, max(max(created), max(completed)) * 1.2 + 1)
    ax_counts_occ.set_ylim(0, max(max(main_occ), max(branch_occ), 1) * 1.4 + 1)
    ax_counts.set_xlabel("Time (s)")
    ax_counts.set_ylabel("Throughput count")
    ax_counts_occ.set_ylabel("Conveyor occupancy")
    ax_counts.set_title("Throughput and Occupancy", fontweight="bold")
    ax_counts.grid(True, alpha=0.3)
    legend_lines = [line_created, line_completed, line_main_occ, line_branch_occ]
    ax_counts.legend(
        legend_lines,
        [line.get_label() for line in legend_lines],
        loc="upper left",
        fontsize=9,
    )

    ax_detail.set_title("Spur Transfer Count", fontweight="bold")
    ax_detail.set_xlim(times[0], max_time)
    ax_detail.set_ylim(0, max(spur_transferred) * 1.2 + 1 if spur_transferred else 1)
    ax_detail.set_xlabel("Time (s)")
    ax_detail.set_ylabel("Transfers")
    ax_detail.grid(True, alpha=0.3)
    (line_spur,) = ax_detail.plot([], [], color="#6A1B9A", lw=2.2, label="Spur transfers")
    ax_detail.legend(loc="upper left", fontsize=9)

    transfer_duration_hint = model.main_conveyor.entry_headway_time_s()

    def update(frame_idx: int):
        if frame_idx >= len(snapshots):
            frame_idx = len(snapshots) - 1
        snap = snapshots[frame_idx]
        current_time = snap.t

        main_x, main_y, _main_origins = _active_trace_positions(
            conveyor_traces,
            current_time=current_time,
            conveyor_id="main",
        )
        branch_x, branch_y, _branch_origins = _active_trace_positions(
            conveyor_traces,
            current_time=current_time,
            conveyor_id="branch",
        )
        main_scatter.set_offsets(
            np.column_stack([main_x, main_y]) if len(main_x) else np.empty((0, 2))
        )
        branch_scatter.set_offsets(
            np.column_stack([branch_x, branch_y])
            if len(branch_x)
            else np.empty((0, 2))
        )
        transfer_scatter.set_offsets(
            _active_transfer_positions(
                transfer_traces,
                current_time=current_time,
                transfer_duration_hint_s=transfer_duration_hint,
            )
        )

        layout_text.set_text(
            f"t={current_time:.1f}s\n"
            f"created={snap.created} completed={snap.completed}\n"
            f"main_occ={snap.main_occ} branch_occ={snap.branch_occ}\n"
            f"spur_transferred={snap.spur_transferred}"
        )

        stat_texts["main_src"].set_text(f"out:{snap.main_created}")
        stat_texts["main_svc"].set_text(
            f"in:{snap.main_service_in}\nq:{snap.main_service_queue}\nb:{snap.main_service_busy}\nout:{snap.main_service_out}"
        )
        stat_texts["main_enter"].set_text(
            f"in:{snap.main_enter_in}\nout:{snap.main_enter_out}"
        )
        stat_texts["main_convey"].set_text(
            f"in:{snap.main_convey_in}\nout:{snap.main_convey_out}"
        )
        stat_texts["main_exit"].set_text(
            f"in:{snap.main_exit_in}\nout:{snap.main_exit_out}"
        )
        stat_texts["service2"].set_text(
            f"in:{snap.service2_in}\nq:{snap.service2_queue}\nb:{snap.service2_busy}\nout:{snap.service2_out}"
        )
        stat_texts["sink"].set_text(
            f"in:{snap.sink_in}\nmain:{snap.main_completed}\nbr:{snap.branch_completed}"
        )
        stat_texts["branch_src"].set_text(f"out:{snap.branch_created}")
        stat_texts["branch_svc"].set_text(
            f"in:{snap.branch_service_in}\nq:{snap.branch_service_queue}\nb:{snap.branch_service_busy}\nout:{snap.branch_service_out}"
        )
        stat_texts["branch_enter"].set_text(
            f"in:{snap.branch_enter_in}\nout:{snap.branch_enter_out}"
        )
        stat_texts["branch_convey"].set_text(
            f"in:{snap.branch_convey_in}\nout:{snap.branch_convey_out}"
        )
        stat_texts["spur"].set_text(f"in:{snap.spur_in}\nout:{snap.spur_out}")

        line_created.set_data(times[: frame_idx + 1], created[: frame_idx + 1])
        line_completed.set_data(times[: frame_idx + 1], completed[: frame_idx + 1])
        line_main_occ.set_data(times[: frame_idx + 1], main_occ[: frame_idx + 1])
        line_branch_occ.set_data(times[: frame_idx + 1], branch_occ[: frame_idx + 1])
        line_spur.set_data(
            times[: frame_idx + 1], spur_transferred[: frame_idx + 1]
        )

        return [
            main_scatter,
            branch_scatter,
            transfer_scatter,
            layout_text,
            *stat_texts.values(),
            line_created,
            line_completed,
            line_main_occ,
            line_branch_occ,
            line_spur,
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
    parser = argparse.ArgumentParser(description="Animate Model 4 conveyor spur simulation.")
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
        default=300.0,
        help="Override simulation time in seconds. Default: 300",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Build the animation with a non-interactive backend, close it, and exit.",
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
    print("MODEL 4 CONVEYOR SPUR ANIMATION")
    print("=" * 70)
    print(f"Mode: FULL ({speed}x speed)")
    print(
        f"  - Snapshot resolution: {record_fps:.2f} fps ({sample_dt:.3f}s per snapshot)"
    )
    print(f"  - Target render rate: {playback_fps:.1f} fps")

    params = Model4Params()
    snapshots, model, conveyor_traces, transfer_traces = run_and_record(
        params=params,
        sample_dt=sample_dt,
        sim_time_override=args.sim_time,
    )

    total_sim_time = snapshots[-1].t
    expected_playback_time = total_sim_time / speed if speed > 0 else 0.0
    print(f"\nCollected {len(snapshots)} snapshots over {total_sim_time:.1f}s")
    print(f"Tracked {len(conveyor_traces)} conveyor trace segments")
    print(f"Tracked {len(transfer_traces)} spur transfers")
    print(f"Expected playback duration: {expected_playback_time:.1f}s")

    fig, anim = build_animation(
        snapshots=snapshots,
        conveyor_traces=conveyor_traces,
        transfer_traces=transfer_traces,
        model=model,
        fps=playback_fps,
        playback_speed=speed,
    )

    fig._mhsim_animation = anim
    if args.no_show:
        anim._draw_was_started = True
        fig.canvas.draw()
        plt.close(fig)
        print("Animation built successfully (--no-show).")
        return

    print("Showing:")
    print("  Top Left:  Main conveyor, branch conveyor, and ConveyorSpur merge")
    print("  Top Right: Block counters for both source lines")
    print("  Bottom Left: Throughput and conveyor occupancy")
    print("  Bottom Right: Spur transfer count over time")
    print("\nClose the window when done.")
    print("=" * 70 + "\n")
    plt.show()


def main():
    run_animation_cli()


if __name__ == "__main__":
    main()
