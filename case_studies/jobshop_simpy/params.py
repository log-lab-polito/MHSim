from __future__ import annotations

from dataclasses import dataclass

from jobshop_base.params import JobShopBaseParams


@dataclass
class JobShopParams(JobShopBaseParams):
    """SimPy-specific parameters (extends base)."""

    progress_interval: float = 60.0  # Report interval in seconds
