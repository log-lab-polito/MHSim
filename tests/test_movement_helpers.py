import math
import unittest

from mhsim.movement import (
    AcceleratingInterpolator,
    HorizontalMovement,
    Position3D,
    clamp01,
    constant_accel_distance,
    constant_accel_speed,
    distance_to_speed,
    time_to_cover_distance,
)


class MovementHelperTests(unittest.TestCase):
    def test_constant_acceleration_helpers_are_consistent(self):
        self.assertEqual(clamp01(-1), 0.0)
        self.assertEqual(clamp01(2), 1.0)
        self.assertAlmostEqual(constant_accel_speed(1.0, 2.0, 3.0), 7.0)
        self.assertAlmostEqual(constant_accel_distance(1.0, 2.0, 3.0), 12.0)
        self.assertAlmostEqual(distance_to_speed(1.0, 2.0, 7.0), 12.0)
        self.assertAlmostEqual(time_to_cover_distance(1.0, 2.0, 12.0), 3.0)

    def test_horizontal_profile_matches_travel_time_and_interpolator(self):
        movement = HorizontalMovement(max_speed=4.0, acceleration=2.0, deceleration=2.0)
        profile = movement.solve_profile(20.0)
        self.assertAlmostEqual(profile.travel_time, movement.travel_time(20.0))
        self.assertAlmostEqual(profile.distance_at_time(profile.travel_time), 20.0)

        start = Position3D(0, 0, 0)
        end = Position3D(20, 0, 0)
        interpolator = AcceleratingInterpolator(start, end, movement)
        position = interpolator.update(interpolator.travel_time)
        self.assertAlmostEqual(position.x, end.x)
        self.assertAlmostEqual(position.y, end.y)

    def test_squared_distances_match_unsquared_distances(self):
        a = Position3D(0, 0, 0)
        b = Position3D(3, 4, 12)
        self.assertAlmostEqual(a.sqr_distance_xy(b), a.distance_xy(b) ** 2)
        self.assertAlmostEqual(a.sqr_distance_to(b), a.distance_to(b) ** 2)
        self.assertAlmostEqual(math.sqrt(a.sqr_distance_to(b)), 13.0)


if __name__ == "__main__":
    unittest.main()
