# MHSim SimPy Models: Run Guide

This README covers:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `case_studies/model_3_simpy`
- `case_studies/model_4_simpy`
- `case_studies/model_5_simpy`
- `mhsim`

## What each package is

- `mhsim`: shared simulation library primitives for movement, spatial layout, routing, forklift behavior, AnyLogic-style blocks, storage logic, visualization, experiments, and logging.
- `case_studies/model_1_simpy`: simplified single-move transporter reference matching AnyLogic Model 1 (`Source -> moveByTransporter -> Sink`).
- `case_studies/model_2_simpy`: simplified transporter-focused warehouse model built around `MoveByTransporter` to validate forklift fleet movement behavior.
- `case_studies/model_3_simpy`: conveyor-focused scenario for `Conveyor Enter`, `Convey`, and `Conveyor Exit`.
- `case_studies/model_4_simpy`: conveyor spur merge scenario for `Conveyor Spur`.
- `case_studies/model_5_simpy`: parameterized warehouse model with `Store` and `Retrieve` blocks. This is the main warehouse parity model and shared warehouse reporting/stats home.

## AnyLogic Mapping

- SimPy Model 1 validates against `anylogic/Model 1` and `logs/anylogic_model_1*`.
- SimPy Model 2 validates against `anylogic/Model 2` and `logs/anylogic_model_2*`.
- SimPy Model 3 validates against `anylogic/Model 3`.
- SimPy Model 4 remains WIP.
- SimPy Model 5 validates against `anylogic/Model 5` and `logs/anylogic_model_5*`.
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

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_1_simpy.compare_benchmark_results --anylogic logs/anylogic_model_1_parameter_variation_range.txt --csv logs/model_1_benchmark_comparison.csv
```

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_1_simpy.run_parameter_variation
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python -m case_studies.model_1_simpy.compare_parameter_variation_range
```

Run stochastic ranged replications with exponential interarrival times and
triangular transporter loading/unloading times. The default stochastic run
matches the AnyLogic `StochasticAnalysis` experiment: 64 parameter combinations,
50 replications per iteration:

```bash
python -m case_studies.model_1_simpy.run_stochastic_replications
```

Outputs:

```text
logs/model_1_stochastic_replications_runs.csv
logs/model_1_stochastic_replications_summary.csv
```

Compare stochastic AnyLogic and SimPy replication samples:

```bash
python -m case_studies.model_1_simpy.compare_stochastic_replications \
  --anylogic logs/anylogic_model_1_stochastic_replications.txt \
  --simpy-runs logs/model_1_stochastic_replications_runs.csv \
  --output-csv logs/model_1_stochastic_comparison.csv
```

Write a curated text report:

```bash
python -m case_studies.model_1_simpy.compare_parameter_variation_range \
  --view report \
  --metric benchmark_avg_only \
  --top 25 \
  --output logs/model_1_parameter_variation_range_report.txt
```

Write an interactive HTML report:

```bash
python -m case_studies.model_1_simpy.compare_parameter_variation_range \
  --view report \
  --metric benchmark_avg_only \
  --top 25 \
  --output logs/model_1_parameter_variation_range_report.html
```

HTML report options that usually matter:

```text
--output ...html       Writes HTML automatically when the path ends in .html or .htm.
--format html          Forces HTML when the output path does not use an HTML extension.
--metric               Controls the Top Offenders section; benchmark_avg_only is the
                       recommended benchmark-focused view.
--top                  Controls how many Top Offenders rows are included.
```

Only pass `--anylogic`, `--simpy-runs`, or `--simpy-summary` when comparing
against non-default input files. `--view` mostly affects text output; HTML
always includes the interactive report with overview, offenders, and
per-iteration benchmark details.

Run animation:

```bash
python -m case_studies.model_1_simpy.run_model_animation
```

Compare AnyLogic and SimPy cyclic forklift traces:

```bash
python -m case_studies.model_1_simpy.compare_movement_trace
```

Animate the current AnyLogic cyclic position log against a SimPy trace:

```bash
python -m case_studies.model_1_simpy.run_range_trace_animation
```

For parameter-variation logs, pass the SimPy settings that match the AnyLogic
run that produced `anylogic/Model 1/log_file.txt`. The script infers the SimPy
forklift count from the AnyLogic trace column count. By default the script
applies the Simulation experiment A/B displacement geometry; add
`--no-apply-displacement-geometry` for parameter-variation logs that use the
original markup positions.

```bash
python -m case_studies.model_1_simpy.run_range_trace_animation --arrival-rate-s 60 --forklift-max-speed 20 --forklift-acceleration 1 --displacement-m 100 --no-apply-displacement-geometry
```

The range trace animation derives AnyLogic speed and acceleration from
`t=..., x=..., y=...` cyclic position samples. It uses timestamp deltas and
central differences after converting logged presentation coordinates to model
meters with `/ 10.0`; these are sample-derived estimates, not AnyLogic internal
solver state.

