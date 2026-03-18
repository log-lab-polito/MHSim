from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model4Params(SimulationParams):
    """Parameters for the conveyor spur merge test model."""

    log_filename_prefix: str = "simpy_model4"

    # Sources
    main_arrival_rate_per_min: float = 4.0
    branch_arrival_rate_per_min: float = 2.0

    # Process
    main_service_time_s: float = 6.0
    branch_service_time_s: float = 4.0
    downstream_service_time_s: float = 5.0

    # Main conveyor
    main_conveyor_length_m: float = 30.0
    main_conveyor_speed_mps: float = 0.8
    main_conveyor_max_items: int = 12
    main_conveyor_item_length_m: float = 1.2
    main_conveyor_min_gap_m: float = 0.3

    # Branch conveyor
    branch_conveyor_length_m: float = 9.0
    branch_conveyor_speed_mps: float = 0.8
    branch_conveyor_max_items: int = 4
    branch_conveyor_item_length_m: float = 1.2
    branch_conveyor_min_gap_m: float = 0.3

    # Spur
    spur_merge_offset_m: float = 18.0

    def main_arrival_rate_per_second(self) -> float:
        return self.main_arrival_rate_per_min / 60.0

    def branch_arrival_rate_per_second(self) -> float:
        return self.branch_arrival_rate_per_min / 60.0
