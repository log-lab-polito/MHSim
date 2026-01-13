"""
Example: 3D Warehouse Movement Simulation

This example demonstrates how to use the new 3D movement system with:
- Custom warehouse layout
- Physics-based movement profiles
- Independent forklift agents
- Path-based routing
"""

import simpy
from model_1_simpy.movement import (
    Position3D,
    MovementProfile,
    HorizontalMovement,
    VerticalMovement,
)
from model_1_simpy.spatial import (
    RectangularNode,
    Shelf,
    Storage,
    Path,
    WarehouseLayout,
)
from model_1_simpy.forklift import Forklift, ForkliftFleet, create_forklift_fleet
from model_1_simpy.routing import Router
from model_1_simpy.pallet import Pallet
from model_1_simpy.setup import WarehouseBuilder, MovementProfileBuilder


def example_1_simple_movement():
    """Example 1: Basic forklift movement"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Simple Forklift Movement")
    print("="*60)

    env = simpy.Environment()

    # Define movement profile
    movement = MovementProfile(
        horizontal=HorizontalMovement(
            max_speed=5.0, acceleration=2.0, deceleration=2.0),
        elevation=VerticalMovement(speed=1.0),
        loading_time=10.0,
        unloading_time=10.0,
    )

    # Create forklift
    forklift = Forklift(
        id="fl_01",
        env=env,
        movement_profile=movement,
        position=Position3D(0, 0, 0),
    )

    def movement_task():
        print(f"[{env.now:.1f}s] Forklift at {forklift.position}")

        # Move to point A
        target_a = Position3D(10, 20, 0)
        yield from forklift.move_to(target_a)
        print(f"[{env.now:.1f}s] Arrived at {forklift.position}")

        # Load something
        yield from forklift.load(Pallet(id=1, created_at=env.now))
        print(f"[{env.now:.1f}s] Loaded pallet, status: {forklift.status}")

        # Move and elevate simultaneously
        target_b = Position3D(30, 20, 5)
        yield from forklift.move_to(target_b)
        print(f"[{env.now:.1f}s] Arrived at {forklift.position}")

        # Unload
        yield from forklift.unload()
        print(f"[{env.now:.1f}s] Unloaded pallet")

    env.process(movement_task())
    env.run()


def example_2_warehouse_layout():
    """Example 2: Complete warehouse with layout"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Warehouse Layout with Shelves")
    print("="*60)

    env = simpy.Environment()

    # Build warehouse using builder
    layout = (
        WarehouseBuilder()
        .set_inbound_area(Position3D(0, 0, 0), width=20, depth=10)
        .set_outbound_area(Position3D(100, 0, 0), width=20, depth=10)
        .set_forklifts_home(Position3D(50, 50, 0), width=10, depth=10)
        .add_shelf("rack_1", Position3D(30, 10, 0), levels=6, positions_per_level=10)
        .add_shelf("rack_2", Position3D(30, 30, 0), levels=6, positions_per_level=10)
        .build()
    )

    print("\nWarehouse Areas:")
    print(
        f"  Inbound: {layout.inbound_area.position} ({layout.inbound_area.width}x{layout.inbound_area.depth})")
    print(
        f"  Outbound: {layout.outbound_area.position} ({layout.outbound_area.width}x{layout.outbound_area.depth})")
    print(f"  Home: {layout.forklifts_home.position}")

    print("\nStorage:")
    for shelf in layout.storage.shelves:
        print(
            f"  {shelf.id}: {shelf.levels} levels × {shelf.positions_per_level} positions")
        cell_pos = shelf.get_cell_position(level=3, position=5)
        print(f"    Cell at level 3, position 5: {cell_pos}")


