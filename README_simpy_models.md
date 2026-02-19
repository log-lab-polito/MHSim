# MHSim SimPy Models: Run Guide

This README covers:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `mhsim`

## What each package is

- `mhsim`: shared simulation library primitives (movement, spatial, routing, forklift, blocks, storage slots, visualization, logger).
- `case_studies/model_1_simpy`: Model 1 scenario implementation and runnable entrypoints.
- `case_studies/model_2_simpy`: Model 2 scenario wrappers and runnable entrypoints.

## Prerequisites

Run from repo root.

Install core dependency:

```bash
python -m pip install -r mhsim/core_requirements.txt
```

For animation scripts, also install:

```bash
python -m pip install -r mhsim/anim_requirements.txt
```

## Runnable scripts

### Model 1

Run model:

```bash
python -m case_studies.model_1_simpy.run_model
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_1_simpy.compare_blocks
```

Run parameter sweep and export CSV:

```bash
python -m case_studies.model_1_simpy.compare_blocks_cases
```

Optional custom output path:

```bash
python -m case_studies.model_1_simpy.compare_blocks_cases --output case_studies/model_1_simpy/compare_blocks_cases.csv
```

Run animation:

```bash
python -m case_studies.model_1_simpy.run_model_animation
```

Common animation options:

```bash
python -m case_studies.model_1_simpy.run_model_animation --speed 10 --fps 20 --record-fps 20 --trail-seconds 15 --sim-time 900
```

### Model 2

Run model:

```bash
python -m case_studies.model_2_simpy.run_model
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_2_simpy.compare_blocks
```

Run animation:

```bash
python -m case_studies.model_2_simpy.run_model_animation
```

Common animation options:

```bash
python -m case_studies.model_2_simpy.run_model_animation --speed 10 --fps 20 --record-fps 20 --trail-seconds 15 --sim-time 900
```

## About `mhsim`

`mhsim` currently provides reusable modules and classes, but no direct `python -m mhsim...` entrypoint script yet.
