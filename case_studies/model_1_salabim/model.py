from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random
from typing import Optional

import salabim as sim

from .params import Model1Params
from .stats import Model1Stats


class Pallet(sim.Component):
    def setup(self, model: "Model1SblModel"):
        self.model = model
        self.created_at = self.env.now()
        self._x, self._y = self.model.stage_positions["source"]
        self.current_stage: Optional[str] = None
        self._anim = None
        if self.model.params.enable_animation:
            self._anim = sim.AnimateRectangle(
                spec=lambda: (self._x - 10, self._y - 10,
                              self._x + 10, self._y + 10, 3),
                fillcolor="#3498db",
                linecolor="#2c3e50",
                text=lambda: f"P{self.sequence_number()}",
                textcolor="#2c3e50",
                fontsize=9,
                parent=self,
                env=self.env,
            )

    def _set_stage(self, stage: str):
        pos = self.model.stage_positions.get(stage)
        if pos:
            self._x, self._y = pos
        # update stage counts for animation stats
        if self.current_stage:
            self.model.stage_counts[self.current_stage] = max(
                0, self.model.stage_counts.get(self.current_stage, 0) - 1
            )
        self.current_stage = stage
        self.model.stage_counts[stage] = self.model.stage_counts.get(
            stage, 0) + 1

    def _service(self, resource: sim.Resource, service_time: float, queue_cap: int):
        # Enforce queue capacity by waiting until room.
        while queue_cap and len(resource.requesters()) >= queue_cap:
            yield self.hold(0)
        yield self.request(resource)
        yield self.hold(service_time)
        self.release(resource)

    def _travel_time(self, kind: str) -> float:
        params = self.model.params
        dist = params.store_distance_m if kind == "store" else params.retrieve_distance_m
        speed = max(params.forklift_speed_mps, 1e-9)
        base = dist / speed
        cv = params.travel_time_noise_cv
        if cv <= 0:
            return base
        sigma = math.sqrt(math.log(1 + cv * cv))
        mu = -0.5 * sigma * sigma
        # lognormal multiplier
        mult = self.env.random.lognormvariate(mu, sigma)
        return base * mult

    def _store_with_forklift(self):
        m = self.model
        yield self.request(m.forklift_res)
        travel = self._travel_time("store")
        if travel > 0:
            yield self.hold(travel)
        if m.params.forklift_store_time_s > 0:
            yield self.hold(m.params.forklift_store_time_s)
        self.release(m.forklift_res)
        # Wait for storage space
        while m.storage_level >= m.params.storage_capacity:
            yield self.hold(0)
        m.storage_level += 1

    def _retrieve_with_forklift(self):
        m = self.model
        # Wait for available pallet
        while m.storage_level <= 0:
            yield self.hold(0)
        m.storage_level -= 1
        yield self.request(m.forklift_res)
        travel = self._travel_time("retrieve")
        if travel > 0:
            yield self.hold(travel)
        if m.params.forklift_retrieve_time_s > 0:
            yield self.hold(m.params.forklift_retrieve_time_s)
        self.release(m.forklift_res)

    def process(self):
        m = self.model
        # Service 1
        self._set_stage("service1")
        yield from self._service(
            resource=m.service1_res,
            service_time=m.params.service1_time_s,
            queue_cap=m.params.service1_queue_capacity,
        )
        # Store (forklift + storage level)
        self._set_stage("store")
        yield from self._store_with_forklift()
        # Delay
        self._set_stage("delay")
        yield self.hold(m.params.delay_time_s)
        # Retrieve (storage down + forklift)
        self._set_stage("retrieve")
        yield from self._retrieve_with_forklift()
        # Service 2
        self._set_stage("service2")
        yield from self._service(
            resource=m.service2_res,
            service_time=m.params.service2_time_s,
            queue_cap=m.params.service2_queue_capacity,
        )
        # Sink
        self._set_stage("sink")
        duration = self.env.now() - self.created_at
        m.stats.record_completed(duration)
        if self._anim:
            self._anim.visible(False)
        # Remove from stage count on completion
        if self.current_stage:
            m.stage_counts[self.current_stage] = max(
                0, m.stage_counts.get(self.current_stage, 0) - 1
            )
            self.current_stage = None


class Source(sim.Component):
    def setup(self, model: "Model1SblModel"):
        self.model = model

    def _next_interarrival(self) -> float:
        rate = self.model.params.arrival_rate_per_second()
        if rate <= 0:
            return float("inf")
        return self.model.rng.expovariate(rate)

    def _batch_size(self) -> int:
        p = self.model.params
        return self.model.rng.randint(p.pallet_per_arrival_min, p.pallet_per_arrival_max)

    def process(self):
        m = self.model
        while True:
            ia = self._next_interarrival()
            if ia == float("inf"):
                break
            yield self.hold(ia)
            batch = self._batch_size()
            m.stats.record_created(batch)
            for _ in range(batch):
                Pallet(env=self.env, model=m)


