from __future__ import annotations
from jobshop_base.stats import JobShopBaseStats


class JobShopStats(JobShopBaseStats):
    """Thin subclass exposing the shared JobShop statistics for Salabim.

    This class is intentionally empty and exists so callers can import
    `jobshop_salabim.JobShopStats` directly. All fields and helper methods are
    defined on `jobshop_base.stats.JobShopBaseStats`.
    """

    # Intentionally empty; all fields and helpers live in JobShopBaseStats.
    pass
