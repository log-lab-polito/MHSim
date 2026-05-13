from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model3Params(SimulationParams):
    """Parameters for the conveyor-focused SimPy test model."""

    # AnyLogic Model 3 drives source.inject() from a cyclic event whose
    # recurrence is named arrival_rate. In stochastic mode this is treated as
    # the mean interarrival time while preserving the first arrival at t=0.
    arrival_rate_s: float = 60.0

    # Process
    service1_time_s: float = 10.0
    service2_time_s: float = 8.0

    # Stochastic timing. Deterministic mode remains the default so existing
    # AnyLogic parity checks keep their current semantics.
    random_arrival_times: bool = False
    random_service_times: bool = False
    arrival_time_distribution: str = "exponential"
    service_time_distribution: str = "triangular"
    service_time_triangular_spread: float = 0.5

    # Conveyor
    conveyor_length_m: float = 30.0
    conveyor_speed_mps: float = 0.8
    conveyor_max_items: int = 100
    conveyor_item_length_m: float = 1.2
    conveyor_min_gap_m: float = 0.3

    def arrival_rate_per_second(self) -> float:
        return (1.0 / self.arrival_rate_s) if self.arrival_rate_s > 0 else 0.0
