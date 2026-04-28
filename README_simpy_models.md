# MHSim SimPy Models: Run Guide

This README covers:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `case_studies/model_3_simpy`
- `case_studies/model_4_simpy`
- `mhsim`

## What each package is

- `mhsim`: shared simulation library primitives for movement, spatial layout, routing, forklift behavior, AnyLogic-style blocks, storage logic, visualization, experiments, and logging.
- `case_studies/model_1_simpy`: parameterized warehouse model with `Store` and `Retrieve` blocks. This is the main warehouse parity model.
- `case_studies/model_2_simpy`: simplified transporter-focused warehouse model built around `MoveByTransporter` to validate forklift fleet movement behavior.
- `case_studies/model_3_simpy`: conveyor-focused scenario for `Conveyor Enter`, `Convey`, and `Conveyor Exit`.
- `case_studies/model_4_simpy`: conveyor spur merge scenario for `Conveyor Spur`.

## AnyLogic Mapping

- SimPy Model 1 validates against `anylogic/Model 1` and `logs/anylogic_model_1*`.
- SimPy Model 2 validates against `anylogic/Model 2` and `logs/anylogic_model_2*`.
- SimPy Model 3 validates against `anylogic/Model 3`.
- SimPy Model 4 remains WIP.
- `anylogic/Legacy Model 1` is retained as historical context only.

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

Run model and print summary plus forklift benchmark rows:

```bash
python -m case_studies.model_1_simpy.run_model
```

Export the forklift benchmark table as CSV:

```bash
python -m case_studies.model_1_simpy.run_model --csv logs/model_1_forklift_benchmarks.csv
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_1_simpy.compare_blocks
```

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_1_simpy.compare_benchmark_results --anylogic logs/anylogic_model_1_forklift_timing.txt --csv logs/model_1_benchmark_comparison.csv
```

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_1_simpy.run_parameter_variation
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python case_studies/model_1_simpy/compare_parameter_variation_range.py --view overview
```

Run animation:

```bash
python -m case_studies.model_1_simpy.run_model_animation
```

### Model 2

Run model and print summary plus phase benchmark rows:

```bash
python -m case_studies.model_2_simpy.run_model
```

Export the forklift benchmark table as CSV:

```bash
python -m case_studies.model_2_simpy.run_model --csv logs/model_2_forklift_benchmarks.csv
```

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_2_simpy.compare_benchmark_results --anylogic logs/anylogic_model_2_forklift_timing.txt --csv logs/model_2_benchmark_comparison.csv
```

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_2_simpy.run_parameter_variation
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python case_studies/model_2_simpy/compare_parameter_variation_range.py --view overview
```

Show the top benchmark-average offenders against the AnyLogic range export:

```bash
python3 case_studies/model_2_simpy/compare_parameter_variation_range.py \
  --anylogic logs/anylogic_model_2_parameter_variation_range.txt \
  --view offenders \
  --metric benchmark_avg_only \
  --top 10
```

For the offenders view, use `--view offenders`. The offender count is controlled
by `--top`; the metric filter is controlled by `--metric`.

Accepted `--metric` shortcuts for offenders:

```text
all
benchmark_avg_only
```

Accepted summary `--metric` values for offenders:

```text
created
completed
in_flight
avg_time_in_system_s
storage_level
throughput_per_hour
forklift_utilization
```

Accepted forklift benchmark average shorthand `--metric` values for offenders:

```text
store_enter_to_seize_s
store_seize_to_loading_start_s
store_loading_duration_s
store_loading_finish_to_unloading_start_s
store_unloading_duration_s
store_unloading_finish_to_release_s
retrieve_enter_to_seize_s
retrieve_seize_to_loading_start_s
retrieve_loading_duration_s
retrieve_loading_finish_to_unloading_start_s
retrieve_unloading_duration_s
retrieve_unloading_finish_to_release_s
```

Accepted full forklift benchmark `--metric` values for offenders:

```text
benchmark_store_enter_to_seize_s__average
benchmark_store_enter_to_seize_s__minimum
benchmark_store_enter_to_seize_s__maximum
benchmark_store_enter_to_seize_s__std_dev_pop
benchmark_store_seize_to_loading_start_s__average
benchmark_store_seize_to_loading_start_s__minimum
benchmark_store_seize_to_loading_start_s__maximum
benchmark_store_seize_to_loading_start_s__std_dev_pop
benchmark_store_loading_duration_s__average
benchmark_store_loading_duration_s__minimum
benchmark_store_loading_duration_s__maximum
benchmark_store_loading_duration_s__std_dev_pop
benchmark_store_loading_finish_to_unloading_start_s__average
benchmark_store_loading_finish_to_unloading_start_s__minimum
benchmark_store_loading_finish_to_unloading_start_s__maximum
benchmark_store_loading_finish_to_unloading_start_s__std_dev_pop
benchmark_store_unloading_duration_s__average
benchmark_store_unloading_duration_s__minimum
benchmark_store_unloading_duration_s__maximum
benchmark_store_unloading_duration_s__std_dev_pop
benchmark_store_unloading_finish_to_release_s__average
benchmark_store_unloading_finish_to_release_s__minimum
benchmark_store_unloading_finish_to_release_s__maximum
benchmark_store_unloading_finish_to_release_s__std_dev_pop
benchmark_retrieve_enter_to_seize_s__average
benchmark_retrieve_enter_to_seize_s__minimum
benchmark_retrieve_enter_to_seize_s__maximum
benchmark_retrieve_enter_to_seize_s__std_dev_pop
benchmark_retrieve_seize_to_loading_start_s__average
benchmark_retrieve_seize_to_loading_start_s__minimum
benchmark_retrieve_seize_to_loading_start_s__maximum
benchmark_retrieve_seize_to_loading_start_s__std_dev_pop
benchmark_retrieve_loading_duration_s__average
benchmark_retrieve_loading_duration_s__minimum
benchmark_retrieve_loading_duration_s__maximum
benchmark_retrieve_loading_duration_s__std_dev_pop
benchmark_retrieve_loading_finish_to_unloading_start_s__average
benchmark_retrieve_loading_finish_to_unloading_start_s__minimum
benchmark_retrieve_loading_finish_to_unloading_start_s__maximum
benchmark_retrieve_loading_finish_to_unloading_start_s__std_dev_pop
benchmark_retrieve_unloading_duration_s__average
benchmark_retrieve_unloading_duration_s__minimum
benchmark_retrieve_unloading_duration_s__maximum
benchmark_retrieve_unloading_duration_s__std_dev_pop
benchmark_retrieve_unloading_finish_to_release_s__average
benchmark_retrieve_unloading_finish_to_release_s__minimum
benchmark_retrieve_unloading_finish_to_release_s__maximum
benchmark_retrieve_unloading_finish_to_release_s__std_dev_pop
```

Show the full AnyLogic vs SimPy parameter-variation comparison table:

```bash
python3 case_studies/model_2_simpy/compare_parameter_variation_range.py \
  --anylogic logs/anylogic_model_2_parameter_variation_range.txt \
  --view full
```

Run animation:

```bash
python -m case_studies.model_2_simpy.run_model_animation
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

### Model 4

Run conveyor spur model:

```bash
python -m case_studies.model_4_simpy.run_model
```
