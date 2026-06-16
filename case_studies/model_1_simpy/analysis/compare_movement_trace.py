from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from ..model import Model1SimModel
from ..params import Model1Params


TRACE_LINE_RE = re.compile(r"t=([-+0-9.]+)")
POSITION_RE = re.compile(r"x=([-+0-9.]+),\s*y=([-+0-9.]+)")


@dataclass(frozen=True)
class TraceSample:
    time: float
    positions: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class StationaryRun:
    start: float
    end: float
    position: tuple[float, float]


@dataclass(frozen=True)
class TracePhases:
    movement_start: float | None
    loading_start: float | None
    loading_finish: float | None
    unloading_start: float | None
    unloading_finish: float | None

    @property
    def seize_to_loading_start(self) -> float | None:
        if self.loading_start is None:
            return None
        return self.loading_start

    @property
    def loading_finish_to_unloading_start(self) -> float | None:
        if self.loading_finish is None or self.unloading_start is None:
            return None
        return self.unloading_start - self.loading_finish


def parse_trace(path: str | Path) -> list[TraceSample]:
    samples: list[TraceSample] = []
    with Path(path).open(encoding="utf-8") as handle:
        for raw_line in handle:
            time_match = TRACE_LINE_RE.search(raw_line)
            if time_match is None:
                continue
            positions = tuple(
                (float(x), float(y)) for x, y in POSITION_RE.findall(raw_line)
            )
            if not positions:
                continue
            samples.append(
                TraceSample(time=float(time_match.group(1)), positions=positions)
            )
    return samples


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _first_position(sample: TraceSample) -> tuple[float, float]:
    return sample.positions[0]


def _stationary_runs(
    samples: list[TraceSample],
    *,
    epsilon: float = 0.02,
    min_duration_s: float = 0.5,
) -> list[StationaryRun]:
    runs: list[StationaryRun] = []
    if len(samples) < 2:
        return runs

    active_start: float | None = None
    active_position: tuple[float, float] | None = None
    for index in range(1, len(samples)):
        previous = samples[index - 1]
        current = samples[index]
        is_stationary = (
            _distance(_first_position(previous), _first_position(current)) <= epsilon
        )
        if is_stationary:
            if active_start is None:
                active_start = previous.time
                active_position = _first_position(previous)
        elif active_start is not None and active_position is not None:
            if current.time - active_start >= min_duration_s:
                runs.append(
                    StationaryRun(
                        start=active_start,
                        end=current.time,
                        position=active_position,
                    )
                )
            active_start = None
            active_position = None

    if active_start is not None and active_position is not None:
        final_time = samples[-1].time
        if final_time - active_start >= min_duration_s:
            runs.append(
                StationaryRun(
                    start=active_start,
                    end=final_time,
                    position=active_position,
                )
            )
    return runs


def infer_trace_phases(samples: list[TraceSample]) -> TracePhases:
    if not samples:
        return TracePhases(None, None, None, None, None)

    initial = _first_position(samples[0])
    movement_start = None
    for sample in samples[1:]:
        if _distance(initial, _first_position(sample)) > 0.02:
            movement_start = sample.time
            break

    dwell_runs = [
        run
        for run in _stationary_runs(samples)
        if movement_start is not None and run.start > movement_start
    ]
    loading = dwell_runs[0] if len(dwell_runs) >= 1 else None
    unloading = dwell_runs[1] if len(dwell_runs) >= 2 else None
    return TracePhases(
        movement_start=movement_start,
        loading_start=None if loading is None else loading.start,
        loading_finish=None if loading is None else loading.end,
        unloading_start=None if unloading is None else unloading.start,
        unloading_finish=None if unloading is None else unloading.end,
    )


def max_position_error(
    anylogic_samples: list[TraceSample],
    simpy_samples: list[TraceSample],
) -> float | None:
    anylogic_by_time = {
        round(sample.time, 2): _first_position(sample)
        for sample in anylogic_samples
    }
    simpy_by_time = {
        round(sample.time, 2): _first_position(sample)
        for sample in simpy_samples
    }
    common_times = sorted(set(anylogic_by_time) & set(simpy_by_time))
    if not common_times:
        return None
    return max(
        _distance(anylogic_by_time[time], simpy_by_time[time])
        for time in common_times
    )


