# MHSim SimPy Models: Run Guide

This README covers:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `case_studies/model_3_simpy`
- `case_studies/model_4_simpy`
- `mhsim`

## What each package is

- `mhsim`: shared simulation library primitives (movement, spatial, routing, forklift, blocks, storage slots, visualization, logger).
- `case_studies/model_1_simpy`: Model 1 scenario implementation and runnable entrypoints.
- `case_studies/model_2_simpy`: Model 2 scenario wrappers and runnable entrypoints.
- `case_studies/model_3_simpy`: Conveyor-focused scenario for testing `Conveyor Enter`/`Convey`/`Conveyor Exit`.
- `case_studies/model_4_simpy`: Conveyor spur merge scenario for testing `Conveyor Spur`.

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

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_2_simpy.run_parameter_variation
```

Run the ranged validation with explicit options:

```bash
python -m case_studies.model_2_simpy.run_parameter_variation --run-until 1200 --range-replications 2
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python case_studies/model_2_simpy/compare_parameter_variation_range.py
```

The comparison script supports multiple console views. The default `--view full`
prints the detailed per-combination audit table.

Quick summary view:

```bash
python case_studies/model_2_simpy/compare_parameter_variation_range.py --view overview
```

Hotspot matrix for a single metric:

```bash
python case_studies/model_2_simpy/compare_parameter_variation_range.py --view matrix --metric avg_time_in_system_s
```

Worst mismatches first:

```bash
python case_studies/model_2_simpy/compare_parameter_variation_range.py --view offenders --top 8
```

Available views:

- `full`: detailed per-parameter-combination comparison table
- `overview`: one compact summary row per metric with match/close/diff counts
- `matrix`: grid view by `arrival_rate_s x delay_time_s`, split by forklift count
- `offenders`: top mismatches sorted by severity
- `all`: prints overview, matrix, offenders, and full in sequence

Metric filtering is supported for `matrix` and `offenders` via `--metric`. Use
`--metric all` or one of:
`created`, `completed`, `in_flight`, `avg_time_in_system_s`, `storage_level`,
`throughput_per_hour`.

Run animation:

```bash
python -m case_studies.model_2_simpy.run_model_animation
```

Common animation options:

```bash
python -m case_studies.model_2_simpy.run_model_animation --speed 10 --fps 20 --record-fps 20 --trail-seconds 15 --sim-time 900
```

### Model 3

Run conveyor model:

```bash
python -m case_studies.model_3_simpy.run_model
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_3_simpy.compare_blocks
```

Run conveyor animation:

```bash
python -m case_studies.model_3_simpy.run_model_animation
```

Common animation options:

```bash
python -m case_studies.model_3_simpy.run_model_animation --speed 10 --fps 20 --record-fps 20 --sim-time 900
```

### Model 4

Run conveyor spur model:

```bash
python -m case_studies.model_4_simpy.run_model
```

## About `mhsim`

`mhsim` currently provides reusable modules and classes, but no direct `python -m mhsim...` entrypoint script yet.
