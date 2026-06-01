"""
Visualization and animation module for 3D warehouse movements.

Provides tools to record forklift movements during simulation and create
matplotlib animations showing the movement in 2D and 3D.
"""

from __future__ import annotations

import simpy
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import numpy as np

from mhsim.movement import Position3D
from mhsim.forklift import Forklift, ForkliftStatus


@dataclass
class PositionRecord:
    """Record of a position at a specific time."""
    time: float
    position: Position3D
    status: ForkliftStatus
    has_load: bool = False


@dataclass
class ForkliftTrajectory:
    """Complete trajectory of a forklift throughout simulation."""
    forklift_id: str
    records: List[PositionRecord] = field(default_factory=list)

    def add_record(self, time: float, position: Position3D, status: ForkliftStatus, has_load: bool = False):
        """Add a position record."""
        self.records.append(PositionRecord(time, position, status, has_load))

    def get_times(self) -> np.ndarray:
        """Get array of all time points."""
        return np.array([r.time for r in self.records])

    def get_positions_xy(self) -> np.ndarray:
        """Get array of (x, y) positions."""
        return np.array([(r.position.x, r.position.y) for r in self.records])

    def get_positions_xyz(self) -> np.ndarray:
        """Get array of (x, y, z) positions."""
        return np.array([(r.position.x, r.position.y, r.position.z) for r in self.records])

    def get_x_coordinates(self) -> np.ndarray:
        """Get X coordinates."""
        return np.array([r.position.x for r in self.records])

    def get_y_coordinates(self) -> np.ndarray:
        """Get Y coordinates."""
        return np.array([r.position.y for r in self.records])

    def get_z_coordinates(self) -> np.ndarray:
        """Get Z coordinates."""
        return np.array([r.position.z for r in self.records])

    def get_speeds_horizontal(self) -> np.ndarray:
        """Calculate instantaneous speed in the horizontal plane (XY only) in m/s.

        This excludes vertical (Z) movement, showing only the planar motion speed.
        Zeros out speeds when forklift is not actively MOVING to avoid aliasing artifacts.
        """
        positions_xy = self.get_positions_xy()
        times = self.get_times()

        if len(positions_xy) < 2:
            return np.array([])

        # Calculate distances between consecutive points (XY only)
        diffs = np.diff(positions_xy, axis=0)
        distances = np.linalg.norm(diffs, axis=1)

        # Calculate time differences
        dt = np.diff(times)

        # Speed = distance / time
        speeds = distances / dt

        # Add initial speed (0) to match array length
        speeds = np.concatenate([[0], speeds])

        # Zero out speeds when forklift is not in MOVING status
        # This eliminates aliasing artifacts from position recording misalignment
        speeds_filtered = np.zeros_like(speeds)
        for i, record in enumerate(self.records):
            if i < len(speeds) and record.status == ForkliftStatus.MOVING:
                speeds_filtered[i] = speeds[i]

        return speeds_filtered


class MovementRecorder:
    """Records forklift movements during simulation for later visualization."""

    def __init__(self):
        self.trajectories: Dict[str, ForkliftTrajectory] = {}

    def record(self, forklift: Forklift, time: float):
        """Record current state of a forklift."""
        if forklift.id not in self.trajectories:
            self.trajectories[forklift.id] = ForkliftTrajectory(forklift.id)

        self.trajectories[forklift.id].add_record(
            time=time,
            position=forklift.position,
            status=forklift.status,
            has_load=forklift.current_load is not None
        )

    def record_fleet(self, forklifts: List[Forklift], time: float):
        """Record all forklifts in a list."""
        for fl in forklifts:
            self.record(fl, time)

    def get_trajectory(self, forklift_id: str) -> Optional[ForkliftTrajectory]:
        """Get trajectory for a specific forklift."""
        return self.trajectories.get(forklift_id)

    def get_all_trajectories(self) -> Dict[str, ForkliftTrajectory]:
        """Get all trajectories."""
        return self.trajectories

    def clear(self):
        """Clear all recorded data."""
        self.trajectories.clear()


def create_recording_process(
    env: simpy.Environment,
    forklifts: List[Forklift],
    recorder: MovementRecorder,
    recording_interval: float = 0.1
):
    """
    Create a SimPy process that records forklift positions at regular intervals.

    Args:
        env: SimPy environment
        forklifts: List of forklifts to record
        recorder: MovementRecorder instance
        recording_interval: Time between recordings (seconds)

    Returns:
        Generator function for env.process()
    """
    def record_loop():
        while True:
            recorder.record_fleet(forklifts, env.now)
            yield env.timeout(recording_interval)

    return record_loop()


