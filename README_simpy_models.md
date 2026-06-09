# MHSim SimPy Models: Run Guide

This guide lists runnable commands for the active SimPy packages:

- `case_studies/model_1_simpy`
- `case_studies/model_2_simpy`
- `case_studies/model_3_simpy`
- `case_studies/model_4_simpy`
- `case_studies/model_5_simpy`
- `case_studies/model_6_simpy`
- shared support under `mhsim`

Run commands from the repository root. Activate `.venv` first, or replace `python` with `.venv/bin/python`. Do not use system Python for project commands.

## What Each Package Is

- `mhsim`: shared simulation library primitives for movement, routing, traffic, forklift behavior, blocks, conveyor behavior, storage logic, stats, reporting, random durations, experiments, stochastic replications, range comparison, visualization, and logging.
- `case_studies/model_1_simpy`: simplified single-move transporter reference matching AnyLogic Model 1.
- `case_studies/model_2_simpy`: simplified transporter-validation flow built around `MoveByTransporterBlock`.
- `case_studies/model_3_simpy`: conveyor reference model.
- `case_studies/model_4_simpy`: conveyor spur/merge reference model.
- `case_studies/model_5_simpy`: parameterized warehouse model with `Store` and `Retrieve`; canonical warehouse topology.
- `case_studies/model_6_simpy`: AnyLogic-mirrored conveyor batching model with pallet unbatching, loose item batching, and explicit conveyor markup.

## AnyLogic Mapping

- SimPy Model 1 validates against `anylogic/Model 1`.
- SimPy Model 2 validates against `anylogic/Model 2`.
- SimPy Model 3 validates against `anylogic/Model 3`.
- SimPy Model 4 validates against `anylogic/Model 4`.
- SimPy Model 5 validates against `anylogic/Model 5`.
- SimPy Model 6 validates against `anylogic/Model 6`.

## Prerequisites

Install core dependencies:

```bash
python -m pip install -r mhsim/core_requirements.txt
```

For animation scripts, also install:

```bash
python -m pip install -r mhsim/anim_requirements.txt
```

## Model 1

Purpose: `Source -> moveByTransporter -> Sink` single-move transporter validation.

Run model:

```bash
python -m case_studies.model_1_simpy.run_model
```

Export forklift benchmark CSV:

```bash
python -m case_studies.model_1_simpy.run_model --csv logs/model_1_forklift_benchmarks.csv
```

Compare forklift benchmark text export:

```bash
python -m case_studies.model_1_simpy.analysis.compare_benchmark_results \
  --anylogic "anylogic/Model 1/log_file.txt" \
  --csv logs/model_1_benchmark_comparison.csv
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_1_simpy.run_parameter_variation
```

Run a return-home policy variation artifact:

```bash
python -m case_studies.model_1_simpy.run_parameter_variation \
  --forklift-return-home-policy idle \
  --output-prefix model_1_release_policy_idle_parameter_variation_range
```

Compare parameter variation:

```bash
python -m case_studies.model_1_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 1/log_file.txt" \
  --view overview
```

Write text report:

```bash
python -m case_studies.model_1_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 1/log_file.txt" \
  --view report \
  --metric benchmark_avg_only \
  --top 25 \
  --output logs/model_1_parameter_variation_range_report.txt
```

Write HTML report:

```bash
python -m case_studies.model_1_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 1/log_file.txt" \
  --view report \
  --metric benchmark_avg_only \
  --top 25 \
  --output logs/model_1_parameter_variation_range_report.html
```

Run stochastic replications:

```bash
python -m case_studies.model_1_simpy.run_stochastic_replications
```

Compare stochastic replications:

```bash
python -m case_studies.model_1_simpy.analysis.compare_stochastic_replications \
  --anylogic "anylogic/Model 1/log_file_stochastic.txt" \
  --simpy-runs logs/model_1_stochastic_replications_runs.csv \
  --output-csv logs/model_1_stochastic_comparison.csv
```

Run animation:

```bash
python -m case_studies.model_1_simpy.run_model_animation \
  --sim-time 5 \
  --fps 1 \
  --record-fps 1 \
  --no-show
```

Compare cyclic movement trace:

```bash
python -m case_studies.model_1_simpy.analysis.compare_movement_trace
```

Optional parity-step diff:

```bash
python -m case_studies.model_1_simpy.analysis.compare_parity_step baseline current
```

Optional return-home policy candidate evaluation:

```bash
python -m case_studies.model_1_simpy.analysis.evaluate_release_policy_candidates
```

Animate AnyLogic range trace against SimPy:

