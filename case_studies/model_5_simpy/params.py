from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model5Params(SimulationParams):
    """
    Parameters mirroring the parameterized warehouse Model 5 configuration.
    """

    log_filename_prefix: str = "simpy_model5"
    sim_time: float = 18000.0  # seconds, 5 hours

    # Source
    arrival_rate_per_min: float = 0.5

    # Process times
    service1_time_s: float = 30.0  # Upstream service
    service2_time_s: float = 30.0  # Downstream service
    delay_time_s: float = 3 * 60.0  # Delay block
    loading_time_s: float = 1.0  # Store: load pallet onto forklift
    unloading_time_s: float = 1.0  # Retrieve: unload pallet at destination

    # Storage / transport
    storage_capacity: int = 60
    n_forklifts: int = 1  # Single forklift working
    # AnyLogic Store fills bay 0 from its lowest free shelf (docs/forklift_rules/R5).
    storage_store_policy: str = "LOWEST"  # FIRST, BEST or LOWEST
    storage_retrieve_policy: str = "FIFO"  # FIFO, LIFO, or BEST
    # Forklift request priorities (lower = higher priority)
    forklift_store_priority: int = 1
    forklift_retrieve_priority: int = 1

    # ==================== 3D Movement Parameters ====================

    # Horizontal movement (in-plane navigation)
    forklift_max_speed: float = 1.0  # m/s
    forklift_acceleration: float = 1.0  # m/s^2
    forklift_deceleration: float = 1.0  # m/s^2

    # Vertical movement (lift/lower). Horizontal motion stays on designed paths.
    forklift_elevation_speed: float = 0.2  # m/s - used by STORE
    forklift_lowering_speed: float = 0.2  # m/s - used by RETRIEVE
    forklift_turn_radius: float = 0.5  # m - rounded corner radius on path-guided routes
    # AnyLogic path-guided transporters use the line-guided controller on every route;
    # with R1 MHSim's controller matches it to 1e-6 s on Model 1's probe legs.
    forklift_routed_motion_mode: str = "anylogic_line_guided"
    forklift_line_guided_update_timestep_s: float = 0.5
    # Rack transfer at a bay's path exit (docs/forklift_rules/R5). The Forklift agent is
    # 1 m tall and its initial speed is 10 m/s in the .alp; it drives 1.5 m from the path
    # exit to the aisle centreline and back, and reaches 2.2 m (half the aisle plus half
    # the 2.4 m cell depth) across. Matches the probe to 3e-12 s on all six cases.
    forklift_cargo_height_m: float = 1.0
    rack_approach_m: float = 1.5
    rack_reach_m: float = 2.2
    rack_handling_speed_mps: float = 10.0
    # The rack lies on the +y side of its aisle: the transporter backs 1.5 m that way (R5).
    rack_approach_heading_deg: float = 90.0
    forklift_route_calc_delay_s: float = 0.0  # s - delay for route calculation
    forklift_resume_delay_s: float = 0.0  # s - delay to resume movement
    forklift_min_distance_to_obstacle_m: float = 1.0  # m - AnyLogic default
    forklift_avoid_collisions: bool = False
    # AnyLogic transporters see, slow down for, stop for and pass each other even with
    # TransporterControl avoidCollisions = false (docs/forklift_rules/R8).
    forklift_line_guided_traffic: bool = True  # AnyLogic TransporterControl option
    # Forklift return-home policy: "stay", "always", or "idle" (no queued tasks)
    forklift_return_home_policy: str = "idle"

    # ==================== Storage Configuration (AnyLogic style) ====================
    # Rack dimensions and organization
    rack_depth: float = 2.4  # meters - depth of each rack
    nof_racks: int = 2  # number of racks
    nof_bays: int = 10  # number of bays (horizontal positions per rack)
    nof_shelves: int = 6  # number of shelves (vertical levels)
    shelf_height: float = 1.0  # meters - height between shelf levels

    # Stochastic timing. Deterministic mode remains the default so existing
    # AnyLogic parity checks keep their current semantics.
    random_arrival_times: bool = False
    random_service_times: bool = False
    arrival_time_distribution: str = "exponential"
    service_time_distribution: str = "triangular"
    service_time_triangular_spread: float = 0.5

    def arrival_rate_per_second(self) -> float:
        """Convert arrival rate from per minute to per second."""
        return self.arrival_rate_per_min / 60.0
