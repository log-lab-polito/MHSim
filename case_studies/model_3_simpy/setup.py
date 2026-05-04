"""Factory utilities for SimPy Model 3."""

from __future__ import annotations

import simpy

from mhsim.conveyor import Conveyor

from .params import Model3Params


def create_model3_conveyor(env: simpy.Environment, params: Model3Params) -> Conveyor:
    """Create the conveyor used by the AnyLogic Model 3 parity scenario."""
    return Conveyor(
        id="main_conveyor",
        env=env,
        length_m=params.conveyor_length_m,
        speed_mps=params.conveyor_speed_mps,
        max_items=params.conveyor_max_items,
        item_length_m=params.conveyor_item_length_m,
        min_gap_m=params.conveyor_min_gap_m,
    )
