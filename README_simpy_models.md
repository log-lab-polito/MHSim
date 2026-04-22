# MHSim SimPy Models: Run Guide

This README covers:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `case_studies/model_3_simpy`
- `case_studies/model_4_simpy`
- `case_studies/model_6_simpy`
- `mhsim`

## What each package is

- `mhsim`: shared simulation library primitives (movement, spatial, routing, forklift, blocks, storage slots, visualization, logger).
- `case_studies/model_1_simpy`: Model 1 scenario implementation and runnable entrypoints.
- `case_studies/model_2_simpy`: Model 2 scenario wrappers and runnable entrypoints.
- `case_studies/model_3_simpy`: Conveyor-focused scenario for testing `Conveyor Enter`/`Convey`/`Conveyor Exit`.
- `case_studies/model_4_simpy`: Conveyor spur merge scenario for testing `Conveyor Spur`.
- `case_studies/model_6_simpy`: Simplified transporter-focused warehouse scenario for AnyLogic Model 6 parity work.

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

The Model 2 runner now prints forklift benchmark rows for both:

- the original six legacy timing windows used by the existing AnyLogic
  comparison workflow
- the `MoveByTransporter`-style phase windows
  (`enter -> seize -> loading start -> loading finish -> unloading start ->
  unloading finish -> release`)

To export the same table as CSV:

```bash
python -m case_studies.model_2_simpy.run_model --csv logs/model_2_forklift_benchmarks.csv
```

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_2_simpy.compare_benchmark_results --anylogic logs/anylogic_model_2_forklift_timing.txt --csv logs/model_2_benchmark_comparison.csv
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
`throughput_per_hour`, `forklift_utilization`.

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

### Model 6

Run model:

```bash
python -m case_studies.model_6_simpy.run_model
```

Export the forklift benchmark table as CSV:

```bash
python -m case_studies.model_6_simpy.run_model --csv logs/model_6_forklift_benchmarks.csv
```

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_6_simpy.compare_benchmark_results --anylogic logs/anylogic_model_6_forklift_timing.txt --csv logs/model_6_benchmark_comparison.csv
```

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_6_simpy.run_parameter_variation
```

Run the ranged validation with explicit options:

```bash
python -m case_studies.model_6_simpy.run_parameter_variation --run-until 1200 --range-replications 2
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py
```

The range comparison reads these SimPy CSVs by default:

- `logs/model_6_parameter_variation_range_runs.csv`
- `logs/model_6_parameter_variation_range_summary.csv`

If you recently changed the range metrics or benchmark export logic, rerun the
Model 6 range experiment first so those files are refreshed.

Detailed full view:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view full
```

Quick summary view:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view overview
```

Hotspot matrix for a single metric:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view matrix --metric avg_time_in_system_s
```

Worst mismatches first:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view offenders --top 8
```

Worst mismatches for one forklift phase benchmark average:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view offenders --metric benchmark_store_loading_finish_to_unloading_start_s__average --top 8
```

Worst mismatches across all forklift average-duration benchmarks:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --view offenders --metric benchmark_avg_only --top 10
```

The `--metric` option accepts:

- summary metrics such as `avg_time_in_system_s`, `throughput_per_hour`, and `forklift_utilization`
- forklift phase benchmark metrics such as `benchmark_store_seize_to_loading_start_s__average`
- the shortcut `benchmark_avg_only` to combine all forklift phase `__average` duration metrics in one offenders ranking

To compare against non-default SimPy CSV outputs:

```bash
python case_studies/model_6_simpy/compare_parameter_variation_range.py --anylogic logs/anylogic_model_6_parameter_variation_range.txt --simpy-runs /tmp/model6_phase_only/model_6_parameter_variation_range_runs.csv --simpy-summary /tmp/model6_phase_only/model_6_parameter_variation_range_summary.csv --view offenders --metric benchmark_avg_only --top 10
```

Run animation:

```bash
python -m case_studies.model_6_simpy.run_model_animation
```

Common animation options:

```bash
python -m case_studies.model_6_simpy.run_model_animation --speed 10 --fps 20 --record-fps 20 --trail-seconds 15 --sim-time 900
```

## About `mhsim`

`mhsim` currently provides reusable modules and classes, but no direct `python -m mhsim...` entrypoint script yet.