Model 1 reports `Move: ...` benchmark labels for its single
`moveByTransporter` block.

Accepted Model 1 summary `--metric` values:

```text
created
completed
avg_wip
avg_time_in_system_s
throughput_per_hour
forklift_utilization
```

Accepted Model 1 forklift benchmark average shorthand `--metric` values:

```text
move_enter_to_seize_s
move_seize_to_loading_start_s
move_loading_duration_s
move_loading_finish_to_unloading_start_s
move_unloading_duration_s
move_unloading_finish_to_release_s
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
python -m case_studies.model_2_simpy.compare_parameter_variation_range --view overview
```

Run stochastic ranged replications with exponential interarrival times and
triangular service/loading/unloading times. `delay_time_s` remains
deterministic. The default stochastic run matches the AnyLogic
`StochasticAnalysis` experiment: 36 parameter combinations, 50 replications per
iteration:

```bash
python -m case_studies.model_2_simpy.run_stochastic_replications
```

Outputs:

```text
logs/model_2_stochastic_replications_runs.csv
logs/model_2_stochastic_replications_summary.csv
```

Compare stochastic AnyLogic and SimPy replication samples:

```bash
python -m case_studies.model_2_simpy.compare_stochastic_replications \
  --anylogic logs/anylogic_model_2_stochastic_replications.txt \
  --simpy-runs logs/model_2_stochastic_replications_runs.csv \
  --output-csv logs/model_2_stochastic_comparison.csv
```

Show the top benchmark-average offenders against the AnyLogic range export:

```bash
python -m case_studies.model_2_simpy.compare_parameter_variation_range \
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
avg_wip
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
python -m case_studies.model_2_simpy.compare_parameter_variation_range \
  --anylogic logs/anylogic_model_2_parameter_variation_range.txt \
  --view full
```

Run animation:

```bash
python -m case_studies.model_2_simpy.run_model_animation
```

### Model 3

Run conveyor model and print conveyor summary metrics:

```bash
python -m case_studies.model_3_simpy.run_model
```

Run with a shorter stop time:

```bash
python -m case_studies.model_3_simpy.run_model --sim-time 600
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_3_simpy.compare_blocks
```

Model 3 does not generate runtime logs. It validates the conveyor reference
through summary metrics, block counts, parameter-variation exports, and
animation inspection. The checked-in AnyLogic parameter-variation source is
`anylogic/Model 3/log_file.txt`.

Run ranged parameter-variation validation experiments:

```bash
python -m case_studies.model_3_simpy.run_parameter_variation
```

This writes:

```text
logs/model_3_parameter_variation_range_runs.csv
logs/model_3_parameter_variation_range_summary.csv
```

The ranged experiment mirrors AnyLogic's Model 3 sensitivity analysis:

```text
arrival_rate_s       60, 120, 180, 240
conveyor_speed_mps   0.5, 1.0, 1.5, 2.0
conveyor_min_gap_m   0.3, 0.6, 0.9, 1.2
stop time            3600 s
```

Run stochastic replications with exponential interarrival times and triangular
service times:

```bash
python -m case_studies.model_3_simpy.run_stochastic_replications \
  --replications 100 \
  --run-until 18000
```

This writes:

```text
logs/model_3_stochastic_replications_runs.csv
logs/model_3_stochastic_replications_summary.csv
```

Compare stochastic AnyLogic and SimPy replication samples:

```bash
python -m case_studies.model_3_simpy.compare_stochastic_replications \
  --anylogic "anylogic/Model 3/log_file.txt" \
  --simpy-runs logs/model_3_stochastic_replications_runs.csv \
  --output-csv logs/model_3_stochastic_comparison.csv
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python -m case_studies.model_3_simpy.compare_parameter_variation_range
```

Show the average-cycle hotspot matrix:

```bash
python -m case_studies.model_3_simpy.compare_parameter_variation_range \
  --view matrix \
  --metric avg_time_in_system_s
```

Write a curated text report:

```bash
python -m case_studies.model_3_simpy.compare_parameter_variation_range \
  --view report \
  --top 25 \
  --output logs/model_3_parameter_variation_range_report.txt
```

Write an HTML report:

```bash
python -m case_studies.model_3_simpy.compare_parameter_variation_range \
  --view report \
  --top 25 \
  --output logs/model_3_parameter_variation_range_report.html
```

Only pass `--anylogic`, `--simpy-runs`, or `--simpy-summary` when comparing
against non-default input files. The default AnyLogic input is
`anylogic/Model 3/log_file.txt`.

Accepted Model 3 summary `--metric` values:

```text
created
completed
avg_wip
avg_time_in_system_s
throughput_per_hour
conveyor_entered
conveyor_exited
conveyor_occupancy_end
```

Run conveyor animation:

```bash
python -m case_studies.model_3_simpy.run_model_animation
```

