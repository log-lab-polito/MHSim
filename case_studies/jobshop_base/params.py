from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JobShopBaseParams:
    """Common parameters for job shop models (time in seconds)."""

    random_seed: int = 1
    sim_time: float = 8 * 3600.0
    delivery_truck_interval: float = 2.5 * 3600.0
    truck_capacity: int = 16
    pallet_capacity: int = 9
    pickup_part_delay: float = 5.0
    palletizing_delay: float = 3.0
    put_in_storage_delay: float = 5.0
    pick_from_storage_delay: float = 5.0
    proc_min: float = 60.0
    proc_mode: float = 120.0
    proc_max: float = 240.0
    n_cnc_machines: int = 3
    n_forklifts: int = 2
    n_workers: int = 1
    forklift_speed_mps: float = 2.0
    truck_speed_mps: float = 3.0
    worker_speed_mps: float = 1.0
    receiving_to_cnc_distance_m: float = 35.0
    cnc_to_shipping_distance_m: float = 28.0
    shipping_to_dock_distance_m: float = 12.0
    path_multiplier: float = 1.15
    shipping_truck_interval: float = 2.5 * 3600.0
    shipping_truck_capacity: int = 16
    shipping_load_time_per_pallet: float = 5.0
    raw_storage_capacity: int = 40
    finished_storage_capacity: int = 40
