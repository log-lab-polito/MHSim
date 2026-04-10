"""Shared path-guided traffic control for forklift movement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .routing import RouteStep


WAIT_REASON_LEADER_GAP = "leader_gap"
WAIT_REASON_EDGE_CONFLICT = "edge_conflict"
WAIT_REASON_NODE_CONFLICT = "node_conflict"
WAIT_REASON_RESERVATION = "reservation_wait"

TRAFFIC_WAIT_REASONS = (
    WAIT_REASON_LEADER_GAP,
    WAIT_REASON_EDGE_CONFLICT,
    WAIT_REASON_NODE_CONFLICT,
    WAIT_REASON_RESERVATION,
)


@dataclass(frozen=True)
class TrafficAllowance:
    """Movement allowance for the current simulation tick."""

    allowed_distance_m: float
    wait_reason: Optional[str] = None


class PathTrafficController:
    """Coordinates shared path occupancy for routed forklift movement."""

    def __init__(
        self,
        *,
        min_distance_to_obstacle_m: float = 1.0,
        avoid_collisions: bool = False,
        debug_enabled: bool = False,
    ):
        self.min_distance_to_obstacle_m = max(0.0, min_distance_to_obstacle_m)
        self.avoid_collisions = avoid_collisions
        self.debug_enabled = debug_enabled
        self.debug_events: list[dict[str, object]] = []

        self._edge_occupants: Dict[str, set[str]] = {}
        self._directed_progress: Dict[str, Dict[str, float]] = {}
        self._current_step_by_forklift: Dict[str, RouteStep] = {}
        self._node_occupants: Dict[str, str] = {}
        self._node_reservations: Dict[str, str] = {}
        self._edge_reservations: Dict[str, str] = {}
        self._reserved_nodes_by_forklift: Dict[str, set[str]] = {}
        self._reserved_edges_by_forklift: Dict[str, set[str]] = {}

    def _debug(self, event: str, **payload: object) -> None:
        if not self.debug_enabled:
            return
        data = {"event": event}
        data.update(payload)
        self.debug_events.append(data)

    def release_forklift(self, forklift_id: str) -> None:
        """Release all occupancy and reservations held by a forklift."""
        current_step = self._current_step_by_forklift.pop(forklift_id, None)
        if current_step is not None:
            self.leave_edge(forklift_id, current_step)

        occupied_nodes = [
            node_id
            for node_id, occupant_id in self._node_occupants.items()
            if occupant_id == forklift_id
        ]
        for node_id in occupied_nodes:
            self.leave_node(forklift_id, node_id)

        self._release_reserved_nodes(forklift_id)
        self._release_reserved_edges(forklift_id)

    def _release_reserved_nodes(self, forklift_id: str, *, exclude: set[str] | None = None) -> None:
        exclude = exclude or set()
        reserved_nodes = self._reserved_nodes_by_forklift.get(forklift_id, set())
        retained_nodes = {node_id for node_id in reserved_nodes if node_id in exclude}
        for node_id in list(reserved_nodes):
            if node_id in exclude:
                continue
            if self._node_reservations.get(node_id) == forklift_id:
                self._node_reservations.pop(node_id, None)
        if retained_nodes:
            self._reserved_nodes_by_forklift[forklift_id] = retained_nodes
        else:
            self._reserved_nodes_by_forklift.pop(forklift_id, None)

    def _release_reserved_edges(self, forklift_id: str, *, exclude: set[str] | None = None) -> None:
        exclude = exclude or set()
        reserved_edges = self._reserved_edges_by_forklift.get(forklift_id, set())
        retained_edges = {edge_id for edge_id in reserved_edges if edge_id in exclude}
        for edge_id in list(reserved_edges):
            if edge_id in exclude:
                continue
            if self._edge_reservations.get(edge_id) == forklift_id:
                self._edge_reservations.pop(edge_id, None)
        if retained_edges:
            self._reserved_edges_by_forklift[forklift_id] = retained_edges
        else:
            self._reserved_edges_by_forklift.pop(forklift_id, None)

    def _reserve_node(self, forklift_id: str, node_id: str) -> bool:
        occupant_id = self._node_occupants.get(node_id)
        reservation_owner = self._node_reservations.get(node_id)
        if occupant_id not in (None, forklift_id):
            return False
        if reservation_owner not in (None, forklift_id):
            return False
        self._node_reservations[node_id] = forklift_id
        self._reserved_nodes_by_forklift.setdefault(forklift_id, set()).add(node_id)
        return True

    def _reserve_edge(self, forklift_id: str, edge_id: str) -> bool:
        reservation_owner = self._edge_reservations.get(edge_id)
        if reservation_owner not in (None, forklift_id):
            return False
        occupants = self._edge_occupants.get(edge_id, set())
        if occupants and occupants != {forklift_id}:
            return False
        self._edge_reservations[edge_id] = forklift_id
        self._reserved_edges_by_forklift.setdefault(forklift_id, set()).add(edge_id)
        return True

    def _reserve_future(self, forklift_id: str, step: RouteStep, next_step: Optional[RouteStep]) -> bool:
        if not self._reserve_node(forklift_id, step.end_node_id):
            return False
        if next_step is not None and not self._reserve_edge(forklift_id, next_step.edge_id):
            self._release_reserved_nodes(forklift_id, exclude=set())
            return False
        return True

    def try_enter_edge(
        self,
        forklift_id: str,
        step: RouteStep,
        next_step: Optional[RouteStep] = None,
    ) -> Optional[str]:
        """Attempt to place a forklift on an edge."""
        current_step = self._current_step_by_forklift.get(forklift_id)
        if current_step is not None and current_step.directed_edge_id == step.directed_edge_id:
            return None

        if self.avoid_collisions and not self._reserve_future(forklift_id, step, next_step):
            return WAIT_REASON_RESERVATION

        reservation_owner = self._edge_reservations.get(step.edge_id)
        if reservation_owner not in (None, forklift_id):
            return WAIT_REASON_RESERVATION

        opposite_occupants = set()
        for directed_edge_id, occupants in self._directed_progress.items():
            if directed_edge_id == step.directed_edge_id:
                continue
            if step.edge_id != self._current_edge_id_for_directed(directed_edge_id):
                continue
            opposite_occupants.update(occupants)
        if opposite_occupants - {forklift_id}:
            return WAIT_REASON_EDGE_CONFLICT

        self._edge_occupants.setdefault(step.edge_id, set()).add(forklift_id)
        self._directed_progress.setdefault(step.directed_edge_id, {})[forklift_id] = 0.0
        self._current_step_by_forklift[forklift_id] = step

        # Consumes any prior reservation once the edge is actually entered.
        if self._edge_reservations.get(step.edge_id) == forklift_id:
            self._edge_reservations.pop(step.edge_id, None)
            reserved_edges = self._reserved_edges_by_forklift.get(forklift_id)
            if reserved_edges is not None:
                reserved_edges.discard(step.edge_id)
                if not reserved_edges:
                    self._reserved_edges_by_forklift.pop(forklift_id, None)

        self._debug(
            "enter_edge",
            forklift_id=forklift_id,
            edge_id=step.edge_id,
            directed_edge_id=step.directed_edge_id,
        )
        return None

    def _current_edge_id_for_directed(self, directed_edge_id: str) -> Optional[str]:
        occupants = self._directed_progress.get(directed_edge_id)
        if not occupants:
            return None
        sample_forklift_id = next(iter(occupants))
        step = self._current_step_by_forklift.get(sample_forklift_id)
        return None if step is None else step.edge_id

    def update_progress(self, forklift_id: str, step: RouteStep, progress_m: float) -> None:
        """Update the tracked progress of a forklift along its current edge."""
        self._directed_progress.setdefault(step.directed_edge_id, {})[forklift_id] = progress_m

    def available_distance(
        self,
        forklift_id: str,
        step: RouteStep,
        progress_m: float,
        requested_distance_m: float,
    ) -> TrafficAllowance:
        """Return how much the forklift may move along the current edge this tick."""
        requested = max(0.0, requested_distance_m)
        if requested <= 0:
            return TrafficAllowance(0.0, None)

        self.update_progress(forklift_id, step, progress_m)

        limit = requested
        wait_reason: Optional[str] = None

        directed_progress = self._directed_progress.get(step.directed_edge_id, {})
        leader_progress = min(
            (
                other_progress
                for other_id, other_progress in directed_progress.items()
                if other_id != forklift_id and other_progress >= progress_m - 1e-9
            ),
            default=None,
        )
        if leader_progress is not None:
            follower_limit = max(0.0, leader_progress - progress_m - self.min_distance_to_obstacle_m)
            if follower_limit < limit:
                limit = follower_limit
                if limit <= 1e-9:
                    wait_reason = WAIT_REASON_LEADER_GAP

        remaining_edge_distance = max(0.0, step.length - progress_m)
        if progress_m + limit >= step.length - 1e-9 and not self._can_enter_node(forklift_id, step.end_node_id):
            node_limit = max(0.0, remaining_edge_distance - 1e-6)
            if node_limit < limit:
                limit = node_limit
            if limit <= 1e-9:
                wait_reason = WAIT_REASON_NODE_CONFLICT

        return TrafficAllowance(limit, wait_reason)

    def _can_enter_node(self, forklift_id: str, node_id: str) -> bool:
        occupant_id = self._node_occupants.get(node_id)
        if occupant_id not in (None, forklift_id):
            return False
        reservation_owner = self._node_reservations.get(node_id)
        return reservation_owner in (None, forklift_id)

    def enter_node(self, forklift_id: str, node_id: str) -> Optional[str]:
        """Attempt to occupy a node."""
        if not self._can_enter_node(forklift_id, node_id):
            return WAIT_REASON_NODE_CONFLICT
        self._node_occupants[node_id] = forklift_id
        if self._node_reservations.get(node_id) == forklift_id:
            self._node_reservations.pop(node_id, None)
            reserved_nodes = self._reserved_nodes_by_forklift.get(forklift_id)
            if reserved_nodes is not None:
                reserved_nodes.discard(node_id)
                if not reserved_nodes:
                    self._reserved_nodes_by_forklift.pop(forklift_id, None)
        self._debug("enter_node", forklift_id=forklift_id, node_id=node_id)
        return None

    def leave_node(self, forklift_id: str, node_id: str) -> None:
        """Release a node occupied by a forklift."""
        if self._node_occupants.get(node_id) == forklift_id:
            self._node_occupants.pop(node_id, None)
            self._debug("leave_node", forklift_id=forklift_id, node_id=node_id)

    def leave_edge(self, forklift_id: str, step: RouteStep) -> None:
        """Release the current edge occupancy for a forklift."""
        current_progress = self._directed_progress.get(step.directed_edge_id)
        if current_progress is not None:
            current_progress.pop(forklift_id, None)
            if not current_progress:
                self._directed_progress.pop(step.directed_edge_id, None)

        edge_occupants = self._edge_occupants.get(step.edge_id)
        if edge_occupants is not None:
            edge_occupants.discard(forklift_id)
            if not edge_occupants:
                self._edge_occupants.pop(step.edge_id, None)

        if self._current_step_by_forklift.get(forklift_id) == step:
            self._current_step_by_forklift.pop(forklift_id, None)

        self._debug(
            "leave_edge",
            forklift_id=forklift_id,
            edge_id=step.edge_id,
            directed_edge_id=step.directed_edge_id,
        )
