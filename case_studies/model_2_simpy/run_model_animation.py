#!/usr/bin/env python3
"""Animate Model 2 warehouse simulation with forklift paths and metrics."""

from __future__ import annotations

from case_studies.model_5_simpy.run_model_animation import Snapshot, run_animation_cli

from .model import Model2SimModel
from .params import Model2Params


def _block_contains(block) -> int:
    return max(
        0,
        getattr(block, "entered_count", 0) - getattr(block, "completed_count", 0),
    )


def build_model2_snapshot(model: Model2SimModel) -> Snapshot:
    service1 = model.service1
    service2 = model.service2

    return Snapshot(
        t=model.env.now,
        created=model.stats.created,
        completed=model.stats.completed,
        storage_level=model.get_storage_level(),
        stage_stats={
            "source": f"out:{model.stats.created}",
            "service1": (
                f"in:{getattr(service1, 'entered_count', 0)}\n"
                f"queue:{len(service1.resource.queue)}\n"
                f"delay:{service1.resource.count}\n"
                f"out:{getattr(service1, 'finished_count', 0)}"
            ),
            "moveToStorage": (
                f"in:{getattr(model.move_to_storage, 'entered_count', 0)}\n"
                f"out:{getattr(model.move_to_storage, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.move_to_storage)}"
            ),
            "delay": (
                f"in:{getattr(model.delay, 'entered_count', 0)}\n"
                f"out:{getattr(model.delay, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.delay)}"
            ),
            "moveToOutbound": (
                f"in:{getattr(model.move_to_outbound, 'entered_count', 0)}\n"
                f"out:{getattr(model.move_to_outbound, 'finished_count', 0)}\n"
                f"cont:{_block_contains(model.move_to_outbound)}"
            ),
            "service2": (
                f"in:{getattr(service2, 'entered_count', 0)}\n"
                f"queue:{len(service2.resource.queue)}\n"
                f"delay:{service2.resource.count}\n"
                f"out:{getattr(service2, 'finished_count', 0)}"
            ),
            "sink": f"in:{getattr(model.sink, 'entered_count', model.stats.completed)}",
        },
        rack_occupancy=None,
    )


def main():
    run_animation_cli(
        model_label="Model 2",
        params_factory=Model2Params,
        model_factory=Model2SimModel,
        snapshot_builder=build_model2_snapshot,
        layout_resolver=lambda model: model.layout,
        pipeline_stage_names=[
            "source",
            "service1",
            "moveToStorage",
            "delay",
            "moveToOutbound",
            "service2",
            "sink",
        ],
    )


if __name__ == "__main__":
    main()
