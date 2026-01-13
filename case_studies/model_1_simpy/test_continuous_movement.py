#!/usr/bin/env python3
"""
Test continuous movement - verifies that forklifts move smoothly not in discrete jumps.
"""

from model_1_simpy.visualization import (
    MovementRecorder,
    create_recording_process,
    Visualizer2D,
    AnimationBuilder,
)
from model_1_simpy.params import Model1Params
from model_1_simpy.setup import create_warehouse_with_standard_config
import simpy
import matplotlib.pyplot as plt
import matplotlib
import sys
sys.path.insert(0, '..')

matplotlib.use('TkAgg')


print("\n" + "="*70)
print("🎬 TESTING CONTINUOUS MOVEMENT")
print("="*70)

env = simpy.Environment()
params = Model1Params()
layout, router, fleet = create_warehouse_with_standard_config(env, params)

# Record at 0.05s intervals to capture smooth motion
recorder = MovementRecorder()
env.process(create_recording_process(
    env, fleet.forklifts, recorder, recording_interval=0.05))


def task(fl):
    """Simple movement task."""
    positions = [
        layout.inbound_area.get_access_point(),
        layout.storage.get_shelf("rack_1").get_access_point(),
        layout.outbound_area.get_access_point(),
    ]
    for pos in positions:
        # Use continuous movement with 0.05s update intervals
        yield from fl.move_to(pos, update_interval=0.05)
        yield env.timeout(1)  # Brief pause


# Run with just one forklift for clarity
for fl in fleet.forklifts[:1]:
    env.process(task(fl))

print("\n⏳ Running simulation...")
env.run(until=80)

traj = recorder.trajectories[fleet.forklifts[0].id]
times = traj.get_times()
positions = traj.get_positions_xy()
speeds = traj.get_speeds()

print(f"\n✅ Simulation complete!")
print(f"   Recorded: {len(times)} position records")
print(f"   Unique positions: {len(set(map(tuple, positions)))}")
print(f"   Time range: {times[0]:.2f}s to {times[-1]:.2f}s")
print(f"   Average dt: {(times[-1] - times[0]) / len(times):.3f}s")
print(f"   Max speed: {speeds.max():.2f} m/s")

# Create visualizations
print("\n📊 Creating visualizations...")

# 1. Speed and acceleration
viz = Visualizer2D(recorder.get_all_trajectories())
fig_metrics, (ax_speed, ax_accel) = viz.plot_speed_and_acceleration()

# 2. Smooth animation with many frames
builder = AnimationBuilder(recorder.get_all_trajectories())
builder.set_warehouse_bounds(0, 120, 0, 60)
builder.set_frame_interval(40)   # 25 FPS
builder.set_num_frames(400)      # 400 frames for ultra-smooth motion

fig_anim, ax_anim, anim = builder.build_2d_animation()

print("\n" + "="*70)
print("✅ VISUALIZATIONS READY!")
print("="*70)
print("\nTwo windows will open:")
print("  1. Speed & Acceleration plots")
print("     - Should show smooth curves (not discrete jumps)")
print("     - Acceleration/deceleration phases visible")
print()
print("  2. Animation")
print("     - 400 frames @ 25 FPS")
print("     - Watch the point move continuously")
print("     - Should see smooth speed changes")
print()
print("Close windows when done.")
print("="*70 + "\n")

plt.show()
