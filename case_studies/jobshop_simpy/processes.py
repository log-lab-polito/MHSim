from __future__ import annotations

import simpy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from jobshop_base.trace import traceln

if TYPE_CHECKING:
    from random import Random
    from .params import JobShopParams
    from .stats import JobShopStats
    from .environment import Environment


# --- Entities ----------------------------------------------------------------


@dataclass
class Pallet:
    name: str
    capacity: int
    created_time: float
    delivered_time: Optional[float] = None
    finished_time: Optional[float] = None
    ready_for_shipping_time: Optional[float] = None
    shipped_time: Optional[float] = None
    parts_completed: int = 0
    transfer_requested: bool = False


@dataclass
class ForkliftTask:
    task_type: str
    pallet: Pallet
    distance_m: float
    pickup_time: float
    dropoff_time: float
    on_drop: Optional[Callable[[Pallet], None]] = None
    description: str = ""
    priority: int = 0


# --- Core processes ----------------------------------------------------------


def _pop_waiting(stack: list[Pallet]) -> Optional[Pallet]:
    return stack.pop() if stack else None


def part_process(
    env: Environment,
    name: str,
    cnc: simpy.Resource,
    params: JobShopParams,
    stats: JobShopStats,
    rng: Random,
    pallet: Pallet,
    schedule_finished_cb: Callable[[Pallet], None],
):
    """Part lifecycle: waits for CNC, processes, and palletizes."""
    arrival_time = env.now
    worker_speed = max(1e-6, params.worker_speed_mps)

    with cnc.request() as req:
        yield req
        wait_for_cnc = env.now - arrival_time
        stats.add_time("time_raw_storage_s", wait_for_cnc, parts=1)
        traceln(
            f"{name} START_PICKUP",
            color="blue",
            sim_time=env.now,
            channel="detail",
        )
        pickup_delay = params.pickup_part_delay / worker_speed
        with env.worker.request() as wreq:
            yield wreq
            yield env.timeout(pickup_delay)

        proc_time = rng.triangular(
            params.proc_min, params.proc_max, params.proc_mode)
        palletize_delay = params.palletizing_delay / worker_speed
        stats.add_time(
            "time_processing_and_palletizing_s", proc_time + palletize_delay, parts=1
        )
        traceln(
            f"{name} START_CNC for {proc_time:.2f}s",
            color="magenta",
            sim_time=env.now,
            channel="detail",
        )
        yield env.timeout(proc_time)

        traceln(
            f"{name} START_PALLETIZE",
            color="blue",
            sim_time=env.now,
            channel="detail",
        )
        with env.worker.request() as wreq2:
            yield wreq2
            yield env.timeout(palletize_delay)

    stats.completed_parts += 1
    pallet.parts_completed += 1
    if pallet.parts_completed >= pallet.capacity and not pallet.transfer_requested:
        pallet.transfer_requested = True
        pallet.finished_time = env.now
        stats.completed_pallets += 1
        schedule_finished_cb(pallet)
        traceln(
            f"{pallet.name} COMPLETED pallet (waiting for forklift)",
            color="green",
            sim_time=env.now,
            channel="detail",
        )

    soj = env.now - arrival_time
    stats.sojourn_times.append(soj)
    traceln(
        f"{name} DONE  sojourn={soj:.2f}s",
        color="green",
        sim_time=env.now,
        channel="detail",
    )


def forklift_worker(
    env: Environment,
    name: str,
    params: JobShopParams,
    stats: JobShopStats,
):
    speed = max(1e-6, params.forklift_speed_mps)
    while True:
        _, _, task = yield env.forklift_tasks.get()
        pallet = task.pallet
        parts = pallet.capacity

        # Waits in storage before pickup
        if task.task_type == "raw_to_cnc":
            wait_before_pick = max(0.0, env.now - pallet.created_time)
            stats.add_time("time_raw_storage_s", wait_before_pick, parts=parts)
            env.raw_storage_count = max(0, env.raw_storage_count - 1)
            if (
                env.raw_wait_queue
                and env.raw_storage_count < params.raw_storage_capacity
            ):
                queued = _pop_waiting(env.raw_wait_queue)
                if queued:
                    schedule_raw_delivery(env, params, queued)
        elif task.task_type == "cnc_to_shipping" and pallet.finished_time is not None:
            wait_finished = max(0.0, env.now - pallet.finished_time)
            stats.add_time("time_finished_storage_s",
                           wait_finished, parts=parts)

        traceln(
            f"{name} START {task.description}",
            color="blue",
            sim_time=env.now,
            channel="detail",
        )

        # Pickup
        yield env.timeout(task.pickup_time)

        # Travel
        travel_time = task.distance_m / speed
        yield env.timeout(travel_time)

        # Dropoff
        yield env.timeout(task.dropoff_time)

        # Metrics
        stats.forklift_tasks_completed += 1
        stats.forklift_distance_m += task.distance_m
        stats.forklift_travel_time_s += travel_time

        if task.task_type == "raw_to_cnc":
            stats.add_time(
                "time_unloading_raw_s",
                task.pickup_time + task.dropoff_time,
                parts=parts,
            )
            stats.add_time("time_moving_raw_to_cnc_s",
                           travel_time, parts=parts)
            pallet.delivered_time = env.now
        elif task.task_type == "cnc_to_shipping":
            move_total = task.pickup_time + travel_time + task.dropoff_time
            stats.add_time("time_moving_finished_to_storage_s",
                           move_total, parts=parts)
            pallet.ready_for_shipping_time = env.now
            env.shipping_buffer.append(pallet)

        if task.on_drop:
            task.on_drop(pallet)

        traceln(
            f"{name} DONE {task.description}",
            color="green",
            sim_time=env.now,
            channel="detail",
        )


