"""AnyLogic Model 1 ranged-parameter metadata.

The current ALP declares the ranged parameters as ``arrival_rate_s``,
``forklift_capacity``, ``forklift_max_speed_ms``,
``forklift_acceleration_ms2``, and ``displacement_m``. The exported range log
nests hidden values as arrival, displacement, acceleration, capacity, then
max speed, so the values below follow that exported behavior.
``mhsim.experiments.RangeVariation`` iterates the last configured parameter
fastest, so callers should use ``range_variation_parameters()`` when building
SimPy experiments.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from mhsim.experiments import ChoiceParameter


@dataclass(frozen=True)
class Model1RangeValues:
    arrival_rate_s: float
    n_forklifts: int
    forklift_max_speed: float
    forklift_acceleration: float
    displacement_m: float

    @property
    def match_key(self) -> tuple[float, int, float, float, float]:
        return (
            self.arrival_rate_s,
            self.n_forklifts,
            self.forklift_max_speed,
            self.forklift_acceleration,
            self.displacement_m,
        )


ANYLOGIC_RANGE_VALUES: dict[str, tuple[Any, ...]] = {
    "arrival_rate_s": (60.0, 120.0),
    "displacement_m": (100.0, 200.0),
    "forklift_acceleration": (1.0, 2.0),
    "n_forklifts": (1, 2, 3, 4),
    "forklift_max_speed": (10.0, 20.0),
}


def range_values_for_iteration(iteration: int) -> Model1RangeValues:
    """Return AnyLogic ranged values for a 1-based iteration number."""
    if iteration < 1:
        raise ValueError("AnyLogic iteration numbers are 1-based")

    zero_based = iteration - 1
    names = tuple(ANYLOGIC_RANGE_VALUES)
    values_by_name: dict[str, Any] = {}
    divisor = 1
    for name in names:
        values = ANYLOGIC_RANGE_VALUES[name]
        values_by_name[name] = values[(zero_based // divisor) % len(values)]
        divisor *= len(values)

    return Model1RangeValues(
        arrival_rate_s=float(values_by_name["arrival_rate_s"]),
        n_forklifts=int(values_by_name["n_forklifts"]),
        forklift_max_speed=float(values_by_name["forklift_max_speed"]),
        forklift_acceleration=float(values_by_name["forklift_acceleration"]),
        displacement_m=float(values_by_name["displacement_m"]),
    )


def range_variation_parameters() -> list[ChoiceParameter]:
    """Return parameters in the order needed for SimPy's cartesian product."""
    return [
        ChoiceParameter(name, values)
        for name, values in reversed(tuple(ANYLOGIC_RANGE_VALUES.items()))
    ]
