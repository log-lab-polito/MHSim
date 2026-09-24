"""Regenerate SimPy results and AnyLogic parity comparisons for every model.

The AnyLogic side cannot be automated: the installed edition is AnyLogic 8 PLE,
which ships no headless runner and no standalone-export plugin, so every
AnyLogic experiment has to be started by hand in the IDE. This module automates
everything around those manual runs:

* `anylogic-prepare` truncates an export before its run. Every `TextFile` in the
  `.alp` models is `WRITE_APPEND`, and the range parser turns every
  `ITERATION #n` block it finds into a row, so running on top of a stale export
  silently duplicates iterations.
* `anylogic-capture` renames the trace exports that are written as `log_file.txt`.
* `anylogic-verify` parses each export and reports block counts and duplicates.
* `simpy` and `compare` run the documented SimPy and comparison commands.

Run from the repository root, for example::

    python -m scripts.regenerate simpy --models all
    python -m scripts.regenerate compare --models all
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
MODELS = (1, 2, 3, 4, 5, 6)

ITERATION_RE = re.compile(r"^ITERATION #(\d+)(?:,\s*REPLICATION #(\d+))?\s*$")


@dataclass(frozen=True)
class Step:
    """One command in the regeneration sweep.

    Attributes:
        name: Short slug used for the per-step log file name.
        argv: Command arguments after the interpreter.
        stage: Either `simpy` (produces results) or `compare` (consumes both
            sides and writes comparison artifacts).
        tier: `core` for the parity mainline, `trace` for the trace-level
            diagnostics that depend on the special AnyLogic trace exports.
        slow: True for steps that take minutes rather than seconds.
    """

    name: str
    argv: tuple[str, ...]
    stage: str
    tier: str = "core"
    slow: bool = False


@dataclass(frozen=True)
class AnyLogicExport:
    """An export file one AnyLogic experiment has to produce.

    Attributes:
        key: Short name used on the command line.
        path: Export path relative to the repository root.
        experiment: AnyLogic experiment to run in the IDE.
        written_as: Path the model actually writes, when it differs from `path`
            and the result has to be renamed afterwards.
        setup: Model settings to apply before the run.
        expected_blocks: Number of `ITERATION` blocks a correct export holds.
    """

    key: str
    path: Path
    experiment: str
    written_as: Path | None = None
    setup: tuple[str, ...] = ()
    expected_blocks: int | None = None


def _anylogic(model: int, filename: str) -> Path:
    return Path("anylogic") / f"Model {model}" / filename


ANYLOGIC_EXPORTS: dict[int, tuple[AnyLogicExport, ...]] = {
    1: (
        AnyLogicExport(
            key="range",
            path=_anylogic(1, "log_file.txt"),
            experiment="SensitivityAnalysis",
            expected_blocks=64,
        ),
        AnyLogicExport(
            key="stochastic",
            path=_anylogic(1, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=3200,
        ),
        AnyLogicExport(
            key="movement",
            path=_anylogic(1, "log_file_movement_trace.txt"),
            experiment="Simulation",
            written_as=_anylogic(1, "log_file.txt"),
            setup=(
                (
                    "nothing to change: the Simulation experiment already runs "
                    "arrival_rate_s = 120, displacement_m = 40, 3600 s, with "
                    "the enable_cyclic_logger default of true"
                ),
            ),
            expected_blocks=1,
        ),
    ),
    2: (
        AnyLogicExport(
            key="range",
            path=_anylogic(2, "log_file.txt"),
            experiment="SensitivityAnalysis",
            expected_blocks=36,
        ),
        AnyLogicExport(
            key="stochastic",
            path=_anylogic(2, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=1800,
        ),
    ),
    3: (
        AnyLogicExport(
            key="range",
            path=_anylogic(3, "log_file.txt"),
            experiment="SensitivityAnalysis",
            expected_blocks=64,
        ),
        AnyLogicExport(
            key="stochastic",
            path=_anylogic(3, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=3200,
        ),
    ),
    4: (
        AnyLogicExport(
            key="range",
            path=_anylogic(4, "log_file.txt"),
            experiment="SensitivityAnalysis",
            setup=(
                (
                    "trace_enabled = false on Main (it defaults to true, which "
                    "would append ~50k TRACE rows for iteration 1)"
                ),
            ),
            expected_blocks=64,
        ),
        AnyLogicExport(
            key="stochastic",
            # The committed export holds 6400 blocks because it predates the
            # model's change to 50 replications per iteration. The comparison
            # caps at 50 per iteration, so 3200 is sufficient and current.
            path=_anylogic(4, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=3200,
        ),
        AnyLogicExport(
            key="trace",
            path=_anylogic(4, "log_file_trace.txt"),
            experiment="Simulation",
            written_as=_anylogic(4, "log_file.txt"),
            setup=(
                (
                    "trace_enabled = true and trace_iteration = 1 on Main "
                    "(both are the defaults; Simulation sets iteration = 1)"
                ),
            ),
            expected_blocks=1,
        ),
    ),
    5: (
        AnyLogicExport(
            key="range",
            path=_anylogic(5, "log_file.txt"),
            experiment="SensitivityAnalysis",
            expected_blocks=36,
        ),
        AnyLogicExport(
            key="stochastic",
            path=_anylogic(5, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=1800,
        ),
    ),
    6: (
        AnyLogicExport(
            key="range",
            path=_anylogic(6, "log_file.txt"),
            experiment="SensitivityAnalysis",
            expected_blocks=2,
        ),
        AnyLogicExport(
            key="stochastic",
            path=_anylogic(6, "log_file_stochastic.txt"),
            experiment="StochasticAnalysis",
            expected_blocks=200,
        ),
        # Model 6 writes both trace files from DestroyCode on both branches, so
        # SensitivityAnalysis appends 2 deterministic blocks and
        # StochasticAnalysis appends 200 replication blocks. A complete export
        # is the sum of one of each, in that order, which is why these have to
        # be truncated before the range run rather than before the stochastic
        # one. `compare_flow_trace` reads the deterministic blocks and
        # `compare_rng_trace --replication` reads the replication blocks.
        AnyLogicExport(
            key="diagnostic",
            path=_anylogic(6, "model_6_diagnostic_trace.txt"),
            experiment="SensitivityAnalysis, then StochasticAnalysis",
            setup=("truncate before the range run; both runs append to it",),
            expected_blocks=202,
        ),
        AnyLogicExport(
            key="flow-debug",
            path=_anylogic(6, "model_6_flow_debug_trace.txt"),
            experiment="SensitivityAnalysis, then StochasticAnalysis",
            setup=("truncate before the range run; both runs append to it",),
            expected_blocks=202,
        ),
    ),
}


def _module(model: int, name: str) -> str:
    return f"case_studies.model_{model}_simpy.{name}"


def _range_report_steps(model: int, *, metric: str | None = None) -> list[Step]:
    """Build the console overview plus the HTML range report for one model."""
    anylogic = str(_anylogic(model, "log_file.txt"))
    overview = [
        "-m",
        _module(model, "analysis.compare_parameter_variation_range"),
        "--anylogic",
        anylogic,
        "--view",
        "overview",
    ]
    report = [
        "-m",
        _module(model, "analysis.compare_parameter_variation_range"),
        "--anylogic",
        anylogic,
        "--view",
        "report",
        "--top",
        "25",
        "--output",
        f"logs/model_{model}_parameter_variation_range_report.html",
    ]
    if metric is not None:
        overview += ["--metric", metric]
        report += ["--metric", metric]
    return [
        Step(f"m{model}_range_overview", tuple(overview), "compare"),
        Step(f"m{model}_range_report_html", tuple(report), "compare"),
    ]


def _stochastic_compare_step(model: int) -> Step:
    return Step(
        f"m{model}_stochastic_compare",
        (
            "-m",
            _module(model, "analysis.compare_stochastic_replications"),
            "--anylogic",
            str(_anylogic(model, "log_file_stochastic.txt")),
            "--simpy-runs",
            f"logs/model_{model}_stochastic_replications_runs.csv",
            "--output-csv",
            f"logs/model_{model}_stochastic_comparison.csv",
        ),
        "compare",
    )


def _benchmark_steps(model: int) -> list[Step]:
    """Forklift benchmark export and its AnyLogic comparison."""
    return [
        Step(
            f"m{model}_run_model",
            (
                "-m",
                _module(model, "run_model"),
                "--csv",
                f"logs/model_{model}_forklift_benchmarks.csv",
            ),
            "simpy",
        ),
        Step(
            f"m{model}_benchmark_compare",
            (
                "-m",
                _module(model, "analysis.compare_benchmark_results"),
                "--anylogic",
                str(_anylogic(model, "log_file.txt")),
                "--csv",
                f"logs/model_{model}_benchmark_comparison.csv",
            ),
            "compare",
        ),
    ]


def build_steps(model: int) -> list[Step]:
    """Return the ordered regeneration steps for one model."""
    steps: list[Step] = []

    if model in (1, 2, 5):
        steps += _benchmark_steps(model)
    else:
        steps.append(
            Step(f"m{model}_run_model", ("-m", _module(model, "run_model")), "simpy")
        )

    if model in (3, 4, 5):
        steps.append(
            Step(
                f"m{model}_compare_blocks",
                ("-m", _module(model, "analysis.compare_blocks")),
                "compare",
            )
        )

    steps.append(
        Step(
            f"m{model}_parameter_variation",
            ("-m", _module(model, "run_parameter_variation")),
            "simpy",
            slow=True,
        )
    )
    steps += _range_report_steps(
        model, metric="benchmark_avg_only" if model == 1 else None
    )

    # Flags mirror README_simpy_models.md so the sweep reproduces the
    # documented artifacts rather than a second, undocumented configuration.
    stochastic: list[str] = ["-m", _module(model, "run_stochastic_replications")]
    if model in (3, 4):
        stochastic += ["--replications", "100", "--run-until", "18000"]
    elif model in (2, 5, 6):
        stochastic += ["--workers", "auto"]
    steps.append(
        Step(f"m{model}_stochastic", tuple(stochastic), "simpy", slow=True)
    )
    steps.append(_stochastic_compare_step(model))

    if model == 1:
        steps.append(
            Step(
                "m1_range_report_text",
                (
                    "-m",
                    _module(1, "analysis.compare_parameter_variation_range"),
                    "--anylogic",
                    str(_anylogic(1, "log_file.txt")),
                    "--view",
                    "report",
                    "--metric",
                    "benchmark_avg_only",
                    "--top",
                    "25",
                    "--output",
                    "logs/model_1_parameter_variation_range_report.txt",
                ),
                "compare",
            )
        )
        steps.append(
            Step(
                "m1_movement_trace",
                ("-m", _module(1, "analysis.compare_movement_trace")),
                "compare",
                tier="trace",
            )
        )

    if model == 4:
        steps.append(
            Step(
                "m4_trace_csv",
                (
                    "-m",
                    _module(4, "run_model"),
                    "--trace-csv",
                    "logs/model_4_trace.csv",
                ),
                "simpy",
                tier="trace",
            )
        )
        steps.append(
            Step(
                "m4_compare_trace",
                (
                    "-m",
                    _module(4, "analysis.compare_trace"),
                    "--anylogic",
                    str(_anylogic(4, "log_file_trace.txt")),
                ),
                "compare",
                tier="trace",
            )
        )
        steps.append(
            Step(
                "m4_trace_diagnostics",
                (
                    "-m",
                    _module(4, "analysis.analyze_trace_diagnostics"),
                    "--anylogic",
                    str(_anylogic(4, "log_file_trace.txt")),
                ),
                "compare",
                tier="trace",
            )
        )

    if model == 5:
        steps.append(
            Step(
                "m5_compare_blocks_cases",
                (
                    "-m",
                    _module(5, "analysis.compare_blocks_cases"),
                    "--output",
                    "logs/model_5_compare_blocks_cases.csv",
                ),
                "compare",
                slow=True,
            )
        )

    if model == 6:
        steps.append(
            Step(
                "m6_flow_trace",
                (
                    "-m",
                    _module(6, "analysis.compare_flow_trace"),
                    "--run-until",
                    "300",
                    "--trace-limit",
                    "200",
                    "--compare-limit",
                    "50",
                    "--replay",
                ),
                "compare",
                tier="trace",
            )
        )
        steps.append(
            Step(
                "m6_rng_trace",
                ("-m", _module(6, "analysis.compare_rng_trace")),
                "compare",
                tier="trace",
            )
        )

    return steps


def parse_models(raw: str | list[str]) -> tuple[int, ...]:
    """Parse a `--models` value such as `all`, `1 2 5`, or `1,2,5`."""
    text = " ".join(raw) if isinstance(raw, list) else raw
    if text.strip().lower() == "all":
        return MODELS
    values = tuple(int(part) for part in text.replace(",", " ").split())
    unknown = [value for value in values if value not in MODELS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown models: {unknown}")
    return values


def _interpreter() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    print(
        f"warning: {VENV_PYTHON} not found, falling back to {sys.executable}",
        file=sys.stderr,
    )
    return sys.executable


def run_steps(steps: list[Step], *, log_dir: Path, dry_run: bool, keep_going: bool) -> int:
    """Run steps in order, tee-ing each one into its own log file."""
    interpreter = _interpreter()
    failures: list[str] = []

    if dry_run:
        for index, step in enumerate(steps, start=1):
            marker = " [slow]" if step.slow else ""
            print(f"{index:02d} {step.name}{marker}: python {' '.join(step.argv)}")
        return 0

    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"logging to {log_dir}")
    started = time.monotonic()

    for index, step in enumerate(steps, start=1):
        log_path = log_dir / f"{index:02d}_{step.name}.log"
        label = f"[{index:02d}/{len(steps)}] {step.name}"
        print(f"{label} ...", flush=True)
        step_started = time.monotonic()
        with log_path.open("w") as handle:
            handle.write(f"$ python {' '.join(step.argv)}\n\n")
            handle.flush()
            completed = subprocess.run(
                [interpreter, *step.argv],
                cwd=REPO_ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        elapsed = time.monotonic() - step_started
        if completed.returncode == 0:
            print(f"{label} ok ({elapsed:.1f}s)")
            continue
        failures.append(step.name)
        print(
            f"{label} FAILED rc={completed.returncode} ({elapsed:.1f}s) -> {log_path}",
            file=sys.stderr,
        )
        if not keep_going:
            return 1

    print(f"\ntotal {time.monotonic() - started:.1f}s")
    if failures:
        print(f"failed steps: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout


def _git_is_dirty(path: Path) -> bool:
    return bool(_git("status", "--porcelain", "--", str(path)).strip())


def _lfs_content_missing(path: Path) -> bool:
    """True when `path` is LFS-tracked but its object is not available locally.

    Most AnyLogic exports are Git LFS objects. Restoring one after a truncation
    needs the object in the local store, so a pointer-only file has no offline
    copy to fall back on.
    """
    relative = path.relative_to(REPO_ROOT).as_posix()
    for line in _git("lfs", "ls-files").splitlines():
        # Format: "<oid> <marker> <path>", marker "*" local, "-" pointer only.
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[2] == relative:
            return parts[1] != "*"
    return False


def summarize_export(path: Path) -> tuple[int, list[int]]:
    """Return the block count and the iteration numbers seen more than expected."""
    counts: Counter[tuple[int, int | None]] = Counter()
    blocks = 0
    with path.open(errors="replace") as handle:
        for line in handle:
            match = ITERATION_RE.match(line.rstrip("\n"))
            if match is None:
                continue
            blocks += 1
            iteration = int(match.group(1))
            replication = int(match.group(2)) if match.group(2) else None
            counts[(iteration, replication)] += 1
    duplicates = sorted({key[0] for key, count in counts.items() if count > 1})
    return blocks, duplicates


def cmd_prepare(args: argparse.Namespace) -> int:
    """Truncate the export an upcoming AnyLogic run will append to."""
    exports = _select_exports(args.model, args.target)
    if not exports:
        return 1

    for export in exports:
        target = REPO_ROOT / (export.written_as or export.path)
        if not target.exists():
            print(f"note: {target} does not exist yet; AnyLogic will create it")
        elif _git_is_dirty(target) and not args.force:
            print(
                f"refusing to truncate {target}: it has uncommitted changes, so git "
                "holds no recoverable copy. Commit or restore it first, or pass --force.",
                file=sys.stderr,
            )
            return 1
        elif _lfs_content_missing(target) and not args.force:
            print(
                f"refusing to truncate {target}: it is an LFS pointer with no local "
                "object, so it could not be restored. Run `git lfs pull` first.",
                file=sys.stderr,
            )
            return 1
        else:
            target.write_text("")
            print(f"truncated {target}")

        print(f"\nNow run in AnyLogic: Model {args.model} -> {export.experiment}")
        for line in export.setup:
            print(f"  set: {line}")
        if export.written_as is not None:
            print(
                f"  the model writes {export.written_as}; afterwards run:\n"
                f"    python -m scripts.regenerate anylogic-capture "
                f"--model {args.model} --target {export.key}"
            )
        if export.expected_blocks is not None:
            print(f"  expect {export.expected_blocks} ITERATION blocks")
        print()
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    """Move a trace export written as `log_file.txt` to its final name."""
    exports = [
        export
        for export in _select_exports(args.model, args.target)
        if export.written_as is not None
    ]
    if not exports:
        print(
            f"model {args.model} target {args.target} is written directly; "
            "nothing to capture",
            file=sys.stderr,
        )
        return 1

    for export in exports:
        source = REPO_ROOT / export.written_as
        destination = REPO_ROOT / export.path
        if not source.exists() or not source.stat().st_size:
            print(f"{source} is missing or empty; run the experiment first", file=sys.stderr)
            return 1
        destination.write_bytes(source.read_bytes())
        # Restore the scratch file from git rather than leaving it empty: an
        # empty file counts as an uncommitted change, which would then block
        # `anylogic-prepare` on the export that legitimately writes there next.
        # Restore from HEAD, not from the index: writing a filtered file (every
        # log_file.txt is a Git LFS object) can leave the index holding the new
        # content, in which case an index-based checkout restores nothing.
        tracked = bool(_git("ls-files", "--error-unmatch", "--", str(source)).strip())
        if tracked:
            _git("checkout", "HEAD", "--", str(source))
            if _git_is_dirty(source):
                print(
                    f"captured {destination}, but {source} could not be restored "
                    "from HEAD. Restore it yourself before the next prepare.",
                    file=sys.stderr,
                )
                return 1
            restored = "restored from HEAD"
        else:
            source.write_text("")
            restored = "cleared"
        blocks, duplicates = summarize_export(destination)
        print(f"captured {destination} ({blocks} blocks); {source.name} {restored}")
        if duplicates:
            print(f"  warning: repeated iterations {duplicates}", file=sys.stderr)
    return 0


def _select_exports(model: int, target: str) -> list[AnyLogicExport]:
    exports = ANYLOGIC_EXPORTS[model]
    if target == "all":
        return list(exports)
    matches = [export for export in exports if export.key == target]
    if not matches:
        keys = ", ".join(export.key for export in exports)
        print(
            f"model {model} has no target {target!r}; available: {keys}",
            file=sys.stderr,
        )
    return matches


def cmd_verify(args: argparse.Namespace) -> int:
    """Report block counts and duplicate iterations for the AnyLogic exports."""
    status = 0
    for model in parse_models(args.models):
        print(f"--- Model {model} ---")
        for export in ANYLOGIC_EXPORTS[model]:
            path = REPO_ROOT / export.path
            if not path.exists():
                print(f"  {export.key:<11} MISSING {export.path}")
                status = 1
                continue
            blocks, duplicates = summarize_export(path)
            age = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
            note = ""
            if export.expected_blocks is not None and blocks != export.expected_blocks:
                note = f"  EXPECTED {export.expected_blocks}"
                status = 1
            if duplicates:
                note += f"  DUPLICATE ITERATIONS {duplicates[:5]}"
                status = 1
            print(f"  {export.key:<11} {blocks:>6} blocks  {age}{note}")
    return status


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run the SimPy, comparison, or full sweep for the selected models."""
    stages = {"simpy": ("simpy",), "compare": ("compare",), "all": ("simpy", "compare")}[
        args.command
    ]
    models = parse_models(args.models)
    steps = [
        step
        for model in models
        for step in build_steps(model)
        if step.stage in stages
        and (args.tier == "all" or step.tier == args.tier)
        and not (args.skip_slow and step.slow)
        and (args.only is None or args.only in step.name)
    ]
    if not steps:
        print("no steps selected", file=sys.stderr)
        return 1
    return run_steps(
        steps,
        log_dir=REPO_ROOT / args.log_dir,
        dry_run=args.dry_run,
        keep_going=args.continue_on_error,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.regenerate",
        description="Regenerate MHSim results and AnyLogic parity comparisons.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    default_log_dir = f"logs/regeneration_{datetime.now().astimezone():%Y%m%d_%H%M%S}"

    for name, help_text in (
        ("simpy", "Run the SimPy result-producing commands."),
        ("compare", "Run the comparison commands against the AnyLogic exports."),
        ("all", "Run the SimPy commands and then the comparisons."),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--models", nargs="+", default=["all"])
        sub.add_argument(
            "--tier",
            choices=("all", "core", "trace"),
            default="all",
            help="Limit to the core parity steps or the trace-level diagnostics.",
        )
        sub.add_argument("--log-dir", default=default_log_dir)
        sub.add_argument("--only", help="Run only steps whose name contains this text.")
        sub.add_argument("--skip-slow", action="store_true")
        sub.add_argument("--dry-run", action="store_true")
        sub.add_argument("--continue-on-error", action="store_true")
        sub.set_defaults(handler=cmd_sweep)

    prepare = subparsers.add_parser(
        "anylogic-prepare",
        help="Truncate an AnyLogic export before its manual run and print the checklist.",
    )
    prepare.add_argument("--model", type=int, choices=MODELS, required=True)
    prepare.add_argument("--target", default="all")
    prepare.add_argument(
        "--force",
        action="store_true",
        help="Truncate even when the export has uncommitted changes.",
    )
    prepare.set_defaults(handler=cmd_prepare)

    capture = subparsers.add_parser(
        "anylogic-capture",
        help="Rename a trace export that AnyLogic wrote as log_file.txt.",
    )
    capture.add_argument("--model", type=int, choices=MODELS, required=True)
    capture.add_argument("--target", required=True)
    capture.set_defaults(handler=cmd_capture)

    verify = subparsers.add_parser(
        "anylogic-verify", help="Check the AnyLogic exports for size and duplicates."
    )
    verify.add_argument("--models", nargs="+", default=["all"])
    verify.set_defaults(handler=cmd_verify)

    return parser


def main() -> int:
    """Entry point."""
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
