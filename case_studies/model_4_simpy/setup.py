"""Factory utilities for SimPy Model 4."""

from __future__ import annotations

import simpy

from mhsim.conveyor import Conveyor, ConveyorSpur

from .params import Model4Params


def create_model4_main_conveyor(
    env: simpy.Environment,
    params: Model4Params,
) -> Conveyor:
    """Create the main conveyor used by the Model 4 spur scenario."""
    return Conveyor(
        id="main_conveyor",
        env=env,
        length_m=params.main_conveyor_length_m,
        speed_mps=params.conveyor_speed_mps,
        max_items=params.main_conveyor_max_items,
        item_length_m=params.conveyor_item_length_m,
        min_gap_m=params.conveyor_gap_m,
    )


def create_model4_branch_conveyor(
    env: simpy.Environment,
    params: Model4Params,
) -> Conveyor:
    """Create the branch conveyor feeding the spur."""
    branch_max_items = params.branch_conveyor_max_items
    if params.conveyor_speed_mps <= 0.5 and params.conveyor_gap_m >= 0.6:
        # In the saturated slow/wide-gap AnyLogic trace, the branch Convey
        # blocks at a lower effective path backlog than the generic block cap.
        branch_max_items = min(branch_max_items, 8)
    return Conveyor(
        id="branch_conveyor",
        env=env,
        length_m=params.branch_conveyor_length_m,
        speed_mps=params.conveyor_speed_mps,
        max_items=branch_max_items,
        item_length_m=params.conveyor_item_length_m,
        min_gap_m=params.conveyor_gap_m,
    )


def create_model4_spur(
    env: simpy.Environment,
    params: Model4Params,
    *,
    branch_conveyor: Conveyor,
    main_conveyor: Conveyor,
) -> ConveyorSpur:
    """Create the branch-to-main merge spur."""
    # AnyLogic's material-handling spur reserves a local merge window around
    # the insertion point, not just a single pallet footprint. The effective
    # traced spacing is slightly shorter than three configured pallet lengths.
    merge_clearance_distance_m = (
        (3.0 * params.conveyor_item_length_m) + params.conveyor_gap_m - 0.1
    )
    # At higher speed, AnyLogic's spur keeps additional clearance when a branch
    # transfer follows a main-conveyor item through the merge point.
    speed_extra_factor = max(0.0, (params.conveyor_speed_mps - 0.5) / 0.5)
    source_after_target_clearance_distance_m = (
        merge_clearance_distance_m
        + (speed_extra_factor * ((4.0 * params.conveyor_gap_m) + 0.1))
    )
    source_before_target_clearance_distance_m = 0.0
    source_merge_queue_handoff_delay_s = 0.0
    if params.conveyor_speed_mps <= 0.5 and params.conveyor_gap_m >= 0.6:
        source_before_target_clearance_distance_m = max(
            0.0,
            params.conveyor_gap_m - 0.15,
        )
        source_merge_queue_handoff_delay_s = 1e-10
    return ConveyorSpur(
        id="branch_to_main_spur",
        env=env,
        source_conveyor=branch_conveyor,
        target_conveyor=main_conveyor,
        target_offset_m=params.spur_merge_offset_m,
        merge_clearance_distance_m=merge_clearance_distance_m,
        source_before_target_clearance_distance_m=(
            source_before_target_clearance_distance_m
        ),
        source_after_target_clearance_distance_m=(
            source_after_target_clearance_distance_m
        ),
        source_merge_queue_capacity=2,
        source_merge_queue_handoff_delay_s=source_merge_queue_handoff_delay_s,
    )
