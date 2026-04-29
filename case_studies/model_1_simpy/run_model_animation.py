#!/usr/bin/env python3
"""Animate Model 1 transporter simulation with forklift paths and metrics."""

from __future__ import annotations

from case_studies.model_5_simpy.run_model_animation import Snapshot, run_animation_cli

from .model import Model1SimModel
from .params import Model1Params


def _block_contains(block) -> int:
    return max(
        0,
        getattr(block, "entered_count", 0) - getattr(block, "completed_count", 0),
    )


def build_model1_snapshot(model: Model1SimModel) -> Snapshot:
    move_by_transporter = model.move_by_transporter

    return Snapshot(
        t=model.env.now,
        created=model.stats.created,
        completed=model.stats.completed,
        storage_level=model.stats.created - model.stats.completed,
        stage_stats={
            "source": f"out:{model.stats.created}",
            "moveByTransporter": (
                f"in:{getattr(move_by_transporter, 'entered_count', 0)}\n"
                f"out:{getattr(move_by_transporter, 'finished_count', 0)}\n"
                f"cont:{_block_contains(move_by_transporter)}"
            ),
            "sink": f"in:{getattr(model.sink, 'entered_count', model.stats.completed)}",
        },
        rack_occupancy=None,
    )


def main():
    run_animation_cli(
        model_label="Model 1",
        params_factory=Model1Params,
        model_factory=Model1SimModel,
        snapshot_builder=build_model1_snapshot,
        layout_resolver=lambda model: model.layout,
        pipeline_stage_names=[
            "source",
            "moveByTransporter",
            "sink",
        ],
        storage_metric_label="In flight",
    )


if __name__ == "__main__":
    main()
