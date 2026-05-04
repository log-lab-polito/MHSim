from dataclasses import dataclass


@dataclass
class SimulationParams:
    sim_time: float = 18000.0  # seconds, RunConfiguration final time
    random_seed: int = 1
