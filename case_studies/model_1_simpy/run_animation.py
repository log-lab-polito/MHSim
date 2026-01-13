#!/usr/bin/env python3
"""
Simple script to watch forklift animations.

Usage:
    python3 run_animation.py          # Run 2D animation (default)
    python3 run_animation.py 2d       # Run 2D animation
    python3 run_animation.py 3d       # Run 3D animation
    python -m case_studies.model_1_simpy.run_animation
"""

from .visualization import Visualizer2D
from .examples_visualization import example_5_2d_animation, example_6_3d_animation
import matplotlib.pyplot as plt
import sys

import matplotlib
matplotlib.use('TkAgg')  # Interactive backend


def main():
    animation_type = sys.argv[1] if len(sys.argv) > 1 else '2d'

    print("\n" + "="*70)
    print("🎬 FORKLIFT MOVEMENT ANIMATION WITH SPEED & ACCELERATION")
    print("="*70)

    if animation_type == '3d':
        print("\nStarting 3D animation...")
        recorder, anim = example_6_3d_animation()
    else:
        print("\nStarting 2D animation...")
        recorder, anim = example_5_2d_animation()

    print("\n" + "="*70)
    print("📊 Creating speed & acceleration plots...")
    print("="*70)

    # Add speed and acceleration visualization
    viz = Visualizer2D(recorder.get_all_trajectories())
    fig_metrics, (ax_speed, ax_accel) = viz.plot_speed_and_acceleration()

    print("\n✅ Three windows will appear:")
    print("   1. Speed & Acceleration vs Time (static plot)")
    print("      - Shows velocity changes during acceleration/deceleration")
    print("      - Shows acceleration spikes when starting/stopping")
    print("   2. Animation window")
    print("      - Live movement with time indicator")
    if animation_type == '3d':
        print("      - Drag with mouse to rotate the 3D view")
    print("\nControls:")
    print("  - The animation loops automatically")
    print("  - You can zoom, pan, and interact with plots")
    print("  - Close windows when finished")
    print("="*70 + "\n")

    # Keep animation alive and show all windows
    plt.show()


if __name__ == "__main__":
    main()
