"""Spatial nodes module for warehouse layout.

Defines various node types for storage areas, picking zones, and shelves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from .movement import Position3D


@dataclass
class Node(ABC):
    """Base class for spatial nodes."""
    id: str
    position: Position3D

    @abstractmethod
    def get_access_point(self) -> Position3D:
        """Get the point from which a forklift accesses this node."""
        pass


@dataclass
class PointNode(Node):
    """A single point in 3D space."""

    def get_access_point(self) -> Position3D:
        """Return the node position itself, since a point has no extent.

        Returns:
            The node's own coordinate.
        """
        return self.position


@dataclass
class RectangularNode(Node):
    """A rectangular area in 3D space."""
    position: Position3D
    width: float  # x dimension (meters)
    depth: float  # y dimension (meters)
    height: float  # z dimension (meters)

    def get_access_point(self) -> Position3D:
        """Get center point of the rectangle at ground level."""
        return Position3D(
            self.position.x + self.width / 2,
            self.position.y + self.depth / 2,
            0,
        )


@dataclass
class Shelf(Node):
    """Warehouse shelf with multiple levels and positions."""
    levels: int  # number of vertical levels
    positions_per_level: int  # number of storage cells per level
    cell_depth: float = 1.0  # meters
    level_height: float = 1.5  # meters (height between levels)
    position_spacing: float = 1.2  # meters (spacing between positions)

    def get_cell_position(self, level: int, position: int) -> Position3D:
        """Get 3D position of a cell."""
        if level < 0 or level >= self.levels:
            raise ValueError(f"Level {level} out of range [0, {self.levels})")
        if position < 0 or position >= self.positions_per_level:
            raise ValueError(
                f"Position {position} out of range [0, {self.positions_per_level})"
            )

        z = self.position.z + level * self.level_height
        x = self.position.x + position * self.position_spacing
        y = self.position.y

        return Position3D(x, y, z)

    def get_access_point(self) -> Position3D:
        """Get front-center access point of shelf."""
        return Position3D(
            self.position.x + (self.positions_per_level - 1) *
            self.position_spacing / 2,
            self.position.y - self.cell_depth,  # In front of the shelf
            0,
        )


@dataclass
class Storage:
    """Collection of AnyLogic-style rack shelves for warehouse storage."""
    shelves: List[Shelf] = field(default_factory=list)

    def add_shelf(self, shelf: Shelf) -> None:
        """Add a shelf to storage."""
        self.shelves.append(shelf)

    def get_shelf(self, shelf_id: str) -> Optional[Shelf]:
        """Get shelf by ID."""
        for shelf in self.shelves:
            if shelf.id == shelf_id:
                return shelf
        return None


@dataclass
class Path:
    """A path connecting nodes with waypoints."""
    id: str
    waypoints: List[Position3D] = field(default_factory=list)
    bidirectional: bool = True

    def add_waypoint(self, position: Position3D) -> None:
        """Add a waypoint to the path."""
        self.waypoints.append(position)

    def get_total_distance(self) -> float:
        """Get total distance along the path."""
        if len(self.waypoints) < 2:
            return 0.0

        total = 0.0
        for i in range(len(self.waypoints) - 1):
            total += self.waypoints[i].distance_xy(self.waypoints[i + 1])
        return total

    def get_point_at_distance(self, distance: float) -> Optional[Position3D]:
        """Get position at given distance along path."""
        if distance < 0 or not self.waypoints:
            return None

        cumulative = 0.0
        for i in range(len(self.waypoints) - 1):
            start = self.waypoints[i]
            end = self.waypoints[i + 1]
            segment_dist = start.distance_xy(end)

            if cumulative + segment_dist >= distance:
                # Point is on this segment
                remaining = distance - cumulative
                return start.move_towards(end, remaining)

            cumulative += segment_dist

        return self.waypoints[-1]  # End of path


@dataclass
class WarehouseLayout:
    """Defines the designed movement layout for a material-handling model."""
    inbound_area: Node
    outbound_area: Node
    forklifts_home: Optional[RectangularNode] = None
    storage: Optional[Storage] = None
    paths: List[Path] = field(default_factory=list)

    def add_path(self, path: Path) -> None:
        """Add a movement path."""
        self.paths.append(path)

    def get_path(self, path_id: str) -> Optional[Path]:
        """Get path by ID."""
        for path in self.paths:
            if path.id == path_id:
                return path
        return None