class Visualizer2D:
    """Create 2D matplotlib visualizations of forklift movements."""

    def __init__(self, trajectories: Dict[str, ForkliftTrajectory], warehouse_bounds: Optional[Tuple] = None):
        """
        Initialize 2D visualizer.

        Args:
            trajectories: Dictionary of forklift trajectories
            warehouse_bounds: Tuple of (x_min, x_max, y_min, y_max) for plot limits
        """
        self.trajectories = trajectories
        self.warehouse_bounds = warehouse_bounds

    def plot_all_trajectories(self, figsize=(12, 8), show_grid=True):
        """
        Create a 2D plot showing all forklift trajectories.

        Args:
            figsize: Figure size (width, height)
            show_grid: Whether to show grid

        Returns:
            (fig, ax) matplotlib objects
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        fig, ax = plt.subplots(figsize=figsize)

        # Plot each trajectory
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))
        for (fl_id, trajectory), color in zip(self.trajectories.items(), colors):
            xs = trajectory.get_x_coordinates()
            ys = trajectory.get_y_coordinates()

            # Plot path
            ax.plot(xs, ys, 'o-', label=fl_id, color=color,
                    markersize=3, linewidth=1.5)

            # Mark start and end
            ax.plot(xs[0], ys[0], 'g^', markersize=10, label=f"{fl_id} start")
            ax.plot(xs[-1], ys[-1], 'rs', markersize=10, label=f"{fl_id} end")

        ax.set_xlabel("X Position (m)", fontsize=12)
        ax.set_ylabel("Y Position (m)", fontsize=12)
        ax.set_title("Forklift Trajectories - 2D View",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=9)
        ax.grid(show_grid, alpha=0.3)

        if self.warehouse_bounds:
            x_min, x_max, y_min, y_max = self.warehouse_bounds
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)

        ax.set_aspect('equal')
        fig.tight_layout()
        return fig, ax

    def plot_time_series(self, figsize=(14, 10)):
        """
        Create time series plots showing X, Y, Z positions over time.

        Returns:
            (fig, axes) matplotlib objects
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        fig, axes = plt.subplots(3, 1, figsize=figsize, sharex=True)
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))

        for (fl_id, trajectory), color in zip(self.trajectories.items(), colors):
            times = trajectory.get_times()
            xs = trajectory.get_x_coordinates()
            ys = trajectory.get_y_coordinates()
            zs = trajectory.get_z_coordinates()

            axes[0].plot(times, xs, 'o-', label=fl_id,
                         color=color, markersize=2)
            axes[1].plot(times, ys, 'o-', label=fl_id,
                         color=color, markersize=2)
            axes[2].plot(times, zs, 'o-', label=fl_id,
                         color=color, markersize=2)

        axes[0].set_ylabel("X Position (m)", fontsize=11)
        axes[1].set_ylabel("Y Position (m)", fontsize=11)
        axes[2].set_ylabel("Z Position (m)", fontsize=11)
        axes[2].set_xlabel("Time (s)", fontsize=11)

        axes[0].set_title("Forklift Position Over Time",
                          fontsize=14, fontweight='bold')
        axes[0].legend(loc='best', fontsize=9)
        axes[0].grid(True, alpha=0.3)
        axes[1].grid(True, alpha=0.3)
        axes[2].grid(True, alpha=0.3)

        fig.tight_layout()
        return fig, axes


