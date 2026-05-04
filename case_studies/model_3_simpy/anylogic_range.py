"""AnyLogic Model 3 ranged-parameter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mhsim.experiments import ChoiceParameter


@dataclass(frozen=True)
class Model3RangeValues:
    arrival_rate_s: float
    conveyor_speed_mps: float
    conveyor_min_gap_m: float

    @property
    def match_key(self) -> tuple[float, float, float]:
        return (
            self.arrival_rate_s,
            self.conveyor_speed_mps,
            self.conveyor_min_gap_m,
        )


ANYLOGIC_RANGE_VALUES: dict[str, tuple[Any, ...]] = {
    "arrival_rate_s": (60.0, 120.0, 180.0, 240.0),
    "conveyor_min_gap_m": (0.3, 0.6, 0.9, 1.2),
    "conveyor_speed_mps": (0.5, 1.0, 1.5, 2.0),
}


def range_values_for_iteration(iteration: int) -> Model3RangeValues:
    """Return AnyLogic ranged values for a 1-based iteration number."""
    if iteration < 1:
        raise ValueError("AnyLogic iteration numbers are 1-based")

    zero_based = iteration - 1
    values_by_name: dict[str, Any] = {}
    divisor = 1
    for name, values in ANYLOGIC_RANGE_VALUES.items():
        values_by_name[name] = values[(zero_based // divisor) % len(values)]
        divisor *= len(values)

    return Model3RangeValues(
        arrival_rate_s=float(values_by_name["arrival_rate_s"]),
        conveyor_speed_mps=float(values_by_name["conveyor_speed_mps"]),
        conveyor_min_gap_m=float(values_by_name["conveyor_min_gap_m"]),
    )


def range_variation_parameters() -> list[ChoiceParameter]:
    """Return parameters in the order needed for SimPy's cartesian product."""
    return [
        ChoiceParameter(name, values)
        for name, values in reversed(tuple(ANYLOGIC_RANGE_VALUES.items()))
    ]
