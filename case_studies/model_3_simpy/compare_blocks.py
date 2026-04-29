#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 3.
"""

from __future__ import annotations

from case_studies.model_5_simpy.reporting import compare_blocks_with_anylogic

from .model import Model3SimModel
from .params import Model3Params

# AnyLogic results transcribed from the provided Model 3 screenshot.
ANYLOGIC_BLOCKS = {
    "source": 1081,
    "service1": 1080,
    "conveyorEnter": 1080,
    "convey": 1076,
    "conveyorExit": 1076,
    "service2": 1075,
    "sink": 1075,
}

BLOCK_MAPPING = [
    ("service1", "service1", "SERVICE1"),
    ("conveyor_enter", "conveyorEnter", "CONVEYOR ENTER"),
    ("convey", "convey", "CONVEY"),
    ("conveyor_exit", "conveyorExit", "CONVEYOR EXIT"),
    ("service2", "service2", "SERVICE2"),
]


def compare_blocks(params: Model3Params | None = None):
    """Run the model and compare block finished counts with AnyLogic reference."""
    if params is None:
        params = Model3Params()

    return compare_blocks_with_anylogic(
        model_cls=Model3SimModel,
        params=params,
        anylogic_blocks=ANYLOGIC_BLOCKS,
        block_mapping=BLOCK_MAPPING,
        console_logging=False,
    )


if __name__ == "__main__":
    compare_blocks()
