"""Routing module for path-guided forklift navigation."""

from __future__ import annotations

import math
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


@dataclass(frozen=True)
class RouteMotionSegment:
    """A physical motion segment used to traverse a routed path."""

    kind: str
    start: Position3D
    end: Position3D
    length: float
    step_index: Optional[int] = None
    node_id: Optional[str] = None
    start_progress_m: float = 0.0
    end_progress_m: float = 0.0
    center: Optional[Position3D] = None
    radius: float = 0.0
    start_angle_rad: float = 0.0
    sweep_angle_rad: float = 0.0

    def position_at(self, progress_m: float) -> Position3D:
        """Interpolate a position along this motion segment."""
        if self.length <= 1e-9:
            return self.end

        fraction = max(0.0, min(1.0, progress_m / self.length))
        if self.kind == "arc" and self.center is not None and self.radius > 0:
            angle = self.start_angle_rad + self.sweep_angle_rad * fraction
            return Position3D(
                self.center.x + math.cos(angle) * self.radius,
                self.center.y + math.sin(angle) * self.radius,
                0,
            )

        return Position3D(
            self.start.x + (self.end.x - self.start.x) * fraction,
            self.start.y + (self.end.y - self.start.y) * fraction,
            0,
        )


@dataclass
class Route:
    """A complete route from start to destination."""

    waypoints: List[Position3D]
    total_distance: float
    steps: List[RouteStep] = field(default_factory=list)
    raw_distance: float = 0.0
    motion_segments: List[RouteMotionSegment] = field(default_factory=list)

    def __iter__(self):
        """Iterate through waypoints."""
        return iter(self.waypoints)


