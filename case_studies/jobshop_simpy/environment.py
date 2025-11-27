from __future__ import annotations

import simpy
from typing import Any, Dict, List, Tuple


class Environment(simpy.Environment):
    """Extended simpy.Environment with job shop-specific attributes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.params: Any = None
        self.stats: Any = None
        self.rng: Any = None
        self.cnc: Any = None
        self.worker: Any = None
        self.forklift_coordinator: Any = None
        self.forklift_tasks: Any = None
        self.shipping_buffer: Any = None
        self.raw_storage_count: int = 0
        self.finished_storage_count: int = 0
        self.raw_wait_queue: List[Any] = []
        self.finished_wait_queue: List[Any] = []
        self.task_seq: int = 0
        self.layout_positions: Dict[str, Tuple[float, float]] = {}
        self.model_ref: Any = None
