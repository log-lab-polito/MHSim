"""
Movement simulation module for 3D forklift movement.

Handles horizontal movement (with acceleration/deceleration/constant speed)
and vertical movement (load lift/lower at constant speed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple, Tuple


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
        if distance <= 0:
            return 0.0

        accel_dist = self.distance_to_max_speed()
        decel_dist = self.distance_to_decelerate_from_max()
        min_dist = accel_dist + decel_dist

        if distance >= min_dist:
            # Can reach max speed
            cruise_dist = distance - accel_dist - decel_dist
            accel_time = self.time_to_reach_max_speed()
            cruise_time = cruise_dist / self.max_speed
            decel_time = self.max_speed / self.deceleration
            return accel_time + cruise_time + decel_time
        else:
            # Cannot reach max speed; symmetric acceleration/deceleration
            # Solve: 0.5 * a * t1² + 0.5 * d * t2² = distance
            # where t1 = time to accelerate, t2 = time to decelerate
            # For symmetric: t1 = t2 = t, so: 0.5 * (a + d) * t² = distance
            # t = sqrt(2 * distance / (a + d))
            combined_accel = self.acceleration + self.deceleration
            return math.sqrt(2 * distance / combined_accel)


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
    loading_time: float  # seconds
    unloading_time: float  # seconds

    def horizontal_travel_time(self, distance_m: float) -> float:
        """Time for horizontal movement."""
        return self.horizontal.travel_time(distance_m)

    def vertical_travel_time(self, height_change_m: float) -> float:
        """Time for vertical movement."""
        return self.elevation.travel_time(height_change_m)

    def point_to_point_time(self, start: Position3D, end: Position3D) -> float:
        """Time to move from start to end (parallel vertical and horizontal)."""
        horizontal_dist = start.distance_xy(end)
        vertical_dist = abs(end.z - start.z)

        h_time = self.horizontal_travel_time(horizontal_dist)
        v_time = self.vertical_travel_time(vertical_dist)

        # Movements happen in parallel, so total time is max
        return max(h_time, v_time)


class LinearInterpolator:
    """Smooth position interpolation along a path."""

    def __init__(self, start: Position3D, end: Position3D, travel_time: float):
        self.start = start
        self.end = end
        self.travel_time = travel_time
        self.elapsed = 0.0

    def update(self, dt: float) -> Position3D:
        """Update elapsed time and return current position."""
        self.elapsed = min(self.elapsed + dt, self.travel_time)
        if self.travel_time == 0:
            return self.end

        progress = self.elapsed / self.travel_time
        return Position3D(
            self.start.x + (self.end.x - self.start.x) * progress,
            self.start.y + (self.end.y - self.start.y) * progress,
            self.start.z + (self.end.z - self.start.z) * progress,
        )

    def is_complete(self) -> bool:
        """Check if movement is complete."""
        return self.elapsed >= self.travel_time


class AcceleratingInterpolator:
    """Position interpolation with acceleration/deceleration profile.

    Implements realistic movement: accelerate -> cruise -> decelerate
    """

    def __init__(self, start: Position3D, end: Position3D, horizontal_movement: HorizontalMovement):
        self.start = start
        self.end = end
        self.horiz = horizontal_movement
        self.elapsed = 0.0

        # Calculate horizontal distance and movement profile
        self.distance = start.distance_xy(end)
        self.travel_time = horizontal_movement.travel_time(self.distance)

        # Calculate movement phases
        self.accel_time = self.horiz.time_to_reach_max_speed()
        self.accel_dist = self.horiz.distance_to_max_speed()
        self.decel_dist = self.horiz.distance_to_decelerate_from_max()

        # If distance is large enough for full profile
        if self.distance >= self.accel_dist + self.decel_dist:
            self.cruise_dist = self.distance - self.accel_dist - self.decel_dist
            self.cruise_time = self.cruise_dist / \
                self.horiz.max_speed if self.horiz.max_speed > 0 else 0
            self.decel_time = self.horiz.max_speed / self.horiz.deceleration
        else:
            # Limited distance - symmetric acceleration/deceleration
            # Distance = 0.5*a*t1² + 0.5*d*t2²
            # For symmetric: t1 = t2 = t => distance = 0.5*(a+d)*t²
            # Solve for t: t = sqrt(2*distance / (a+d))

            self.cruise_dist = 0
            self.cruise_time = 0
            combined_accel = self.horiz.acceleration + self.horiz.deceleration
            self.accel_time = math.sqrt(2 * self.distance / combined_accel)
            self.decel_time = self.accel_time

            # Recalculate accel/decel distances for this time
            self.accel_dist = 0.5 * self.horiz.acceleration * self.accel_time ** 2
            self.decel_dist = 0.5 * self.horiz.deceleration * self.decel_time ** 2

    def get_distance_at_time(self, t: float) -> float:
        """Calculate distance traveled at time t with acceleration profile."""
        if t <= 0:
            return 0.0

        # Phase 1: Acceleration
        if t <= self.accel_time:
            return 0.5 * self.horiz.acceleration * t ** 2

        # Phase 2: Cruise (if exists)
        accel_time = self.accel_time
        cruise_start_dist = self.accel_dist
        cruise_start_time = accel_time

        cruise_duration = self.cruise_dist / \
            self.horiz.max_speed if self.horiz.max_speed > 0 else 0
        cruise_end_time = cruise_start_time + cruise_duration

        if t <= cruise_end_time:
            cruise_time = t - cruise_start_time
            return cruise_start_dist + self.horiz.max_speed * cruise_time

        # Phase 3: Deceleration
        decel_start_dist = self.accel_dist + self.cruise_dist
        decel_start_time = cruise_end_time
        decel_elapsed = t - decel_start_time

        # Distance during deceleration: d = v0*t - 0.5*a*t^2
        dist_in_decel = self.horiz.max_speed * decel_elapsed - \
            0.5 * self.horiz.deceleration * decel_elapsed ** 2
        return decel_start_dist + dist_in_decel

    def update(self, dt: float) -> Position3D:
        """Update elapsed time and return current position with acceleration profile."""
        self.elapsed = min(self.elapsed + dt, self.travel_time)

        if self.travel_time == 0:
            return self.end

        # Get distance traveled using acceleration profile
        distance_traveled = self.get_distance_at_time(self.elapsed)

        # Calculate position along the path
        if self.distance > 0:
            progress = distance_traveled / self.distance
        else:
            progress = 1.0

        progress = min(progress, 1.0)

        return Position3D(
            self.start.x + (self.end.x - self.start.x) * progress,
            self.start.y + (self.end.y - self.start.y) * progress,
            self.start.z + (self.end.z - self.start.z) * progress,
        )

    def is_complete(self) -> bool:
        """Check if movement is complete."""
        return self.elapsed >= self.travel_time
