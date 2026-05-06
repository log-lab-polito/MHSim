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
    # The offset previously masked a kinematic discretization bug where the
    # forklift "snapped" to its destination before fully decelerating. Now
    # that `_move_along_route` tops up to the analytical kinematic time,
    # AnyLogic and SimPy report the same physical phase boundaries directly.
    move_benchmark_loading_boundary_offset_s: float = 0.0

    # Fleet
    sim_time: float = 3600.0
    n_forklifts: int = 1

    # Horizontal movement
    forklift_max_speed: float = 10.0
    forklift_acceleration: float = 1.0
    forklift_deceleration: float | None = None

    # AnyLogic's line-guided path smooths the C turn. The cyclic trace enters
    # the corner near (600,390) and exits near (590,400) in presentation
    # coordinates, i.e. a 10 px / 1.0 m radius in SimPy's /10 scale.
    forklift_turn_radius: float = 1.0
    # AnyLogic's line-guided transporter controller recomputes motion profiles
    # at its MHLSettings lineGuidedUpdateTimestep. On cornered routes this can
    # delay deceleration relative to a single closed-form route solve; keep
    # straight routes analytical, but use the line-guided corner behavior for
    # parity.
    forklift_routed_motion_mode: str = "anylogic_line_guided"
    forklift_line_guided_update_timestep_s: float = 0.5
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
