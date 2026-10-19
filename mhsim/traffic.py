"""Shared path-guided traffic control for forklift movement."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    ) -> None:
        """Configure the traffic policy for a fleet sharing one path network.

        Args:
            min_distance_to_obstacle_m: Minimum gap in metres a follower keeps
                behind the forklift ahead of it on the same directed edge.
                Negative values are clamped to zero.
            avoid_collisions: When true, forklifts reserve nodes and edges
                before entering them and wait when a reservation is refused.
                When false, occupancy is still tracked but never blocks
                movement, which is the deterministic-parity default.
            debug_enabled: Record every allow and block decision into
                `debug_events`. Off by default because the log grows with
                every movement step.
        """
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


# ---------------------------------------------------------------------------------------
# AnyLogic line-guided interaction (docs/forklift_rules/R8_line_guided_traffic.md)
# ---------------------------------------------------------------------------------------

_VISION_EPS_M = 1.0e-4
_LOOKAHEAD_BRAKING_FACTOR = 1.5  # look-ahead = Lb/2 + 1.5 * braking distance + W/2
_FOLLOW_FRACTION = 0.5  # brake towards half the leader's speed along the vision direction


def _rect_corners(x: float, y: float, heading: float, length: float, width: float) -> list[tuple[float, float]]:
    c, s = math.cos(heading), math.sin(heading)
    hl, hw = length / 2.0, width / 2.0
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]


def _point_segment_distance(p, a, b) -> float:
    ux, uy = b[0] - a[0], b[1] - a[1]
    l2 = ux * ux + uy * uy
    if l2 == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / l2))
    return math.hypot(p[0] - a[0] - t * ux, p[1] - a[1] - t * uy)


def _segments_distance(p, q, a, b) -> float:
    def cross(o, s, t):
        return (s[0] - o[0]) * (t[1] - o[1]) - (s[1] - o[1]) * (t[0] - o[0])

    d1, d2, d3, d4 = cross(a, b, p), cross(a, b, q), cross(p, q, a), cross(p, q, b)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(_point_segment_distance(p, a, b), _point_segment_distance(q, a, b),
               _point_segment_distance(a, p, q), _point_segment_distance(b, p, q))


def _inside(point, quad) -> bool:
    sign = None
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        c = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
        if abs(c) < 1e-12:
            continue
        if sign is None:
            sign = c > 0
        elif (c > 0) != sign:
            return False
    return True


def _rect_distance(first, second) -> float:
    if any(_inside(p, second) for p in first) or any(_inside(q, first) for q in second):
        return 0.0
    return min(
        _segments_distance(first[i], first[(i + 1) % 4], second[j], second[(j + 1) % 4])
        for i in range(4)
        for j in range(4)
    )


def _circle_meets_rect(cx: float, cy: float, radius: float, quad) -> bool:
    if _inside((cx, cy), quad):
        return True
    return any(_point_segment_distance((cx, cy), quad[j], quad[(j + 1) % 4]) <= radius for j in range(4))


def _snap_right_angle(angle: float) -> float:
    angle = math.atan2(math.sin(angle), math.cos(angle))
    quarters = abs(angle) / (math.pi / 2.0)
    nearest = round(quarters)
    if abs(nearest - quarters) < 1e-4:
        return math.copysign(nearest * math.pi / 2.0, angle)
    return angle


def _advance(speed: float, acceleration: float, target: float, dt: float) -> tuple[float, float]:
    """Distance and speed after ``dt`` while accelerating towards ``target`` and then holding it."""
    if dt <= 0.0:
        return 0.0, speed
    if acceleration == 0.0:
        return speed * dt, speed
    t_reach = max(0.0, (target - speed) / acceleration)
    if dt <= t_reach:
        return speed * dt + 0.5 * acceleration * dt * dt, speed + acceleration * dt
    distance = speed * t_reach + 0.5 * acceleration * t_reach * t_reach
    return distance + target * (dt - t_reach), target


@dataclass
class _Vision:
    seen: bool = False
    touch: bool = False
    ignore: bool = False
    release_at_m: float = math.nan


@dataclass
class _Track:
    """What the coordinator knows about one transporter."""

    order: int
    forklift: object
    mode: str = "idle"  # move | proc | rack | idle
    segments: list = field(default_factory=list)
    arrival_m: float = 0.0
    plan_m: float = 0.0
    t0: float = 0.0
    d0: float = 0.0
    v0: float = 0.0
    a: float = 0.0
    vt: float = 0.0
    vision: Dict[int, _Vision] = field(default_factory=dict)
    departed_at: float = -math.inf
    # Distance travelled before the current movement; the ignore range is odometer-based.
    odometer_base_m: float = 0.0
    # (x, y, heading) inside the rack during a rack transfer.
    rack_pose: Optional[tuple] = None


class LineGuidedTraffic:
    """AnyLogic-style vision interaction between line-guided transporters (rule R8).

    One instance is shared by a fleet. Each forklift reports its movement to it, and
    asks it for its speed profile on the global controller ticks and on its own
    route-boundary, departure and arrival updates. Nothing is reserved: transporters
    slow down, stop and pass each other only through what their vision sees.
    """

    def __init__(
        self,
        *,
        body_length_m: float = 1.0,
        body_width_m: float = 1.0,
        min_distance_to_obstacle_m: float = 1.0,
    ) -> None:
        """Configure the shared interaction model.

        Args:
            body_length_m: Transporter length (AnyLogic Forklift agent: 1 m).
            body_width_m: Transporter width (AnyLogic Forklift agent: 1 m).
            min_distance_to_obstacle_m: Fleet minimum distance to obstacle
                (AnyLogic default 1 m).
        """
        self.body_length_m = body_length_m
        self.body_width_m = body_width_m
        self.min_distance_m = min_distance_to_obstacle_m
        self._tracks: Dict[str, _Track] = {}
        self._ordered: list[_Track] = []
        self._last_tick: Optional[float] = None

    # -- registry and state -------------------------------------------------------------
    def register(self, forklift: object) -> None:
        """Add a forklift; creation order decides the right-of-way tie-break."""
        track = _Track(order=len(self._ordered), forklift=forklift)
        self._tracks[forklift.id] = track
        self._ordered.append(track)

    def _track(self, forklift: object) -> _Track:
        return self._tracks[forklift.id]

    def _odometer(self, track: _Track, t: float) -> float:
        return track.odometer_base_m + self._distance_speed(track, t)[0]

    def _distance_speed(self, track: _Track, t: float) -> tuple[float, float]:
        if track.mode != "move":
            return track.d0, 0.0
        distance, speed = _advance(track.v0, track.a, track.vt, t - track.t0)
        return min(track.d0 + distance, track.arrival_m), speed

    def _pose(self, track: _Track, distance_m: float) -> tuple[float, float, float]:
        progress = 0.0
        last = None
        for segment in track.segments:
            last = segment
            if distance_m <= progress + segment.length + 1e-12:
                local = max(0.0, distance_m - progress)
                return self._segment_pose(segment, local)
            progress += segment.length
        if last is None:
            position = track.forklift.position
            return position.x, position.y, 0.0
        return self._segment_pose(last, last.length)

    @staticmethod
    def _segment_pose(segment, local_m: float) -> tuple[float, float, float]:
        point = segment.position_at(local_m)
        if segment.kind == "arc" and segment.center is not None and segment.radius > 0:
            fraction = 0.0 if segment.length <= 1e-12 else max(0.0, min(1.0, local_m / segment.length))
            angle = segment.start_angle_rad + segment.sweep_angle_rad * fraction
            heading = angle + math.copysign(math.pi / 2.0, segment.sweep_angle_rad)
        else:
            heading = math.atan2(segment.end.y - segment.start.y, segment.end.x - segment.start.x)
        return point.x, point.y, heading

    def _rect(self, track: _Track, t: float):
        if track.mode == "rack" and track.rack_pose is not None:
            x, y, heading = track.rack_pose
            return _rect_corners(x, y, heading, self.body_length_m, self.body_width_m), (x, y, heading)
        distance, _ = self._distance_speed(track, t)
        x, y, heading = self._pose(track, distance)
        return _rect_corners(x, y, heading, self.body_length_m, self.body_width_m), (x, y, heading)

    def _vision_offsets(self, speed: float, remaining_m: float, deceleration: float) -> tuple[list[float], float]:
        braking = speed * speed / (2.0 * deceleration) if deceleration > 0 else 0.0
        look = self.body_length_m / 2.0 + _LOOKAHEAD_BRAKING_FACTOR * braking + self.body_width_m / 2.0
        look = max(0.0, min(look, remaining_m - _VISION_EPS_M))
        radius = self.body_width_m / 2.0 + self.min_distance_m
        count = 2 + max(math.ceil((look - 3.0 * radius) / (2.0 * radius)), 0)
        first = min(look, radius)
        offsets = [first] * count
        if first == look:
            look += _VISION_EPS_M
        offsets[-1] = look
        if count > 2:
            step = (look - radius) / (count - 1)
            for i in range(1, count - 1):
                offsets[i] = offsets[i - 1] + step
        return offsets, radius

    # -- rules ----------------------------------------------------------------------------
    @staticmethod
    def _updated(track: _Track, arrival: bool) -> bool:
        # Moving units are updated; so is a unit in a rack transfer, which keeps its own
        # vision and right of way while the others cannot see it; a unit loading or
        # unloading at a node only takes its arrival update.
        return track.mode in ("move", "rack") or (arrival and track.mode == "proc")

    def _update(self, track: _Track, t: float, arrival: bool = False) -> None:
        if not self._updated(track, arrival):
            return
        horizontal = track.forklift.movement_profile.horizontal
        acceleration = max(0.0, horizontal.acceleration)
        deceleration = max(0.0, horizontal.deceleration)
        max_speed = max(0.0, horizontal.max_speed)
        distance, speed = self._distance_speed(track, t)
        remaining = max(0.0, track.plan_m - distance) if track.mode == "move" else 0.0
        braking = speed * speed / (2.0 * deceleration) if deceleration > 0 else math.inf
        to_arrival = max(0.0, track.arrival_m - distance) if track.mode == "move" else 0.0
        free_target = 0.0 if braking >= to_arrival - 1e-12 and speed > 0.0 else max_speed
        offsets, radius = self._vision_offsets(speed, remaining, deceleration)
        if track.mode == "rack" and track.rack_pose is not None:
            circles = [track.rack_pose for _ in offsets]
        else:
            circles = [self._pose(track, distance + offset) for offset in offsets]
        own_rect, (_, _, own_heading) = self._rect(track, t)
        chord = (circles[-1][0] - circles[0][0], circles[-1][1] - circles[0][1])
        vision_dir = math.atan2(chord[1], chord[0]) if math.hypot(*chord) > 1e-12 else own_heading
        hard = slow = False
        target = math.inf
        for other in self._ordered:
            if other is track:
                continue
            entry = track.vision.setdefault(other.order, _Vision())
            entry.touch = False
            if other.mode not in ("move", "proc"):
                track.vision[other.order] = _Vision()
                continue
            other_rect, (_, _, other_heading) = self._rect(other, t)
            if not any(_circle_meets_rect(cx, cy, radius, other_rect) for cx, cy, _ in circles):
                track.vision[other.order] = _Vision()
                continue
            entry.seen = True
            gap = _rect_distance(own_rect, other_rect) - self.min_distance_m
            if gap < _VISION_EPS_M:
                entry.touch = True
            if entry.ignore:
                continue
            if gap < _VISION_EPS_M:
                hard = True
            other_speed = self._distance_speed(other, t)[1] if other.mode == "move" else 0.0
            along = math.cos(_snap_right_angle(other_heading - vision_dir)) * other_speed
            if deceleration > 0 and gap <= speed * speed / deceleration and along < speed:
                slow = True
                target = 0.0 if along <= 0.0 else min(along * _FOLLOW_FRACTION, target)
        if track.mode != "move":
            return
        if hard:
            speed, accel, aim = 0.0, 0.0, 0.0
        elif slow:
            accel, aim = -deceleration, target
        elif speed > free_target:
            accel, aim = -deceleration, free_target
        elif speed < free_target:
            accel, aim = acceleration, free_target
        else:
            accel, aim = 0.0, free_target
        track.t0, track.d0, track.v0, track.a, track.vt = t, distance, speed, accel, aim

    def _resolve(self, track: _Track, t: float, arrival: bool = False) -> None:
        if not self._updated(track, arrival):
            return
        distance = self._odometer(track, t)
        seen = [order for order, entry in track.vision.items() if entry.seen]
        _, (ux, uy, _) = self._rect(track, t)
        for order in seen:
            entry = track.vision[order]
            other = self._ordered[order]
            if entry.ignore and distance > entry.release_at_m:
                entry.ignore = False
                entry.release_at_m = math.nan
            if not entry.touch or entry.ignore:
                continue
            reverse = other.vision.get(track.order)
            mutual = reverse is not None and reverse.seen and reverse.touch
            _, (ox, oy, oh) = self._rect(other, t)
            in_front = (ux - ox) * math.cos(oh) + (uy - oy) * math.sin(oh) >= 0.0
            if mutual or in_front:
                others_seen = sum(1 for e in other.vision.values() if e.seen)
                wins = (track.order < other.order) if (len(seen) == 1 and others_seen == 1) else True
            else:
                wins = False
            if wins:
                entry.ignore = True
                entry.release_at_m = distance + 1.0 + self.body_length_m * (2 if track.order < other.order else 4)

    def _tick(self, t: float) -> None:
        # A transporter departing at this very instant takes its own departure update
        # after the tick, so the tick leaves it out.
        movers = [tr for tr in self._ordered if abs(tr.departed_at - t) > 1e-12]
        for track in movers:
            self._update(track, t)
        for track in movers:
            self._resolve(track, t)

    # -- interface used by Forklift -------------------------------------------------------
    def begin_move(self, forklift: object, segments: list, arrival_m: float, plan_m: float, t: float, speed: float) -> None:
        """A movement starts (departure or re-dispatch)."""
        track = self._track(forklift)
        track.departed_at = t
        track.odometer_base_m += track.d0
        track.mode = "move"
        track.rack_pose = None
        track.segments = list(segments)
        track.arrival_m, track.plan_m = arrival_m, plan_m
        track.t0, track.d0, track.v0, track.a, track.vt = t, 0.0, speed, 0.0, speed

    def report(self, forklift: object, t: float, distance_m: float, speed: float) -> None:
        """A movement slice ended: record the exact state, keeping the current profile."""
        track = self._track(forklift)
        if track.mode != "move" or abs(track.t0 - t) < 1e-6:
            # Not moving, or already updated at this instant by a fleet-wide tick (whose
            # clock may differ from this forklift's by floating-point drift).
            return
        accel, aim = track.a, track.vt
        if (accel > 0 and speed >= aim - 1e-12) or (accel < 0 and speed <= aim + 1e-12):
            speed, accel = aim, 0.0
        track.t0, track.d0, track.v0, track.a = t, distance_m, speed, accel

    def decide(self, forklift: object, t: float, tick: bool) -> tuple[float, float, float]:
        """Speed profile ``(speed, acceleration, target speed)`` after an update at ``t``."""
        track = self._track(forklift)
        if tick:
            if self._last_tick is None or abs(self._last_tick - t) > 1e-6:
                self._last_tick = t
                self._tick(t)
        else:
            self._update(track, t)
            self._resolve(track, t)
        return track.v0, track.a, track.vt

    def arrive(self, forklift: object, t: float, processing: bool) -> None:
        """A movement ended at its destination."""
        track = self._track(forklift)
        track.t0, track.d0, track.v0, track.a, track.vt = t, track.arrival_m, 0.0, 0.0, 0.0
        track.mode = "proc" if processing else "idle"
        if processing:
            for order, entry in track.vision.items():
                if not entry.ignore:
                    continue
                other = self._ordered[order]
                reverse = other.vision.get(track.order)
                if reverse is not None and not reverse.ignore and reverse.seen and reverse.touch:
                    reverse.ignore = True
                    other_distance = self._odometer(other, t)
                    reverse.release_at_m = (
                        other_distance + 1.0 + self.body_length_m * (2 if other.order < track.order else 4)
                    )
                    entry.ignore = False
            self._update(track, t, arrival=True)
            self._resolve(track, t, arrival=True)

    def interrupt(self, forklift: object, t: float, distance_m: float, speed: float) -> None:
        """A movement was taken over mid-way (R3); the continuation follows at once."""
        track = self._track(forklift)
        track.t0, track.d0, track.v0, track.a, track.vt = t, distance_m, speed, 0.0, speed

    def position_of(self, forklift: object, t: float):
        """Exact position of a moving forklift at ``t``, or None when it is not moving."""
        track = self._tracks.get(forklift.id)
        if track is None or track.mode != "move":
            return None
        distance, _ = self._distance_speed(track, t)
        x, y, _ = self._pose(track, distance)
        return type(forklift.position)(x, y, forklift.position.z)

    def set_processing(self, forklift: object, visible: bool = True, pose: Optional[tuple] = None) -> None:
        """The forklift loads or unloads (not updated).

        At a node it stays where it is and others still see it. A rack transfer
        (``visible=False``) takes it off the network into the rack, where others do not
        see it. ``pose`` is where it stands in the rack.
        """
        track = self._track(forklift)
        track.mode = "proc" if visible else "rack"
        track.rack_pose = None if visible else pose
        track.v0 = track.a = track.vt = 0.0

    def set_idle(self, forklift: object) -> None:
        """The forklift was released and stands idle (not seen by others)."""
        track = self._track(forklift)
        if track.mode in ("proc", "rack"):
            track.mode = "idle"
        track.rack_pose = None

    def clear_vision(self, forklift: object) -> None:
        """Start a fresh vision state (released after a delivery and seized again in place)."""
        self._track(forklift).vision = {}
