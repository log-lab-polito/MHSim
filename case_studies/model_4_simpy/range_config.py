"""Model 4 ranged-parameter metadata."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from mhsim.experiments import ChoiceParameter


@dataclass(frozen=True)
class Model4RangeValues:
    main_arrival_time_s: float
    conveyor_speed_mps: float
    conveyor_gap_m: float
    branch_arrival_time_s: float

    @property
    def match_key(self) -> tuple[float, float, float, float]:
        return (
            self.main_arrival_time_s,
            self.conveyor_speed_mps,
            self.conveyor_gap_m,
            self.branch_arrival_time_s,
        )


RANGE_VALUES: dict[str, tuple[Any, ...]] = {
    "main_arrival_time_s": (15.0, 30.0, 45.0, 60.0),
    "conveyor_speed_mps": (0.5, 1.0),
    "conveyor_gap_m": (0.3, 0.6),
    "branch_arrival_time_s": (15.0, 30.0, 45.0, 60.0),
}


def range_values_for_iteration(iteration: int) -> Model4RangeValues:
    """Return AnyLogic ranged values for a 1-based iteration number."""
    if iteration < 1:
        raise ValueError("Iteration numbers are 1-based")

    names = tuple(RANGE_VALUES)
    combinations = tuple(product(*(RANGE_VALUES[name] for name in names)))
    if iteration > len(combinations):
        raise ValueError(
            f"Iteration {iteration} is outside the Model 4 range grid "
            f"1..{len(combinations)}"
        )

    # AnyLogic advances the last ranged parameter fastest. Keeping the same
    # order here lets us infer branch arrival from logs that only print the
    # first three parameters.
    values_by_name = dict(zip(names, combinations[iteration - 1]))

    return Model4RangeValues(
        main_arrival_time_s=float(values_by_name["main_arrival_time_s"]),
        conveyor_speed_mps=float(values_by_name["conveyor_speed_mps"]),
        conveyor_gap_m=float(values_by_name["conveyor_gap_m"]),
        branch_arrival_time_s=float(values_by_name["branch_arrival_time_s"]),
    )


def range_variation_parameters() -> list[ChoiceParameter]:
    """Return parameters in AnyLogic ranged-experiment order."""
    return [ChoiceParameter(name, values) for name, values in RANGE_VALUES.items()]
