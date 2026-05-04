from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model3Params(SimulationParams):
    """Parameters for the conveyor-focused SimPy test model."""

    # AnyLogic Model 3 drives source.inject() from a cyclic event whose
    # recurrence is named arrival_rate.
    arrival_rate_s: float = 60.0

    # Process
    service1_time_s: float = 10.0
    service2_time_s: float = 8.0

    # Conveyor
    conveyor_length_m: float = 30.0
    conveyor_speed_mps: float = 0.8
    conveyor_max_items: int = 100
    conveyor_item_length_m: float = 1.2
    conveyor_min_gap_m: float = 0.3

    def arrival_rate_per_second(self) -> float:
        return (1.0 / self.arrival_rate_s) if self.arrival_rate_s > 0 else 0.0