```bash
python -m case_studies.model_1_simpy.run_range_trace_animation \
  --arrival-rate-s 60 \
  --forklift-max-speed 20 \
  --forklift-acceleration 1 \
  --displacement-m 100 \
  --no-apply-displacement-geometry
```

Common outputs:

```text
logs/model_1_forklift_benchmarks.csv
logs/model_1_benchmark_comparison.csv
logs/model_1_parameter_variation_range_runs.csv
logs/model_1_parameter_variation_range_summary.csv
logs/model_1_parameter_variation_range_report.txt
logs/model_1_parameter_variation_range_report.html
logs/model_1_stochastic_replications_runs.csv
logs/model_1_stochastic_replications_summary.csv
logs/model_1_stochastic_comparison.csv
logs/model_1_parity_<step>_benchmark_comparison.csv
logs/model_1_parity_<step>_parameter_variation_range_runs.csv
logs/model_1_parity_<step>_parameter_variation_range_summary.csv
logs/model_1_release_policy_<policy>_parameter_variation_range_runs.csv
logs/model_1_release_policy_<policy>_parameter_variation_range_summary.csv
```

Benchmark prefix: `move`.

## Model 2

Purpose: simplified transporter-validation flow around two `MoveByTransporterBlock` instances.

Run model:

```bash
python -m case_studies.model_2_simpy.run_model
```

Export forklift benchmark CSV:

```bash
python -m case_studies.model_2_simpy.run_model --csv logs/model_2_forklift_benchmarks.csv
```

Compare forklift benchmark text export:

```bash
python -m case_studies.model_2_simpy.analysis.compare_benchmark_results \
  --anylogic "anylogic/Model 2/log_file.txt" \
  --csv logs/model_2_benchmark_comparison.csv
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_2_simpy.run_parameter_variation
```

Compare parameter variation:

```bash
python -m case_studies.model_2_simpy.analysis.compare_parameter_variation_range --view overview
```

Show benchmark offenders:

```bash
python -m case_studies.model_2_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 2/log_file.txt" \
  --view offenders \
  --metric benchmark_avg_only \
  --top 10
```

Write HTML report:

```bash
python -m case_studies.model_2_simpy.analysis.compare_parameter_variation_range \
  --view report \
  --top 25 \
  --output logs/model_2_parameter_variation_range_report.html
```

Run stochastic replications:

```bash
python -m case_studies.model_2_simpy.run_stochastic_replications --workers auto
```

Expected runtime: this is a full stochastic parity run; `--workers auto` keeps the parity defaults but uses local CPU workers.

Compare stochastic replications:

```bash
python -m case_studies.model_2_simpy.analysis.compare_stochastic_replications \
  --anylogic "anylogic/Model 2/log_file_stochastic.txt" \
  --simpy-runs logs/model_2_stochastic_replications_runs.csv \
  --output-csv logs/model_2_stochastic_comparison.csv
```

Run animation:

```bash
python -m case_studies.model_2_simpy.run_model_animation \
  --sim-time 5 \
  --fps 1 \
  --record-fps 1 \
  --no-show
```

Optional parity-step diff:

```bash
python -m case_studies.model_2_simpy.analysis.compare_parity_step baseline current
```

Optional release-policy candidate evaluation:

```bash
python -m case_studies.model_2_simpy.analysis.evaluate_release_policy_candidates
```

Common outputs:

```text
logs/model_2_forklift_benchmarks.csv
logs/model_2_benchmark_comparison.csv
logs/model_2_parameter_variation_range_runs.csv
logs/model_2_parameter_variation_range_summary.csv
logs/model_2_parameter_variation_range_report.html
logs/model_2_stochastic_replications_runs.csv
logs/model_2_stochastic_replications_summary.csv
logs/model_2_stochastic_comparison.csv
logs/model_2_parity_<step>_benchmark_comparison.csv
logs/model_2_parity_<step>_parameter_variation_range_runs.csv
logs/model_2_parity_<step>_parameter_variation_range_summary.csv
logs/model_2_release_policy_<candidate>_parameter_variation_range_runs.csv
logs/model_2_release_policy_<candidate>_parameter_variation_range_summary.csv
```

Important note: Model 2 uses `arrival_rate_s` as an interarrival interval in seconds. It also uses line-guided routed motion defaults with per-leg movement overrides.

## Model 3

Purpose: conveyor reference model.

Run model:

```bash
python -m case_studies.model_3_simpy.run_model
```

Run shorter model:

```bash
python -m case_studies.model_3_simpy.run_model --sim-time 600
```

