from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model6Params(SimulationParams):
    """Parameters mirroring AnyLogic Model 6 simplified transporter behavior."""

    log_filename_prefix: str = "simpy_model6"

    # Source
    arrival_rate_per_min: float = 0.5

    # Process times
    service1_time_s: float = 30.0
    service2_time_s: float = 30.0
    delay_time_s: float = 180.0
    store_loading_time_s: float = 1.0
    store_unloading_time_s: float = 1.0
    retrieve_loading_time_s: float = 1.0
    retrieve_unloading_time_s: float = 1.0

    # Fleet
    sim_time: float = 18000.0
    n_forklifts: int = 1

    # Horizontal movement
    forklift_max_speed: float = 1.0
    forklift_acceleration: float = 1.0
    forklift_deceleration: float = 1.0

    # Vertical movement
    forklift_elevation_speed: float = 0.2
    forklift_lowering_speed: float = 0.2
    forklift_turn_radius: float = 0.5
    forklift_route_calc_delay_s: float = 0.0
    forklift_resume_delay_s: float = 0.0
    forklift_min_distance_to_obstacle_m: float = 1.0
    forklift_avoid_collisions: bool = False
    # AnyLogic Model 6 releases the transporter and returns it to its current
    # home location when no other tasks are waiting.
    forklift_return_home_policy: str = "idle"

    # Geometry retained for routed movement semantics.
    shelf_height: float = 1.0

    def arrival_rate_per_second(self) -> float:
        return self.arrival_rate_per_min / 60.0