@dataclass
class Model1SblModel:
    params: Model1Params = field(default_factory=Model1Params)
    console_logging: bool = False

    def __post_init__(self):
        sim.yieldless(False)
        self.env = sim.Environment(random_seed=self.params.random_seed)
        if self.params.enable_animation:
            # Turn on animation before creating animated objects.
            self.env.animate(True)
            # Set initial animation speed; user can still change via GUI.
            self.env.speed(self.params.animation_speed)
        # salabim uses its own RNG; keep a Python RNG for batch/arrival numbers to mirror SimPy model
        self.rng = Random(self.params.random_seed)
        self.stats = Model1Stats()
        self.stage_positions = {
            "source": (100, 220),
            "service1": (220, 220),
            "store": (340, 220),
            "delay": (460, 220),
            "retrieve": (580, 220),
            "service2": (700, 220),
            "sink": (820, 220),
        }
        self.stage_counts = {k: 0 for k in self.stage_positions}

        self.forklift_res = sim.Resource(
            name="forklifts", env=self.env, capacity=self.params.n_forklifts
        )
        self.service1_res = sim.Resource(
            name="service1", env=self.env, capacity=1
        )
        self.service2_res = sim.Resource(
            name="service2", env=self.env, capacity=1
        )
        self.storage_level = 0
        self.source = Source(env=self.env, model=self)
        if self.params.enable_animation:
            self._setup_animation()

    def run(self, until: Optional[float] = None) -> Model1Stats:
        stop_time = until if until is not None else self.params.sim_time
        self.env.run(till=stop_time)
        if self.console_logging:
            self._log_summary()
        return self.stats

    def _log_summary(self) -> None:
        print(
            f"completed={self.stats.completed} avg_Tsys={self.stats.avg_time_in_system:.2f}s "
            f"created={self.stats.created} storage_level={self.storage_level}"
        )

    def _setup_animation(self) -> None:
        # Stations
        block_w = 110
        block_h = 60
        for name, (x, y) in self.stage_positions.items():
            sim.AnimateRectangle(
                spec=(x - block_w / 2, y - block_h / 2,
                      x + block_w / 2, y + block_h / 2, 3),
                fillcolor="#ecf0f1",
                linecolor="#7f8c8d",
                text=name,
                textcolor="#2c3e50",
                fontsize=10,
                env=self.env,
            )

        def res_text(res: sim.Resource, label: str):
            return lambda: f"{label}\nin use {len(res.claimers())}/{res.capacity()}\nqueue {len(res.requesters())}"

        def stage_text(stage: str):
            return lambda: f"{stage}:\nin stage {self.stage_counts.get(stage, 0)}"

        # Resource status texts placed above blocks
        sim.AnimateText(
            text=res_text(self.service1_res, "service1"),
            x=self.stage_positions["service1"][0],
            y=self.stage_positions["service1"][1] - block_h / 2 - 8,
            fontsize=12,
            text_anchor="n",
            env=self.env,
        )
        sim.AnimateText(
            text=res_text(self.service2_res, "service2"),
            x=self.stage_positions["service2"][0],
            y=self.stage_positions["service2"][1] - block_h / 2 - 8,
            fontsize=12,
            text_anchor="n",
            env=self.env,
        )
        sim.AnimateText(
            text=res_text(self.forklift_res, "forklifts"),
            x=self.stage_positions["store"][0],
            y=self.stage_positions["store"][1] + block_h / 2 + 8,
            fontsize=12,
            text_anchor="s",
            env=self.env,
        )

        # Stage occupancy texts for store, delay, retrieve
        for stage in ("store", "delay", "retrieve"):
            x, y = self.stage_positions[stage]
            sim.AnimateText(
                text=stage_text(stage),
                x=x,
                y=y - block_h / 2 - 8,
                fontsize=11,
                text_anchor="n",
                env=self.env,
            )

        # Global counters
        sim.AnimateText(
            text=lambda: f"Time: {self.env.now():.1f}s",
            x=40,
            y=40,
            fontsize=15,
            env=self.env,
        )
        sim.AnimateText(
            text=lambda: f"Created: {self.stats.created}",
            x=40,
            y=65,
            fontsize=15,
            env=self.env,
        )
        sim.AnimateText(
            text=lambda: f"Completed: {self.stats.completed}",
            x=40,
            y=90,
            fontsize=15,
            env=self.env,
        )
