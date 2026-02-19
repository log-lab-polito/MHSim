#!/usr/bin/env python3
"""
Block-by-block comparison between AnyLogic and SimPy for Model 2.
"""

from __future__ import annotations

from case_studies.model_1_simpy.reporting import (
    DEFAULT_BLOCK_MAPPING,
    compare_blocks_with_anylogic,
)
from case_studies.model_1_simpy.model import Model1SimModel
from .params import Model2Params

# AnyLogic results from provided screenshot (Model 2)
ANYLOGIC_BLOCKS = {
    "source": 301,
    "service1": 300,  # upstream service
    "store": 299,
    "delay": 294,
    "retrieve": 293,
    "service2": 292,  # downstream service
    "sink": 292,
}
BLOCK_MAPPING = DEFAULT_BLOCK_MAPPING


def compare_blocks(params: Model2Params | None = None):
    """Run the model and compare block finished counts with AnyLogic reference."""
    if params is None:
        params = Model2Params()

    return compare_blocks_with_anylogic(
        model_cls=Model1SimModel,
        params=params,
        anylogic_blocks=ANYLOGIC_BLOCKS,
        block_mapping=BLOCK_MAPPING,
        console_logging=False,
    )


if __name__ == "__main__":
    compare_blocks()