Compare block counts:

```bash
python -m case_studies.model_3_simpy.analysis.compare_blocks
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_3_simpy.run_parameter_variation
```

Compare parameter variation:

```bash
python -m case_studies.model_3_simpy.analysis.compare_parameter_variation_range
```

Show matrix:

```bash
python -m case_studies.model_3_simpy.analysis.compare_parameter_variation_range \
  --view matrix \
  --metric avg_time_in_system_s
```

Write HTML report:

```bash
python -m case_studies.model_3_simpy.analysis.compare_parameter_variation_range \
  --view report \
  --top 25 \
  --output logs/model_3_parameter_variation_range_report.html
```

Run stochastic replications:

```bash
python -m case_studies.model_3_simpy.run_stochastic_replications \
  --replications 100 \
  --run-until 18000
```

Compare stochastic replications:

```bash
python -m case_studies.model_3_simpy.analysis.compare_stochastic_replications \
  --anylogic "anylogic/Model 3/log_file_stochastic.txt" \
  --simpy-runs logs/model_3_stochastic_replications_runs.csv \
  --output-csv logs/model_3_stochastic_comparison.csv
```

Run animation:

```bash
python -m case_studies.model_3_simpy.run_model_animation \
  --sim-time 5 \
  --fps 1 \
  --record-fps 1 \
  --no-show
```

Common outputs:

```text
logs/model_3_parameter_variation_range_runs.csv
logs/model_3_parameter_variation_range_summary.csv
logs/model_3_parameter_variation_range_report.html
logs/model_3_stochastic_replications_runs.csv
logs/model_3_stochastic_replications_summary.csv
logs/model_3_stochastic_comparison.csv
```

## Model 4

Purpose: conveyor spur/merge reference model.

Run model:

```bash
python -m case_studies.model_4_simpy.run_model
```

Run shorter model:

```bash
python -m case_studies.model_4_simpy.run_model --sim-time 600
```

Write event trace:

```bash
python -m case_studies.model_4_simpy.run_model --trace-csv logs/model_4_trace.csv
```

Compare block counts:

```bash
python -m case_studies.model_4_simpy.analysis.compare_blocks
```

Show fresh SimPy block counts only:

```bash
python -m case_studies.model_4_simpy.analysis.compare_blocks --simpy-only
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_4_simpy.run_parameter_variation
```

Compare parameter variation:

```bash
python -m case_studies.model_4_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 4/log_file.txt"
```

Write HTML report:

```bash
python -m case_studies.model_4_simpy.analysis.compare_parameter_variation_range \
  --anylogic "anylogic/Model 4/log_file.txt" \
  --view report \
  --top 25 \
  --output logs/model_4_parameter_variation_range_report.html
```

Run stochastic replications:

```bash
python -m case_studies.model_4_simpy.run_stochastic_replications \
  --replications 100 \
  --run-until 18000
```

Compare stochastic replications:

```bash
python -m case_studies.model_4_simpy.analysis.compare_stochastic_replications \
  --anylogic "anylogic/Model 4/log_file_stochastic.txt" \
  --simpy-runs logs/model_4_stochastic_replications_runs.csv \
  --output-csv logs/model_4_stochastic_comparison.csv
```

Compare traces:

```bash
python -m case_studies.model_4_simpy.analysis.compare_trace \
  --anylogic "anylogic/Model 4/log_file_trace.txt"
```

Analyze trace diagnostics:

```bash
python -m case_studies.model_4_simpy.analysis.analyze_trace_diagnostics \
  --anylogic "anylogic/Model 4/log_file_trace.txt"
```

Run animation:

```bash
python -m case_studies.model_4_simpy.run_model_animation \
  --sim-time 5 \
  --fps 1 \
  --record-fps 1 \
  --no-show
```

Common outputs:

```text
logs/model_4_parameter_variation_range_runs.csv
logs/model_4_parameter_variation_range_summary.csv
logs/model_4_parameter_variation_range_report.html
logs/model_4_stochastic_replications_runs.csv
logs/model_4_stochastic_replications_summary.csv
logs/model_4_stochastic_comparison.csv
```

## Model 5

Purpose: canonical parameterized warehouse flow.

Run model:

```bash
python -m case_studies.model_5_simpy.run_model
```

Export forklift benchmark CSV:

```bash
python -m case_studies.model_5_simpy.run_model --csv logs/model_5_forklift_benchmarks.csv
```

Compare block counts:

```bash
python -m case_studies.model_5_simpy.analysis.compare_blocks
```

Compare forklift benchmark text export:

