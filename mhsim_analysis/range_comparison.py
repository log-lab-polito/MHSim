from __future__ import annotations

import csv
import html
import io
import json
import math
import re
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RangeComparisonSpec:
    model_label: str
    parameter_fields: tuple[str, ...]
    parameter_labels: Mapping[str, str]
    parameter_short_labels: Mapping[str, str]
    metrics: tuple[tuple[str, str], ...]
    optional_metrics: tuple[tuple[str, str], ...] = ()
    benchmark_metric_labels: Mapping[str, str] = field(default_factory=dict)
    benchmark_stat_fields: tuple[tuple[str, str], ...] = ()
    benchmark_stat_display_labels: Mapping[str, str] = field(default_factory=dict)
    benchmark_avg_only_name: str = "benchmark_avg_only"
    header_note: str | None = None


@dataclass(frozen=True)
class RangeRow:
    iteration: int
    params: Mapping[str, int | float]
    metrics: Mapping[str, int | float | None]
    benchmarks: Mapping[str, Any] = field(default_factory=dict)
    replications: int | None = None
    replication: int | None = None

    def match_key(self, spec: RangeComparisonSpec) -> tuple[int | float, ...]:
        return tuple(self.params[name] for name in spec.parameter_fields)


@dataclass(frozen=True)
class ComparisonContext:
    spec: RangeComparisonSpec
    validation_issues: list[str]
    anylogic_by_key: dict[tuple[int | float, ...], RangeRow]
    simpy_by_key: dict[tuple[int | float, ...], RangeRow]
    common_keys: list[tuple[int | float, ...]]
    anylogic_only: list[tuple[int | float, ...]]
    simpy_only: list[tuple[int | float, ...]]


@dataclass(frozen=True)
class MetricComparisonRow:
    metric_name: str
    label: str
    anylogic_value: int | float
    simpy_value: int | float
    diff: float
    diff_pct: float | None
    status: str


def parse_anylogic_summary_log(
    path: str | Path,
    *,
    key_map: Mapping[str, str],
    parameter_fields: Sequence[str],
    metric_fields: Sequence[str],
    optional_metric_fields: Sequence[str] = (),
) -> list[RangeRow]:
    iteration_re = re.compile(r"^ITERATION #(\d+)(?:,\s*REPLICATION #\d+)?\s*$")
    key_value_re = re.compile(r"^\s*([^:]+):\s*(.+?)\s*$")
    rows: list[RangeRow] = []
    current_iteration: int | None = None
    current_values: dict[str, int | float] = {}

    def finalize_current() -> None:
        nonlocal current_iteration, current_values
        if current_iteration is None:
            return

        missing = [
            name
            for name in (*parameter_fields, *metric_fields)
            if name not in current_values
        ]
        if missing:
            raise ValueError(
                f"AnyLogic iteration #{current_iteration} is missing fields: "
                + ", ".join(missing)
            )

        rows.append(
            RangeRow(
                iteration=current_iteration,
                params={name: current_values[name] for name in parameter_fields},
                metrics={
                    **{name: current_values[name] for name in metric_fields},
                    **{
                        name: current_values[name]
                        for name in optional_metric_fields
                        if name in current_values
                    },
                },
            )
        )
        current_iteration = None
        current_values = {}

    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            iteration_match = iteration_re.match(line)
            if iteration_match:
                finalize_current()
                current_iteration = int(iteration_match.group(1))
                continue

            if current_iteration is None or not stripped:
                continue
            if stripped in {"PARAMETERS", "RESULTS"}:
                continue

            key_value_match = key_value_re.match(line)
            if key_value_match is None:
                continue
            raw_key, raw_value = key_value_match.groups()
            field_name = key_map.get(raw_key.strip())
            if field_name is None:
                continue
            current_values[field_name] = _parse_number(raw_value)

    finalize_current()
    return rows


def load_simpy_summary_rows(
    path: str | Path,
    spec: RangeComparisonSpec,
) -> list[RangeRow]:
    rows: list[RangeRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                RangeRow(
                    iteration=_int_field(record, "iteration"),
                    replications=_int_field(record, "replications"),
                    params={
                        name: _float_field(record, f"param_{name}")
                        for name in spec.parameter_fields
                    },
                    metrics={
                        name: _metric_number_field(record, name)
                        for name, _label in _all_metric_fields(spec)
                    },
                    benchmarks=_load_summary_benchmarks(record, spec),
                )
            )
    return rows


def load_simpy_run_rows(
    path: str | Path,
    spec: RangeComparisonSpec,
) -> list[RangeRow]:
    rows: list[RangeRow] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                RangeRow(
                    iteration=_int_field(record, "iteration"),
                    replication=_int_field(record, "replication"),
                    params={
                        name: _float_field(record, f"param_{name}")
                        for name in spec.parameter_fields
                    },
                    metrics={
                        name: _number_field(record, f"metric_{name}")
                        for name, _label in _all_metric_fields(spec)
                    },
                    benchmarks=_load_run_benchmarks(record, spec),
                )
            )
    return rows


def build_comparison_context(
    anylogic_rows: list[RangeRow],
    simpy_summary_rows: list[RangeRow],
    simpy_run_rows: list[RangeRow],
    *,
    spec: RangeComparisonSpec,
) -> ComparisonContext:
    validation_issues = validate_simpy_runs(
        simpy_summary_rows,
        simpy_run_rows,
        spec=spec,
    )
    anylogic_by_key = {row.match_key(spec): row for row in anylogic_rows}
    simpy_by_key = {row.match_key(spec): row for row in simpy_summary_rows}
    anylogic_keys = set(anylogic_by_key)
    simpy_keys = set(simpy_by_key)
    return ComparisonContext(
        spec=spec,
        validation_issues=validation_issues,
        anylogic_by_key=anylogic_by_key,
        simpy_by_key=simpy_by_key,
        common_keys=sorted(anylogic_keys & simpy_keys),
        anylogic_only=sorted(anylogic_keys - simpy_keys),
        simpy_only=sorted(simpy_keys - anylogic_keys),
    )


