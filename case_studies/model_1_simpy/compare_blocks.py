#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 1.
"""

from __future__ import annotations

from .reporting import DEFAULT_BLOCK_MAPPING, compare_blocks_with_anylogic
from .model import Model1SimModel
from .params import Model1Params

ANYLOGIC_BLOCKS = {
    "source": 181,
    "service1": 180,  # upstream service
    "store": 126,
    "delay": 124,
    "retrieve": 87,
    "service2": 87,  # downstream service
    "sink": 87,
}
BLOCK_MAPPING = DEFAULT_BLOCK_MAPPING


def compare_blocks(params: Model1Params | None = None):
    """Run the model and compare block finished counts with AnyLogic reference."""
    if params is None:
        params = Model1Params()

    return compare_blocks_with_anylogic(
        model_cls=Model1SimModel,
        params=params,
        anylogic_blocks=ANYLOGIC_BLOCKS,
        block_mapping=BLOCK_MAPPING,
        console_logging=False,
    )


if __name__ == "__main__":
    compare_blocks()
