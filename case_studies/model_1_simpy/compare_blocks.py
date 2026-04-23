#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 1.
"""

from __future__ import annotations

from .reporting import DEFAULT_BLOCK_MAPPING, compare_blocks_with_anylogic
from .model import Model1SimModel
from .params import Model1Params

ANYLOGIC_BLOCKS = {
    "source": 151,
    "service1": 150,  # upstream service
    "store": 150,
    "delay": 148,
    "retrieve": 148,
    "service2": 147,  # downstream service
    "sink": 147,
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