def example_3_forklift_fleet():
    """Example 3: Fleet of independent forklifts"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Forklift Fleet with Independent Agents")
    print("="*60)

    env = simpy.Environment()

    # Create movement profile
    movement = (
        MovementProfileBuilder()
        .set_max_speed(5.0)
        .set_acceleration(2.0)
        .set_deceleration(2.0)
        .set_loading_time(10.0)
        .build()
    )

    # Create warehouse
    layout = (
        WarehouseBuilder()
        .set_inbound_area(Position3D(0, 0, 0))
        .set_outbound_area(Position3D(100, 0, 0))
        .set_forklifts_home(Position3D(50, 50, 0))
        .add_shelf("rack_1", Position3D(30, 10, 0))
        .build()
    )

    router = Router(layout)

    # Create fleet of 3 forklifts
    fleet = create_forklift_fleet(
        env=env,
        count=3,
        movement_profile=movement,
        router=router,
        home_position=layout.forklifts_home.get_access_point(),
        name_prefix="fl"
    )

    print(f"Created fleet with {fleet.count_total()} forklifts")
    print(f"Available: {fleet.count_available()}")

    def task_1():
        fl = fleet.get_forklift("fl_0")
        print(f"\n[{env.now:.1f}s] FL-0 starting task")
        yield from fl.move_to(Position3D(10, 5, 0))
        yield from fl.load(Pallet(id=1, created_at=env.now))
        print(f"[{env.now:.1f}s] FL-0 loaded, moving to rack")
        yield from fl.move_to(Position3D(30, 10, 0))
        yield from fl.unload()
        print(f"[{env.now:.1f}s] FL-0 complete")

    def task_2():
        yield env.timeout(5)  # Start 5 seconds later
        fl = fleet.get_forklift("fl_1")
        print(f"\n[{env.now:.1f}s] FL-1 starting task")
        yield from fl.move_to(Position3D(20, 5, 0))
        yield from fl.load(Pallet(id=2, created_at=env.now))
        print(f"[{env.now:.1f}s] FL-1 loaded, moving to rack")
        yield from fl.move_to(Position3D(30, 10, 0))
        yield from fl.unload()
        print(f"[{env.now:.1f}s] FL-1 complete")

    env.process(task_1())
    env.process(task_2())
    env.run(until=100)


def example_4_routing():
    """Example 4: Path-based routing"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Path-Based Routing")
    print("="*60)

    env = simpy.Environment()

    # Create layout with paths
    layout = (
        WarehouseBuilder()
        .set_inbound_area(Position3D(0, 0, 0))
        .set_outbound_area(Position3D(100, 0, 0))
        .set_forklifts_home(Position3D(50, 50, 0))
        .add_shelf("rack_1", Position3D(30, 10, 0))
        .add_path(
            "inbound_to_storage",
            waypoints=[
                Position3D(10, 5, 0),
                Position3D(20, 5, 0),
                Position3D(30, 10, 0),
            ]
        )
        .add_path(
            "storage_to_outbound",
            waypoints=[
                Position3D(30, 10, 0),
                Position3D(50, 5, 0),
                Position3D(90, 5, 0),
            ]
        )
        .build()
    )

    router = Router(layout)

    # Test routing
    print("\nDirect route (no path):")
    route_direct = router.route_between_nodes(
        Position3D(10, 5, 0),
        Position3D(30, 10, 0)
    )
    print(f"  Waypoints: {len(route_direct.waypoints)}")
    print(f"  Distance: {route_direct.total_distance:.1f} m")

    print("\nRoute via predefined path:")
    route_guided = router.route_between_nodes(
        Position3D(10, 5, 0),
        Position3D(30, 10, 0),
        preferred_path_id="inbound_to_storage"
    )
    print(f"  Waypoints: {len(route_guided.waypoints)}")
    print(f"  Distance: {route_guided.total_distance:.1f} m")


def example_5_advanced_movements():
    """Example 5: Advanced movement profiles"""
    print("\n" + "="*60)
    print("EXAMPLE 5: Advanced Movement Profiles")
    print("="*60)

    env = simpy.Environment()

    # Different movement profiles
    profiles = {
        "slow": MovementProfile(
            horizontal=HorizontalMovement(
                max_speed=2.0, acceleration=1.0, deceleration=1.0),
            elevation=VerticalMovement(speed=0.5),
            loading_time=15.0,
            unloading_time=15.0,
        ),
        "medium": MovementProfile(
            horizontal=HorizontalMovement(
                max_speed=5.0, acceleration=2.0, deceleration=2.0),
            elevation=VerticalMovement(speed=1.0),
            loading_time=10.0,
            unloading_time=10.0,
        ),
        "fast": MovementProfile(
            horizontal=HorizontalMovement(
                max_speed=8.0, acceleration=3.0, deceleration=3.0),
            elevation=VerticalMovement(speed=1.5),
            loading_time=5.0,
            unloading_time=5.0,
        ),
    }

    # Calculate travel times for same distance
    distance = Position3D(0, 0, 0).distance_to(Position3D(50, 50, 5))

    print(f"\nTravel profile for {distance:.1f}m distance:")
    for name, profile in profiles.items():
        time = profile.point_to_point_time(
            Position3D(0, 0, 0), Position3D(50, 50, 5))
        print(
            f"  {name:8s}: {time:.1f}s (speed: {profile.horizontal.max_speed} m/s)")


if __name__ == "__main__":
    example_1_simple_movement()
    example_2_warehouse_layout()
    example_3_forklift_fleet()
    example_4_routing()
    example_5_advanced_movements()

    print("\n" + "="*60)
    print("All examples completed!")
    print("="*60)
