from dataclasses import dataclass

from case_studies.model_1_simpy.params import Model1Params


@dataclass
class Model2Params(Model1Params):
    """
    Parameters for Model 2, based on Model 1 with different fleet/time settings.
    """

    log_filename_prefix: str = "simpy_model2"
    sim_time: float = 18000.0  # seconds, 5 hours
    n_forklifts: int = 1