def _interpolate_first_position(
    samples: list[TraceSample],
    time: float,
) -> tuple[float, float] | None:
    """Linearly interpolate the lead position at ``time`` within the trace span.

    Returns None outside the sampled time span. Interpolation (rather than
    rounding to a shared 0.01 s grid) keeps the per-timestep residual honest
    when the two traces are sampled on a slightly offset phase.
    """
    if not samples:
        return None
    if time < samples[0].time or time > samples[-1].time:
        return None
    # Samples are emitted in increasing time order; binary search the bracket.
    lo, hi = 0, len(samples) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if samples[mid].time < time:
            lo = mid + 1
        else:
            hi = mid
    if samples[lo].time == time or lo == 0:
        return _first_position(samples[lo])
    before = samples[lo - 1]
    after = samples[lo]
    span = after.time - before.time
    if span <= 0:
        return _first_position(after)
    frac = (time - before.time) / span
    bx, by = _first_position(before)
    ax, ay = _first_position(after)
    return (bx + (ax - bx) * frac, by + (ay - by) * frac)


@dataclass(frozen=True)
class PositionResidual:
    time: float
    anylogic: tuple[float, float]
    simpy: tuple[float, float]
    error: float


@dataclass(frozen=True)
class ResidualStats:
    count: int
    max_error: float
    max_error_time: float
    mean_error: float
    rms_error: float
    p95_error: float


def position_residual_series(
    anylogic_samples: list[TraceSample],
    simpy_samples: list[TraceSample],
) -> list[PositionResidual]:
    """Per-timestep lead-forklift position residual, SimPy vs AnyLogic.

    AnyLogic positions are interpolated onto each SimPy sample time that falls
    within the AnyLogic trace span, so the residual is a true position-vs-time
    error envelope rather than a single worst-case scalar.
    """
    residuals: list[PositionResidual] = []
    for sample in simpy_samples:
        anylogic_pos = _interpolate_first_position(anylogic_samples, sample.time)
        if anylogic_pos is None:
            continue
        simpy_pos = _first_position(sample)
        residuals.append(
            PositionResidual(
                time=sample.time,
                anylogic=anylogic_pos,
                simpy=simpy_pos,
                error=_distance(anylogic_pos, simpy_pos),
            )
        )
    return residuals


def residual_stats(residuals: list[PositionResidual]) -> ResidualStats | None:
    if not residuals:
        return None
    errors = [r.error for r in residuals]
    worst = max(residuals, key=lambda r: r.error)
    ordered = sorted(errors)
    # Nearest-rank p95.
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ResidualStats(
        count=len(errors),
        max_error=worst.error,
        max_error_time=worst.time,
        mean_error=sum(errors) / len(errors),
        rms_error=math.sqrt(sum(e * e for e in errors) / len(errors)),
        p95_error=ordered[rank],
    )


def write_residual_csv(path: str | Path, residuals: list[PositionResidual]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["t", "anylogic_x", "anylogic_y", "simpy_x", "simpy_y", "position_error"]
        )
        for r in residuals:
            writer.writerow(
                [
                    f"{r.time:.4f}",
                    f"{r.anylogic[0]:.6f}",
                    f"{r.anylogic[1]:.6f}",
                    f"{r.simpy[0]:.6f}",
                    f"{r.simpy[1]:.6f}",
                    f"{r.error:.6f}",
                ]
            )
    return output_path


def generate_simpy_trace(sim_time: float) -> Path:
    params = Model1Params()
    params.sim_time = sim_time
    params.log_filename_prefix = "simpy_model1_trace"
    model = Model1SimModel(params=params, console_logging=False, enable_logging=True)
    model.run(until=sim_time)
    if model.logger is None:
        raise RuntimeError("Model 1 trace logging was not enabled")
    return model.logger.log_file