def shipping_truck_generator(
    env: Environment,
    params: JobShopParams,
    stats: JobShopStats,
):
    truck_id = 0
    while True:
        # First truck at t=0
        if truck_id > 0:
            yield env.timeout(params.shipping_truck_interval)
        truck_id += 1
        stats.shipping_trucks_arrived += 1
        loaded = 0
        traceln(
            f"SHIP_TRUCK {truck_id} ARRIVED",
            color="yellow",
            sim_time=env.now,
            channel="detail",
        )
        while loaded < params.shipping_truck_capacity and env.shipping_buffer:
            pallet: Pallet = env.shipping_buffer.pop(0)
            parts = pallet.capacity
            if pallet.ready_for_shipping_time is not None:
                wait_for_truck = env.now - pallet.ready_for_shipping_time
                stats.add_time("time_finished_storage_s",
                               wait_for_truck, parts=parts)
            dock_num = params.shipping_to_dock_distance_m * params.path_multiplier
            dock_travel = dock_num / max(1e-6, params.truck_speed_mps)
            load_time = params.shipping_load_time_per_pallet + dock_travel
            stats.add_time("time_shipping_finished_s", load_time, parts=parts)
            yield env.timeout(load_time)
            pallet.shipped_time = env.now
            stats.pallets_shipped += 1
            env.finished_storage_count = max(0, env.finished_storage_count - 1)
            loaded += 1
            traceln(
                f"SHIP_TRUCK {truck_id} LOADED {pallet.name}",
                color="cyan",
                sim_time=env.now,
                channel="detail",
            )
            # After freeing a slot, dispatch a waiting finished pallet if any.
            if (
                env.finished_wait_queue
                and env.finished_storage_count < params.finished_storage_capacity
            ):
                queued = _pop_waiting(env.finished_wait_queue)
                if queued:
                    schedule_finished_pallet(env, params, queued)
        if loaded >= params.shipping_truck_capacity:
            stats.shipping_trucks_departed_full += 1
        elif loaded > 0:
            stats.shipping_trucks_departed_partial += 1
        traceln(
            f"SHIP_TRUCK {truck_id} DEPART loaded={loaded}",
            color="yellow",
            sim_time=env.now,
            channel="detail",
        )


def schedule_raw_delivery(
    env: Environment,
    params: JobShopParams,
    pallet: Pallet,
):
    """Queue forklift task to move raw pallet to CNC buffer."""
    if env.raw_storage_count >= params.raw_storage_capacity:
        env.raw_wait_queue.append(pallet)
        return
    env.raw_storage_count += 1
    distance = params.receiving_to_cnc_distance_m * params.path_multiplier

    task = ForkliftTask(
        task_type="raw_to_cnc",
        pallet=pallet,
        distance_m=distance,
        pickup_time=params.pick_from_storage_delay,
        dropoff_time=params.put_in_storage_delay,
        on_drop=lambda p: begin_pallet_processing(env, p),
        description=(f"Deliver {pallet.name} to CNC buffer"),
        priority=0,
    )
    env.task_seq += 1
    env.forklift_tasks.put((task.priority, env.task_seq, task))


def schedule_finished_pallet(
    env: Environment,
    params: JobShopParams,
    pallet: Pallet,
):
    """Queue forklift task to move finished pallet to shipping."""
    if env.finished_storage_count >= params.finished_storage_capacity:
        env.finished_wait_queue.append(pallet)
        return
    env.finished_storage_count += 1
    distance = params.cnc_to_shipping_distance_m * params.path_multiplier

    task = ForkliftTask(
        task_type="cnc_to_shipping",
        pallet=pallet,
        distance_m=distance,
        pickup_time=params.pick_from_storage_delay,
        dropoff_time=params.put_in_storage_delay,
        on_drop=lambda p: env.shipping_buffer.append(p),
        description=(f"Move {pallet.name} to shipping"),
        priority=1,
    )
    env.task_seq += 1
    env.forklift_tasks.put((task.priority, env.task_seq, task))


def begin_pallet_processing(env: Environment, pallet: Pallet):
    params = env.params
    stats = env.stats
    rng = env.rng
    for idx in range(pallet.capacity):
        part_name = f"{pallet.name}.part{idx + 1}"
        stats.generated_parts += 1
        env.process(
            part_process(
                env=env,
                name=part_name,
                cnc=env.cnc,
                params=params,
                stats=stats,
                rng=rng,
                pallet=pallet,
                schedule_finished_cb=lambda p: schedule_finished_pallet(
                    env, params, p),
            )
        )


def raw_truck_generator(
    env: Environment,
    params: JobShopParams,
    stats: JobShopStats,
):
    truck_id = 0
    while True:
        if truck_id > 0:
            yield env.timeout(params.delivery_truck_interval)
        truck_id += 1
        stats.trucks_received += 1
        traceln(
            f"RAW_TRUCK {truck_id} ARRIVED (+{params.truck_capacity} pallets)",
            color="yellow",
            sim_time=env.now,
            channel="detail",
        )
        for j in range(params.truck_capacity):
            pallet = Pallet(
                name=f"raw_pallet_{truck_id}_{j + 1}",
                capacity=params.pallet_capacity,
                created_time=env.now,
            )
            stats.pallets_created += 1
            schedule_raw_delivery(env, params, pallet)
        # After unloading, dispatch queued raw pallets if capacity opens.
        while (
            env.raw_wait_queue and env.raw_storage_count < params.raw_storage_capacity
        ):
            queued = _pop_waiting(env.raw_wait_queue)
            if queued:
                schedule_raw_delivery(env, params, queued)
