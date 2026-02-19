from __future__ import annotations

from case_studies.model_1_simpy.reporting import run_model_and_print_summary
from case_studies.model_1_simpy.model import Model1SimModel
from .params import Model2Params


def main():
    params = Model2Params()
    run_model_and_print_summary(
        model_cls=Model1SimModel,
        params=params,
        model_label="Model 2",
        console_logging=True,
    )


if __name__ == "__main__":
    main()
