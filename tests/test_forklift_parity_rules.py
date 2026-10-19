"""Regression tests pinning the probe-confirmed forklift rules (docs/forklift_rules/R1-R8).

Reference numbers come from instrumented probe runs of renamed copies of the AnyLogic models
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


class LineGuidedTrafficTests(unittest.TestCase):
    """R8: route-boundary updates and vision interaction between two forklifts (Model 2)."""

    def _model2(self, sim_time):
        from case_studies.model_2_simpy.model import Model2SimModel
        from case_studies.model_2_simpy.params import Model2Params

        params = Model2Params(arrival_rate_s=72.0, n_forklifts=2, delay_time_s=180.0, sim_time=sim_time)
        return Model2SimModel(params=params, enable_logging=False), params

    def test_route_boundaries_are_path_ends(self):
        # F2 probe: odometer readings (from the nominal origin) of every path start and end.
        model, params = self._model2(1.0)
        layout, router = model.layout, model.router
        rack = layout.storage_rack.get_access_point()
        expected = {
            layout.inbound_area.get_access_point(): [
                1.0001, 5.0001, 6.5709, 10.5709, 15.5709, 17.5709, 22.5709, 26.5709, 28.1417
            ],
            layout.outbound_area.get_access_point(): [1.0001, 5.0001, 7.0001],
        }
        for target, marks in expected.items():
            route = router.route_between_nodes(rack, target, turn_radius=params.forklift_turn_radius)
            self.assertEqual([round(m, 4) for m in router.path_boundaries(route)], marks)

    def test_controller_tick_absorbs_float_drift(self):
        tick = forklift_module.Forklift._next_controller_update_time
        self.assertEqual(tick(107.49999999999997, 0.5), 108.0)
        self.assertEqual(tick(107.5, 0.5), 108.0)
        self.assertEqual(tick(107.2, 0.5), 107.5)

    def test_first_right_of_way_episode(self):
        # F2idle probe: both forklifts touch at the 108.5 s tick near node4. The earlier-created
        # one stops there and drives on at the 109.0 s tick; the other waits until 113.5 s.
        model, _ = self._model2(120.0)
        traffic = model.fleet.vision_traffic
        speeds = {}

        def sampler(env):
            for t in (108.75, 109.25, 113.25, 113.75):
                yield env.timeout(t - env.now)
                speeds[t] = [traffic._distance_speed(track, env.now)[1] for track in traffic._ordered]

        model.env.process(sampler(model.env))
        model.run()
        self.assertEqual(speeds[108.75], [0.0, 0.0])
        self.assertGreater(speeds[109.25][0], 0.0)
        self.assertEqual(speeds[109.25][1], 0.0)
        self.assertEqual(speeds[113.25][1], 0.0)
        self.assertGreater(speeds[113.75][1], 0.0)


class DispatchAndRackTests(unittest.TestCase):
    """R9 and the rack side of R8, pinned to the two- and three-forklift Model 5 probes and
    the three-forklift Model 2 probe (AnyLogic ARRIVE times, seconds)."""

    @staticmethod
    def _arrivals(model, until):
        traffic = model.fleet.vision_traffic
        seen = {}
        original = traffic.arrive

        def arrive(forklift, t, processing):
            seen.setdefault(traffic._track(forklift).order, []).append(t)
            return original(forklift, t, processing)

        traffic.arrive = arrive
        model.run(until=until)
        return seen

    @staticmethod
    def _model5(n, sim_time):
        from case_studies.model_5_simpy.model import Model5SimModel
        from case_studies.model_5_simpy.params import Model5Params

        params = Model5Params()
        params.arrival_rate_per_min = 60.0 / 96.0
        params.n_forklifts = n
        params.delay_time_s = 180.0
        params.sim_time = sim_time
        return Model5SimModel(params=params, enable_logging=False)

    def test_model5_home_spots(self):
        model = self._model5(3, 1.0)
        homes = [(f.home_position.x, f.home_position.y) for f in model.fleet.forklifts]
        self.assertEqual(homes, [(24.5, 28.0), (27.0, 28.0), (29.5, 28.0)])

    def test_model5_two_forklifts(self):
        arrivals = self._arrivals(self._model5(2, 2400.0), 2400.0)
        # Unit 1 leaves home at (27, 28) for the rack while unit 0, inside the rack, is
        # invisible to it but already holds right of way for its trip home (283.07).
        self.assertAlmostEqual(arrivals[1][0], 283.072684866, delta=1e-6)
        # Re-dispatched inside node4 at 318 s: straight to path5's start, then home.
        self.assertAlmostEqual(arrivals[1][4], 383.448087, delta=1e-5)
        # Re-dispatched on the aisle at 459.17 s: U-turn on node4's edge, back to the rack.
        self.assertAlmostEqual(arrivals[0][13], 464.261732317, delta=1e-6)
        # Exact through the first 38 minutes.
        self.assertAlmostEqual(arrivals[1][57], 2304.121824, delta=1e-5)

    def test_model5_three_forklifts(self):
        arrivals = self._arrivals(self._model5(3, 1500.0), 1500.0)
        # Unit 1 waits at the bay until unit 2 is out of the rack (373.56 s), then
        # retrieves (5.52 s) and delivers.
        self.assertAlmostEqual(arrivals[1][1], 393.660318, delta=1e-5)
        # The 807.5 s hard stop of units 0 and 2 near node4 holds although the tick and
        # unit 0's own update differ by floating-point drift.
        self.assertAlmostEqual(arrivals[2][19], 994.133816, delta=1e-5)
        # At 1053.0 s exactly 0.5 m is left to D + eps at 1 m/s: AnyLogic brakes (R1).
        self.assertAlmostEqual(arrivals[2][20], 1053.999999785, delta=1e-6)
        # Inside the rack at the 1431.0 s tick unit 0 does not touch unit 2, so coming out
        # at 1431.17 s it waits for it and gets home at 1446.90 s.
        self.assertAlmostEqual(arrivals[0][35], 1446.903307, delta=1e-5)

    def test_release_and_request_at_the_same_instant(self):
        # The reference experiments run simultaneous events last-scheduled first: a forklift
        # whose release falls at the instant a request is raised (by an event scheduled
        # earlier) is free for that request (Model 2 probe at a = 60 s, d = 180 s: all 186
        # such retrieves went to the forklift just released at the rack).
        import simpy

        from mhsim.forklift import create_forklift_fleet
        from mhsim.movement import MovementProfile, VerticalMovement

        home, rack = Position3D(60.0, 32.0, 0), Position3D(40.0, 40.0, 0)
        layout = WarehouseLayout(
            inbound_area=PointNode(id="A", position=rack),
            outbound_area=PointNode(id="B", position=home),
            paths=[Path("p", [home, rack])],
        )
        env = simpy.Environment()
        fleet = create_forklift_fleet(
            env,
            count=2,
            movement_profile=MovementProfile(
                horizontal=HorizontalMovement(max_speed=1.0, acceleration=1.0, deceleration=1.0),
                elevation=VerticalMovement(speed=0.2),
            ),
            router=Router(layout),
            home_position=home,
        )
        chosen = []

        def store(env):
            assignment = yield from fleet.seize()
            assignment.forklift.position = rack
            yield env.timeout(5.0)
            yield env.timeout(5.0)  # scheduled after the request's timeout below
            fleet.release(assignment)

        def retrieve(env):
            yield env.timeout(10.0)
            assignment = yield from fleet.seize(near_position=rack)
            chosen.append(assignment.forklift.id)

        env.process(store(env))
        env.process(retrieve(env))
        env.run(until=11.0)
        self.assertEqual(chosen, [fleet.forklifts[0].id])
