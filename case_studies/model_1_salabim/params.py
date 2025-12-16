from dataclasses import dataclass


@dataclass
class Model1Params:
    """Parameters mirroring AnyLogic Model 1 configuration."""

    sim_time: float = 18000.0  # seconds
    random_seed: int = 1

    # Source
    arrival_rate_per_min: float = 1.0
    pallet_per_arrival_min: int = 1
    pallet_per_arrival_max: int = 1

    # Process times
    service1_time_s: float = 30.0  # upstream service
    service2_time_s: float = 30.0  # downstream service
    service1_queue_capacity: int = 100
    service2_queue_capacity: int = 100
    delay_time_s: float = 5 * 60.0

    # Storage / transport
    storage_capacity: int = 120  # based on rack structure
    n_forklifts: int = 3
    forklift_store_time_s: float = 0.0
    forklift_retrieve_time_s: float = 0.0
    forklift_speed_mps: float = 10.0
    store_distance_m: float = 270.0   # receiving -> rack
    retrieve_distance_m: float = 110.0  # rack -> outbound
    travel_time_noise_cv: float = 0.0  # lognormal CV multiplier

    # Animation
    enable_animation: bool = False
    animation_speed: float = 1.0  # salabim speed multiplier when animation is on

    def arrival_rate_per_second(self) -> float:
        return self.arrival_rate_per_min / 60.0
