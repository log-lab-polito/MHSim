# MHSim

Discrete-event simulation primitives for material handling and warehouse logistics,
built on [SimPy](https://simpy.readthedocs.io/).

MHSim supplies the domain layer that bare SimPy leaves open: process blocks, forklift
fleets with acceleration-aware movement, path routing and traffic control, storage slot
policies, conveyor networks, and the statistics and experiment machinery needed to compare
a model against a commercial reference tool.

## Scope of this reference

This site documents the reusable core package, `mhsim`. Three neighbouring parts of the
repository are deliberately **not** covered here:

| Area | Why it is excluded |
| --- | --- |
| `mhsim_analysis/` | Comparison and visualisation tooling, not library API. Ships separately from the distribution. |
| `case_studies/` | Models that *consume* the library. Each has its own runnable guide. |
| `tests/` | Verification, not public surface. |

## Installation

From the repository root:

```bash
python -m pip install -e .              # core (simpy)
python -m pip install -e ".[anim]"      # animation extras (numpy, matplotlib)
python -m pip install -e ".[docs,dev]"  # this site, plus lint and coverage tooling
```

Requires Python 3.10 or newer. The only runtime dependency is `simpy`.

## Orientation

The API reference is grouped by concern rather than alphabetically:

- **Core types** — coordinates, movement profiles, layout geometry, and the parameter and
  pallet records passed between blocks.
- **Process blocks** — the AnyLogic-shaped block palette, the forklift fleet, and the
  conveyor network.
- **Movement control** — path routing, traffic reservation, and storage slot assignment.
- **Randomness** — duration samplers, and a `java.util.Random` port used for seed parity
  with AnyLogic.
- **Results** — statistics accumulation, benchmark summaries, and reporting.
- **Experiments** — parameter variation and seeded multi-replication runs.

If you are reading the source alongside this site, [Conventions](conventions.md) explains
the docstring contract every public symbol here follows, and how to regenerate both this
site and the machine-readable API schema under `api/`.

## A note on AnyLogic parity

MHSim is validated against a set of AnyLogic reference models, and many of its behaviours
deliberately mirror that tool rather than following the most obvious Python design. Where
that is true, the docstring says so explicitly under a **Parity** heading. Treat those
notes as load-bearing: changing the behaviour they describe will break validation runs even
when the code still looks correct.
