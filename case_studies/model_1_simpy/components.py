from __future__ import annotations

import simpy
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class Pallet:
    id: int
    created_at: float
    attributes: Dict[str, object] = field(default_factory=dict)


class ForkliftFleet:
    """Simple transporter fleet abstraction backed by a SimPy Resource."""

    def __init__(
        self,
        env: simpy.Environment,
        count: int,
        store_time_s: float = 0.0,
        retrieve_time_s: float = 0.0,
        store_travel_time_s: float = 0.0,
        retrieve_travel_time_s: float = 0.0,
        travel_time_fn: Optional[Callable[[str, Pallet], float]] = None,
        name: str = "forklifts",
    ):
        self.env = env
        self.resource = simpy.Resource(env, capacity=count)
        self.store_time_s = store_time_s
        self.retrieve_time_s = retrieve_time_s
        self.store_travel_time_s = store_travel_time_s
        self.retrieve_travel_time_s = retrieve_travel_time_s
        self.travel_time_fn = travel_time_fn
        self.name = name

    def store(self, pallet: Pallet):
        with self.resource.request() as req:
            yield req
            travel_time = None
            if self.travel_time_fn:
                travel_time = self.travel_time_fn("store", pallet)
            elif self.store_travel_time_s > 0:
                travel_time = self.store_travel_time_s
            if travel_time and travel_time > 0:
                yield self.env.timeout(travel_time)
            if self.store_time_s > 0:
                yield self.env.timeout(self.store_time_s)

    def retrieve(self, pallet: Pallet):
        with self.resource.request() as req:
            yield req
            travel_time = None
            if self.travel_time_fn:
                travel_time = self.travel_time_fn("retrieve", pallet)
            elif self.retrieve_travel_time_s > 0:
                travel_time = self.retrieve_travel_time_s
            if travel_time and travel_time > 0:
                yield self.env.timeout(travel_time)
            if self.retrieve_time_s > 0:
                yield self.env.timeout(self.retrieve_time_s)
