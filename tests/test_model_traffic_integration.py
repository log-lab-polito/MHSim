from __future__ import annotations

import unittest


try:
    import simpy  # noqa: F401
except ImportError:  # pragma: no cover - handled by skip
    simpy = None


@unittest.skipIf(simpy is None, "simpy is not installed")
class ModelTrafficIntegrationTests(unittest.TestCase):
    def test_traffic_controller_introduces_waits_and_reduces_throughput(self) -> None:
        from case_studies.model_1_simpy.model import Model1SimModel
        from case_studies.model_2_simpy.params import Model2Params

        traffic_params = Model2Params()
        traffic_params.sim_time = 1800.0
        traffic_params.arrival_rate_per_min = 1.25
        traffic_params.n_forklifts = 2
        traffic_params.delay_time_s = 180.0
        traffic_params.random_seed = 7

        traffic_model = Model1SimModel(
            params=traffic_params,
            console_logging=False,
            enable_logging=False,
        )
        traffic_stats = traffic_model.run()

        total_wait_s = sum(traffic_stats.traffic_wait_time_s.values())
        total_wait_events = sum(traffic_stats.traffic_wait_counts.values())
        self.assertGreater(total_wait_s, 0.0)
        self.assertGreater(total_wait_events, 0)

        baseline_params = Model2Params()
        baseline_params.sim_time = traffic_params.sim_time
        baseline_params.arrival_rate_per_min = traffic_params.arrival_rate_per_min
        baseline_params.n_forklifts = traffic_params.n_forklifts
        baseline_params.delay_time_s = traffic_params.delay_time_s
        baseline_params.random_seed = traffic_params.random_seed

        baseline_model = Model1SimModel(
            params=baseline_params,
            console_logging=False,
            enable_logging=False,
        )
        baseline_model.fleet.traffic_controller = None
        for forklift in baseline_model.fleet.forklifts:
            forklift.traffic_controller = None
        baseline_stats = baseline_model.run()

        self.assertLessEqual(traffic_stats.completed, baseline_stats.completed)


if __name__ == "__main__":
    unittest.main()
