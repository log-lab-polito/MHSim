"""Base simulation parameter record shared by every MHSim case study."""

from dataclasses import dataclass


@dataclass
class SimulationParams:
    """Run-level settings common to all models.

    Case studies subclass this and add their own fields — fleet sizes, arrival
    rates, layout dimensions — while inheriting the run length and seed that the
    shared experiment and replication machinery reads.

    Attributes:
        sim_time: Simulated run length in seconds. The default of
            `18000.0` is five hours, matching the final time configured in the
            AnyLogic reference models.
        random_seed: Seed for the model's random source. Only consulted by
            models that opt into stochastic behaviour; deterministic parity runs
            ignore it.

    Parity:
        `sim_time` mirrors the AnyLogic `RunConfiguration` stop time rather than
        a SimPy `env.run(until=...)` convention, so the two tools observe the
        same benchmark window.
    """

    sim_time: float = 18000.0  # seconds, RunConfiguration final time
    random_seed: int = 1