def _format_value(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _diff(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return right - left


def _classification(
    *,
    max_error: float | None,
    anylogic_phases: TracePhases,
    simpy_phases: TracePhases,
) -> str:
    if max_error is None:
        return "no common timestamps"
    if max_error > 1.0:
        return "physical route timing mismatch"

    phase_diffs = [
        _diff(
            anylogic_phases.seize_to_loading_start,
            simpy_phases.seize_to_loading_start,
        ),
        _diff(
            anylogic_phases.loading_finish_to_unloading_start,
            simpy_phases.loading_finish_to_unloading_start,
        ),
    ]
    if any(diff is not None and abs(diff) > 0.1 for diff in phase_diffs):
        return "benchmark phase attribution mismatch"
    return "trace phases match"


def _rows(
    anylogic_phases: TracePhases,
    simpy_phases: TracePhases,
    max_error: float | None,
    classification: str,
) -> list[dict[str, str]]:
    metrics = [
        ("movement_start", anylogic_phases.movement_start, simpy_phases.movement_start),
        ("loading_start", anylogic_phases.loading_start, simpy_phases.loading_start),
        ("loading_finish", anylogic_phases.loading_finish, simpy_phases.loading_finish),
        ("unloading_start", anylogic_phases.unloading_start, simpy_phases.unloading_start),
        ("unloading_finish", anylogic_phases.unloading_finish, simpy_phases.unloading_finish),
        (
            "seize_to_loading_start_s",
            anylogic_phases.seize_to_loading_start,
            simpy_phases.seize_to_loading_start,
        ),
        (
            "loading_finish_to_unloading_start_s",
            anylogic_phases.loading_finish_to_unloading_start,
            simpy_phases.loading_finish_to_unloading_start,
        ),
        ("max_position_error", 0.0 if max_error is not None else None, max_error),
    ]
    rows: list[dict[str, str]] = []
    for metric, anylogic_value, simpy_value in metrics:
        rows.append(
            {
                "metric": metric,
                "anylogic": _format_value(anylogic_value),
                "simpy": _format_value(simpy_value),
                "diff": _format_value(_diff(anylogic_value, simpy_value)),
                "classification": classification,
            }
        )
    return rows


def write_csv(path: str | Path, rows: list[dict[str, str]]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "anylogic", "simpy", "diff", "classification"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def print_report(
    *,
    anylogic_path: Path,
    simpy_path: Path,
    rows: list[dict[str, str]],
) -> None:
    print("--- Model 1 Movement Trace Comparison ---")
    print(f"AnyLogic trace: {anylogic_path}")
    print(f"SimPy trace: {simpy_path}")
    print()
    print("metric                                  anylogic    simpy       diff        classification")
    print("-" * 96)
    for row in rows:
        print(
            f"{row['metric']:<38}"
            f"{row['anylogic']:>10}  "
            f"{row['simpy']:>10}  "
            f"{row['diff']:>10}  "
            f"{row['classification']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AnyLogic and SimPy Model 1 cyclic forklift traces."
    )
    parser.add_argument(
        "--anylogic-trace",
        default="anylogic/Model 1/log_file_movement_trace.txt",
        help="AnyLogic cyclic position trace path.",
    )
    parser.add_argument(
        "--simpy-trace",
        default=None,
        help="Optional existing SimPy cyclic position trace path.",
    )
    parser.add_argument(
        "--sim-time",
        type=float,
        default=30.0,
        help="Simulation time used when generating a fresh SimPy trace.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV output path for comparison rows.",
    )
    parser.add_argument(
        "--residual-csv",
        default=None,
        help="Optional CSV output path for the per-timestep position residual.",
    )
    parser.add_argument(
        "--max-position-error",
        type=float,
        default=None,
        help=(
            "Regression gate: exit non-zero if the max per-timestep position "
            "error (presentation units) exceeds this value."
        ),
    )
    args = parser.parse_args()

    anylogic_path = Path(args.anylogic_trace)
    if args.simpy_trace is None:
        simpy_path = generate_simpy_trace(args.sim_time)
    else:
        simpy_path = Path(args.simpy_trace)

    anylogic_samples = parse_trace(anylogic_path)
    simpy_samples = parse_trace(simpy_path)
    anylogic_phases = infer_trace_phases(anylogic_samples)
    simpy_phases = infer_trace_phases(simpy_samples)
    max_error = max_position_error(anylogic_samples, simpy_samples)
    classification = _classification(
        max_error=max_error,
        anylogic_phases=anylogic_phases,
        simpy_phases=simpy_phases,
    )
    rows = _rows(anylogic_phases, simpy_phases, max_error, classification)
    print_report(anylogic_path=anylogic_path, simpy_path=simpy_path, rows=rows)

    residuals = position_residual_series(anylogic_samples, simpy_samples)
    stats = residual_stats(residuals)
    if stats is not None:
        print()
        print("Per-timestep position residual (interpolated onto SimPy samples):")
        print(
            f"  samples={stats.count}  max={stats.max_error:.4f} @ t={stats.max_error_time:.2f}s"
            f"  mean={stats.mean_error:.4f}  rms={stats.rms_error:.4f}"
            f"  p95={stats.p95_error:.4f}"
        )

    if args.csv:
        output_path = write_csv(args.csv, rows)
        print(f"\nTrace comparison CSV: {output_path}")
    if args.residual_csv:
        residual_path = write_residual_csv(args.residual_csv, residuals)
        print(f"Per-timestep residual CSV: {residual_path}")

    if args.max_position_error is not None:
        observed = stats.max_error if stats is not None else None
        if observed is None:
            print("\nPOSITION-ERROR GATE: no overlapping samples to compare.")
            sys.exit(1)
        if observed > args.max_position_error:
            print(
                f"\nPOSITION-ERROR GATE FAILED: max residual {observed:.4f} "
                f"> {args.max_position_error:.4f} (at t={stats.max_error_time:.2f}s)."
            )
            sys.exit(1)
        print(
            f"\nPOSITION-ERROR GATE PASSED: max residual {observed:.4f} "
            f"<= {args.max_position_error:.4f}."
        )


if __name__ == "__main__":
    main()
