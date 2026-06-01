#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 3.
"""

from __future__ import annotations

from mhsim_analysis.reporting import compare_blocks_with_anylogic

from ..model import Model3SimModel
from ..params import Model3Params

# AnyLogic results transcribed from the current Model 3 reference output.
# Model 3 intentionally does not parse event logs or generate SimPy logs.
ANYLOGIC_BLOCKS = {
    "source": 301,
    "service1": 300,
    "conveyorEnter": 300,
    "convey": 300,
    "conveyorExit": 300,
    "service2": 300,
    "sink": 300,
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
