"""
Routing module for forklift path planning and navigation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from .movement import Position3D
from .spatial import Path, WarehouseLayout


@dataclass
class Route:
    """A complete route from start to destination."""
    waypoints: List[Position3D]
    total_distance: float

    def __iter__(self):
        """Iterate through waypoints."""
        return iter(self.waypoints)


class Router:
    """Handles routing between locations in the warehouse."""

    def __init__(self, layout: WarehouseLayout):
        self.layout = layout
        # Build a graph from path waypoints for multi-path routing
        self._nodes: List[Position3D] = []
        self._adj: Dict[int, List[Tuple[int, float]]] = {}
        self._build_graph()

    @staticmethod
    def _key(p: Position3D) -> Tuple[float, float]:
        # Merge nearly-identical coordinates by rounding
        return (round(p.x, 3), round(p.y, 3))

    def _index_for(self, p: Position3D) -> int:
        key = self._key(p)
        for i, n in enumerate(self._nodes):
            if self._key(n) == key:
                return i
        # New node
        self._nodes.append(Position3D(key[0], key[1], 0))
        idx = len(self._nodes) - 1
        self._adj[idx] = []
        return idx

    def _add_edge(self, i: int, j: int, w: float, bidirectional: bool):
        self._adj[i].append((j, w))
        if bidirectional:
            self._adj[j].append((i, w))

    def _build_graph(self):
        self._nodes = []
        self._adj = {}
        if not getattr(self.layout, 'paths', None):
            return
        for path in self.layout.paths:
            wps = path.waypoints
            if len(wps) < 2:
                continue
            # Add nodes and edges for consecutive waypoints
            idxs = [self._index_for(p) for p in wps]
            for a, b in zip(idxs[:-1], idxs[1:]):
                pa = self._nodes[a]
                pb = self._nodes[b]
                dist = pa.distance_xy(pb)
                self._add_edge(a, b, dist, path.bidirectional)

    def _find_node_index(self, p: Position3D) -> Optional[int]:
        key = self._key(p)
        for i, n in enumerate(self._nodes):
            if self._key(n) == key:
                return i
        return None

    def _project_onto_paths(
        self,
        position: Position3D,
        preferred_path: Optional[Path] = None,
    ) -> Optional[Tuple[Position3D, Position3D, Position3D]]:
        """Project a point onto the nearest path segment."""
        def project_point(p: Position3D, a: Position3D, b: Position3D) -> Position3D:
            abx = b.x - a.x
            aby = b.y - a.y
            denom = abx * abx + aby * aby
            if denom <= 1e-12:
                return a
            t = ((p.x - a.x) * abx + (p.y - a.y) * aby) / denom
            t = max(0.0, min(1.0, t))
            return Position3D(a.x + abx * t, a.y + aby * t, 0)

        best = None
        best_dist = float("inf")
        paths = (
            [preferred_path] if preferred_path is not None else getattr(self.layout, "paths", [])
        )
        for path in paths:
            wps = path.waypoints
            if len(wps) < 2:
                continue
            for a, b in zip(wps[:-1], wps[1:]):
                proj = project_point(position, a, b)
                d = position.distance_xy(proj)
                if d < best_dist:
                    best_dist = d
                    best = (proj, a, b)
        return best

    def route_between_nodes(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None
    ) -> Route:
        """
        Create a route strictly along predefined paths using shortest-path over
        the path graph. Start/end are projected to nearest graph nodes.
        Falls back to direct route if no graph is available.
        """
        # Ensure graph reflects latest layout
        if not self._nodes or not self._adj:
            self._build_graph()

        if not self._nodes:
            # No paths defined
            return Route(waypoints=[start, end], total_distance=start.distance_xy(end))

        bias_path = self.layout.get_path(preferred_path_id) if preferred_path_id else None
        proj_start = self._project_onto_paths(start, bias_path)
        proj_end = self._project_onto_paths(end, None)
        if proj_start is None or proj_end is None:
            return Route(waypoints=[start, end], total_distance=start.distance_xy(end))

        proj_s, seg_s_a, seg_s_b = proj_start
        proj_e, seg_e_a, seg_e_b = proj_end

        # Clone graph for projection nodes
        nodes = list(self._nodes)
        adj: Dict[int, List[Tuple[int, float]]] = {i: list(v) for i, v in self._adj.items()}

        def ensure_node(p: Position3D) -> int:
            key = self._key(p)
            for i, n in enumerate(nodes):
                if self._key(n) == key:
                    return i
            idx = len(nodes)
            nodes.append(Position3D(key[0], key[1], 0))
            adj[idx] = []
            return idx

        def add_projection(proj: Position3D, a: Position3D, b: Position3D) -> int:
            idx_proj = ensure_node(proj)
            idx_a = ensure_node(a)
            idx_b = ensure_node(b)
            dist_a = proj.distance_xy(a)
            dist_b = proj.distance_xy(b)
            if idx_proj != idx_a:
                adj[idx_proj].append((idx_a, dist_a))
                adj[idx_a].append((idx_proj, dist_a))
            if idx_proj != idx_b:
                adj[idx_proj].append((idx_b, dist_b))
                adj[idx_b].append((idx_proj, dist_b))
            return idx_proj

        i_start = add_projection(proj_s, seg_s_a, seg_s_b)
        i_end = add_projection(proj_e, seg_e_a, seg_e_b)

        # Dijkstra for shortest path
        import heapq
        N = len(nodes)
        dist = [float('inf')] * N
        prev = [-1] * N
        dist[i_start] = 0.0
        pq = [(0.0, i_start)]
        visited = [False] * N
        while pq:
            d, u = heapq.heappop(pq)
            if visited[u]:
                continue
            visited[u] = True
            if u == i_end:
                break
            for v, w in adj.get(u, []):
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        # Reconstruct
        if dist[i_end] == float('inf'):
            # Unreachable, fallback to direct
            return Route(waypoints=[start, end], total_distance=start.distance_xy(end))

        path_idxs = []
        u = i_end
        while u != -1:
            path_idxs.append(u)
            u = prev[u]
        path_idxs.reverse()

        waypoints = [start] + [nodes[i] for i in path_idxs] + [end]
        # Remove duplicates and compress identical consecutive points
        unique = []
        for wp in waypoints:
            if not unique or wp.distance_xy(unique[-1]) > 1e-6:
                unique.append(wp)

        total_dist = 0.0
        for i in range(len(unique) - 1):
            total_dist += unique[i].distance_xy(unique[i + 1])

        return Route(waypoints=unique, total_distance=total_dist)

    def distance_between(
        self,
        start: Position3D,
        end: Position3D,
        preferred_path_id: Optional[str] = None
    ) -> float:
        """Get distance between two positions."""
        route = self.route_between_nodes(start, end, preferred_path_id)
        return route.total_distance

    def nearest_path_id(self, position: Position3D) -> Optional[str]:
        """Return the ID of the nearest path to a given position.

        Uses simple minimum distance to any waypoint on each path as a proxy
        for proximity. If no paths exist, returns None.
        """
        if not getattr(self.layout, 'paths', None):
            return None

        best_id = None
        best_dist = float('inf')

        for path in self.layout.paths:
            for wp in path.waypoints:
                d = position.distance_xy(wp)
                if d < best_dist:
                    best_dist = d
                    best_id = path.id

        return best_id
