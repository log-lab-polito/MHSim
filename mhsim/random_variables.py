"""Duration sampling helpers used by service, delay, and dwell times."""

from __future__ import annotations

from random import Random
from typing import Any, Callable

DurationSampler = Callable[[], float]
"""Callable that samples one positive duration in seconds."""

DurationValue = float | DurationSampler
"""Either a fixed duration in seconds or a sampler returning one."""


def sample_duration_s(value: DurationValue, *, name: str = "duration") -> float:
    """Resolve a duration value to a concrete, validated number of seconds.

    Args:
        value: Either a fixed duration in seconds or a zero-argument sampler
            returning one.
        name: Label used in the error message when validation fails.

    Returns:
        The resolved duration in seconds.

    Raises:
        ValueError: If the resolved duration is not strictly positive. Sampled
            distributions can legitimately return zero or negative draws, so
            this is checked on every call rather than only at construction.
    """
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
    """Build a sampler drawing durations from the named distribution.

    Args:
        mean_s: Mean duration in seconds. Must be strictly positive.
        rng: Random source the returned sampler draws from. Pass a
            `mhsim.random_streams.JavaRandom` for AnyLogic seed parity.
        distribution: One of `deterministic`, `exponential`, or
            `triangular`.
        triangular_spread: Half-width of the triangular support as a fraction
            of the mean, so `0.5` gives a symmetric range of
            `[0.5 * mean_s, 1.5 * mean_s]` with the mode at the mean. Must be
            in `[0, 1)`. Ignored by the other distributions.
        name: Label used in error messages.

    Returns:
        A zero-argument callable returning one duration in seconds. The
        `deterministic` case returns the mean unchanged and never
        consults `rng`.

    Raises:
        ValueError: If `mean_s` is not positive, if `triangular_spread`
            falls outside `[0, 1)`, or if `distribution` is not recognised.
    """
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
    """Resolve a service duration from a model's randomisation settings.

    Args:
        params: Simulation parameters. Read for `random_service_times`,
            `service_time_distribution`, and
            `service_time_triangular_spread`.
        rng: Random source used when sampling. Unused in deterministic mode.
        mean_s: Mean service duration in seconds.
        name: Block or model label, used to build the sampler's error-message
            prefix.

    Returns:
        `mean_s` unchanged when `params.random_service_times` is false,
        otherwise a sampler built by `make_duration_sampler`.

    Parity:
        Returning the bare float rather than a constant sampler keeps
        deterministic runs bit-identical to the AnyLogic reference, which draws
        no random numbers at all when service times are fixed.
    """
    if not params.random_service_times:
        return mean_s
    return make_duration_sampler(
        mean_s,
        rng=rng,
        distribution=params.service_time_distribution,
        triangular_spread=params.service_time_triangular_spread,
        name=f"{name}.service_time_s",
    )
