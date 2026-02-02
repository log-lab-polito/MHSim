from dataclasses import dataclass


@dataclass
class Model1Params:
    """
    Parameters mirroring AnyLogic Model 1 configuration.
    """

    sim_time: float = 10800.0  # seconds, RunConfiguration final time
    random_seed: int = 1

    # Source
    arrival_rate_per_min: float = 1.0

    # Process times
    service1_time_s: float = 30.0  # Upstream service
    service2_time_s: float = 30.0  # Downstream service
    delay_time_s: float = 5 * 60.0  # Delay block
    loading_time_s: float = 1.0  # Store: load pallet onto forklift
    unloading_time_s: float = 1.0  # Retrieve: unload pallet at destination

    # Storage / transport
    storage_capacity: int = 120
    n_forklifts: int = 1  # Single forklift working
    storage_store_policy: str = "BEST"  # FIRST or BEST
    storage_retrieve_policy: str = "FIFO"  # FIFO, LIFO, or BEST

    # ==================== 3D Movement Parameters ====================

    # Horizontal movement (in-plane navigation)
    forklift_max_speed: float = 1.0  # m/s
    forklift_acceleration: float = 1.0  # m/s²
    forklift_deceleration: float = 1.0  # m/s²

    # Vertical movement (lift/lower)
    forklift_elevation_speed: float = 0.2  # m/s - used by STORE
    forklift_lowering_speed: float = 0.2  # m/s - used by RETRIEVE
    forklift_turn_radius: float = 1.0  # m - rounded corner radius
    forklift_route_calc_delay_s: float = 0.0  # s - delay for route calculation
    forklift_resume_delay_s: float = 0.0  # s - delay to resume movement
    # Forklift return-home policy: "stay", "always", or "idle" (no queued tasks)
    forklift_return_home_policy: str = "idle"

    # ==================== Storage Configuration (AnyLogic style) ====================
    # Rack dimensions and organization
    rack_depth: float = 2.4  # meters - depth of each rack
    nof_racks: int = 2  # number of racks
    nof_bays: int = 10  # number of bays (horizontal positions per rack)
    nof_shelves: int = 6  # number of shelves (vertical levels)
    shelf_height: float = 1.0  # meters - height between shelf levels

    def arrival_rate_per_second(self) -> float:
        """Convert arrival rate from per minute to per second."""
        return self.arrival_rate_per_min / 60.0