```bash
python -m case_studies.model_5_simpy.analysis.compare_benchmark_results \
  --anylogic "anylogic/Model 5/log_file.txt" \
  --csv logs/model_5_benchmark_comparison.csv
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_5_simpy.run_parameter_variation
```

Compare parameter variation:

```bash
python -m case_studies.model_5_simpy.analysis.compare_parameter_variation_range --view overview
```

Write HTML report:

```bash
python -m case_studies.model_5_simpy.analysis.compare_parameter_variation_range \
  --view report \
  --top 25 \
  --output logs/model_5_parameter_variation_range_report.html
```

Run policy-sweep block comparison:

```bash
python -m case_studies.model_5_simpy.analysis.compare_blocks_cases
```

Run stochastic replications:

```bash
python -m case_studies.model_5_simpy.run_stochastic_replications --workers auto
```

Expected runtime: this is a full stochastic parity run; `--workers auto` keeps the parity defaults but uses local CPU workers.

Compare stochastic replications:

```bash
python -m case_studies.model_5_simpy.analysis.compare_stochastic_replications \
  --anylogic "anylogic/Model 5/log_file_stochastic.txt" \
  --simpy-runs logs/model_5_stochastic_replications_runs.csv \
  --output-csv logs/model_5_stochastic_comparison.csv
```

Run animation:

```bash
python -m case_studies.model_5_simpy.run_model_animation \
  --sim-time 5 \
  --fps 1 \
  --record-fps 1 \
  --no-show
```

Common outputs:

```text
logs/model_5_forklift_benchmarks.csv
logs/model_5_benchmark_comparison.csv
logs/model_5_parameter_variation_range_runs.csv
logs/model_5_parameter_variation_range_summary.csv
logs/model_5_parameter_variation_range_report.html
logs/model_5_compare_blocks_cases.csv
logs/model_5_stochastic_replications_runs.csv
logs/model_5_stochastic_replications_summary.csv
logs/model_5_stochastic_comparison.csv
```

## Model 6

Purpose: AnyLogic-mirrored conveyor batching flow with explicit conveyor network, positions, stations, spur, manual sources, and permanent batching.

Range workflows keep arrival interval, conveyor speed, and conveyor gap fixed at the current AnyLogic Model 6 parity values, and vary `max_items_per_pallet` over `10, 20`; `min_items_per_pallet` defaults to `5`.

Run model:

```bash
python -m case_studies.model_6_simpy.run_model
```

Run deterministic parameter variation:

```bash
python -m case_studies.model_6_simpy.run_parameter_variation
```

Compare parameter variation:

```bash
python -m case_studies.model_6_simpy.analysis.compare_parameter_variation_range --view overview
```

Compare the diagnostic flow trace:

```bash
python -m case_studies.model_6_simpy.analysis.compare_flow_trace --run-until 300 --trace-limit 200 --compare-limit 50 --replay
```

Add SimPy block/station context around the first mismatch:

```bash
python -m case_studies.model_6_simpy.analysis.compare_flow_trace --run-until 300 --trace-limit 300 --compare-limit 75 --replay --include-debug
```

Run stochastic replications:

```bash
python -m case_studies.model_6_simpy.run_stochastic_replications --workers auto
```

Expected runtime: this is a full stochastic parity run across the Model 6 range grid. Use `--replications` and `--run-until` for short smoke checks.

Common outputs:

```text
logs/model_6_parameter_variation_range_runs.csv
logs/model_6_parameter_variation_range_summary.csv
logs/model_6_parameter_variation_range_report.html
logs/model_6_stochastic_replications_runs.csv
logs/model_6_stochastic_replications_summary.csv
logs/model_6_stochastic_comparison.csv
```

## Shared CLI Notes

Range comparison scripts commonly support:

```text
--view overview|matrix|offenders|report|full|all
--metric all|benchmark_avg_only|<metric-name>
--top <count>
--output <path>
--format text|html
```

Exact options vary by model. Use:

```bash
python -m case_studies.model_5_simpy.analysis.compare_parameter_variation_range --help
```

Stochastic replication scripts commonly support:

```text
--output-dir
--run-until
--replications
--base-seed
--workers auto|N
--arrival-distribution deterministic|exponential|triangular
--service-distribution deterministic|exponential|triangular
--service-triangular-spread
--deterministic-arrivals
--deterministic-services
```

Use:

```bash
python -m case_studies.model_5_simpy.run_stochastic_replications --help
```

Deterministic parity defaults remain deterministic. Stochastic commands opt into random arrivals and/or services through their own params.
