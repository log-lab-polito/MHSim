from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model3Params(SimulationParams):
    """Parameters for the conveyor-focused SimPy test model."""

    log_filename_prefix: str = "simpy_model3"

    # Source
    arrival_rate_per_min: float = 6.0

    # Process
    service1_time_s: float = 10.0
    service2_time_s: float = 8.0

    # Conveyor
    conveyor_length_m: float = 27.0
    conveyor_speed_mps: float = 0.8
    conveyor_max_items: int = 12
    conveyor_item_length_m: float = 1.2
    conveyor_min_gap_m: float = 0.3

    def arrival_rate_per_second(self) -> float:
        return self.arrival_rate_per_min / 60.0
