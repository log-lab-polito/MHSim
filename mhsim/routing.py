"""Routing module for forklift path planning and navigation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .movement import Position3D
from .spatial import Path, WarehouseLayout


@dataclass(frozen=True)
class RouteStep:
    """A single traversable path segment in a route."""

    start_node_id: str
    end_node_id: str
    edge_id: str
    directed_edge_id: str
    start: Position3D
    end: Position3D
    length: float
    path_id: Optional[str] = None


@dataclass
class Route:
    """A complete route from start to destination."""

    waypoints: List[Position3D]
    total_distance: float
    steps: List[RouteStep] = field(default_factory=list)

    def __iter__(self):
        """Iterate through waypoints."""
        return iter(self.waypoints)


class Router:
    """Handles routing between locations in the warehouse."""

    def __init__(self, layout: WarehouseLayout):
        self.layout = layout
        self._node_positions: Dict[str, Position3D] = {}
        self._adj: Dict[str, List[Tuple[str, float, Optional[str]]]] = {}
        self._build_graph()

    @staticmethod
    def _key(p: Position3D) -> Tuple[float, float]:
        # Merge nearly-identical coordinates by rounding.
        return (round(p.x, 3), round(p.y, 3))

    @classmethod
    def _node_id(cls, p: Position3D) -> str:
        x, y = cls._key(p)
        return f"{x:.3f}:{y:.3f}"

    @staticmethod
    def _edge_id(start_node_id: str, end_node_id: str) -> str:
        first, second = sorted((start_node_id, end_node_id))
        return f"{first}|{second}"

    @staticmethod
    def _directed_edge_id(start_node_id: str, end_node_id: str) -> str:
        return f"{start_node_id}->{end_node_id}"

    def _ensure_node(self, p: Position3D, nodes: Optional[Dict[str, Position3D]] = None) -> str:
        node_positions = self._node_positions if nodes is None else nodes
        node_id = self._node_id(p)
        if node_id not in node_positions:
            x, y = self._key(p)
            node_positions[node_id] = Position3D(x, y, 0)
        return node_id

    def _add_edge(
        self,
        start_node_id: str,
        end_node_id: str,
        weight: float,
        bidirectional: bool,
        path_id: Optional[str],
        adj: Optional[Dict[str, List[Tuple[str, float, Optional[str]]]]] = None,
    ) -> None:
        adjacency = self._adj if adj is None else adj
        adjacency.setdefault(start_node_id, []).append((end_node_id, weight, path_id))
        if bidirectional:
            adjacency.setdefault(end_node_id, []).append((start_node_id, weight, path_id))

    def _build_graph(self) -> None:
        self._node_positions = {}
        self._adj = {}
        if not getattr(self.layout, "paths", None):
            return

        for path in self.layout.paths:
            waypoints = path.waypoints
            if len(waypoints) < 2:
                continue
            node_ids = [self._ensure_node(point) for point in waypoints]
            for start_node_id, end_node_id in zip(node_ids[:-1], node_ids[1:]):
                start = self._node_positions[start_node_id]
                end = self._node_positions[end_node_id]
                distance = start.distance_xy(end)
                self._add_edge(
                    start_node_id,
                    end_node_id,
                    distance,
                    path.bidirectional,
                    path.id,
                )

    def _project_onto_paths(
        self,
        position: Position3D,
        preferred_path: Optional[Path] = None,
    ) -> Optional[Tuple[Position3D, Position3D, Position3D, Optional[str]]]:
        """Project a point onto the nearest path segment."""

        def project_point(point: Position3D, a: Position3D, b: Position3D) -> Position3D:
            abx = b.x - a.x
            aby = b.y - a.y
            denom = abx * abx + aby * aby
            if denom <= 1e-12:
                return a
            t = ((point.x - a.x) * abx + (point.y - a.y) * aby) / denom
            t = max(0.0, min(1.0, t))
            return Position3D(a.x + abx * t, a.y + aby * t, 0)

        best = None
        best_dist = float("inf")
        paths = [preferred_path] if preferred_path is not None else getattr(self.layout, "paths", [])
        for path in paths:
            if path is None:
                continue
            waypoints = path.waypoints
            if len(waypoints) < 2:
                continue
            for a, b in zip(waypoints[:-1], waypoints[1:]):
                projection = project_point(position, a, b)
                distance = position.distance_xy(projection)
                if distance < best_dist:
                    best_dist = distance
                    best = (projection, a, b, path.id)
        return best

    def _clone_graph(
        self,
    ) -> tuple[Dict[str, Position3D], Dict[str, List[Tuple[str, float, Optional[str]]]]]:
        nodes = dict(self._node_positions)
        adj = {node_id: list(edges) for node_id, edges in self._adj.items()}
        return nodes, adj

    def route_between_nodes(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None,
    ) -> Route:
        """
        Create a route strictly along predefined paths using shortest-path over
        the path graph. Start/end are projected to nearest graph nodes.
        Falls back to direct route if no graph is available.
        """
        if not self._node_positions or not self._adj:
            self._build_graph()

        if not self._node_positions:
            return Route(
                waypoints=[start, end],
                total_distance=start.distance_xy(end),
                steps=[],
            )

        bias_path = self.layout.get_path(preferred_path_id) if preferred_path_id else None
        projected_start = self._project_onto_paths(start, bias_path)
        projected_end = self._project_onto_paths(end, None)
        if projected_start is None or projected_end is None:
            return Route(
                waypoints=[start, end],
                total_distance=start.distance_xy(end),
                steps=[],
            )

        start_projection, start_a, start_b, start_path_id = projected_start
        end_projection, end_a, end_b, end_path_id = projected_end

        nodes, adj = self._clone_graph()

        def ensure_node(point: Position3D) -> str:
            return self._ensure_node(point, nodes)

        def add_projection(
            projection: Position3D,
            a: Position3D,
            b: Position3D,
            path_id: Optional[str],
        ) -> str:
            projection_node_id = ensure_node(projection)
            a_node_id = ensure_node(a)
            b_node_id = ensure_node(b)

            dist_to_a = projection.distance_xy(nodes[a_node_id])
            dist_to_b = projection.distance_xy(nodes[b_node_id])
            if projection_node_id != a_node_id:
                self._add_edge(
                    projection_node_id,
                    a_node_id,
                    dist_to_a,
                    True,
                    path_id,
                    adj=adj,
                )
            if projection_node_id != b_node_id:
                self._add_edge(
                    projection_node_id,
                    b_node_id,
                    dist_to_b,
                    True,
                    path_id,
                    adj=adj,
                )
            return projection_node_id

        start_node_id = add_projection(start_projection, start_a, start_b, start_path_id)
        end_node_id = add_projection(end_projection, end_a, end_b, end_path_id)

        import heapq

        distances = {node_id: float("inf") for node_id in nodes}
        previous: Dict[str, Optional[str]] = {node_id: None for node_id in nodes}
        distances[start_node_id] = 0.0
        pq: list[tuple[float, str]] = [(0.0, start_node_id)]
        visited: set[str] = set()

        while pq:
            distance, node_id = heapq.heappop(pq)
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id == end_node_id:
                break
            for neighbor_id, weight, _path_id in adj.get(node_id, []):
                next_distance = distance + weight
                if next_distance < distances[neighbor_id]:
                    distances[neighbor_id] = next_distance
                    previous[neighbor_id] = node_id
                    heapq.heappush(pq, (next_distance, neighbor_id))

        if distances[end_node_id] == float("inf"):
            return Route(
                waypoints=[start, end],
                total_distance=start.distance_xy(end),
                steps=[],
            )

        node_path: list[str] = []
        cursor: Optional[str] = end_node_id
        while cursor is not None:
            node_path.append(cursor)
            cursor = previous[cursor]
        node_path.reverse()

        full_node_path = list(node_path)
        actual_start_node_id = ensure_node(start)
        actual_end_node_id = ensure_node(end)
        if nodes[actual_start_node_id].distance_xy(nodes[start_node_id]) > 1e-6:
            full_node_path = [actual_start_node_id] + full_node_path
        if nodes[actual_end_node_id].distance_xy(nodes[end_node_id]) > 1e-6:
            full_node_path = full_node_path + [actual_end_node_id]

        unique_waypoints: list[Position3D] = []
        for waypoint in [nodes[node_id] for node_id in full_node_path]:
            if not unique_waypoints or waypoint.distance_xy(unique_waypoints[-1]) > 1e-6:
                unique_waypoints.append(waypoint)

        steps: list[RouteStep] = []
        total_distance = 0.0
        for step_start_id, step_end_id in zip(full_node_path[:-1], full_node_path[1:]):
            step_start = nodes[step_start_id]
            step_end = nodes[step_end_id]
            length = step_start.distance_xy(step_end)
            if length <= 1e-9:
                continue

            path_id = None
            for neighbor_id, _weight, candidate_path_id in adj.get(step_start_id, []):
                if neighbor_id == step_end_id:
                    path_id = candidate_path_id
                    break

            steps.append(
                RouteStep(
                    start_node_id=step_start_id,
                    end_node_id=step_end_id,
                    edge_id=self._edge_id(step_start_id, step_end_id),
                    directed_edge_id=self._directed_edge_id(step_start_id, step_end_id),
                    start=step_start,
                    end=step_end,
                    length=length,
                    path_id=path_id,
                )
            )
            total_distance += length

        return Route(waypoints=unique_waypoints, total_distance=total_distance, steps=steps)

    def distance_between(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None,
    ) -> float:
        """Get distance between two positions."""
        route = self.route_between_nodes(start, end, preferred_path_id)
        return route.total_distance

    def nearest_path_id(self, position: Position3D) -> Optional[str]:
        """Return the ID of the nearest path to a given position."""
        if not getattr(self.layout, "paths", None):
            return None

        best_id = None
        best_dist = float("inf")
        for path in self.layout.paths:
            for waypoint in path.waypoints:
                distance = position.distance_xy(waypoint)
                if distance < best_dist:
                    best_dist = distance
                    best_id = path.id
        return best_id
