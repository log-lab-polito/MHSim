#!/usr/bin/env python3
"""Animate Model 2 warehouse simulation with forklift paths and metrics."""

from __future__ import annotations

from case_studies.model_1_simpy.run_model_animation import run_animation_cli

from .params import Model2Params


def main():
    run_animation_cli(model_label="Model 2", params_factory=Model2Params)


if __name__ == "__main__":
    main()
