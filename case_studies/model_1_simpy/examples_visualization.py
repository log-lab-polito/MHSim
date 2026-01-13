"""
Visualization examples for 3D warehouse movement simulation.

Demonstrates how to:
1. Record forklift movements during simulation
2. Create static visualizations (2D plots, 3D plots, time series)
3. Create animated visualizations (2D and 3D animations)
"""

import simpy
from .setup import create_warehouse_with_standard_config
from .params import Model1Params
from .pallet import Pallet
from .visualization import (
    MovementRecorder,
    create_recording_process,
    Visualizer2D,
    Visualizer3D,
    AnimationBuilder,
)


def example_1_record_and_plot_2d():
    """Example 1: Record movements and create 2D plot"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Record Movements & Create 2D Plot")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    # Create movement recorder
    recorder = MovementRecorder()

    # Start recording process
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.5))

    # Define simple tasks for each forklift
    def task_forklift(fl, task_id):
        positions = [
            layout.inbound_area.get_access_point(),
            layout.storage.get_shelf("rack_1").get_access_point(),
            layout.outbound_area.get_access_point(),
        ]

        for pos in positions:
            yield from fl.move_to(pos)
            yield env.timeout(2)  # Wait at each position

    # Start tasks
    for i, fl in enumerate(fleet.forklifts):
        env.process(task_forklift(fl, i))

    env.run()

    # Create visualizations
    print(f"\nRecorded {len(recorder.trajectories)} forklift trajectories")
    for fl_id, traj in recorder.trajectories.items():
        print(f"  {fl_id}: {len(traj.records)} position records")

    # Create 2D visualization
    visualizer2d = Visualizer2D(
        recorder.get_all_trajectories(),
        warehouse_bounds=(0, 120, 0, 60)
    )
    fig, ax = visualizer2d.plot_all_trajectories()
    print("\n2D Trajectory plot created!")

    return recorder, visualizer2d


def example_2_time_series_plots():
    """Example 2: Create time series plots (X, Y, Z over time)"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Time Series Plots (X, Y, Z vs Time)")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=1.0))

    def moving_task(fl, target_count):
        positions = [
            layout.inbound_area.get_access_point(),
            layout.storage.get_shelf("rack_1").get_access_point(),
            layout.storage.get_shelf("rack_2").get_access_point(),
            layout.outbound_area.get_access_point(),
        ]

        for _ in range(target_count):
            for pos in positions:
                yield from fl.move_to(pos)

    # Give each forklift different tasks
    for i, fl in enumerate(fleet.forklifts):
        env.process(moving_task(fl, 2 + i))  # Different number of runs

    env.run(until=150)

    print(f"\nRecorded movements for {len(recorder.trajectories)} forklifts")

    visualizer2d = Visualizer2D(recorder.get_all_trajectories())
    fig, axes = visualizer2d.plot_time_series()
    print("Time series plots created!")
    print("  - Top plot: X position over time")
    print("  - Middle plot: Y position over time")
    print("  - Bottom plot: Z position (elevation) over time")

    return recorder


def example_3_3d_visualization():
    """Example 3: Create 3D visualization"""
    print("\n" + "="*60)
    print("EXAMPLE 3: 3D Trajectory Visualization")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.5))

    def task_with_elevation(fl):
        # Move around warehouse with elevation changes
        positions = [
            layout.inbound_area.get_access_point(),
            layout.storage.get_shelf("rack_1").get_access_point(),
            layout.storage.get_shelf("rack_2").get_access_point(),
            layout.outbound_area.get_access_point(),
        ]

        for pos in positions:
            yield from fl.move_to(pos)
            yield env.timeout(1)

    for fl in fleet.forklifts[:2]:  # Just first 2 forklifts for clarity
        env.process(task_with_elevation(fl))

    env.run(until=100)

    print(f"\nRecorded {len(recorder.trajectories)} trajectories")

    # Create 3D visualization
    visualizer3d = Visualizer3D(
        recorder.get_all_trajectories(),
        warehouse_bounds=(0, 120, 0, 60, 0, 10)
    )
    fig, ax = visualizer3d.plot_3d_trajectories()
    print("3D trajectory visualization created!")
    print("  - Green triangles: Start positions")
    print("  - Red squares: End positions")

    return recorder, visualizer3d


