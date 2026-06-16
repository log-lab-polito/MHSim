"""Unit tests for the Model 1 parity instruments added in Step 4.

Covers the per-timestep movement-trace residual (interpolation + stats) and the
range-comparison regression-gate offender collection. These guard the tooling
that gates movement-parity regressions in CI.
"""

import unittest

from case_studies.model_1_simpy.analysis.compare_movement_trace import (
    TraceSample,
    position_residual_series,
    residual_stats,
)
from mhsim_analysis.range_comparison import (
    ComparisonContext,
    RangeComparisonSpec,
    RangeRow,
    build_comparison_context,
    collect_parity_offenders,
)


def _sample(t: float, x: float, y: float) -> TraceSample:
    return TraceSample(time=t, positions=((x, y),))


class MovementResidualTests(unittest.TestCase):
    def test_residual_interpolates_anylogic_onto_simpy_times(self):
        # AnyLogic sampled at 0.0 and 1.0; SimPy at 0.5 lands halfway.
        anylogic = [_sample(0.0, 0.0, 0.0), _sample(1.0, 10.0, 0.0)]
        simpy = [_sample(0.5, 4.0, 0.0)]
        residuals = position_residual_series(anylogic, simpy)
        self.assertEqual(len(residuals), 1)
        # Interpolated AnyLogic position at t=0.5 is x=5.0, SimPy x=4.0 -> err 1.0.
        self.assertAlmostEqual(residuals[0].anylogic[0], 5.0)
        self.assertAlmostEqual(residuals[0].error, 1.0)

    def test_residual_skips_times_outside_anylogic_span(self):
        anylogic = [_sample(0.0, 0.0, 0.0), _sample(1.0, 1.0, 0.0)]
        simpy = [_sample(-0.5, 0.0, 0.0), _sample(0.5, 0.5, 0.0), _sample(2.0, 0.0, 0.0)]
        residuals = position_residual_series(anylogic, simpy)
        # Only t=0.5 is within [0, 1]; it interpolates to a perfect match.
        self.assertEqual([r.time for r in residuals], [0.5])
        self.assertAlmostEqual(residuals[0].error, 0.0)

    def test_residual_stats_summarize_envelope(self):
        anylogic = [_sample(t / 10.0, 0.0, 0.0) for t in range(0, 11)]
        simpy = [
            _sample(0.0, 0.0, 0.0),
            _sample(0.5, 3.0, 4.0),  # error 5.0 (3-4-5)
            _sample(1.0, 0.0, 1.0),  # error 1.0
        ]
        stats = residual_stats(position_residual_series(anylogic, simpy))
        self.assertIsNotNone(stats)
        self.assertEqual(stats.count, 3)
        self.assertAlmostEqual(stats.max_error, 5.0)
        self.assertAlmostEqual(stats.max_error_time, 0.5)
        self.assertAlmostEqual(stats.mean_error, (0.0 + 5.0 + 1.0) / 3.0)

    def test_residual_stats_none_when_no_overlap(self):
        self.assertIsNone(residual_stats([]))


_SPEC = RangeComparisonSpec(
    model_label="test",
    parameter_fields=("p",),
    parameter_labels={"p": "p"},
    parameter_short_labels={"p": "p"},
    metrics=(("benchmark_leg_s", "Leg (s)"), ("summary_metric", "Summary")),
)


def _ctx(anylogic_metrics: dict, simpy_metrics: dict) -> ComparisonContext:
    anylogic_rows = [RangeRow(iteration=1, params={"p": 1.0}, metrics=anylogic_metrics)]
    simpy_rows = [RangeRow(iteration=1, params={"p": 1.0}, metrics=simpy_metrics)]
    return build_comparison_context(
        anylogic_rows, simpy_rows, simpy_rows, spec=_SPEC
    )


class ParityGateTests(unittest.TestCase):
    def test_abs_gate_flags_only_breaching_benchmark_metric(self):
        ctx = _ctx(
            {"benchmark_leg_s": 6.685220, "summary_metric": 0.41},
            {"benchmark_leg_s": 6.685143, "summary_metric": 0.41},  # 7.7e-5 off
        )
        # Loose threshold: no offenders.
        self.assertEqual(
            collect_parity_offenders(ctx, max_abs_diff=1e-3, metric_name_prefix="benchmark_"),
            [],
        )
        # Tight threshold: the benchmark leg breaches.
        offenders = collect_parity_offenders(
            ctx, max_abs_diff=1e-5, metric_name_prefix="benchmark_"
        )
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0].metric_name, "benchmark_leg_s")

    def test_prefix_scope_excludes_summary_metric(self):
        ctx = _ctx(
            {"benchmark_leg_s": 6.685220, "summary_metric": 0.41},
            {"benchmark_leg_s": 6.685220, "summary_metric": 0.50},  # summary off
        )
        # benchmark_ scope ignores the summary metric divergence.
        self.assertEqual(
            collect_parity_offenders(ctx, max_abs_diff=1e-6, metric_name_prefix="benchmark_"),
            [],
        )
        # Whole-scope gate catches it.
        offenders = collect_parity_offenders(ctx, max_abs_diff=1e-6, metric_name_prefix=None)
        self.assertTrue(any(o.metric_name == "summary_metric" for o in offenders))


if __name__ == "__main__":
    unittest.main()
