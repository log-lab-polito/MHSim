from __future__ import annotations

from dataclasses import dataclass

from jobshop_base.params import JobShopBaseParams


@dataclass
class JobShopParams(JobShopBaseParams):
    """Parameter set shared by the Salabim Job Shop model and benchmark harness.

    Extends `JobShopBaseParams` with Salabim-specific knobs (animation,
    forklift timing, truck patience/polling).
    """

    # Forklift timing (seconds)
    # Time to grab a pallet (picking from storage)
    forklift_pick_time: float = 5.0
    # Time to drop a pallet (putting in storage)
    forklift_drop_time: float = 5.0

    # Animation / UI knobs
    # How often the animation refreshes (seconds)
    animation_refresh_interval: float = 0.5
    # Enable animation (True/False)
    enable_animation: bool = False
    # Animation playback speed multiplier
    animation_speed: float = 1.0

    # Shipping truck behavior
    # Maximum wait before truck leaves (seconds)
    shipping_truck_patience: float = 30 * 60.0
    # How often trucks poll the dock for pallets (seconds)
    shipping_poll_interval: float = 60.0
