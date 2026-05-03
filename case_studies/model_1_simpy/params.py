from dataclasses import dataclass

from mhsim.params import SimulationParams


@dataclass
class Model1Params(SimulationParams):
    """Parameters mirroring the new AnyLogic Model 1 transporter scaffold."""

    log_filename_prefix: str = "simpy_model1"
    log_interval_s: float = 0.1

    # AnyLogic Model 1 drives source.inject() from a cyclic event whose
    # recurrence is named arrival_rate_s. The Simulation experiment overrides
    # the class default to 120 s.
    arrival_rate_s: float = 120.0

    # MoveByTransporter handling times
    move_loading_time_s: float = 1.0
    move_unloading_time_s: float = 1.0
    # AnyLogic Model 1 reports MoveByTransporter loading callback boundaries
    # one loading dwell earlier than SimPy's physical dwell start. This only
    # affects benchmark phase attribution, not pallet or transporter movement.
    move_benchmark_loading_boundary_offset_s: float = 1.0

    # Fleet
    sim_time: float = 3600.0
    n_forklifts: int = 1

    # Horizontal movement
    forklift_max_speed: float = 10.0
    forklift_acceleration: float = 1.0
    forklift_deceleration: float | None = None

    forklift_turn_radius: float = 0.0
    forklift_route_calc_delay_s: float = 0.0
    forklift_resume_delay_s: float = 0.0
    forklift_min_distance_to_obstacle_m: float = 1.0
    forklift_avoid_collisions: bool = False
    forklift_return_home_policy: str = "idle"

    # AnyLogic's Simulation experiment moves receiving/outbound to
    # 600 +/- 5 * displacement_m before each run. Model 1 setup applies the
    # same geometry update in the /10 SimPy coordinate frame.
    displacement_m: float = 40.0
    # AnyLogic's Parameter Variation experiment does not carry the Simulation
    # experiment's before-run A/B relocation code, so range validation can
    # intentionally leave the original A/B geometry in place.
    apply_displacement_geometry: bool = True

    def arrival_rate_per_second(self) -> float:
        return (1.0 / self.arrival_rate_s) if self.arrival_rate_s > 0 else 0.0
