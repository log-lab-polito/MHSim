#!/usr/bin/env python3
"""
Enhanced animation with smooth movements and speed/acceleration visualization.

Demonstrates:
1. Smoother animations with more frames and interpolation
2. Speed vs time plots
3. Acceleration vs time plots

Usage:
    python run_smooth_animation.py
    python run_smooth_animation.py quick
    python -m case_studies.model_1_simpy.run_smooth_animation
"""

from .visualization import (
    MovementRecorder,
    create_recording_process,
    Visualizer2D,
    AnimationBuilder,
)
from .params import Model1Params
from .setup import create_warehouse_with_standard_config
from .movement import Position3D
import simpy
import matplotlib.pyplot as plt
import sys

import matplotlib
matplotlib.use('TkAgg')


def smooth_animation_with_metrics():
    """Create smooth animation and plot speed/acceleration."""
    print("\n" + "="*70)
    print("🎬 SMOOTH ANIMATION WITH SPEED & ACCELERATION METRICS")
    print("="*70)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    # Record with high frequency (0.05s) to capture continuous movement
    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.05))

    def complex_movement(fl, forklift_id):
        """Complex movement pattern - different for each forklift."""
        # Define unique paths for each forklift
        if forklift_id == 0:
            # Forklift 0: Inbound → Rack 1 → Rack 2 → Outbound
            positions = [
                layout.inbound_area.get_access_point(),
                layout.storage.get_shelf("rack_1").get_access_point(),
                layout.storage.get_shelf("rack_2").get_access_point(),
                layout.outbound_area.get_access_point(),
                layout.inbound_area.get_access_point(),
            ]
        elif forklift_id == 1:
            # Forklift 1: Outbound → Rack 2 → Rack 1 → Inbound (opposite direction)
            positions = [
                layout.outbound_area.get_access_point(),
                layout.storage.get_shelf("rack_2").get_access_point(),
                layout.storage.get_shelf("rack_1").get_access_point(),
                layout.inbound_area.get_access_point(),
                layout.outbound_area.get_access_point(),
            ]
        else:
            # Forklift 2: Inbound → Rack 1 → Inbound (shorter route, repeat)
            positions = [
                layout.inbound_area.get_access_point(),
                layout.storage.get_shelf("rack_1").get_access_point(),
                layout.inbound_area.get_access_point(),
                layout.storage.get_shelf("rack_2").get_access_point(),
                layout.inbound_area.get_access_point(),
            ]

        for pos in positions:
            yield from fl.move_to(pos, update_interval=0.05)
            yield env.timeout(0.5)  # Brief pause at each location

    for i, fl in enumerate(fleet.forklifts):
        env.process(complex_movement(fl, i))

    print("\n⏳ Running simulation...")
    # Progress reporter: print every 10s of sim time

    def progress():
        total = 200
        interval = 10
        while env.now < total:
            yield env.timeout(interval)
            pct = (env.now/total)*100
            print(f"   ... progress {env.now:.0f}/{total}s ({pct:.0f}%)")
    env.process(progress())
    env.run(until=200)

    print(f"\n✅ Simulation complete!")
    print(f"   Recorded {len(recorder.trajectories)} forklifts")

    for fl_id, traj in recorder.trajectories.items():
        print(f"   {fl_id}: {len(traj.records)} position records")

    # Create visualizations
    print("\n📊 Creating visualizations...")

    # 1. Speed and Acceleration plots
    print("   1. Speed & Acceleration vs Time...")
    viz = Visualizer2D(recorder.get_all_trajectories())
    fig_metrics, (ax_speed, ax_accel) = viz.plot_speed_and_acceleration()

    # 2. Smooth 2D animation
    print("   2. Smooth 2D Animation...")
    builder = AnimationBuilder(recorder.get_all_trajectories())
    # Draw areas and paths as background
    builder.set_layout(layout)
    # AnyLogic layout: X=80-430 (inbound to outbound), Y=260-453 (home to storage)
    builder.set_warehouse_bounds(50, 480, 240, 480)
    # Lower FPS for performance
    builder.set_frame_interval(80)  # ~12.5 FPS
    builder.set_num_frames(240)      # Fewer frames for faster rendering

    fig_anim, ax_anim, anim = builder.build_2d_animation()

    print("\n" + "="*70)
    print("✅ VISUALIZATIONS READY!")
    print("="*70)
    print("\nTwo windows will appear:")
    print("  1. Speed & Acceleration vs Time (static plot)")
    print("     - Shows velocity changes during acceleration/deceleration")
    print("     - Shows acceleration spikes when starting/stopping")
    print()
    print("  2. Smooth 2D Animation (animated)")
    print("     - 300 frames with interpolation for smooth movement")
    print("     - 50ms between frames (20 FPS)")
    print("     - You'll see smooth velocity changes")
    print()
    print("Close each window when done viewing.")
    print("="*70 + "\n")

    plt.show()

    return recorder, fig_metrics, anim


def quick_smooth_animation():
    """Quick example with just smooth animation."""
    print("\n" + "="*70)
    print("🎬 QUICK SMOOTH ANIMATION")
    print("="*70)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    # Record with high frequency (0.05s) to capture continuous movement
    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.05))

    def simple_movement(fl, forklift_id):
        # Loop on predefined path grid only (no free movement)
        path_points = [
            Position3D(230, 355, 0),
            Position3D(290, 355, 0),
            Position3D(350, 355, 0),
            Position3D(350, 405, 0),
            Position3D(350, 453, 0),
            Position3D(290, 453, 0),
            Position3D(230, 453, 0),
            Position3D(230, 405, 0),
            Position3D(230, 355, 0),
        ]

        # Offset start for variety
        offset = forklift_id % len(path_points)
        loop = path_points[offset:] + path_points[:offset]

        for pos in loop:
            # Route via nearest path automatically
            yield from fl.move_to(pos)
            yield env.timeout(0.5)

    for i, fl in enumerate(fleet.forklifts):
        env.process(simple_movement(fl, i))

    # Progress reporter
    def progress_q():
        total = 100
        interval = 10
        while env.now < total:
            yield env.timeout(interval)
            pct = (env.now/total)*100
            print(f"   ... quick progress {env.now:.0f}/{total}s ({pct:.0f}%)")
    env.process(progress_q())
    env.run(until=100)  # Limit simulation time

    # Create smooth animation
    builder = AnimationBuilder(recorder.get_all_trajectories())
    builder.set_layout(layout)
    # AnyLogic layout: X=80-430, Y=260-453
    builder.set_warehouse_bounds(50, 480, 240, 480)
    builder.set_frame_interval(80)   # ~12.5 FPS for performance
    builder.set_num_frames(300)      # Reasonable total frames

    fig, ax, anim = builder.build_2d_animation()

    print("\n✅ Ultra-smooth animation ready! (500 frames @ 33 FPS)")
    print("   You should see very smooth point movement")

    plt.show()

    return recorder, anim


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'quick':
        quick_smooth_animation()
    else:
        smooth_animation_with_metrics()