def validate_simpy_runs(
    summary_rows: list[RangeRow],
    run_rows: list[RangeRow],
    *,
    spec: RangeComparisonSpec,
) -> list[str]:
    issues: list[str] = []
    metrics = _available_simpy_metrics(summary_rows, run_rows, spec)
    summary_by_iteration = {row.iteration: row for row in summary_rows}
    runs_by_iteration: dict[int, list[RangeRow]] = {}
    for row in run_rows:
        runs_by_iteration.setdefault(row.iteration, []).append(row)

    for iteration, rows in sorted(runs_by_iteration.items()):
        first = rows[0]
        for other in rows[1:]:
            for field_name, _label in metrics:
                if not _values_match(
                    _metric_value(first, field_name),
                    _metric_value(other, field_name),
                ):
                    issues.append(
                        f"SimPy iteration {iteration} differs across replications "
                        f"for '{field_name}': replication {first.replication}="
                        f"{_metric_value(first, field_name)} vs replication "
                        f"{other.replication}={_metric_value(other, field_name)}"
                    )
        summary = summary_by_iteration.get(iteration)
        if summary is None:
            issues.append(f"SimPy summary is missing iteration {iteration}")
            continue
        for field_name, _label in metrics:
            if not _values_match(
                _metric_value(first, field_name),
                _metric_value(summary, field_name),
            ):
                issues.append(
                    f"SimPy summary mismatch for iteration {iteration} field "
                    f"'{field_name}': summary={_metric_value(summary, field_name)} "
                    f"runs={_metric_value(first, field_name)}"
                )
    return issues


def print_comparison_report(
    context: ComparisonContext,
    *,
    view: str,
    metric_name: str,
    top: int,
) -> None:
    _print_report_header(context)
    _print_unmatched(context)
    if not context.common_keys:
        print("\nNo common parameter combinations found.")
        return

    if view == "full":
        _print_full_view(context)
    elif view == "overview":
        _print_overview_view(context)
    elif view == "matrix":
        _print_matrix_view(context, metric_name=metric_name)
    elif view == "offenders":
        _print_offenders_view(context, metric_name=metric_name, top=top)
    elif view == "report":
        _print_report_view(context, metric_name=metric_name, top=top)
    elif view == "all":
        _print_overview_view(context)
        _print_matrix_view(context, metric_name=metric_name)
        _print_offenders_view(context, metric_name=metric_name, top=top)
        _print_full_view(context)
    else:
        raise ValueError(f"Unsupported view: {view}")


def render_comparison_report_text(
    context: ComparisonContext,
    *,
    view: str,
    metric_name: str,
    top: int,
) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        print_comparison_report(
            context,
            view=view,
            metric_name=metric_name,
            top=top,
        )
    return output.getvalue()


