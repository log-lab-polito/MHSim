# Docstring conventions

Every public symbol in `mhsim/` carries a docstring in **Google style**, parsed by
[Griffe](https://mkdocstrings.github.io/griffe/) and rendered by mkdocstrings. This page is
the contract; `ruff` and `interrogate` enforce the mechanical parts of it.

## The contract

Each public module, class, function, and method states:

1. **Purpose** — one imperative summary line, ending in a full stop.
2. **Parameters, with units.** Durations are seconds, distances metres, speeds
   metres per second unless the docstring says otherwise. Say which.
3. **Returns** — what comes back, in the same unit discipline.
4. **Raises** — only where the caller can reasonably trigger it.
5. **Parity** — see below, wherever behaviour deliberately mirrors AnyLogic.

Prose is written in **UK English** (`utilisation`, `behaviour`, `modelling`), because these
docstrings feed the thesis appendix. Identifiers are left exactly as they are: the code says
`utilization_percent`, and renaming it is out of scope.

## Shape

```python
def make_service_time(
    params: SimulationParams,
    rng: random.Random,
    mean_s: float,
    name: str,
) -> DurationValue:
    """Resolve a service duration as either a fixed value or a sampler.

    Args:
        params: Simulation parameters; `random_service_times` selects the mode.
        rng: Random source used when sampling. Ignored in deterministic mode.
        mean_s: Mean service duration in seconds.
        name: Label used in error messages when validation fails.

    Returns:
        The mean itself when service times are deterministic, otherwise a
        zero-argument callable returning a sampled duration in seconds.

    Raises:
        ValueError: If `mean_s` is not strictly positive.
    """
```

## The Parity heading

AnyLogic parity is a first-class design constraint, and several behaviours in this library
exist *only* because the reference tool does it that way. Those are recorded inline:

```python
    """Emit the first pallet at simulation time zero.

    Parity:
        AnyLogic sources fire once at `t=0` before the first inter-arrival delay.
        A conventional SimPy source would wait one interval first. Deterministic
        parity runs depend on this; see `docs/decisions.md`.
    """
```

Use the heading when, and only when, the behaviour would otherwise look like a bug or an
odd choice to a reader who does not know the reference model. It is not a place for general
commentary.

## What is exempt

`ruff`'s pydocstyle rules and the `interrogate` coverage gate skip `tests/`,
`case_studies/`, and `mhsim_analysis/`. Private members (leading underscore) and magic
methods are excluded from the coverage count, though a private helper with non-obvious
behaviour is still worth documenting.

## Checking

Everything is wired into `make`:

```bash
make check        # lint + coverage + tests + strict docs build
make docs-serve   # read the rendered result locally
make schema       # dump the Griffe API model into api/
make api-check    # report public API breakages against the last tag
```

`make check` is what must pass before a commit. `pytest` runs the unit tests and the
doctests in `mhsim/` together, because `addopts = "--doctest-modules"` is set in
`pyproject.toml` — an example that stops working is a test failure, not stale prose.

The `fail-under` value in `pyproject.toml` is a ratchet. It currently sits at **100**; raise
the surface, not the exception.

## The API schema

`make schema` writes a complete Griffe model of the package to
`api/mhsim-<version>.json` — every module, class, function, parameter, default, annotation,
and docstring. It is the machine-readable API contract, committed once per release, and the
input the thesis appendix generator will eventually read rather than parsing source.

`make api-check` compares the current surface against the last tag and reports removals and
signature changes, so a breaking change surfaces in review instead of after publication.
