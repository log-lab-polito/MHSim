"""Duration sampling helpers used by service, delay, and dwell times."""

from __future__ import annotations

from random import Random
from typing import Any, Callable

DurationSampler = Callable[[], float]
"""Callable that samples one positive duration in seconds."""

DurationValue = float | DurationSampler
"""Either a fixed duration in seconds or a sampler returning one."""


def sample_duration_s(value: DurationValue, *, name: str = "duration") -> float:
    duration_s = value() if callable(value) else value
    duration_s = float(duration_s)
    if duration_s <= 0:
        raise ValueError(f"{name} must sample a positive duration, got {duration_s}")
    return duration_s


def make_duration_sampler(
    mean_s: float,
    *,
    rng: Random,
    distribution: str,
    triangular_spread: float = 0.5,
    name: str = "duration",
) -> DurationSampler:
    mean_s = float(mean_s)
    if mean_s <= 0:
        raise ValueError(f"{name} mean must be positive, got {mean_s}")

    if distribution == "deterministic":
        return lambda: mean_s

    if distribution == "exponential":
        rate = 1.0 / mean_s
        return lambda: rng.expovariate(rate)

    if distribution == "triangular":
        if not 0 <= triangular_spread < 1:
            raise ValueError(
                f"{name} triangular_spread must be in [0, 1), got {triangular_spread}"
            )
        low = mean_s * (1.0 - triangular_spread)
        high = mean_s * (1.0 + triangular_spread)
        mode = mean_s
        return lambda: rng.triangular(low, high, mode)

    raise ValueError(
        f"Unsupported {name} distribution '{distribution}'. "
        "Use deterministic, exponential, or triangular."
    )


def make_service_time(params: Any, rng: Random, mean_s: float, name: str) -> DurationValue:
    """Return a fixed or sampled service time based on params randomization settings."""
    if not params.random_service_times:
        return mean_s
    return make_duration_sampler(
        mean_s,
        rng=rng,
        distribution=params.service_time_distribution,
        triangular_spread=params.service_time_triangular_spread,
        name=f"{name}.service_time_s",
    )