def example_4_elevation_profile():
    """Example 4: Elevation profile (Z vs distance traveled)"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Elevation Profile")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.25))

    def elevator_task(fl):
        # Move up and down multiple times
        shelf = layout.storage.get_shelf("rack_1")
        for level in range(6):
            cell_pos = shelf.get_cell_position(level, 5)
            yield from fl.move_to(cell_pos)
            yield env.timeout(1)

    for fl in fleet.forklifts[:1]:  # Just one forklift
        env.process(elevator_task(fl))

    env.run(until=80)

    visualizer3d = Visualizer3D(recorder.get_all_trajectories())
    fig, ax = visualizer3d.plot_elevation_profile()
    print("Elevation profile created!")
    print("Shows how elevation changes as forklift moves through warehouse")

    return recorder


def example_5_2d_animation():
    """Example 5: Create 2D animation"""
    print("\n" + "="*60)
    print("EXAMPLE 5: 2D Movement Animation")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.5))

    def simple_movement(fl, forklift_id):
        # Constrain movement strictly to predefined path grid
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

        # Offset each forklift's starting point for variety
        offset = forklift_id % len(path_points)
        loop = path_points[offset:] + path_points[:offset]

        for pos in loop:
            yield from fl.move_to(pos)
            yield env.timeout(0.5)

    for i, fl in enumerate(fleet.forklifts):
        env.process(simple_movement(fl, i))

    env.run(until=100)

    print(
        f"\nRecorded {len(recorder.trajectories)} trajectories for animation")

    # Build animation
    anim_builder = AnimationBuilder(recorder.get_all_trajectories())
    anim_builder.set_layout(layout)  # Overlay areas, shelves, and paths
    anim_builder.set_warehouse_bounds(50, 480, 240, 480)
    anim_builder.set_frame_interval(80)  # Lower FPS for responsiveness
    anim_builder.set_num_frames(240)

    fig, ax, anim = anim_builder.build_2d_animation()
    print("2D Animation created!")
    print("  - Shows live movement of all forklifts")
    print("  - Time indicator in top-left")

    # Optional: save to file (requires ffmpeg or pillow)
    # from model_1_simpy.visualization import save_animation
    # save_animation(anim, 'forklift_animation_2d.gif')

    return recorder, anim


def example_6_3d_animation():
    """Example 6: Create 3D animation"""
    print("\n" + "="*60)
    print("EXAMPLE 6: 3D Movement Animation")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=0.5))

    def moving_task(fl, forklift_id):
        if forklift_id == 0:
            # Forklift 0: Moves through rack_1 at different levels
            shelf = layout.storage.get_shelf("rack_1")
            for level in range(3):
                cell = shelf.get_cell_position(level, 5)
                yield from fl.move_to(cell)
                yield env.timeout(2)
        else:
            # Forklift 1: Moves through rack_2 at different levels
            shelf = layout.storage.get_shelf("rack_2")
            for level in range(3):
                cell = shelf.get_cell_position(level, 3)
                yield from fl.move_to(cell)
                yield env.timeout(2)

    # 2 forklifts for clearer animation
    for i, fl in enumerate(fleet.forklifts[:2]):
        env.process(moving_task(fl, i))

    env.run(until=100)

    print(f"\nRecorded {len(recorder.trajectories)} trajectories")

    # Build 3D animation
    anim_builder = AnimationBuilder(recorder.get_all_trajectories())
    # AnyLogic layout: X=80-430, Y=260-453, Z=0-10 (shelf heights)
    anim_builder.set_warehouse_bounds(50, 480, 240, 480, 0, 10)
    anim_builder.set_frame_interval(30)  # 30ms between frames (~33 FPS)

    fig, ax, anim = anim_builder.build_3d_animation()
    print("3D Animation created!")
    print("  - Shows 3D movement with elevation")
    print("  - Can rotate view with mouse")

    return recorder, anim


def example_7_combined_visualization():
    """Example 7: Combine multiple visualizations"""
    print("\n" + "="*60)
    print("EXAMPLE 7: Combined Visualizations")
    print("="*60)

    env = simpy.Environment()
    params = Model1Params()

    layout, router, fleet = create_warehouse_with_standard_config(env, params)

    recorder = MovementRecorder()
    env.process(create_recording_process(
        env, fleet.forklifts, recorder, recording_interval=1.0))

    def complex_task(fl):
        shelf1 = layout.storage.get_shelf("rack_1")
        shelf2 = layout.storage.get_shelf("rack_2")

        shelves = [shelf1, shelf2]
        for shelf in shelves:
            for level in range(2):
                cell = shelf.get_cell_position(level, 5)
                yield from fl.move_to(cell)
                yield env.timeout(1)

    for fl in fleet.forklifts[:2]:
        env.process(complex_task(fl))

    env.run(until=120)

    print(
        f"\nGenerated multiple views of {len(recorder.trajectories)} trajectories:")

    # 2D trajectory
    viz2d = Visualizer2D(recorder.get_all_trajectories(), (0, 120, 0, 60))
    fig1, ax1 = viz2d.plot_all_trajectories()
    print("  ✓ 2D trajectory plot")

    # Time series
    fig2, axes2 = viz2d.plot_time_series()
    print("  ✓ Time series plots (X, Y, Z vs time)")

    # 3D trajectory
    viz3d = Visualizer3D(recorder.get_all_trajectories(),
                         (0, 120, 0, 60, 0, 10))
    fig3, ax3 = viz3d.plot_3d_trajectories()
    print("  ✓ 3D trajectory plot")

    # Elevation profile
    fig4, ax4 = viz3d.plot_elevation_profile()
    print("  ✓ Elevation profile")

    print("\nAll visualizations created successfully!")

    return recorder


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Visualization Examples - 3D Warehouse Movement")
    print("="*60)

    try:
        import matplotlib
        matplotlib.use('TkAgg')  # Use interactive backend
    except:
        pass

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nERROR: matplotlib is required for visualization")
        print("Install it with: pip install matplotlib")
        exit(1)

    # Run all examples
    recorder1, viz2d = example_1_record_and_plot_2d()
    recorder2 = example_2_time_series_plots()
    recorder3, viz3d = example_3_3d_visualization()
    recorder4 = example_4_elevation_profile()
    recorder5, anim2d = example_5_2d_animation()
    recorder6, anim3d = example_6_3d_animation()
    recorder7 = example_7_combined_visualization()

    print("\n" + "="*60)
    print("All visualization examples completed!")
    print("="*60)
    print("\nTo save animations:")
    print("  from model_1_simpy.visualization import save_animation")
    print("  save_animation(anim, 'animation.gif')  # Requires pillow")
    print("  save_animation(anim, 'animation.mp4')  # Requires ffmpeg")

    # Show all plots
    plt.show()
