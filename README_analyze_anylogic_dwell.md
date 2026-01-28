# analyze_anylogic_dwell.py — quick usage

Purpose: summarize **block durations** from event logs, and optionally **dwell periods** from AnyLogic movement logs.

## 1) AnyLogic (dwells + block durations)
Uses the current AnyLogic logs:
```bash
python3 analyze_anylogic_dwell.py \
  --movement-log "anylogic/Model 1/log_file.txt" \
  --event-log "logs/anylogic_model_1.txt"
```

## 2) SimPy (block durations only)
Use the SimPy event log and skip dwell analysis:
```bash
python3 analyze_anylogic_dwell.py \
  --event-log "logs/simpy_model1_20260128_003750.txt" \
  --label "SimPy" \
  --skip-dwell
```

## 3) Export CSV
```bash
python3 analyze_anylogic_dwell.py \
  --movement-log "anylogic/Model 1/log_file.txt" \
  --event-log "logs/anylogic_model_1.txt" \
  --csv dwell_report.csv
```

## 4) Tune dwell detection thresholds
```bash
python3 analyze_anylogic_dwell.py \
  --min-dwell 0.5 \
  --move-eps 1e-3 \
  --rot-eps 1e-3
```

## 5) Compare to expected block times
```bash
python3 analyze_anylogic_dwell.py \
  --movement-log "anylogic/Model 1/log_file.txt" \
  --event-log "logs/anylogic_model_1.txt" \
  --expected-service1 30 \
  --expected-delay 300 \
  --expected-service2 30 \
  --expected-store 1 \
  --expected-retrieve 1
```

## Log format expectations
Event log lines must look like:
```
Pallet <id> entering <blockname> block at <time>
```
Example:
```
Pallet 4609 entering service2 block at 417.52029713433194
Pallet 4609 entering sink block at 447.52029713433194
```

Notes:
- `sink` is terminal, so it will show **entries** but **no duration samples**.
