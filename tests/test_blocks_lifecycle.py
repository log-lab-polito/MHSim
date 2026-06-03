import unittest

import simpy

from mhsim.blocks import DelayBlock, ServiceBlock, Sink
from mhsim.pallet import Pallet
from mhsim.stats import SimulationStats


class BlockLifecycleTests(unittest.TestCase):
    def test_service_delay_sink_counters_keep_existing_semantics(self):
        env = simpy.Environment()
        stats = SimulationStats()
        sink = Sink(env, stats)
        delay = DelayBlock(env, delay_s=2.0, next_block=sink)
        service = ServiceBlock(env, service_time_s=3.0, next_block=delay)
        pallet = Pallet(id=1, created_at=0.0)

        env.process(service.handle(pallet))
        env.run()

        self.assertEqual(service.entered_count, 1)
        self.assertEqual(service.finished_count, 1)
        self.assertEqual(service.completed_count, 1)
        self.assertEqual(delay.entered_count, 1)
        self.assertEqual(delay.finished_count, 1)
        self.assertEqual(delay.completed_count, 1)
        self.assertEqual(sink.entered_count, 1)
        self.assertEqual(stats.completed, 1)
        self.assertEqual(stats.time_in_system, [5.0])


if __name__ == "__main__":
    unittest.main()
