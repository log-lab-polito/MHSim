from __future__ import annotations

from .reporting import run_model_and_print_summary
from .model import Model1SimModel
from .params import Model1Params


def main():
    params = Model1Params()
    run_model_and_print_summary(
        model_cls=Model1SimModel,
        params=params,
        model_label="Model 1",
        console_logging=True,
    )


if __name__ == "__main__":
    main()
