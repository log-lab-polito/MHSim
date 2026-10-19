"""Regression tests pinning the probe-confirmed forklift rules (docs/forklift_rules/R1-R6).

Reference numbers come from black-box probe runs of renamed copies of the AnyLogic models
(scripts/anylogic_probe.py); see docs/forklift_parity_ledger.csv for the evidence.
"""

import unittest

from mhsim.forklift import LiftProfile
from mhsim.movement import HorizontalMovement, Position3D
from mhsim.routing import NodeJunction, Router
from mhsim.spatial import Path, PointNode, WarehouseLayout

from case_studies.model_1_simpy.model import Model1SimModel
from case_studies.model_1_simpy.params import Model1Params
import mhsim.forklift as forklift_module

# Model 1 probe, Simulation geometry (displacement 40 m), arrival every 60.01 s:
# (seize time, pickup, loaded, return) durations in seconds for the first three jobs.
_MODEL1_PROBE_LEGS = [
    (0.0, 8.685219806, 12.635000128, 8.477324851),
    (60.01, 8.713194462, 12.635000128, None),
]
_TOLERANCE_S = 1e-6


class ArrivalToleranceTests(unittest.TestCase):
    """R1: planned 2e-4 m past the target, arrival after D + 1e-4 m."""

    def test_straight_leg_matches_probe(self):
        horizontal = HorizontalMovement(max_speed=10.0, acceleration=1.0, deceleration=1.0)
        self.assertAlmostEqual(horizontal.arrival_time(40.0001, 1e-4), 12.635000128, delta=1e-9)

    def test_range_base_straight_leg_matches_anylogic_log(self):
        horizontal = HorizontalMovement(max_speed=10.0, acceleration=1.0, deceleration=1.0)
        self.assertAlmostEqual(horizontal.arrival_time(20.0001, 1e-4), 8.930174496, delta=1e-8)

    def test_arrival_time_from_speed(self):
        horizontal = HorizontalMovement(max_speed=1.0, acceleration=1.0, deceleration=1.0)
        # Cruising at full speed: 21.5 m cruise plus 1 s braking.
        self.assertAlmostEqual(horizontal.arrival_time(22.0, 0.0, initial_speed=1.0), 22.5)


class NodeConnectorTests(unittest.TestCase):
    """R6: AnyLogic's in-node connector at Model 1 node C."""

    def _router(self) -> Router:
        home = Position3D(60.0, 32.0, 0)
        a = Position3D(40.0, 40.0, 0)
        b = Position3D(80.0, 40.0, 0)
        c = Position3D(60.0, 40.0, 0)
        layout = WarehouseLayout(
            inbound_area=PointNode(id="A", position=a),
            outbound_area=PointNode(id="B", position=b),
            paths=[Path("path", [home, c]), Path("AC", [a, c]), Path("CB", [c, b])],
        )
        return Router(
            layout,
            junctions={(60.0, 40.0): NodeJunction(path_end_offset_m=1.0, centre_attached=((80.0, 40.0),))},
        )

    def test_return_crosses_c_on_the_measured_connector(self):
        route = self._router().route_between_nodes(Position3D(80.0, 40.0, 0), Position3D(60.0, 32.0, 0))
        # B -> C centre 20 m, the measured centre-to-boundary connector 1.1061615 m, then 7 m home.
        self.assertAlmostEqual(route.total_distance, 20.0 + 1.1061615 + 7.0, delta=1e-6)

    def test_pickup_turn_is_a_one_metre_arc(self):
        route = self._router().route_between_nodes(Position3D(60.0, 32.0, 0), Position3D(40.0, 40.0, 0))
        self.assertAlmostEqual(route.total_distance, 7.0 + 1.5707963 + 19.0, delta=1e-6)


class Model1LegTests(unittest.TestCase):
    """R1 and R6 together: Model 1 legs equal the probe durations."""

    def test_legs_match_probe(self):
        legs = []
        original = forklift_module.Forklift.move_to

        def recording(self, target, *args, **kwargs):
            started = self.env.now
            yield from original(self, target, *args, **kwargs)
            legs.append((started, self.env.now - started))

        forklift_module.Forklift.move_to = recording
        try:
            params = Model1Params(arrival_rate_s=60.01, displacement_m=40.0, sim_time=130.0)
            Model1SimModel(params=params, enable_logging=False).run()
        finally:
            forklift_module.Forklift.move_to = original
        moving = [leg for leg in legs if leg[1] > 1e-9]
        expected = []
        for _, pickup, loaded, back in _MODEL1_PROBE_LEGS:
            expected += [pickup, loaded] + ([back] if back is not None else [])
        for (_, got), want in zip(moving, expected):
            self.assertAlmostEqual(got, want, delta=_TOLERANCE_S)


class RackTransferTests(unittest.TestCase):
    """R5: time at Model 5's rack path exit."""

    def test_store_and_retrieve_times_match_probe(self):
        profile = LiftProfile(
            shelf_height=1.0,
            elevation_speed=0.2,
            lowering_speed=0.2,
            cargo_height=1.0,
            rack_approach_m=1.5,
            rack_reach_m=2.2,
            rack_handling_speed=10.0,
        )
        for level, store, retrieve in ((0, 5.52, 0.52), (1, 0.52, 5.52), (2, 5.52, 10.52)):
            self.assertAlmostEqual(profile.rack_transfer_time(level, storing=True), store, delta=1e-9)
            self.assertAlmostEqual(profile.rack_transfer_time(level, storing=False), retrieve, delta=1e-9)


class Model5DispatchTests(unittest.TestCase):
    """R2-R5 together on Model 5 at the reference iteration-1 settings."""

    def test_store_windows_bracket_the_probe(self):
        from case_studies.model_5_simpy.model import Model5SimModel
        from case_studies.model_5_simpy.params import Model5Params
        from mhsim.reporting import build_forklift_movement_benchmark_rows

        params = Model5Params()
        params.sim_time = 18000.0
        params.arrival_rate_per_min = 60.0 / 96.0
        params.n_forklifts = 1
        params.delay_time_s = 180.0
        stats = Model5SimModel(params=params, console_logging=False, enable_logging=False).run()
        rows = {row["metric_key"]: row for row in build_forklift_movement_benchmark_rows(stats)}
        seize_to_load = rows["store_seize_to_load_start_s"]
        # Probe: average 24.6686 s; most stores take over a forklift on its way home (R3),
        # the slowest start from rest at home in 28.0685 s. Individual extremes depend on
        # sub-millisecond timing history, so only the average and the from-rest case are pinned.
        self.assertAlmostEqual(float(seize_to_load["avg_s"]), 24.6686, delta=0.1)
        self.assertLess(float(seize_to_load["min_s"]), 24.0)
        self.assertAlmostEqual(float(seize_to_load["max_s"]), 28.0685, delta=1e-3)
        # Probe: load finish -> release averages 26.5026 s (travel to the path exit plus R5).
        release = rows["store_unload_finish_to_release_s"]
        self.assertAlmostEqual(float(release["avg_s"]), 26.5026, delta=0.05)


if __name__ == "__main__":
    unittest.main()