def render_html_report(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> str:
    title = f"{context.spec.model_label} Parameter Variation Range Report"
    overview_rows = _build_overview_rows(context)
    close_or_diff_rows = [
        row
        for row in overview_rows
        if row["close_count"] > 0 or row["diff_count"] > 0
    ]
    exact_match_metrics = [
        row["label"]
        for row in overview_rows
        if row["close_count"] == 0 and row["diff_count"] == 0
    ]
    offender_items = _build_offender_items(context, metric_name=metric_name, top=top)
    comparison_metrics = _comparison_metrics(context)
    iteration_data = []
    for anylogic, simpy in _matched_rows(context):
        metric_rows = [
            _build_metric_comparison_row(anylogic, simpy, field_name, label)
            for field_name, label in comparison_metrics
        ]
        iteration_data.append(
            {
                "label": (
                    f"AnyLogic {anylogic.iteration} / SimPy {simpy.iteration} - "
                    f"{_format_case(anylogic.match_key(context.spec), context.spec)}"
                ),
                "anylogicIteration": anylogic.iteration,
                "simpyIteration": simpy.iteration,
                "caseLabel": _format_case(anylogic.match_key(context.spec), context.spec),
                "benchmarkRows": [
                    _metric_row_json(row)
                    for row in metric_rows
                    if row.metric_name.startswith("benchmark_")
                ],
                "summaryRows": [
                    _metric_row_json(row)
                    for row in metric_rows
                    if not row.metric_name.startswith("benchmark_")
                ],
            }
        )
    iteration_json = json.dumps(iteration_data, ensure_ascii=True)

    validation_items = "".join(
        f"<li>{_html_escape(issue)}</li>"
        for issue in context.validation_issues
    )
    validation_html = (
        f"<ul>{validation_items}</ul>"
        if context.validation_issues
        else "<p class=\"pass-text\">PASS</p>"
    )
    attention_rows = "".join(
        "<tr>"
        f"<td>{_html_escape(row['label'])}</td>"
        f"<td>{row['match_count']}</td>"
        f"<td>{row['close_count']}</td>"
        f"<td>{row['diff_count']}</td>"
        f"<td>{_html_escape(_format_diff(row['worst_diff']))}</td>"
        f"<td>{_html_escape(_format_percent(row['worst_pct']))}</td>"
        f"<td>{_html_escape(_format_case(row['worst_case'], context.spec))}</td>"
        "</tr>"
        for row in close_or_diff_rows
    )
    if not attention_rows:
        attention_rows = (
            "<tr><td colspan=\"7\" class=\"empty\">No CLOSE or DIFF metrics found.</td></tr>"
        )
    exact_metrics = "".join(
        f"<li>{_html_escape(label)}</li>"
        for label in exact_match_metrics
    ) or "<li>None</li>"
    offender_rows = "".join(_offender_html_row(item, context.spec) for item in offender_items)
    unmatched_html = _unmatched_html(context)
    option_items = "".join(
        f"<option value=\"{index}\">{_html_escape(row['label'])}</option>"
        for index, row in enumerate(iteration_data)
    )
    benchmark_heading = (
        "Benchmark phases"
        if context.spec.benchmark_metric_labels
        else "Benchmark metrics"
    )
    note = context.spec.header_note or ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --border: #d9dde5;
      --text: #20242c;
      --muted: #656d7a;
      --match: #1d7f45;
      --close: #9a6a00;
      --diff: #b42318;
      --header: #eef1f6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px 28px 16px;
      background: #242a34;
      color: white;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; font-weight: 650; }}
    header p {{ margin: 0; color: #d8dde6; }}
    main {{ padding: 22px 28px 32px; max-width: 1280px; margin: 0 auto; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 18px;
      padding: 18px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    h3 {{ margin: 18px 0 10px; font-size: 15px; }}
    .summary-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      margin-top: 14px;
    }}
    .summary-card {{
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .summary-card .label {{ color: var(--muted); font-size: 12px; }}
    .summary-card .value {{ font-size: 22px; font-weight: 650; margin-top: 3px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px 9px; text-align: left; vertical-align: top; }}
    th {{ background: var(--header); color: #343a46; font-weight: 650; position: sticky; top: 0; }}
    tbody tr:hover {{ background: #f9fafc; }}
    .numeric {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--border); border-radius: 6px; }}
    .badge {{ border-radius: 999px; color: white; display: inline-block; font-size: 12px; font-weight: 650; padding: 2px 8px; }}
    .MATCH {{ background: var(--match); }}
    .CLOSE {{ background: var(--close); }}
    .DIFF {{ background: var(--diff); }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; align-items: end; }}
    label {{ display: grid; gap: 4px; color: var(--muted); font-size: 12px; }}
    select, input {{
      border: 1px solid var(--border);
      border-radius: 6px;
      min-height: 34px;
      padding: 6px 8px;
      background: white;
      color: var(--text);
      font: inherit;
    }}
    #iteration-select {{ min-width: min(760px, 100%); }}
    details {{ border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }}
    details + details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 650; }}
    .muted {{ color: var(--muted); }}
    .empty {{ color: var(--muted); text-align: center; }}
    .pass-text {{ color: var(--match); font-weight: 650; margin: 0; }}
    th.sortable {{ cursor: pointer; }}
    th.sortable::after {{ content: " sort"; color: var(--muted); font-size: 11px; font-weight: 400; }}
  </style>
</head>
<body>
  <header>
    <h1>{_html_escape(title)}</h1>
    <p>AnyLogic vs SimPy comparison report</p>
  </header>
  <main>
    <section>
      <h2>Run Summary</h2>
      <div>{validation_html}</div>
      <div class="summary-grid">
        <div class="summary-card"><div class="label">Matched combinations</div><div class="value">{len(context.common_keys)}</div></div>
        <div class="summary-card"><div class="label">AnyLogic-only</div><div class="value">{len(context.anylogic_only)}</div></div>
        <div class="summary-card"><div class="label">SimPy-only</div><div class="value">{len(context.simpy_only)}</div></div>
        <div class="summary-card"><div class="label">Top offender limit</div><div class="value">{top}</div></div>
      </div>
      <p class="muted">{_html_escape(note)}</p>
    </section>

    <section>
      <h2>Metrics Needing Attention</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Metric</th><th class="numeric">Match</th><th class="numeric">Close</th><th class="numeric">Diff</th><th class="numeric">Worst Diff</th><th class="numeric">Worst %</th><th>Worst Case</th></tr></thead>
          <tbody>{attention_rows}</tbody>
        </table>
      </div>
      <details>
        <summary>Exact-match metrics</summary>
        <ul>{exact_metrics}</ul>
      </details>
    </section>

    <section>
      <h2>Top Offenders</h2>
      <div class="table-wrap">
        <table id="offenders-table">
          <thead><tr><th class="sortable" data-type="number">Rank</th><th class="sortable">Metric</th><th>Case</th><th class="sortable" data-type="number">AnyLogic it</th><th class="sortable" data-type="number">SimPy it</th><th class="sortable" data-type="number">Diff</th><th class="sortable" data-type="number">Diff %</th><th class="sortable">Status</th></tr></thead>
          <tbody>{offender_rows}</tbody>
        </table>
      </div>
    </section>

    {unmatched_html}

    <section>
      <h2>Iteration Details</h2>
      <div class="controls">
        <label>Iteration
          <select id="iteration-select">{option_items}</select>
        </label>
        <label>Metric filter
          <input id="metric-filter" type="search" placeholder="Filter metric labels">
        </label>
        <label>Status
          <select id="status-filter">
            <option value="all">All statuses</option>
            <option value="MATCH">MATCH</option>
            <option value="CLOSE">CLOSE</option>
            <option value="DIFF">DIFF</option>
          </select>
        </label>
      </div>
      <p id="iteration-case" class="muted"></p>
      <h3>{_html_escape(benchmark_heading)}</h3>
      <div class="table-wrap"><table><thead><tr><th>Metric</th><th class="numeric">AnyLogic</th><th class="numeric">SimPy</th><th class="numeric">Diff</th><th class="numeric">Diff %</th><th>Status</th></tr></thead><tbody id="benchmark-body"></tbody></table></div>
      <h3>Summary metrics</h3>
      <div class="table-wrap"><table><thead><tr><th>Metric</th><th class="numeric">AnyLogic</th><th class="numeric">SimPy</th><th class="numeric">Diff</th><th class="numeric">Diff %</th><th>Status</th></tr></thead><tbody id="summary-body"></tbody></table></div>
    </section>
  </main>
  <script>
    const iterationData = {iteration_json};

    function escapeHtml(value) {{
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function renderRows(rows, target) {{
      const metricFilter = document.getElementById('metric-filter').value.toLowerCase();
      const statusFilter = document.getElementById('status-filter').value;
      const visibleRows = rows.filter(row => {{
        const matchesMetric = row.label.toLowerCase().includes(metricFilter);
        const matchesStatus = statusFilter === 'all' || row.status === statusFilter;
        return matchesMetric && matchesStatus;
      }});
      if (!visibleRows.length) {{
        target.innerHTML = '<tr><td colspan="6" class="empty">No matching rows.</td></tr>';
        return;
      }}
      target.innerHTML = visibleRows.map(row => `
        <tr>
          <td>${{escapeHtml(row.label)}}</td>
          <td class="numeric">${{escapeHtml(row.anylogic)}}</td>
          <td class="numeric">${{escapeHtml(row.simpy)}}</td>
          <td class="numeric">${{escapeHtml(row.diff)}}</td>
          <td class="numeric">${{escapeHtml(row.diffPct)}}</td>
          <td><span class="badge ${{row.status}}">${{escapeHtml(row.status)}}</span></td>
        </tr>
      `).join('');
    }}

    function renderIteration() {{
      const index = Number(document.getElementById('iteration-select').value || 0);
      const row = iterationData[index];
      if (!row) return;
      document.getElementById('iteration-case').textContent =
        `AnyLogic iteration ${{row.anylogicIteration}} / SimPy iteration ${{row.simpyIteration}} - ${{row.caseLabel}}`;
      renderRows(row.benchmarkRows, document.getElementById('benchmark-body'));
      renderRows(row.summaryRows, document.getElementById('summary-body'));
    }}

    function makeSortable(table) {{
      table.querySelectorAll('th.sortable').forEach((header, columnIndex) => {{
        let ascending = true;
        header.addEventListener('click', () => {{
          const type = header.dataset.type || 'text';
          const rows = Array.from(table.tBodies[0].rows);
          rows.sort((left, right) => {{
            const leftCell = left.cells[columnIndex];
            const rightCell = right.cells[columnIndex];
            const leftValue = leftCell.dataset.sort || leftCell.textContent.trim();
            const rightValue = rightCell.dataset.sort || rightCell.textContent.trim();
            if (type === 'number') {{
              return (Number(leftValue) || 0) - (Number(rightValue) || 0);
            }}
            return leftValue.localeCompare(rightValue);
          }});
          if (!ascending) rows.reverse();
          ascending = !ascending;
          rows.forEach(row => table.tBodies[0].appendChild(row));
        }});
      }});
    }}

    document.getElementById('iteration-select').addEventListener('change', renderIteration);
    document.getElementById('metric-filter').addEventListener('input', renderIteration);
    document.getElementById('status-filter').addEventListener('change', renderIteration);
    makeSortable(document.getElementById('offenders-table'));
    renderIteration();
  </script>
</body>
</html>
"""


def _print_report_header(context: ComparisonContext) -> None:
    print("=" * 92)
    print(
        f"PARAMETER VARIATION RANGE COMPARISON: ANYLOGIC vs SIMPY "
        f"({context.spec.model_label})"
    )
    print("=" * 92)
    if context.validation_issues:
        print("SimPy consistency check: FAIL")
        for issue in context.validation_issues:
            print(f"  - {issue}")
    else:
        print("SimPy consistency check: PASS")
    print(
        f"Matched parameter combinations: {len(context.common_keys)}  "
        f"AnyLogic-only: {len(context.anylogic_only)}  "
        f"SimPy-only: {len(context.simpy_only)}"
    )
    if context.spec.header_note:
        print(context.spec.header_note)


def _print_unmatched(context: ComparisonContext) -> None:
    if context.anylogic_only:
        print("\nAnyLogic combinations without a matching SimPy summary row:")
        for key in context.anylogic_only:
            print(f"  {_format_case(key, context.spec)}")
    if context.simpy_only:
        print("\nSimPy combinations without a matching AnyLogic row:")
        for key in context.simpy_only:
            print(f"  {_format_case(key, context.spec)}")


def _matched_rows(context: ComparisonContext) -> list[tuple[RangeRow, RangeRow]]:
    return [
        (context.anylogic_by_key[key], context.simpy_by_key[key])
        for key in context.common_keys
    ]


def _print_full_view(context: ComparisonContext) -> None:
    metrics = _comparison_metrics(context)
    print("\nMatched comparisons:")
    for anylogic, simpy in _matched_rows(context):
        print(
            f"\n{_format_case(anylogic.match_key(context.spec), context.spec)}  "
            f"AnyLogic iteration={anylogic.iteration}  SimPy iteration={simpy.iteration}"
        )
        print(
            f"  {'Metric':<40} {'AnyLogic':>14} {'SimPy':>14} "
            f"{'Diff':>14} {'Diff %':>10} {'Status':>8}"
        )
        print(f"  {'-' * 102}")
        for field_name, label in metrics:
            row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            _print_metric_row(row)


def _print_overview_view(context: ComparisonContext) -> None:
    print("\nOverview:")
    print(
        f"  {'Metric':<40} {'Match':>7} {'Close':>7} {'Diff':>7} "
        f"{'Worst Diff':>14} {'Worst %':>10} {'Worst Case':>28}"
    )
    print(f"  {'-' * 120}")
    for field_name, label in _comparison_metrics(context):
        counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
        worst_diff: tuple[float, float, tuple[int | float, ...]] | None = None
        worst_pct: tuple[float, float | None, tuple[int | float, ...]] | None = None
        for anylogic, simpy in _matched_rows(context):
            metric_row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            counts[metric_row.status] += 1
            key = anylogic.match_key(context.spec)
            diff_rank = abs(metric_row.diff)
            pct_rank = (
                abs(metric_row.diff_pct)
                if metric_row.diff_pct is not None
                else -1.0
            )
            if worst_diff is None or diff_rank > worst_diff[0]:
                worst_diff = (diff_rank, metric_row.diff, key)
            if worst_pct is None or pct_rank > worst_pct[0]:
                worst_pct = (pct_rank, metric_row.diff_pct, key)
        worst_diff_value = 0.0 if worst_diff is None else worst_diff[1]
        worst_pct_value = None if worst_pct is None else worst_pct[1]
        worst_case_key = None if worst_pct is None else worst_pct[2]
        print(
            f"  {_truncate(label, 40):<40} "
            f"{counts['MATCH']:>7} {counts['CLOSE']:>7} {counts['DIFF']:>7} "
            f"{_format_diff(worst_diff_value):>14} "
            f"{_format_percent(worst_pct_value):>10} "
            f"{_format_case(worst_case_key, context.spec):>28}"
        )
    print("\nStatus thresholds: MATCH = exact, CLOSE = <1% difference, DIFF = >=1% difference")


def _print_matrix_view(context: ComparisonContext, *, metric_name: str) -> None:
    metrics = _selected_metrics(metric_name, _comparison_metrics(context), context.spec)
    if not context.spec.parameter_fields:
        return
    row_field = context.spec.parameter_fields[0]
    other_fields = context.spec.parameter_fields[1:]
    row_values = sorted({key[0] for key in context.common_keys})
    other_value_lists = [
        sorted({key[index + 1] for key in context.common_keys})
        for index, _field in enumerate(other_fields)
    ]
    print("\nHotspot matrices:")
    print("Cells show status and percent difference relative to AnyLogic.")
    print("Legend: MATCH = exact, C = close (<1%), D = diff (>=1%)")
    for field_name, label in metrics:
        for other_values in product(*other_value_lists) if other_fields else [()]:
            fixed = dict(zip(other_fields, other_values))
            suffix = " ".join(
                f"{context.spec.parameter_short_labels.get(name, name)}={_format_value(value)}"
                for name, value in fixed.items()
            )
            print(f"\n{label}" + (f" | {suffix}" if suffix else ""))
            rows: list[list[str]] = []
            for row_value in row_values:
                key = (row_value, *other_values)
                anylogic = context.anylogic_by_key.get(key)
                simpy = context.simpy_by_key.get(key)
                if anylogic is None or simpy is None:
                    cell = "---"
                else:
                    cell = _matrix_cell(
                        _metric_value(anylogic, field_name),
                        _metric_value(simpy, field_name),
                    )
                rows.append(
                    [
                        f"{context.spec.parameter_short_labels.get(row_field, row_field)}={_format_value(row_value)}",
                        cell,
                    ]
                )
            _print_table([row_field, "status"], rows, indent="  ")


def _print_offenders_view(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> None:
    offenders = _build_offenders(context, metric_name=metric_name, top=top)
    print(f"\nTop offenders (top {top}):")
    _print_table(
        ["Rank", "Metric", "Case", "AnyLogic it", "SimPy it", "Diff", "Diff %", "Status"],
        offenders,
        indent="  ",
    )


def _print_report_view(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> None:
    _print_overview_view(context)
    _print_offenders_view(context, metric_name=metric_name, top=top)


def _build_overview_rows(context: ComparisonContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, label in _comparison_metrics(context):
        counts = {"MATCH": 0, "CLOSE": 0, "DIFF": 0}
        worst_diff: tuple[float, float, tuple[int | float, ...]] | None = None
        worst_pct: tuple[float, float | None, tuple[int | float, ...]] | None = None
        for anylogic, simpy in _matched_rows(context):
            metric_row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            counts[metric_row.status] += 1
            key = anylogic.match_key(context.spec)
            diff_rank = abs(metric_row.diff)
            pct_rank = (
                abs(metric_row.diff_pct)
                if metric_row.diff_pct is not None
                else -1.0
            )
            if worst_diff is None or diff_rank > worst_diff[0]:
                worst_diff = (diff_rank, metric_row.diff, key)
            if worst_pct is None or pct_rank > worst_pct[0]:
                worst_pct = (pct_rank, metric_row.diff_pct, key)
        rows.append(
            {
                "metric_name": field_name,
                "label": label,
                "match_count": counts["MATCH"],
                "close_count": counts["CLOSE"],
                "diff_count": counts["DIFF"],
                "worst_diff": 0.0 if worst_diff is None else worst_diff[1],
                "worst_pct": None if worst_pct is None else worst_pct[1],
                "worst_case": None if worst_pct is None else worst_pct[2],
            }
        )
    return rows


def _build_offender_items(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> list[dict[str, Any]]:
    offenders: list[tuple[float, MetricComparisonRow, tuple[int | float, ...], int, int]] = []
    for anylogic, simpy in _matched_rows(context):
        for field_name, label in _selected_metrics(
            metric_name,
            _comparison_metrics(context),
            context.spec,
        ):
            row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            severity = abs(row.diff_pct) if row.diff_pct is not None else abs(row.diff)
            offenders.append(
                (
                    severity,
                    row,
                    anylogic.match_key(context.spec),
                    anylogic.iteration,
                    simpy.iteration,
                )
            )
    offenders.sort(key=lambda item: (item[0], abs(item[1].diff), item[2]), reverse=True)
    return [
        {
            "rank": index,
            "row": row,
            "key": key,
            "anylogic_iteration": anylogic_iteration,
            "simpy_iteration": simpy_iteration,
        }
        for index, (_severity, row, key, anylogic_iteration, simpy_iteration)
        in enumerate(offenders[:top], start=1)
    ]


def _build_offenders(
    context: ComparisonContext,
    *,
    metric_name: str,
    top: int,
) -> list[list[str]]:
    return [
        [
            str(item["rank"]),
            item["row"].label,
            _format_case(item["key"], context.spec),
            str(item["anylogic_iteration"]),
            str(item["simpy_iteration"]),
            _format_diff(item["row"].diff),
            _format_percent(item["row"].diff_pct),
            item["row"].status,
        ]
        for item in _build_offender_items(context, metric_name=metric_name, top=top)
    ]


def _comparison_metrics(context: ComparisonContext) -> list[tuple[str, str]]:
    metrics = list(context.spec.metrics)
    matched = _matched_rows(context)
    for field_name, label in context.spec.optional_metrics:
        if matched and all(
            _metric_value(anylogic, field_name, allow_none=True) is not None
            and _metric_value(simpy, field_name, allow_none=True) is not None
            for anylogic, simpy in matched
        ):
            metrics.append((field_name, label))
    metrics.extend(_comparison_benchmark_metrics(matched, context.spec))
    return metrics


def _available_simpy_metrics(
    summary_rows: list[RangeRow],
    run_rows: list[RangeRow],
    spec: RangeComparisonSpec,
) -> list[tuple[str, str]]:
    metrics = list(spec.metrics)
    for field_name, label in spec.optional_metrics:
        if any(row.metrics.get(field_name) is not None for row in summary_rows) and any(
            row.metrics.get(field_name) is not None for row in run_rows
        ):
            metrics.append((field_name, label))
    metrics.extend(_available_benchmark_metrics(summary_rows, run_rows, spec))
    return metrics


def _all_metric_fields(spec: RangeComparisonSpec) -> tuple[tuple[str, str], ...]:
    return (*spec.metrics, *spec.optional_metrics)


def _build_metric_comparison_row(
    anylogic: RangeRow,
    simpy: RangeRow,
    field_name: str,
    label: str,
) -> MetricComparisonRow:
    anylogic_value = _metric_value(anylogic, field_name)
    simpy_value = _metric_value(simpy, field_name)
    return MetricComparisonRow(
        metric_name=field_name,
        label=label,
        anylogic_value=anylogic_value,
        simpy_value=simpy_value,
        diff=_numeric_diff(anylogic_value, simpy_value),
        diff_pct=_percent_diff(anylogic_value, simpy_value),
        status=_status(anylogic_value, simpy_value),
    )


@dataclass(frozen=True)
class ParityOffender:
    """A single matched metric/case whose diff exceeds a regression gate."""

    metric_name: str
    label: str
    case: tuple[int | float, ...]
    anylogic_value: int | float
    simpy_value: int | float
    diff: float
    diff_pct: float | None


def collect_parity_offenders(
    context: ComparisonContext,
    *,
    max_abs_diff: float | None = None,
    max_pct: float | None = None,
    metric_name_prefix: str | None = None,
) -> list[ParityOffender]:
    """Return matched metric/case rows that breach an absolute or percent gate.

    A row is an offender when its absolute diff exceeds ``max_abs_diff`` OR its
    percent diff exceeds ``max_pct`` (whichever gates are set). ``metric_name_prefix``
    restricts the scan to metrics whose field name starts with that prefix, e.g.
    ``"benchmark_"`` to gate only the second-valued movement-timing windows where
    an absolute-second threshold is well defined. Results are sorted worst-first
    by absolute diff.
    """
    offenders: list[ParityOffender] = []
    for field_name, label in _comparison_metrics(context):
        if metric_name_prefix is not None and not field_name.startswith(metric_name_prefix):
            continue
        for anylogic, simpy in _matched_rows(context):
            row = _build_metric_comparison_row(anylogic, simpy, field_name, label)
            abs_diff = abs(row.diff)
            abs_pct = abs(row.diff_pct) if row.diff_pct is not None else None
            over_abs = max_abs_diff is not None and abs_diff > max_abs_diff
            over_pct = max_pct is not None and abs_pct is not None and abs_pct > max_pct
            if over_abs or over_pct:
                offenders.append(
                    ParityOffender(
                        metric_name=field_name,
                        label=label,
                        case=anylogic.match_key(context.spec),
                        anylogic_value=row.anylogic_value,
                        simpy_value=row.simpy_value,
                        diff=row.diff,
                        diff_pct=row.diff_pct,
                    )
                )
    offenders.sort(key=lambda item: abs(item.diff), reverse=True)
    return offenders


def format_parity_offenders(
    offenders: list[ParityOffender],
    spec: RangeComparisonSpec,
    *,
    limit: int | None = None,
) -> str:
    """Render parity-gate offenders as a compact text block."""
    shown = offenders if limit is None else offenders[:limit]
    lines = [
        f"  {row.label} [{_format_case(row.case, spec)}]: "
        f"AnyLogic={_format_value(row.anylogic_value)} "
        f"SimPy={_format_value(row.simpy_value)} "
        f"diff={_format_diff(row.diff)} ({_format_percent(row.diff_pct)})"
        for row in shown
    ]
    if limit is not None and len(offenders) > limit:
        lines.append(f"  ... and {len(offenders) - limit} more")
    return "\n".join(lines)


def _print_metric_row(row: MetricComparisonRow) -> None:
    print(
        f"  {_truncate(row.label, 40):<40} "
        f"{_format_value(row.anylogic_value):>14} "
        f"{_format_value(row.simpy_value):>14} "
        f"{_format_diff(row.diff):>14} "
        f"{_format_percent(row.diff_pct):>10} "
        f"{row.status:>8}"
    )


def _metric_row_json(row: MetricComparisonRow) -> dict[str, str]:
    return {
        "label": row.label,
        "anylogic": _format_value(row.anylogic_value),
        "simpy": _format_value(row.simpy_value),
        "diff": _format_diff(row.diff),
        "diffPct": _format_percent(row.diff_pct),
        "status": row.status,
    }


def _offender_html_row(
    item: Mapping[str, Any],
    spec: RangeComparisonSpec,
) -> str:
    row: MetricComparisonRow = item["row"]
    diff_pct_sort = "" if row.diff_pct is None else f"{row.diff_pct:.12g}"
    return (
        "<tr>"
        f"<td class=\"numeric\" data-sort=\"{item['rank']}\">{item['rank']}</td>"
        f"<td>{_html_escape(row.label)}</td>"
        f"<td>{_html_escape(_format_case(item['key'], spec))}</td>"
        f"<td class=\"numeric\" data-sort=\"{item['anylogic_iteration']}\">{item['anylogic_iteration']}</td>"
        f"<td class=\"numeric\" data-sort=\"{item['simpy_iteration']}\">{item['simpy_iteration']}</td>"
        f"<td class=\"numeric\" data-sort=\"{row.diff:.12g}\">{_html_escape(_format_diff(row.diff))}</td>"
        f"<td class=\"numeric\" data-sort=\"{diff_pct_sort}\">{_html_escape(_format_percent(row.diff_pct))}</td>"
        f"<td><span class=\"badge {row.status}\">{_html_escape(row.status)}</span></td>"
        "</tr>"
    )


def _unmatched_html(context: ComparisonContext) -> str:
    if not context.anylogic_only and not context.simpy_only:
        return ""
    anylogic_rows = "".join(
        f"<li>{_html_escape(_format_case(key, context.spec))}</li>"
        for key in context.anylogic_only
    ) or "<li>None</li>"
    simpy_rows = "".join(
        f"<li>{_html_escape(_format_case(key, context.spec))}</li>"
        for key in context.simpy_only
    ) or "<li>None</li>"
    return f"""
    <section>
      <h2>Unmatched Combinations</h2>
      <details open>
        <summary>AnyLogic-only</summary>
        <ul>{anylogic_rows}</ul>
      </details>
      <details open>
        <summary>SimPy-only</summary>
        <ul>{simpy_rows}</ul>
      </details>
    </section>
"""


def _html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _selected_metrics(
    metric_name: str,
    available_metrics: list[tuple[str, str]],
    spec: RangeComparisonSpec,
) -> list[tuple[str, str]]:
    normalized = _normalize_selected_metric_name(metric_name, spec)
    if normalized == "all":
        return available_metrics
    if normalized == spec.benchmark_avg_only_name:
        return [
            (field_name, label)
            for field_name, label in available_metrics
            if field_name.startswith("benchmark_") and field_name.endswith("__average")
        ]
    for field_name, label in available_metrics:
        if field_name == normalized:
            return [(field_name, label)]
    raise ValueError(f"Unsupported metric: {metric_name}")


def _normalize_selected_metric_name(metric_name: str, spec: RangeComparisonSpec) -> str:
    if metric_name in {"all", spec.benchmark_avg_only_name}:
        return metric_name
    decoded = _decode_benchmark_metric_name(metric_name, spec)
    if decoded is None:
        if metric_name in spec.benchmark_metric_labels:
            return _benchmark_metric_name(metric_name, "average")
        return metric_name
    metric_key, stat_field = decoded
    if metric_key in spec.benchmark_metric_labels:
        return _benchmark_metric_name(metric_key, stat_field)
    return metric_name


def _metric_value(
    row: RangeRow,
    metric_name: str,
    *,
    allow_none: bool = False,
) -> int | float | None:
    decoded = _decode_benchmark_metric_name(metric_name, None)
    if decoded is None:
        value = row.metrics.get(metric_name)
        if value is None and not allow_none:
            raise KeyError(f"Missing metric '{metric_name}' for iteration {row.iteration}")
        return value
    benchmark_key, stat_field = decoded
    benchmark = row.benchmarks.get(benchmark_key)
    if benchmark is None:
        if allow_none:
            return None
        raise KeyError(f"Missing benchmark '{benchmark_key}' for iteration {row.iteration}")
    return getattr(benchmark, stat_field)


def _load_summary_benchmarks(
    record: dict[str, str],
    spec: RangeComparisonSpec,
) -> dict[str, Any]:
    return _load_benchmarks(
        record,
        spec,
        field_name=lambda metric_key, stat_field: (
            f"metric_{_benchmark_metric_name(metric_key, stat_field)}"
        ),
    )


def _load_run_benchmarks(
    record: dict[str, str],
    spec: RangeComparisonSpec,
) -> dict[str, Any]:
    return _load_benchmarks(
        record,
        spec,
        field_name=lambda metric_key, stat_field: (
            f"metric_{_benchmark_metric_name(metric_key, stat_field)}"
        ),
    )


def _load_benchmarks(record: dict[str, str], spec: RangeComparisonSpec, *, field_name) -> dict[str, Any]:
    if not spec.benchmark_metric_labels or not spec.benchmark_stat_fields:
        return {}
    try:
        from case_studies.model_1_simpy.analysis.compare_benchmark_results import BenchmarkStats
    except Exception:
        return {}
    benchmarks: dict[str, Any] = {}
    for metric_key in spec.benchmark_metric_labels:
        values: dict[str, float] = {}
        for stat_field, _stat_label in spec.benchmark_stat_fields:
            value = _optional_float_field(record, field_name(metric_key, stat_field))
            if value is not None:
                values[stat_field] = value
        required = {field for field, _label in spec.benchmark_stat_fields}
        if required <= set(values):
            benchmarks[metric_key] = BenchmarkStats(
                average=values["average"],
                minimum=values["minimum"],
                maximum=values["maximum"],
                std_dev_pop=values["std_dev_pop"],
            )
    return benchmarks


def _available_benchmark_metrics(
    summary_rows: list[RangeRow],
    run_rows: list[RangeRow],
    spec: RangeComparisonSpec,
) -> list[tuple[str, str]]:
    common_keys = _common_benchmark_keys([*summary_rows, *run_rows])
    return _benchmark_metrics_for_keys(common_keys, spec)


def _comparison_benchmark_metrics(
    matched: list[tuple[RangeRow, RangeRow]],
    spec: RangeComparisonSpec,
) -> list[tuple[str, str]]:
    common_keys = _common_benchmark_keys(
        [row for pair in matched for row in pair]
    )
    return _benchmark_metrics_for_keys(common_keys, spec)


def _common_benchmark_keys(rows: list[RangeRow]) -> set[str]:
    if not rows:
        return set()
    return set.intersection(*(set(row.benchmarks) for row in rows))


def _benchmark_metrics_for_keys(
    common_keys: Iterable[str],
    spec: RangeComparisonSpec,
) -> list[tuple[str, str]]:
    metrics: list[tuple[str, str]] = []
    common_key_set = set(common_keys)
    for metric_key, metric_label in spec.benchmark_metric_labels.items():
        if metric_key not in common_key_set:
            continue
        for stat_field, stat_label in spec.benchmark_stat_fields:
            display = spec.benchmark_stat_display_labels.get(stat_field, stat_label)
            metrics.append(
                (
                    _benchmark_metric_name(metric_key, stat_field),
                    f"{metric_label} [{display}]",
                )
            )
    return metrics


def _decode_benchmark_metric_name(
    metric_name: str,
    spec: RangeComparisonSpec | None,
) -> tuple[str, str] | None:
    if not metric_name.startswith("benchmark_") or "__" not in metric_name:
        return None
    body = metric_name[len("benchmark_"):]
    metric_key, stat_field = body.rsplit("__", 1)
    if spec is not None and metric_key not in spec.benchmark_metric_labels:
        return None
    return metric_key, stat_field


def _benchmark_metric_name(metric_key: str, stat_field: str) -> str:
    return f"benchmark_{metric_key}__{stat_field}"


def _parse_number(text: str) -> int | float:
    value = float(text.strip())
    return int(value) if value.is_integer() else value


def _int_field(record: dict[str, str], field_name: str) -> int:
    return int(float(record[field_name]))


def _float_field(record: dict[str, str], field_name: str) -> float:
    return float(record[field_name])


def _number_field(record: dict[str, str], field_name: str) -> int | float:
    value = float(record[field_name])
    return int(value) if value.is_integer() else value


def _metric_number_field(record: dict[str, str], metric_name: str) -> int | float | None:
    for field_name in (f"metric_{metric_name}", f"metric_{metric_name}_mean"):
        value = _optional_float_field(record, field_name)
        if value is not None:
            return int(value) if value.is_integer() else value
    return None


def _optional_float_field(record: dict[str, str], field_name: str) -> float | None:
    value = record.get(field_name, "")
    if value == "":
        return None
    return float(value)


def _values_match(left: int | float | None, right: int | float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)


def _numeric_diff(left: int | float, right: int | float) -> float:
    return float(right) - float(left)


def _percent_diff(left: int | float, right: int | float) -> float | None:
    baseline = abs(float(left))
    if baseline < 1e-12:
        return None
    return ((float(right) - float(left)) / baseline) * 100.0


def _status(left: int | float, right: int | float) -> str:
    if _values_match(left, right):
        return "MATCH"
    pct = _percent_diff(left, right)
    if pct is not None and abs(pct) < 1.0:
        return "CLOSE"
    return "DIFF"


def _format_case(
    key: tuple[int | float, ...] | None,
    spec: RangeComparisonSpec,
) -> str:
    if key is None:
        return "n/a"
    return " ".join(
        f"{spec.parameter_short_labels.get(name, name)}={_format_value(value)}"
        for name, value in zip(spec.parameter_fields, key)
    )


def _format_value(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    formatted = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def _format_diff(value: float) -> str:
    return f"{value:+.6g}"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    text = f"{value:+.2f}%"
    return text.replace(".00%", "%")


def _matrix_cell(left: int | float, right: int | float) -> str:
    status = _status(left, right)
    marker = "MATCH" if status == "MATCH" else ("C" if status == "CLOSE" else "D")
    return f"{marker} {_format_percent(_percent_diff(left, right))}"


def _print_table(header: list[str], rows: list[list[str]], *, indent: str = "") -> None:
    widths = [
        max(len(str(row[index])) for row in [header, *rows])
        for index in range(len(header))
    ]
    print(indent + "  ".join(header[index].ljust(widths[index]) for index in range(len(header))))
    print(indent + "  ".join("-" * width for width in widths))
    for row in rows:
        print(indent + "  ".join(row[index].ljust(widths[index]) for index in range(len(row))))


def _truncate(text: str, max_width: int) -> str:
    if max_width < 4 or len(text) <= max_width:
        return text
    return text[: max_width - 3] + "..."
