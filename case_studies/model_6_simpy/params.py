from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model6Params(SimulationParams):
    """Parameters for the AnyLogic Model 6 SimPy mirror."""

    sim_time: float = 18000.0

    # AnyLogic cyclic event recurrence, in seconds.
    arrival_rate_s: float = 10.0

    # Process services.
    service1_time_s: float = 10.0
    service2_time_s: float = 8.0

    # Stochastic timing. Deterministic timing remains the parity default.
    random_arrival_times: bool = False
    random_service_times: bool = False
    arrival_time_distribution: str = "exponential"
    service_time_distribution: str = "triangular"
    service_time_triangular_spread: float = 0.5

    # Conveyor network settings.
    conveyor_speed_mps: float = 0.8
    conveyor_gap_m: float = 0.3
    conveyor_item_length_m: float = 1.0
    conveyor_capacity: int = 10

    main_conveyor_length_m: float = 30.0
    storage_conveyor_length_m: float = 8.0
    unbatch_transfer_offset_m: float = 7.0
    unbatch_station_length_m: float = 5.0
    storage_spur_offset_m: float = 10.0
    batch_transfer_offset_m: float = 25.0
    batch_station_length_m: float = 12.0
    station_capacity: int = 10
    station_physical_occupancy: bool = True
    station_physical_release_delay_s: float | None = None
    empty_pallet_remove_from_storage_conveyor: bool = True

    # AnyLogic Batch default is 10 when the block field is omitted.
    batch_size: int = 10

    # Bounded first-N parity event diagnostics.
    diagnostic_trace_limit: int = 50

    # Java new Random() in the .alp is represented explicitly here.
    min_items_per_pallet: int = 5
    max_items_per_pallet: int = 20
    item_count_random_seed: int = 101
    unbatch_random_seed: int = 202

    def __post_init__(self) -> None:
        if self.min_items_per_pallet < 1:
            raise ValueError("min_items_per_pallet must be >= 1")
        if self.max_items_per_pallet < self.min_items_per_pallet:
            raise ValueError(
                "max_items_per_pallet must be >= min_items_per_pallet"
            )

    def arrival_rate_per_second(self) -> float:
        return (1.0 / self.arrival_rate_s) if self.arrival_rate_s > 0 else 0.0
