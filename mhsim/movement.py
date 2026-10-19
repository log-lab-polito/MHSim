"""Movement simulation module for 3D forklift movement.

Handles horizontal movement (with acceleration/deceleration/constant speed)
and vertical movement (load lift/lower at constant speed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple


def clamp01(value: float) -> float:
    """Clamp a numeric value into the inclusive [0, 1] interval."""
    return min(max(float(value), 0.0), 1.0)


def constant_accel_speed(start_speed: float, acceleration: float, time_s: float) -> float:
    """Speed after ``time_s`` under constant acceleration."""
    return start_speed + acceleration * max(0.0, time_s)


def constant_accel_distance(
    start_speed: float,
    acceleration: float,
    time_s: float,
) -> float:
    """Distance covered after ``time_s`` under constant acceleration."""
    elapsed = max(0.0, time_s)
    return start_speed * elapsed + 0.5 * acceleration * elapsed * elapsed


def distance_to_speed(
    start_speed: float,
    acceleration: float,
    target_speed: float,
) -> float:
    """Distance needed to reach ``target_speed`` from ``start_speed``."""
    if start_speed == target_speed:
        return 0.0
    if acceleration == 0.0:
        return math.inf
    if math.copysign(1.0, target_speed - start_speed) != math.copysign(
        1.0,
        acceleration,
    ):
        return math.copysign(math.inf, target_speed - start_speed)
    elapsed = (target_speed - start_speed) / acceleration
    return constant_accel_distance(start_speed, acceleration, elapsed)


def time_to_cover_distance(
    start_speed: float,
    acceleration: float,
    distance: float,
) -> float:
    """Solve non-negative travel time for a distance under constant acceleration."""
    if distance <= 0.0:
        return 0.0
    if acceleration == 0.0:
        return math.inf if start_speed <= 0.0 else distance / start_speed
    discriminant = start_speed * start_speed + 2.0 * acceleration * distance
    if discriminant < 0.0:
        return math.inf
    root = math.sqrt(discriminant)
    candidates = [
        (root - start_speed) / acceleration,
        (-root - start_speed) / acceleration,
    ]
    nonnegative = [value for value in candidates if value >= -1e-12]
    return max(0.0, min(nonnegative)) if nonnegative else math.inf


class Position3D(NamedTuple):
    """3D position in warehouse."""
    x: float
    y: float
    z: float  # elevation/height

    def distance_to(self, other: Position3D) -> float:
        """Euclidean distance to another position (3D)."""
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )

    def distance_xy(self, other: Position3D) -> float:
        """Horizontal distance (ignoring elevation)."""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def sqr_distance_to(self, other: Position3D) -> float:
        """Squared Euclidean distance to another position."""
        return (
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )

    def sqr_distance_xy(self, other: Position3D) -> float:
        """Squared horizontal distance, useful for comparison-only checks."""
        return (self.x - other.x) ** 2 + (self.y - other.y) ** 2

    def move_towards(self, target: Position3D, distance: float) -> Position3D:
        """Move towards target by given distance (3D)."""
        total_dist = self.distance_to(target)
        if total_dist <= distance:
            return target

        direction = (
            (target.x - self.x) / total_dist,
            (target.y - self.y) / total_dist,
            (target.z - self.z) / total_dist,
        )
        return Position3D(
            self.x + direction[0] * distance,
            self.y + direction[1] * distance,
            self.z + direction[2] * distance,
        )


@dataclass(frozen=True)
class HorizontalTravelProfile:
    """Solved horizontal travel profile for one distance."""

    distance: float
    travel_time: float
    peak_speed: float
    accel_time: float
    accel_dist: float
    cruise_time: float
    cruise_dist: float
    decel_time: float
    decel_dist: float
    acceleration: float
    deceleration: float

    def distance_at_time(self, time_s: float) -> float:
        """Distance traveled at ``time_s`` within this solved profile."""
        t = max(0.0, time_s)
        if t <= self.accel_time:
            return constant_accel_distance(0.0, self.acceleration, t)

        cruise_end_time = self.accel_time + self.cruise_time
        if t <= cruise_end_time:
            return self.accel_dist + self.peak_speed * (t - self.accel_time)

        decel_elapsed = t - cruise_end_time
        distance = (
            self.accel_dist
            + self.cruise_dist
            + constant_accel_distance(self.peak_speed, -self.deceleration, decel_elapsed)
        )
        return max(0.0, min(self.distance, distance))


@dataclass
class HorizontalMovement:
    """Horizontal movement profile with acceleration/deceleration."""
    max_speed: float  # m/s
    acceleration: float  # m/s²
    deceleration: float  # m/s²

    def time_to_reach_max_speed(self) -> float:
        """Time to accelerate from 0 to max speed."""
        return self.max_speed / self.acceleration

    def distance_to_max_speed(self) -> float:
        """Distance covered while accelerating to max speed."""
        return 0.5 * self.acceleration * self.time_to_reach_max_speed() ** 2

    def distance_to_decelerate_from_max(self) -> float:
        """Distance covered while decelerating from max speed to 0."""
        return 0.5 * self.deceleration * (self.max_speed / self.deceleration) ** 2

    def min_distance_for_profile(self) -> float:
        """Minimum distance needed for full acceleration + deceleration."""
        return self.distance_to_max_speed() + self.distance_to_decelerate_from_max()

    def travel_time(self, distance: float) -> float:
        """Calculate time to travel a given distance with optimal speed profile."""
        return self.solve_profile(distance).travel_time

    def _profile_from_speed(
        self, distance: float, initial_speed: float
    ) -> tuple[float, float, float, float, float]:
        """Phases of the fastest profile from ``initial_speed`` to rest at ``distance``.

        Returns:
            ``(v0, peak_speed, accel_time, cruise_time, decel_time)``.
        """
        a, d, vmax = self.acceleration, self.deceleration, self.max_speed
        v0 = max(0.0, initial_speed)
        if vmax > 0.0:
            v0 = min(v0, vmax)
        if d <= 0.0:
            speed = vmax if vmax > 0.0 else v0
            return v0, speed, 0.0, (distance / speed if speed > 0.0 else math.inf), 0.0
        braking = v0 * v0 / (2.0 * d)
        if braking >= distance:
            return v0, v0, 0.0, 0.0, v0 / d
        if a <= 0.0:
            cruise = (distance - braking) / v0 if v0 > 0.0 else math.inf
            return v0, v0, 0.0, cruise, v0 / d
        to_max = (vmax * vmax - v0 * v0) / (2.0 * a)
        from_max = vmax * vmax / (2.0 * d)
        if to_max + from_max <= distance:
            return v0, vmax, (vmax - v0) / a, (distance - to_max - from_max) / vmax, vmax / d
        peak = math.sqrt((distance + v0 * v0 / (2.0 * a)) / (1.0 / (2.0 * a) + 1.0 / (2.0 * d)))
        return v0, peak, (peak - v0) / a, 0.0, peak / d

    def state_at(
        self, distance: float, time_s: float, initial_speed: float = 0.0
    ) -> tuple[float, float]:
        """Distance travelled and speed ``time_s`` into the profile to rest at ``distance``.

        Args:
            distance: Planned distance to come to rest, in metres.
            time_s: Time since the profile started, in seconds.
            initial_speed: Speed when the profile started, in m/s.

        Returns:
            ``(distance_m, speed_mps)``.
        """
        v0, peak, t_acc, t_cruise, t_dec = self._profile_from_speed(distance, initial_speed)
        t = max(0.0, time_s)
        if t <= t_acc:
            return v0 * t + 0.5 * self.acceleration * t * t, v0 + self.acceleration * t
        s_acc = v0 * t_acc + 0.5 * self.acceleration * t_acc * t_acc
        if t <= t_acc + t_cruise:
            return s_acc + peak * (t - t_acc), peak
        s_cruise = s_acc + peak * t_cruise
        e = min(t - t_acc - t_cruise, t_dec)
        return (
            min(distance, s_cruise + peak * e - 0.5 * self.deceleration * e * e),
            max(0.0, peak - self.deceleration * e),
        )

    def arrival_time(self, distance: float, overshoot: float, initial_speed: float = 0.0) -> float:
        """Time to cover ``distance`` on a profile planned to rest ``overshoot`` further on.

        AnyLogic plans every movement to come to rest beyond its target and reports the
        destination as reached while still braking (``docs/forklift_rules/R1_arrival_tolerance.md``).

        Args:
            distance: Distance travelled until arrival, in metres.
            overshoot: Planned distance still left at arrival, in metres.
            initial_speed: Speed at the start of the movement, in m/s (R3 re-dispatch).

        Returns:
            Arrival time in seconds from the start of the movement.
        """
        plan = distance + max(0.0, overshoot)
        _, peak, t_acc, t_cruise, t_dec = self._profile_from_speed(plan, initial_speed)
        total = t_acc + t_cruise + t_dec
        if overshoot <= 0.0:
            return total
        d = self.deceleration
        if d > 0.0 and overshoot <= peak * peak / (2.0 * d):
            return total - math.sqrt(2.0 * overshoot / d)
        low, high = 0.0, total
        for _ in range(100):
            mid = 0.5 * (low + high)
            if self.state_at(plan, mid, initial_speed)[0] < distance:
                low = mid
            else:
                high = mid
        return high

    def solve_profile(self, distance: float) -> HorizontalTravelProfile:
        """Solve the triangular/trapezoidal profile for a distance."""
        if distance <= 0:
            return HorizontalTravelProfile(
                distance=0.0,
                travel_time=0.0,
                peak_speed=0.0,
                accel_time=0.0,
                accel_dist=0.0,
                cruise_time=0.0,
                cruise_dist=0.0,
                decel_time=0.0,
                decel_dist=0.0,
                acceleration=self.acceleration,
                deceleration=self.deceleration,
            )

        accel_dist = self.distance_to_max_speed()
        decel_dist = self.distance_to_decelerate_from_max()
        min_dist = accel_dist + decel_dist

        if distance >= min_dist:
            # Can reach max speed
            cruise_dist = distance - accel_dist - decel_dist
            accel_time = self.time_to_reach_max_speed()
            cruise_time = cruise_dist / self.max_speed
            decel_time = self.max_speed / self.deceleration
            travel_time = accel_time + cruise_time + decel_time
            peak_speed = self.max_speed
        else:
            # Cannot reach max speed; triangular profile with peak speed below max.
            # Solve: distance = 0.5 * v^2 * (1/a + 1/d)
            # => v_peak = sqrt(2 * distance * a * d / (a + d))
            # total_time = v_peak * (1/a + 1/d)
            a = self.acceleration
            d = self.deceleration
            if a <= 0 or d <= 0:
                return HorizontalTravelProfile(
                    distance=distance,
                    travel_time=float("inf"),
                    peak_speed=0.0,
                    accel_time=0.0,
                    accel_dist=0.0,
                    cruise_time=0.0,
                    cruise_dist=0.0,
                    decel_time=0.0,
                    decel_dist=0.0,
                    acceleration=a,
                    deceleration=d,
                )
            peak_speed = math.sqrt(2 * distance * a * d / (a + d))
            accel_time = peak_speed / a
            decel_time = peak_speed / d
            accel_dist = constant_accel_distance(0.0, a, accel_time)
            decel_dist = constant_accel_distance(peak_speed, -d, decel_time)
            cruise_dist = 0.0
            cruise_time = 0.0
            travel_time = accel_time + decel_time

        return HorizontalTravelProfile(
            distance=distance,
            travel_time=travel_time,
            peak_speed=peak_speed,
            accel_time=accel_time,
            accel_dist=accel_dist,
            cruise_time=cruise_time,
            cruise_dist=cruise_dist,
            decel_time=decel_time,
            decel_dist=decel_dist,
            acceleration=self.acceleration,
            deceleration=self.deceleration,
        )


@dataclass
class VerticalMovement:
    """Vertical movement (elevation) profile with constant speed."""
    speed: float  # m/s (positive direction)

    def travel_time(self, distance: float) -> float:
        """Time to move vertically by given distance."""
        if self.speed <= 0:
            return float('inf')
        return abs(distance) / self.speed


@dataclass
class MovementProfile:
    """Combined 3D movement profile."""
    horizontal: HorizontalMovement
    elevation: VerticalMovement

    def horizontal_travel_time(self, distance_m: float) -> float:
        """Time for horizontal movement."""
        return self.horizontal.travel_time(distance_m)

    def vertical_travel_time(self, height_change_m: float) -> float:
        """Time for vertical movement."""
        return self.elevation.travel_time(height_change_m)


class AcceleratingInterpolator:
    """Position interpolation with acceleration/deceleration profile.

    Implements realistic movement: accelerate -> cruise -> decelerate
    """

    def __init__(
        self,
        start: Position3D,
        end: Position3D,
        horizontal_movement: HorizontalMovement,
    ) -> None:
        """Solve the speed profile for one straight leg between two points.

        Args:
            start: Leg origin.
            end: Leg destination. Only the XY distance is used; elevation is
                handled separately by `VerticalMovement`.
            horizontal_movement: Speed and acceleration limits to solve against.
        """
        self.start = start
        self.end = end
        self.horiz = horizontal_movement
        self.elapsed = 0.0

        self.distance = start.distance_xy(end)
        self.profile = horizontal_movement.solve_profile(self.distance)
        self.travel_time = self.profile.travel_time
        self.peak_speed = self.profile.peak_speed
        self.accel_time = self.profile.accel_time
        self.accel_dist = self.profile.accel_dist
        self.cruise_time = self.profile.cruise_time
        self.cruise_dist = self.profile.cruise_dist
        self.decel_time = self.profile.decel_time
        self.decel_dist = self.profile.decel_dist

    def get_distance_at_time(self, t: float) -> float:
        """Calculate distance traveled at time t with acceleration profile."""
        return self.profile.distance_at_time(t)

    def update(self, dt: float) -> Position3D:
        """Update elapsed time and return current position with acceleration profile."""
        self.elapsed = min(self.elapsed + dt, self.travel_time)

        if self.travel_time == 0:
            return self.end

        # For pure Z movement (XY distance = 0), use time-based progress
        if self.distance == 0:
            # Pure vertical movement - use time-based interpolation
            progress = self.elapsed / self.travel_time if self.travel_time > 0 else 1.0
        else:
            # Get distance traveled using acceleration profile
            distance_traveled = self.get_distance_at_time(self.elapsed)
            # Calculate position along the path
            progress = distance_traveled / self.distance

        progress = min(progress, 1.0)

        return Position3D(
            self.start.x + (self.end.x - self.start.x) * progress,
            self.start.y + (self.end.y - self.start.y) * progress,
            self.start.z + (self.end.z - self.start.z) * progress,
        )

    def is_complete(self) -> bool:
        """Check if movement is complete."""
        return self.elapsed >= self.travel_time
