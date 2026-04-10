from __future__ import annotations

import unittest

from mhsim.movement import Position3D
from mhsim.routing import RouteStep
from mhsim.traffic import (
    PathTrafficController,
    WAIT_REASON_EDGE_CONFLICT,
    WAIT_REASON_LEADER_GAP,
    WAIT_REASON_NODE_CONFLICT,
    WAIT_REASON_RESERVATION,
)


def make_step(
    start_node_id: str,
    end_node_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
) -> RouteStep:
    return RouteStep(
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        edge_id="|".join(sorted((start_node_id, end_node_id))),
        directed_edge_id=f"{start_node_id}->{end_node_id}",
        start=Position3D(start[0], start[1], 0),
        end=Position3D(end[0], end[1], 0),
        length=Position3D(start[0], start[1], 0).distance_xy(Position3D(end[0], end[1], 0)),
    )


class PathTrafficControllerTests(unittest.TestCase):
    def test_same_direction_following_respects_gap(self) -> None:
        controller = PathTrafficController(min_distance_to_obstacle_m=1.0)
        step = make_step("A", "B", (0, 0), (10, 0))

        self.assertIsNone(controller.try_enter_edge("fl_1", step))
        controller.update_progress("fl_1", step, 5.0)
        self.assertIsNone(controller.try_enter_edge("fl_2", step))

        allowance = controller.available_distance("fl_2", step, 3.5, 10.0)
        self.assertAlmostEqual(allowance.allowed_distance_m, 0.5, places=6)
        self.assertIsNone(allowance.wait_reason)

        blocked = controller.available_distance("fl_2", step, 4.2, 10.0)
        self.assertAlmostEqual(blocked.allowed_distance_m, 0.0, places=6)
        self.assertEqual(blocked.wait_reason, WAIT_REASON_LEADER_GAP)

    def test_opposite_direction_edge_is_blocked(self) -> None:
        controller = PathTrafficController()
        forward = make_step("A", "B", (0, 0), (10, 0))
        reverse = make_step("B", "A", (10, 0), (0, 0))

        self.assertIsNone(controller.try_enter_edge("fl_1", forward))
        self.assertEqual(controller.try_enter_edge("fl_2", reverse), WAIT_REASON_EDGE_CONFLICT)

        controller.leave_edge("fl_1", forward)
        self.assertIsNone(controller.try_enter_edge("fl_2", reverse))

    def test_node_conflict_blocks_entry_to_shared_node(self) -> None:
        controller = PathTrafficController()
        left_to_cross = make_step("A", "X", (0, 0), (5, 0))
        down_to_cross = make_step("B", "X", (5, -5), (5, 0))

        self.assertIsNone(controller.try_enter_edge("fl_1", left_to_cross))
        controller.update_progress("fl_1", left_to_cross, left_to_cross.length)
        self.assertIsNone(controller.enter_node("fl_1", "X"))
        controller.leave_edge("fl_1", left_to_cross)

        self.assertIsNone(controller.try_enter_edge("fl_2", down_to_cross))
        allowance = controller.available_distance(
            "fl_2",
            down_to_cross,
            down_to_cross.length - 1e-7,
            1.0,
        )
        self.assertAlmostEqual(allowance.allowed_distance_m, 0.0, places=6)
        self.assertEqual(allowance.wait_reason, WAIT_REASON_NODE_CONFLICT)

    def test_avoid_collisions_reserves_next_edge(self) -> None:
        controller = PathTrafficController(avoid_collisions=True)
        first_leg = make_step("A", "B", (0, 0), (5, 0))
        shared_next_leg = make_step("B", "C", (5, 0), (10, 0))
        competing_leg = make_step("D", "B", (5, 5), (5, 0))

        self.assertIsNone(controller.try_enter_edge("fl_1", first_leg, shared_next_leg))
        self.assertEqual(
            controller.try_enter_edge("fl_2", competing_leg, shared_next_leg),
            WAIT_REASON_RESERVATION,
        )

        relaxed = PathTrafficController(avoid_collisions=False)
        self.assertIsNone(relaxed.try_enter_edge("fl_1", first_leg, shared_next_leg))
        self.assertIsNone(relaxed.try_enter_edge("fl_2", competing_leg, shared_next_leg))

    def test_release_forklift_clears_occupancy_and_reservations(self) -> None:
        controller = PathTrafficController(avoid_collisions=True)
        first_leg = make_step("A", "B", (0, 0), (5, 0))
        next_leg = make_step("B", "C", (5, 0), (10, 0))
        competing_leg = make_step("D", "B", (5, 5), (5, 0))

        self.assertIsNone(controller.try_enter_edge("fl_1", first_leg, next_leg))
        controller.release_forklift("fl_1")

        self.assertIsNone(controller.try_enter_edge("fl_2", competing_leg, next_leg))


if __name__ == "__main__":
    unittest.main()
