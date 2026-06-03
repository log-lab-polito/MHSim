import unittest

import simpy

from mhsim.conveyor import Conveyor, ConveyorSpur


class ConveyorSpurTests(unittest.TestCase):
    def test_conveyor_entry_headway_and_capacity_counters(self):
        env = simpy.Environment()
        conveyor = Conveyor(
            id="main",
            env=env,
            length_m=10.0,
            speed_mps=2.0,
            item_length_m=2.0,
            min_gap_m=0.0,
        )
        entry_times = []

        def enter():
            yield from conveyor.enter()
            entry_times.append(env.now)

        env.process(enter())
        env.process(enter())
        env.run()

        self.assertEqual(entry_times, [0.0, 1.0])
        self.assertEqual(conveyor.occupancy, 2)
        self.assertEqual(conveyor.total_entered, 2)

    def test_spur_transfer_waits_for_target_capacity(self):
        env = simpy.Environment()
        source = Conveyor("source", env, length_m=10.0, speed_mps=1.0, max_items=1)
        target = Conveyor("target", env, length_m=10.0, speed_mps=1.0, max_items=1)
        spur = ConveyorSpur("spur", env, source, target)

        source._occupancy = 1
        source.total_entered = 1
        target._occupancy = 1
        target.total_entered = 1

        def free_target():
            yield env.timeout(2.0)
            target.leave()

        env.process(spur.transfer())
        env.process(free_target())
        env.run()

        self.assertAlmostEqual(env.now, 2.0)
        self.assertEqual(source.occupancy, 0)
        self.assertEqual(target.occupancy, 1)
        self.assertEqual(spur.total_transferred, 1)

    def test_spur_source_after_target_clearance(self):
        env = simpy.Environment()
        source = Conveyor("source", env, length_m=10.0, speed_mps=1.0)
        target = Conveyor("target", env, length_m=10.0, speed_mps=1.0)
        spur = ConveyorSpur(
            "spur",
            env,
            source,
            target,
            merge_clearance_distance_m=2.0,
            source_after_target_clearance_distance_m=5.0,
        )
        reserve_times = []

        def reserve(path):
            yield from spur.reserve_merge_window(merge_path=path)
            reserve_times.append((path, env.now))

        env.process(reserve("target"))
        env.process(reserve("source"))
        env.run()

        self.assertEqual(reserve_times[0], ("target", 0.0))
        self.assertEqual(reserve_times[1], ("source", 5.0))


if __name__ == "__main__":
    unittest.main()
