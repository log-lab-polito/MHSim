from dataclasses import dataclass


@dataclass
class Model1Params:
    """Parameters mirroring AnyLogic Model 1 configuration."""

    sim_time: float = 18000.0  # seconds, RunConfiguration final time
    random_seed: int = 1

    # Source
    arrival_rate_per_min: float = 1.0
    pallet_per_arrival_min: int = 1  # undefined in .alp; default to single pallet
    pallet_per_arrival_max: int = 1

    # Process times
    service1_time_s: float = 30.0  # Upstream service
    service2_time_s: float = 30.0  # Downstream service
    service1_queue_capacity: int = 100
    service2_queue_capacity: int = 100
    delay_time_s: float = 5 * 60.0  # Delay block

    # Storage / transport
    # derived from rack (2 units * 10 bays * 6 shelves * 1 cell)
    storage_capacity: int = 120
    n_forklifts: int = 3
    # Store loading time not defined in .alp
    forklift_store_time_s: float = 0.0
    # Retrieve unloading time not defined in .alp
    forklift_retrieve_time_s: float = 0.0
    # Total travel time per store/retrieve task (approx. AnyLogic path-guided movement at ~10 m/s)
    # Roughly: receiving_area -> rack ≈ 27 s, rack -> outbound_area ≈ 11 s, rounded up
    forklift_store_travel_time_s: float = 0.0
    forklift_retrieve_travel_time_s: float = 0.0
    # Optional distance/speed-based travel model
    forklift_speed_mps: float = 10.0
    # Distances approximated from AnyLogic node layout: receiving -> rack ≈ 270 m, rack -> outbound ≈ 110 m
    store_distance_m: float = 270.0
    retrieve_distance_m: float = 110.0
    # coefficient of variation for travel time (lognormal multiplier)
    travel_time_noise_cv: float = 0.0

    def arrival_rate_per_second(self) -> float:
        return self.arrival_rate_per_min / 60.0