class Router:
    """Build path-guided routes over the designed warehouse network."""

    def __init__(self, layout: WarehouseLayout):
        self.layout = layout
        self._node_positions: Dict[str, Position3D] = {}
        self._adj: Dict[str, List[Tuple[str, float, Optional[str]]]] = {}
        self._build_graph()

    @staticmethod
    def _key(p: Position3D) -> Tuple[float, float]:
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

    def _ensure_node(
        self,
        p: Position3D,
        nodes: Optional[Dict[str, Position3D]] = None,
    ) -> str:
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
            if len(path.waypoints) < 2:
                continue
            node_ids = [self._ensure_node(point) for point in path.waypoints]
            for start_node_id, end_node_id in zip(node_ids[:-1], node_ids[1:]):
                start = self._node_positions[start_node_id]
                end = self._node_positions[end_node_id]
                self._add_edge(
                    start_node_id,
                    end_node_id,
                    start.distance_xy(end),
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
            if path is None or len(path.waypoints) < 2:
                continue
            for a, b in zip(path.waypoints[:-1], path.waypoints[1:]):
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

    @staticmethod
    def position_along_step(step: RouteStep, progress_m: float) -> Position3D:
        """Interpolate a position along a routed path step."""
        if step.length <= 1e-9:
            return step.end
        fraction = max(0.0, min(1.0, progress_m / step.length))
        return Position3D(
            step.start.x + (step.end.x - step.start.x) * fraction,
            step.start.y + (step.end.y - step.start.y) * fraction,
            0,
        )

    @staticmethod
    def _unit_direction(start: Position3D, end: Position3D) -> tuple[float, float]:
        distance = start.distance_xy(end)
        if distance <= 1e-9:
            return (0.0, 0.0)
        return ((end.x - start.x) / distance, (end.y - start.y) / distance)

    @staticmethod
    def _left_normal(direction: tuple[float, float]) -> tuple[float, float]:
        return (-direction[1], direction[0])

    @staticmethod
    def _right_normal(direction: tuple[float, float]) -> tuple[float, float]:
        return (direction[1], -direction[0])

    def _build_motion_segments(
        self,
        steps: List[RouteStep],
        turn_radius: float,
    ) -> tuple[List[RouteMotionSegment], float]:
        if not steps:
            return ([], 0.0)

        start_trims = [0.0] * len(steps)
        end_trims = [0.0] * len(steps)
        arc_segments: list[Optional[RouteMotionSegment]] = [None] * max(0, len(steps) - 1)

        requested_radius = max(0.0, turn_radius)
        if requested_radius > 0.0:
            for index in range(len(steps) - 1):
                incoming = steps[index]
                outgoing = steps[index + 1]
                incoming_dir = self._unit_direction(incoming.start, incoming.end)
                outgoing_dir = self._unit_direction(outgoing.start, outgoing.end)
                if incoming_dir == (0.0, 0.0) or outgoing_dir == (0.0, 0.0):
                    continue

                dot = max(-1.0, min(1.0, incoming_dir[0] * outgoing_dir[0] + incoming_dir[1] * outgoing_dir[1]))
                cross = incoming_dir[0] * outgoing_dir[1] - incoming_dir[1] * outgoing_dir[0]
                turn_angle = math.acos(dot)
                if abs(cross) <= 1e-9 or turn_angle <= 1e-6 or turn_angle >= math.pi - 1e-6:
                    continue

                tan_half_angle = math.tan(turn_angle / 2.0)
                if tan_half_angle <= 1e-9:
                    continue

                max_trim = min(
                    max(0.0, incoming.length * 0.5 - 1e-6),
                    max(0.0, outgoing.length * 0.5 - 1e-6),
                )
                requested_trim = requested_radius * tan_half_angle
                trim = min(requested_trim, max_trim)
                if trim <= 1e-6:
                    continue

                effective_radius = trim / tan_half_angle
                tangent_in = self.position_along_step(incoming, incoming.length - trim)
                tangent_out = self.position_along_step(outgoing, trim)
                normal = (
                    self._left_normal(incoming_dir)
                    if cross > 0
                    else self._right_normal(incoming_dir)
                )
                center = Position3D(
                    tangent_in.x + normal[0] * effective_radius,
                    tangent_in.y + normal[1] * effective_radius,
                    0,
                )
                start_angle = math.atan2(tangent_in.y - center.y, tangent_in.x - center.x)
                end_angle = math.atan2(tangent_out.y - center.y, tangent_out.x - center.x)
                sweep_angle = end_angle - start_angle
                if cross > 0 and sweep_angle < 0:
                    sweep_angle += 2 * math.pi
                elif cross < 0 and sweep_angle > 0:
                    sweep_angle -= 2 * math.pi

                start_trims[index + 1] = trim
                end_trims[index] = trim
                arc_segments[index] = RouteMotionSegment(
                    kind="arc",
                    start=tangent_in,
                    end=tangent_out,
                    length=abs(sweep_angle) * effective_radius,
                    node_id=incoming.end_node_id,
                    center=center,
                    radius=effective_radius,
                    start_angle_rad=start_angle,
                    sweep_angle_rad=sweep_angle,
                )

        motion_segments: List[RouteMotionSegment] = []
        total_distance = 0.0
        for index, step in enumerate(steps):
            start_progress = start_trims[index]
            end_progress = step.length - end_trims[index]
            straight_length = max(0.0, end_progress - start_progress)
            if straight_length > 1e-9:
                segment = RouteMotionSegment(
                    kind="straight",
                    start=self.position_along_step(step, start_progress),
                    end=self.position_along_step(step, end_progress),
                    length=straight_length,
                    step_index=index,
                    start_progress_m=start_progress,
                    end_progress_m=end_progress,
                )
                motion_segments.append(segment)
                total_distance += straight_length

            if index < len(arc_segments):
                arc_segment = arc_segments[index]
                if arc_segment is not None and arc_segment.length > 1e-9:
                    motion_segments.append(arc_segment)
                    total_distance += arc_segment.length

        return (motion_segments, total_distance)

    def route_between_nodes(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None,
        turn_radius: float = 0.0,
    ) -> Route:
        """
        Create a route strictly along predefined paths using shortest-path over
        the path graph. Start/end are projected to nearest graph nodes.
        """
        if not self._node_positions or not self._adj:
            self._build_graph()

        if not self._node_positions:
            return Route(
                waypoints=[start, end],
                total_distance=start.distance_xy(end),
                steps=[],
                raw_distance=start.distance_xy(end),
            )

        bias_path = self.layout.get_path(preferred_path_id) if preferred_path_id else None
        projected_start = self._project_onto_paths(start, bias_path)
        projected_end = self._project_onto_paths(end, None)
        if projected_start is None or projected_end is None:
            return Route(
                waypoints=[start, end],
                total_distance=start.distance_xy(end),
                steps=[],
                raw_distance=start.distance_xy(end),
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
                self._add_edge(projection_node_id, a_node_id, dist_to_a, True, path_id, adj=adj)
            if projection_node_id != b_node_id:
                self._add_edge(projection_node_id, b_node_id, dist_to_b, True, path_id, adj=adj)
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
                raw_distance=start.distance_xy(end),
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

        motion_segments, motion_distance = self._build_motion_segments(steps, turn_radius)
        return Route(
            waypoints=unique_waypoints,
            total_distance=motion_distance if motion_segments else total_distance,
            steps=steps,
            raw_distance=total_distance,
            motion_segments=motion_segments,
        )

    def distance_between(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None,
        turn_radius: float = 0.0,
    ) -> float:
        """Get distance between two positions."""
        return self.route_between_nodes(start, end, preferred_path_id, turn_radius=turn_radius).total_distance

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