### Model 4

Model 4 is the conveyor spur/merge scenario. Its SimPy process block surface
matches the current AnyLogic Model 4 topology:

```text
mainSource -> mainService -> mainConvey -> downstreamService -> sink
branchSource -> branchService -> branchConvey -> downstreamService -> sink
```

`conveyorSpur` is a physical conveyor-network element inside `branchConvey`,
not a separate process block in the SimPy comparison table.

Run conveyor spur model and print summary metrics:

```bash
python -m case_studies.model_4_simpy.run_model
```

Run with a shorter stop time:

```bash
python -m case_studies.model_4_simpy.run_model --sim-time 600
```

Compare AnyLogic vs SimPy block counts for the spur model:

```bash
python -m case_studies.model_4_simpy.compare_blocks
```

Model 4 follows the Model 3 approach: AnyLogic values are transcribed into
`ANYLOGIC_BLOCKS` in `case_studies/model_4_simpy/compare_blocks.py`. Fill that
dictionary after running the AnyLogic Model 4 reference. Until then, inspect the
SimPy-only block counts with:

```bash
python -m case_studies.model_4_simpy.compare_blocks \
  --simpy-only
```

Run ranged parameter-variation experiments:

```bash
python -m case_studies.model_4_simpy.run_parameter_variation
```

This writes:

```text
logs/model_4_parameter_variation_range_runs.csv
logs/model_4_parameter_variation_range_summary.csv
```

The ranged experiment uses 64 SimPy combinations:

```text
main_arrival_time_s    15, 30, 45, 60
branch_arrival_time_s  15, 30, 45, 60
conveyor_speed_mps     0.5, 1.0
conveyor_gap_m         0.3, 0.6
stop time              3600 s
```

Run stochastic replications with exponential interarrival times and triangular
service times:

```bash
python -m case_studies.model_4_simpy.run_stochastic_replications \
  --replications 100 \
  --run-until 18000
```

This writes:

```text
logs/model_4_stochastic_replications_runs.csv
logs/model_4_stochastic_replications_summary.csv
```

Compare stochastic AnyLogic and SimPy replication samples:

```bash
python -m case_studies.model_4_simpy.compare_stochastic_replications \
  --anylogic "anylogic/Model 4/log_file.txt" \
  --simpy-runs logs/model_4_stochastic_replications_runs.csv \
  --output-csv logs/model_4_stochastic_comparison.csv
```

Validate the SimPy run and summary CSVs:

```bash
python -m case_studies.model_4_simpy.compare_parameter_variation_range
```

If a Model 4 AnyLogic range export is available, pass it explicitly:

```bash
python -m case_studies.model_4_simpy.compare_parameter_variation_range \
  --anylogic "anylogic/Model 4/log_file.txt"
```

Write a text or HTML comparison report when an AnyLogic export is supplied:

```bash
python -m case_studies.model_4_simpy.compare_parameter_variation_range \
  --anylogic "anylogic/Model 4/log_file.txt" \
  --view report \
  --top 25 \
  --output logs/model_4_parameter_variation_range_report.html
```

Accepted Model 4 summary `--metric` values:

```text
created
completed
avg_wip
avg_time_in_system_s
throughput_per_hour
main_created
branch_created
main_completed
branch_completed
main_conveyor_entered
main_conveyor_exited
main_conveyor_occupancy_end
branch_conveyor_entered
branch_conveyor_exited
branch_conveyor_occupancy_end
spur_transferred
spur_remaining_main_distance_m
```

Run conveyor spur animation:

```bash
python -m case_studies.model_4_simpy.run_model_animation
```

The animation shows the main conveyor, branch conveyor, and `ConveyorSpur`
merge point. Branch pallets leave the branch line inside `branchConvey`, enter
the main line at `spur_merge_offset_m`, and then continue to the shared
`downstreamService`.

### Model 5

Run model and print summary plus forklift benchmark rows:

```bash
python -m case_studies.model_5_simpy.run_model
```

Export the forklift benchmark table as CSV:

```bash
python -m case_studies.model_5_simpy.run_model --csv logs/model_5_forklift_benchmarks.csv
```

Compare AnyLogic vs SimPy block counts:

```bash
python -m case_studies.model_5_simpy.compare_blocks
```

Compare an AnyLogic benchmark text export against fresh SimPy runs:

```bash
python -m case_studies.model_5_simpy.compare_benchmark_results --anylogic logs/anylogic_model_5_forklift_timing.txt --csv logs/model_5_benchmark_comparison.csv
```

Run parameter-variation validation experiments:

```bash
python -m case_studies.model_5_simpy.run_parameter_variation
```

Compare AnyLogic vs SimPy parameter-variation range outputs:

```bash
python -m case_studies.model_5_simpy.compare_parameter_variation_range --view overview
```

Run animation:

```bash
python -m case_studies.model_5_simpy.run_model_animation
```
