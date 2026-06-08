from __future__ import annotations

from mhsim.experiments import RangeParameter


def range_variation_parameters():
    return (
        RangeParameter("max_items_per_pallet", 10, 20, 10),
    )


def fixed_range_parameters():
    return {
        "arrival_rate_s": 10.0,
        "conveyor_speed_mps": 0.8,
        "conveyor_gap_m": 0.3,
        "min_items_per_pallet": 5,
    }