class Visualizer3D:
    """Create 3D matplotlib visualizations of forklift movements."""

    def __init__(self, trajectories: Dict[str, ForkliftTrajectory], warehouse_bounds: Optional[Tuple] = None):
        """
        Initialize 3D visualizer.

        Args:
            trajectories: Dictionary of forklift trajectories
            warehouse_bounds: Tuple of (x_min, x_max, y_min, y_max, z_min, z_max)
        """
        self.trajectories = trajectories
        self.warehouse_bounds = warehouse_bounds

    def plot_3d_trajectories(self, figsize=(14, 10), show_grid=True):
        """
        Create a 3D plot showing all forklift trajectories.

        Args:
            figsize: Figure size (width, height)
            show_grid: Whether to show grid

        Returns:
            (fig, ax) matplotlib objects
        """
        try:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        fig = plt.figure(figsize=figsize)
        ax = fig.add_subplot(111, projection='3d')

        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))

        for (fl_id, trajectory), color in zip(self.trajectories.items(), colors):
            positions = trajectory.get_positions_xyz()
            xs = positions[:, 0]
            ys = positions[:, 1]
            zs = positions[:, 2]

            # Plot path
            ax.plot(xs, ys, zs, 'o-', label=fl_id,
                    color=color, markersize=3, linewidth=1.5)

            # Mark start and end
            ax.scatter(xs[0], ys[0], zs[0], marker='^', s=100,
                       color=color, edgecolors='green', linewidth=2)
            ax.scatter(xs[-1], ys[-1], zs[-1], marker='s', s=100,
                       color=color, edgecolors='red', linewidth=2)

        ax.set_xlabel("X Position (m)", fontsize=11)
        ax.set_ylabel("Y Position (m)", fontsize=11)
        ax.set_zlabel("Z Position (m)", fontsize=11)
        ax.set_title("Forklift Trajectories - 3D View",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10)

        if self.warehouse_bounds:
            x_min, x_max, y_min, y_max, z_min, z_max = self.warehouse_bounds
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            ax.set_zlim(z_min, z_max)

        fig.tight_layout()
        return fig, ax

    def plot_elevation_profile(self, figsize=(14, 8)):
        """
        Create elevation (Z) over distance traveled.

        Returns:
            (fig, ax) matplotlib objects
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        fig, ax = plt.subplots(figsize=figsize)
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))

        for (fl_id, trajectory), color in zip(self.trajectories.items(), colors):
            positions = trajectory.get_positions_xyz()
            zs = positions[:, 2]

            # Calculate cumulative distance
            distances = [0.0]
            for i in range(1, len(positions)):
                dx = positions[i, 0] - positions[i-1, 0]
                dy = positions[i, 1] - positions[i-1, 1]
                dist = np.sqrt(dx**2 + dy**2)
                distances.append(distances[-1] + dist)

            ax.plot(distances, zs, 'o-', label=fl_id,
                    color=color, markersize=4)

        ax.set_xlabel("Distance Traveled (m)", fontsize=12)
        ax.set_ylabel("Elevation (m)", fontsize=12)
        ax.set_title("Forklift Elevation Profile",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        return fig, ax


class AnimationBuilder:
    """Builder for creating matplotlib animations of movements."""

    def __init__(self, trajectories: Dict[str, ForkliftTrajectory]):
        self.trajectories = trajectories
        self.warehouse_bounds = None
        # milliseconds between frames (higher = fewer FPS, faster to render)
        self.interval = 80  # ~12.5 FPS by default for performance
        self.show_loading = True
        self.num_frames = 300  # increased for smoother animation
        self._layout = None  # Optional warehouse layout for background overlay

    def set_warehouse_bounds(self, x_min, x_max, y_min, y_max, z_min=0, z_max=10):
        """Set warehouse bounds for the animation."""
        self.warehouse_bounds = (x_min, x_max, y_min, y_max, z_min, z_max)
        return self

    def set_frame_interval(self, interval_ms: int):
        """Set interval between animation frames in milliseconds."""
        self.interval = interval_ms
        return self

    def set_num_frames(self, num_frames: int):
        """Set number of frames in animation (more frames = smoother)."""
        self.num_frames = num_frames
        return self

    def set_show_loading(self, show: bool):
        """Whether to show loading status with different markers."""
        self.show_loading = show
        return self

    def set_layout(self, layout):
        """Set a WarehouseLayout to draw background areas and paths."""
        self._layout = layout
        return self

    def build_2d_animation(self, figsize=(12, 8), line_styles=None):
        """
        Build a 2D animation of forklift movements.

        Args:
            figsize: Figure size (width, height)
            line_styles: List of line styles for each forklift.
                        Examples: ['-', '--', '-.', ':'] for solid, dashed, dash-dot, dotted

        Returns:
            (fig, ax, animation) matplotlib objects and animation
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.animation as animation
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        # Default line styles if not provided
        if line_styles is None:
            line_styles = ['-', '--', '-.', ':',
                           '-', '--', '-.', ':', '-', '--']

        fig, ax = plt.subplots(figsize=figsize)

        # Get maximum time
        max_time = max(
            traj.get_times()[-1] for traj in self.trajectories.values() if len(traj.records) > 0
        )

        # Optional: draw warehouse background (areas, shelves, paths)
        if self._layout is not None:
            from matplotlib.patches import Rectangle, Circle
            from mhsim.spatial import PointNode, RectangularNode

            # Draw areas (inbound, outbound, home)
            areas = [
                (self._layout.inbound_area, {'edgecolor': '#388E3C'}),
                (self._layout.outbound_area, {'edgecolor': '#1976D2'}),
                (self._layout.forklifts_home, {'edgecolor': '#6A1B9A'}),
            ]
            for area, style in areas:
                if area is None:
                    continue
                if isinstance(area, PointNode):
                    # Draw point node as a circle
                    c = Circle((area.position.x, area.position.y), radius=10,
                               fill=False, lw=1.5, linestyle='--', edgecolor=style['edgecolor'], alpha=0.8)
                    ax.add_patch(c)
                    ax.text(area.position.x, area.position.y + 15,
                            area.id, color=style['edgecolor'], ha='center', va='bottom', fontsize=9)
                elif isinstance(area, RectangularNode):
                    # Draw rectangular node as a rectangle
                    r = Rectangle((area.position.x, area.position.y), area.width, area.depth,
                                  fill=False, lw=1.5, linestyle='--', edgecolor=style['edgecolor'], alpha=0.8)
                    ax.add_patch(r)
                    ax.text(area.position.x + area.width/2,
                            area.position.y + area.depth + 3,
                            area.id, color=style['edgecolor'], ha='center', va='bottom', fontsize=9)

            # Draw shelves (storage)
            if self._layout.storage and getattr(self._layout.storage, 'shelves', None):
                for shelf in self._layout.storage.shelves:
                    sr = Rectangle((shelf.position.x, shelf.position.y - shelf.cell_depth),
                                   shelf.positions_per_level * shelf.position_spacing,
                                   shelf.cell_depth,
                                   fill=False, lw=1.2, linestyle='-', edgecolor='#455A64', alpha=0.9)
                    ax.add_patch(sr)
                    ax.text(shelf.position.x,
                            shelf.position.y - shelf.cell_depth - 3,
                            shelf.id, color='#455A64', ha='left', va='top', fontsize=8)

                # Draw paths (solid lines and waypoint markers for connectivity)
            if getattr(self._layout, 'paths', None):
                for path in self._layout.paths:
                    if not path.waypoints:
                        continue
                    xs = [p.x for p in path.waypoints]
                    ys = [p.y for p in path.waypoints]
                    ax.plot(xs, ys, linestyle='-', color='#90CAF9',
                            linewidth=1.2, alpha=0.9)
                    # Subtle markers at waypoints to make connections obvious
                    ax.scatter(xs, ys, s=8, color='#2196F3', alpha=0.8)
                    # Label path near its middle
                    mid_i = len(xs)//2
                    ax.text(xs[mid_i], ys[mid_i] + 2, path.id,
                            fontsize=7, color='#42A5F5', ha='center')

        # Prepare data for forklifts
        lines = {}
        scatters = {}
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))

        for (fl_id, trajectory), color, linestyle in zip(
            self.trajectories.items(),
            colors,
            line_styles[:len(self.trajectories)]
        ):
            line, = ax.plot([], [], linestyle=linestyle, label=fl_id,
                            color=color, linewidth=2.5)
            lines[fl_id] = line
            scatter = ax.scatter([], [], s=100, color=color,
                                 edgecolors='black', linewidth=1.5)
            scatters[fl_id] = scatter

        ax.set_xlabel("X Position (m)", fontsize=12)
        ax.set_ylabel("Y Position (m)", fontsize=12)
        ax.set_title("Forklift Movement Animation",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)

        if self.warehouse_bounds:
            x_min, x_max, y_min, y_max = self.warehouse_bounds[:4]
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
        else:
            ax.autoscale_view()

        ax.set_aspect('equal')
        time_text = ax.text(
            0.02, 0.95, '', transform=ax.transAxes, fontsize=11)

        def animate(frame):
            current_time = (frame / self.num_frames) * max_time

            for fl_id, trajectory in self.trajectories.items():
                times = trajectory.get_times()
                positions_all = trajectory.get_positions_xy()

                # Find all points up to current time
                mask = times <= current_time
                if mask.any():
                    positions = positions_all[mask]

                    if len(positions) > 0:
                        lines[fl_id].set_data(positions[:, 0], positions[:, 1])

                        # Interpolate current position for smoother movement
                        idx = np.searchsorted(times, current_time)
                        if idx > 0 and idx < len(times):
                            # Linear interpolation between two points
                            t0, t1 = times[idx-1], times[idx]
                            p0, p1 = positions_all[idx-1], positions_all[idx]
                            alpha = (current_time - t0) / \
                                (t1 - t0) if t1 > t0 else 0
                            current_pos = p0 + alpha * (p1 - p0)
                            scatters[fl_id].set_offsets([current_pos])
                        else:
                            scatters[fl_id].set_offsets(positions[-1:])

            time_text.set_text(f'Time: {current_time:.2f}s')
            return list(lines.values()) + list(scatters.values()) + [time_text]

        anim = animation.FuncAnimation(
            fig, animate, frames=self.num_frames, interval=self.interval, blit=True, repeat=True
        )

        fig.tight_layout()
        return fig, ax, anim

    def build_3d_animation(self, figsize=(14, 10), line_styles=None):
        """
        Build a 3D animation of forklift movements.

        Args:
            figsize: Figure size (width, height)
            line_styles: List of line styles for each forklift.
                        Examples: ['-', '--', '-.', ':'] for solid, dashed, dash-dot, dotted

        Returns:
            (fig, ax, animation) matplotlib objects and animation
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.animation as animation
            from mpl_toolkits.mplot3d import Axes3D
        except ImportError:
            raise ImportError("matplotlib is required for visualization")

        # Default line styles if not provided
        if line_styles is None:
            line_styles = ['-', '--', '-.', ':',
                           '-', '--', '-.', ':', '-', '--']

        fig = plt.figure(figsize=figsize)
        ax = fig.add_subplot(111, projection='3d')

        max_time = max(
            traj.get_times()[-1] for traj in self.trajectories.values() if len(traj.records) > 0
        )

        lines = {}
        scatters = {}
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.trajectories)))

        for (fl_id, trajectory), color, linestyle in zip(
            self.trajectories.items(),
            colors,
            line_styles[:len(self.trajectories)]
        ):
            line, = ax.plot([], [], [], linestyle=linestyle, label=fl_id,
                            color=color, linewidth=2.5)
            lines[fl_id] = line
            scatter = ax.scatter([], [], [], s=100, color=color,
                                 edgecolors='black', linewidth=1.5)
            scatters[fl_id] = scatter

        ax.set_xlabel("X Position (m)", fontsize=11)
        ax.set_ylabel("Y Position (m)", fontsize=11)
        ax.set_zlabel("Z Position (m)", fontsize=11)
        ax.set_title("Forklift Movement Animation - 3D",
                     fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10)

        if self.warehouse_bounds:
            x_min, x_max, y_min, y_max, z_min, z_max = self.warehouse_bounds
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            ax.set_zlim(z_min, z_max)

        time_text = ax.text2D(
            0.02, 0.95, '', transform=ax.transAxes, fontsize=11)

        def animate(frame):
            current_time = (frame / self.num_frames) * max_time

            for fl_id, trajectory in self.trajectories.items():
                times = trajectory.get_times()
                positions_all = trajectory.get_positions_xyz()
                mask = times <= current_time

                if mask.any():
                    positions = positions_all[mask]

                    if len(positions) > 0:
                        lines[fl_id].set_data(positions[:, 0], positions[:, 1])
                        lines[fl_id].set_3d_properties(positions[:, 2])

                        # Interpolate current position for smoother movement
                        idx = np.searchsorted(times, current_time)
                        if idx > 0 and idx < len(times):
                            t0, t1 = times[idx-1], times[idx]
                            p0, p1 = positions_all[idx-1], positions_all[idx]
                            alpha = (current_time - t0) / \
                                (t1 - t0) if t1 > t0 else 0
                            current_pos = p0 + alpha * (p1 - p0)
                            scatters[fl_id]._offsets3d = (
                                [current_pos[0]], [current_pos[1]], [current_pos[2]])
                        else:
                            current_pos = positions[-1:]
                            scatters[fl_id]._offsets3d = (
                                current_pos[:, 0], current_pos[:, 1], current_pos[:, 2])

            time_text.set_text(f'Time: {current_time:.2f}s')
            return list(lines.values()) + list(scatters.values()) + [time_text]

        anim = animation.FuncAnimation(
            fig, animate, frames=self.num_frames, interval=self.interval, blit=False, repeat=True
        )

        fig.tight_layout()
        return fig, ax, anim


def save_animation(anim, filename: str):
    """
    Save animation to file.

    Args:
        anim: Matplotlib animation object
        filename: Output filename (e.g., 'animation.gif' or 'animation.mp4')

    Note:
        Requires ffmpeg for mp4 format, or pillow for gif format.
    """
    try:
        anim.save(filename, writer='ffmpeg' if filename.endswith(
            '.mp4') else 'pillow')
        print(f"Animation saved to {filename}")
    except Exception as e:
        print(f"Error saving animation: {e}")
