"""Regression tests pinning Model 1 benchmark-comparison geometry.

These guard the fix in ``compare_benchmark_results.run_simpy_benchmark``: the
AnyLogic benchmark export (``log_file.txt``) is the Parameter Variation /
Sensitivity Analysis run, which leaves A/B at their original markup positions.
The fresh SimPy run must therefore mirror the shared range base
(``apply_displacement_geometry=False``) instead of the ``Model1Params()``
default (``True``). When that broke, the loaded leg was timed against the
displacement-relocated 100 m path (~20 s) instead of the line-guided 20 m path
(~8.944 s), producing spurious +100% benchmark diffs.
"""

import math
import unittest

from mhsim.reporting import build_forklift_movement_benchmark_rows

from case_studies.model_1_simpy.analysis.compare_benchmark_results import (
    parse_anylogic_benchmark_output,
    run_simpy_benchmark,
)
from case_studies.model_1_simpy.model import Model1SimModel
from case_studies.model_1_simpy.params import Model1Params

_LOADED_LEG_KEY = "move_loading_finish_to_unloading_start_s"
# The line-guided controller fires arrival within forklift_line_guided_arrival
# _tolerance_m of the target while still decelerating, so a straight leg
# finishes sqrt(2 * tolerance / decel) before a full stop. These fixtures use
# Range-base geometry: A=50, B=70 -> 20 m straight, line-guided full-stop solve.
_RANGE_BASE_LOADED_LEG_S = 2.0 * math.sqrt(20.0)  # 8.94427190999916
# Displacement geometry, disp=100: A=10, B=110 -> 100 m straight = 20 s
# (accelerate 50 m + decelerate 50 m at a=1, vmax=10).
_DISPLACEMENT_LOADED_LEG_S = 20.0
_ANYLOGIC_LOG = "anylogic/Model 1/log_file.txt"


def _loaded_leg_avg(*, apply_displacement_geometry: bool, displacement_m: float) -> float:
    params = Model1Params(apply_displacement_geometry=apply_displacement_geometry)
    params.arrival_rate_s = 60.0
    params.n_forklifts = 1
    params.forklift_max_speed = 10.0
    params.forklift_acceleration = 1.0
    params.displacement_m = displacement_m
    params.sim_time = 3600.0
    model = Model1SimModel(params=params, console_logging=False, enable_logging=False)
    stats = model.run()
    rows = {r["metric_key"]: r for r in build_forklift_movement_benchmark_rows(stats)}
    return float(rows[_LOADED_LEG_KEY]["avg_s"])


class BenchmarkGeometryTests(unittest.TestCase):
    def test_range_base_geometry_uses_line_guided_loaded_leg(self):
        """apply_displacement_geometry=False keeps the original 20 m A/B leg."""
        self.assertAlmostEqual(
            _loaded_leg_avg(apply_displacement_geometry=False, displacement_m=100.0),
            _RANGE_BASE_LOADED_LEG_S,
            places=6,
        )

    def test_displacement_geometry_relocates_ab(self):
        """apply_displacement_geometry=True relocates A/B to a 100 m leg."""
        self.assertAlmostEqual(
            _loaded_leg_avg(apply_displacement_geometry=True, displacement_m=100.0),
            _DISPLACEMENT_LOADED_LEG_S,
            places=6,
        )

    def test_two_regimes_are_distinct(self):
        """The two regimes must produce materially different loaded legs."""
        self.assertGreater(
            abs(_RANGE_BASE_LOADED_LEG_S - _DISPLACEMENT_LOADED_LEG_S),
            1.0,
        )

    def test_run_simpy_benchmark_uses_range_base_geometry(self):
        """The benchmark comparison must mirror the range base, not the default.

        For iteration 1 (a=60, f=1, v=10, acc=1, disp=100) the loaded leg must
        be the line-guided ~8.944 s, never the 20 s displacement-relocated leg.
        """
        anylogic_rows = parse_anylogic_benchmark_output(_ANYLOGIC_LOG)
        self.assertTrue(anylogic_rows, "expected AnyLogic benchmark reference rows")
        first = anylogic_rows[0]
        self.assertEqual(first.iteration, 1)
        self.assertEqual(first.displacement_m, 100.0)

        simpy_row = run_simpy_benchmark(first, sim_time=3600.0)
        loaded = simpy_row.benchmarks[_LOADED_LEG_KEY].average
        self.assertAlmostEqual(loaded, _RANGE_BASE_LOADED_LEG_S, places=6)
        # Guard against silent regression back to the relocated-geometry leg.
        self.assertGreater(abs(loaded - _DISPLACEMENT_LOADED_LEG_S), 1.0)


if __name__ == "__main__":
    unittest.main()
