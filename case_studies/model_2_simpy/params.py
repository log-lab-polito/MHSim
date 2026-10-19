from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model2Params(SimulationParams):
    """Parameters mirroring AnyLogic Model 2 simplified transporter behavior."""

    log_filename_prefix: str = "simpy_model2"

    # Source. AnyLogic Model 2 names this as an interarrival interval in
    # seconds, not a per-minute rate; keep the SimPy parameter aligned.
    arrival_rate_s: float = 120.0

    # Process times
    service1_time_s: float = 30.0
    service2_time_s: float = 30.0
    delay_time_s: float = 180.0
    store_loading_time_s: float = 1.0
    store_unloading_time_s: float = 1.0
    retrieve_loading_time_s: float = 1.0
    retrieve_unloading_time_s: float = 1.0

    # Stochastic timing. Deterministic mode remains the default so existing
    # AnyLogic parity checks keep their current semantics.
    random_arrival_times: bool = False
    random_service_times: bool = False
    arrival_time_distribution: str = "exponential"
    service_time_distribution: str = "triangular"
    service_time_triangular_spread: float = 0.5

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
    # Model 2 is now intentionally migrated to the same recoverable AnyLogic
    # line-guided motion mode as Model 1. The 0.5 m turn radius is retained
    # because it is the existing Model 2 geometry fit.
    forklift_routed_motion_mode: str = "anylogic_line_guided"
    forklift_line_guided_update_timestep_s: float = 0.5
    forklift_route_calc_delay_s: float = 0.0
    forklift_resume_delay_s: float = 0.0
    forklift_min_distance_to_obstacle_m: float = 1.0
    forklift_avoid_collisions: bool = False
    # AnyLogic Model 2 releases the transporter and returns it to its home
    # location when no other task is waiting (the default wrap-up). The 48 s
    # probes are saturated, so they cannot distinguish this from staying put.
    forklift_return_home_policy: str = "idle"
    move_to_storage_apply_post_task_policy: bool = True
    move_to_outbound_apply_post_task_policy: bool = True
    # Per-leg motion-mode overrides stay available for experiments, but none is
    # needed: with R1 and R7 the fleet default matches every probed leg (H4).
    move_to_storage_pickup_routed_motion_mode: str | None = None
    move_to_storage_dropoff_routed_motion_mode: str | None = None
    move_to_outbound_pickup_routed_motion_mode: str | None = None
    move_to_outbound_dropoff_routed_motion_mode: str | None = None

    # Geometry retained for routed movement semantics.
    shelf_height: float = 1.0

    def arrival_rate_per_second(self) -> float:
        return (1.0 / self.arrival_rate_s) if self.arrival_rate_s > 0 else 0.0
