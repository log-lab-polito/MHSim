from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model1Params(SimulationParams):
    """
    Parameters mirroring AnyLogic Model 1 configuration.
    """

    log_filename_prefix: str = "simpy_model1"

    # Source
    arrival_rate_per_min: float = 1 / 0.8

    # Process times
    service1_time_s: float = 30.0  # Upstream service
    service2_time_s: float = 30.0  # Downstream service
    delay_time_s: float = 3 * 60.0  # Delay block
    loading_time_s: float = 1.0  # Store: load pallet onto forklift
    storing_time_s: float = 0.0  # Store: put-away handling time in storage cell
    retrieving_time_s: float = 8.0  # Retrieve: in-slot extraction time (cell -> aisle)
    unloading_time_s: float = 1.0  # Retrieve: unload pallet at destination

    # Storage / transport
    storage_capacity: int = 120
    n_forklifts: int = 1  # Single forklift working
    storage_store_policy: str = "BEST"  # FIRST or BEST
    storage_retrieve_policy: str = "FIFO"  # FIFO, LIFO, or BEST
    # Forklift request priorities (lower = higher priority)
    forklift_store_priority: int = 1
    forklift_retrieve_priority: int = 1

    # ==================== 3D Movement Parameters ====================

    # Horizontal movement (in-plane navigation)
    forklift_max_speed: float = 1.0  # m/s
    forklift_acceleration: float = 1.0  # m/s^2
    forklift_deceleration: float = 1.0  # m/s^2

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
