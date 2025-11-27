from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from random import Random
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import salabim as sim

from .params import JobShopParams
from .stats import JobShopStats
from jobshop_base.trace import TraceConfig, Tracer, set_tracer, traceln


class Part(sim.Component):
    def setup(self, pallet: Pallet, index: int) -> None:
        self.pallet = pallet
        self.index = index

    def process(self):
        env = self.env
        params = env.params
        stats = env.stats
        rng = env.rng
        arrival = self.pallet.created_time if self.pallet else env.now()
        queue_request_time = env.now()
        worker_speed = max(1e-6, params.worker_speed_mps)
        stats.generated_parts += 1
        traceln(
            f"{self.name()} ARRIVED pallet={self.pallet.name()}",
            color="cyan",
            sim_time=env.now(),
            channel="detail",
        )
        yield self.request(env.cnc)
        wait_for_cnc = env.now() - queue_request_time
        stats.add_time("time_raw_storage_s", wait_for_cnc)
        traceln(
            f"{self.name()} START_PICKUP",
            color="blue",
            sim_time=env.now(),
            channel="detail",
        )
        pickup_delay = params.pickup_part_delay / worker_speed
        yield self.request(env.worker)
        yield self.hold(pickup_delay)
        self.release(env.worker)
        proc_time = rng.triangular(
            params.proc_min, params.proc_max, params.proc_mode)
        palletize_delay = params.palletizing_delay / worker_speed
        stats.add_time("time_processing_and_palletizing_s",
                       proc_time + palletize_delay)
        traceln(
            f"{self.name()} START_CNC for {proc_time:.2f}s",
            color="magenta",
            sim_time=env.now(),
            channel="detail",
        )
        yield self.hold(proc_time)
        traceln(
            f"{self.name()} START_PALLETIZE",
            color="blue",
            sim_time=env.now(),
            channel="detail",
        )
        yield self.request(env.worker)
        yield self.hold(palletize_delay)
        self.release(env.worker)
        self.release(env.cnc)
        stats.completed_parts += 1
        soj = env.now() - arrival
        stats.sojourn_times.append(soj)
        self.pallet.record_finished_part()
        traceln(
            f"{self.name()} DONE sojourn={soj:.2f}s",
            color="green",
            sim_time=env.now(),
            channel="detail",
        )


class Pallet(sim.Component):
    COLORS = {
        "raw": "#d9b38c",
        "in_process": "#6fa8dc",
        "finished": "#93c47d",
        "shipping": "#f6b26b",
        "shipped": "#b7b7b7",
    }

    def setup(self, capacity: int) -> None:
        self.capacity = capacity
        self.parts_spawned = 0
        self.parts_completed = 0
        self.state = "raw"
        self.location = "receiving"
        self.transfer_requested = False
        self.ready_for_shipping_time: Optional[float] = None
        self.finished_time: Optional[float] = None
        self.shipped_time: Optional[float] = None
        self.created_time: float = self.env.now()
        self.delivered_to_cnc_time: Optional[float] = None
        self.shipping_pick_time: Optional[float] = None
        self.carrier: Optional["Forklift"] = None
        self._x, self._y = self.env.layout_positions.get(
            "receiving", (60.0, 250.0))
        if self.env.params.enable_animation:
            self._icon = sim.AnimateRectangle(
                spec=lambda: self._rect_spec(),
                fillcolor=lambda: self._color(),
                linecolor="#2f3542",
                text=lambda: f"P{self.sequence_number()}",
                fontsize=10,
                textcolor="#2d3436",
                parent=self,
                env=self.env,
            )

    def process(self):
        yield self.passivate()

    @property
    def display_x(self) -> float:
        if self.carrier:
            return self.carrier.x_pos
        return self._x

    @property
    def display_y(self) -> float:
        if self.carrier:
            return self.carrier.y_pos
        return self._y

    def _rect_spec(self) -> Tuple[float, float, float, float, int]:
        width = 48
        height = 26
        x = self.display_x
        y = self.display_y
        return (
            x - width / 2,
            y - height / 2,
            x + width / 2,
            y + height / 2,
            6,
        )

    def _color(self) -> str:
        return self.COLORS.get(self.state, "#cccccc")

    # State transitions -------------------------------------------------
    def set_location(self, name: str) -> None:
        coords = self.env.layout_positions.get(name)
        if coords:
            self._x, self._y = coords
        self.location = name

    def attach_to(self, forklift: "Forklift") -> None:
        self.carrier = forklift

    def detach(self) -> None:
        self.carrier = None

    def begin_processing(self) -> None:
        if self.parts_spawned:
            return
        env = self.env
        self.state = "in_process"
        self.set_location("cnc_buffer")
        for idx in range(self.capacity):
            Part(env=env, pallet=self, index=idx,
                 name=f"{self.name()}.part{idx + 1}")
            self.parts_spawned += 1
        traceln(
            f"{self.name()} PALLET dropped at CNC buffer",
            color="magenta",
            sim_time=env.now(),
            channel="detail",
        )

    def record_finished_part(self) -> None:
        self.parts_completed += 1
        if self.parts_completed >= self.capacity and not self.transfer_requested:
            self.transfer_requested = True
            self.finished_time = self.env.now()
            self.state = "finished"
            self.env.stats.completed_pallets += 1
            traceln(
                f"{self.name()} COMPLETED pallet (waiting for forklift)",
                color="green",
                sim_time=self.env.now(),
                channel="detail",
            )
            self.env.model_ref.schedule_finished_pallet(self)

    def mark_ready_for_shipping(self) -> None:
        self.state = "shipping"
        self.ready_for_shipping_time = self.env.now()

    def mark_shipped(self) -> None:
        self.state = "shipped"


@dataclass
class ForkliftTask:
    task_type: str
    pallet: Pallet
    source: str
    destination: str
    distance_m: float
    travel_time: float
    pickup_time: float
    dropoff_time: float
    description: str
    on_drop: Optional[Callable[[], None]] = None
    priority: int = 0
    seq: int = 0


class ForkliftCoordinator:
    def __init__(self, env: Any) -> None:
        self.env = env
        self._tasks: List[ForkliftTask] = []
        self._idle: List["Forklift"] = []

    def add_task(self, task: ForkliftTask) -> None:
        self._tasks.append(task)
        self._tasks.sort(key=lambda t: (t.priority, t.seq))
        if self._idle:
            forklift = self._idle.pop(0)
            forklift.activate()

    def pop_task(self) -> Optional[ForkliftTask]:
        if self._tasks:
            return self._tasks.pop(0)
        return None

    def mark_idle(self, forklift: "Forklift") -> None:
        if forklift not in self._idle:
            self._idle.append(forklift)

    def unmark_idle(self, forklift: "Forklift") -> None:
        if forklift in self._idle:
            self._idle.remove(forklift)


class ShippingBuffer:
    def __init__(self, env: Any) -> None:
        self.env = env
        self._queue: Deque[Pallet] = deque()

    def add(self, pallet: Pallet) -> None:
        pallet.mark_ready_for_shipping()
        pallet.set_location("shipping")
        self._queue.append(pallet)

    def pop(self) -> Optional[Pallet]:
        if self._queue:
            return self._queue.popleft()
        return None

    def __len__(self) -> int:
        return len(self._queue)


class Forklift(sim.Component):
    def setup(self, idx: int):
        self.idx = idx
        self.task: Optional[ForkliftTask] = None
        self.x_pos, self.y_pos = self.env.layout_positions.get(
            "receiving", (60.0, 250.0)
        )
        self.carrying: Optional[Pallet] = None
        if self.env.params.enable_animation:
            self._icon = sim.AnimateCircle(
                x=lambda: self.x_pos,
                y=lambda: self.y_pos,
                radius=10,
                fillcolor="#f39c12",
                linecolor="#2f3542",
                text=lambda: f"FL{self.idx}",
                fontsize=10,
                parent=self,
                env=self.env,
            )

    def process(self):
        env = self.env
        controller = env.forklift_coordinator
        params = env.params
        stats = env.stats
        while True:
            controller.unmark_idle(self)
            task = controller.pop_task()
            if not task:
                controller.mark_idle(self)
                yield self.passivate()
                continue
            self.task = task
            pallet = task.pallet
            parts_on_pallet = pallet.capacity if pallet else 0
            traceln(
                f"FORKLIFT {self.idx} START {task.description}",
                color="blue",
                sim_time=env.now(),
                channel="detail",
            )
            if pallet:
                pallet.attach_to(self)
            self.carrying = pallet
            if task.task_type == "raw_to_cnc" and pallet:
                wait_before_pick = max(0.0, env.now() - pallet.created_time)
                stats.add_time(
                    "time_raw_storage_s", wait_before_pick, parts=parts_on_pallet
                )
                env.raw_storage_count = max(0, env.raw_storage_count - 1)
                if (
                    env.raw_wait_queue
                    and env.raw_storage_count < params.raw_storage_capacity
                ):
                    queued = env.raw_wait_queue.pop()
                    env.model_ref.schedule_raw_delivery(queued)
            if (
                task.task_type == "cnc_to_shipping"
                and pallet
                and pallet.finished_time is not None
            ):
                wait_finished = max(0.0, env.now() - pallet.finished_time)
                stats.add_time(
                    "time_finished_storage_s",
                    wait_finished,
                    parts=parts_on_pallet,
                )
            yield self.hold(task.pickup_time)
            yield from self._travel(
                task.travel_time,
                task.source,
                task.destination,
            )
            move_time = task.travel_time + task.dropoff_time
            yield self.hold(task.dropoff_time)
            if task.pallet:
                task.pallet.detach()
                task.pallet.set_location(task.destination)
            self.carrying = None
            if task.on_drop:
                task.on_drop()
            stats.forklift_tasks_completed += 1
            stats.forklift_distance_m += task.distance_m
            stats.forklift_travel_time_s += task.travel_time
            if task.task_type == "raw_to_cnc" and pallet:
                stats.add_time(
                    "time_unloading_raw_s",
                    task.pickup_time + task.dropoff_time,
                    parts=parts_on_pallet,
                )
                stats.add_time(
                    "time_moving_raw_to_cnc_s", task.travel_time, parts=parts_on_pallet
                )
                pallet.delivered_to_cnc_time = env.now()
            elif task.task_type == "cnc_to_shipping" and pallet:
                total_move = task.pickup_time + move_time
                stats.add_time(
                    "time_moving_finished_to_storage_s",
                    total_move,
                    parts=parts_on_pallet,
                )
                pallet.shipping_pick_time = env.now()
                if (
                    env.finished_wait_queue
                    and env.finished_storage_count < params.finished_storage_capacity
                ):
                    queued = env.finished_wait_queue.pop()
                    env.model_ref.schedule_finished_pallet(queued)
            traceln(
                f"FORKLIFT {self.idx} DONE {task.description}",
                color="green",
                sim_time=env.now(),
                channel="detail",
            )

    def _travel(self, travel_time: float, source: str, destination: str):
        start = self.env.layout_positions.get(source, (self.x_pos, self.y_pos))
        end = self.env.layout_positions.get(destination, start)
        steps = 1
        if self.env.params.enable_animation and travel_time > 0:
            refresh = max(0.01, self.env.params.animation_refresh_interval)
            steps = max(1, int(travel_time / refresh))
        dt = travel_time / steps if steps else travel_time
        for step in range(steps):
            frac = (step + 1) / steps
            self.x_pos = start[0] + (end[0] - start[0]) * frac
            self.y_pos = start[1] + (end[1] - start[1]) * frac
            if dt > 0:
                yield self.hold(dt)
        if travel_time == 0:
            yield self.hold(0)


class RawTruckGenerator(sim.Component):
    def process(self):
        env = self.env
        params = env.params
        stats = env.stats
        truck_id = 0
        while True:
            if truck_id > 0:
                yield self.hold(params.delivery_truck_interval)
            truck_id += 1
            stats.trucks_received += 1
            raw_msg = (
                f"RAW_TRUCK {truck_id} ARRIVED " f"(+{params.truck_capacity} pallets)"
            )
            traceln(
                raw_msg,
                color="yellow",
                sim_time=env.now(),
                channel="detail",
            )
            for j in range(params.truck_capacity):
                pallet = Pallet(
                    env=env,
                    name=f"raw_pallet_{truck_id}_{j}",
                    capacity=params.pallet_capacity,
                )
                pallet.set_location("receiving")
                stats.pallets_created += 1
                env.model_ref.schedule_raw_delivery(pallet)
            while (
                env.raw_wait_queue
                and env.raw_storage_count < params.raw_storage_capacity
            ):
                queued = env.raw_wait_queue.pop()
                env.model_ref.schedule_raw_delivery(queued)
            env.model_ref.schedule_shipping_truck_after(
                params.shipping_truck_interval, label=f"after_raw_{truck_id}"
            )


class ShippingTruck(sim.Component):
    def setup(self, capacity: int, patience: float):
        self.capacity = capacity
        self.patience = patience

    def process(self):
        env = self.env
        params = env.params
        stats = env.stats
        arrival = env.now()
        stats.shipping_trucks_arrived += 1
        loaded = 0
        traceln(
            f"SHIP_TRUCK {self.name()} ARRIVED cap={self.capacity}",
            color="yellow",
            sim_time=env.now(),
            channel="detail",
        )
        while loaded < self.capacity and env.now() - arrival < self.patience:
            pallet = env.shipping_buffer.pop()
            if pallet:
                traceln(
                    f"{self.name()} LOADING {pallet.name()}",
                    color="cyan",
                    sim_time=env.now(),
                    channel="detail",
                )
                if pallet.ready_for_shipping_time is not None:
                    wait_for_truck = env.now() - pallet.ready_for_shipping_time
                    stats.add_time(
                        "time_finished_storage_s", wait_for_truck, parts=pallet.capacity
                    )
                _dock_num = params.shipping_to_dock_distance_m * params.path_multiplier
                dock_travel = _dock_num / max(1e-6, params.truck_speed_mps)
                load_time = params.shipping_load_time_per_pallet + dock_travel
                stats.add_time(
                    "time_shipping_finished_s", load_time, parts=pallet.capacity
                )
                yield self.hold(load_time)
                pallet.mark_shipped()
                pallet.shipped_time = env.now()
                stats.pallets_shipped += 1
                env.finished_storage_count = max(
                    0, env.finished_storage_count - 1)
                if pallet.ready_for_shipping_time is not None:
                    stats.pallet_wait_times.append(
                        env.now() - pallet.ready_for_shipping_time
                    )
                loaded += 1
                if (
                    env.finished_wait_queue
                    and env.finished_storage_count < params.finished_storage_capacity
                ):
                    queued = env.finished_wait_queue.pop()
                    env.model_ref.schedule_finished_pallet(queued)
                continue
            wait = min(
                params.shipping_poll_interval,
                max(0.0, self.patience - (env.now() - arrival)),
            )
            if wait <= 0:
                break
            yield self.hold(wait)
        if loaded >= self.capacity:
            stats.shipping_trucks_departed_full += 1
        elif loaded > 0:
            stats.shipping_trucks_departed_partial += 1
        traceln(
            f"{self.name()} DEPART loaded={loaded}",
            color="yellow",
            sim_time=env.now(),
            channel="detail",
        )


class ShippingTruckTrigger(sim.Component):
    def setup(self, delay_time: float):
        self.delay_time = delay_time

    def process(self):
        yield self.hold(self.delay_time)
        self.env.model_ref._spawn_shipping_truck()


class Reporter(sim.Component):
    def setup(self, interval: float):
        self.interval = interval

    def process(self):
        env = self.env
        stats = env.stats
        while True:
            yield self.hold(self.interval)
            avg_part = stats.avg_time_in_system
            msg = (
                f"REPORT parts={stats.completed_parts} "
                f"pallets={stats.completed_pallets} "
                f"shipped={stats.pallets_shipped} "
                f"avg_part={avg_part:.1f}s "
                f"buffer={len(env.shipping_buffer)}"
            )
            traceln(msg, color="grey", sim_time=env.now(), channel="summary")


@dataclass
class JobShopModel:
    params: JobShopParams
    report_interval_s: float = 60.0
    trace_log_file: Optional[str] = None
    trace_log_append: bool = False
    console_level: str = "full"
    _shipping_truck_seq: int = field(init=False, default=0, repr=False)
    shipping_started: bool = field(init=False, default=False, repr=False)
    _tracer: Optional[Tracer] = field(init=False, default=None, repr=False)

    def __post_init__(self):
        sim.yieldless(False)
        self.env = sim.Environment()
        self.env.model_ref = self
        self.env.params = self.params
        self.env.stats = JobShopStats()
        self.env.rng = Random(self.params.random_seed)
        self.env.cnc = sim.Resource(
            "CNC", capacity=self.params.n_cnc_machines, env=self.env
        )
        self.env.worker = sim.Resource(
            "WORKER", capacity=self.params.n_workers, env=self.env
        )
        self.env.forklift_coordinator = ForkliftCoordinator(self.env)
        self.env.shipping_buffer = ShippingBuffer(self.env)
        self.env.raw_storage_count = 0
        self.env.finished_storage_count = 0
        self.env.raw_wait_queue = []
        self.env.finished_wait_queue = []
        self.env.task_seq = 0
        self.env.layout_positions = self._build_layout()
        self._configure_animation()
        self._init_animation_canvas()
        self._forklifts: List[Forklift] = []
        self._tracer = Tracer(
            TraceConfig(
                enabled=True,
                use_color=True,
                prefix_time=False,
                log_path=self.trace_log_file,
                log_append=self.trace_log_append,
                console_level=self.console_level,
            )
        )
        set_tracer(self._tracer)

    def _spawn_shipping_truck(self) -> None:
        self._shipping_truck_seq += 1
        ShippingTruck(
            env=self.env,
            name=f"ship_truck_{self._shipping_truck_seq}",
            capacity=self.params.shipping_truck_capacity,
            patience=self.params.shipping_truck_patience,
        )

    def schedule_shipping_truck_after(self, delay: float, label: str = "") -> None:
        suffix = f"{label}" if label else f"{self._shipping_truck_seq + 1}"
        ShippingTruckTrigger(
            env=self.env,
            name=f"ship_trigger_{suffix}",
            delay_time=delay,
        )

    def _build_layout(self) -> Dict[str, Tuple[float, float]]:
        return {
            "receiving": (80.0, 250.0),
            "cnc_buffer": (260.0, 250.0),
            "shipping": (520.0, 250.0),
            "dock": (700.0, 250.0),
        }

    def _configure_animation(self) -> None:
        if not self.params.enable_animation:
            self.env.animate(False)
            return
        self._verify_animation_dependencies()
        self.env.animate(True)
        self.env.animation_parameters(show_time=False)
        speed = max(0.01, float(self.params.animation_speed or 1.0))
        self.env.speed(speed)

    def _verify_animation_dependencies(self) -> None:
        try:
            from PIL import ImageTk  # type: ignore # noqa: F401
        except ModuleNotFoundError as exc:  # pragma: no cover - env-specific
            missing = (exc.name or "").lower()
            if "pil" in missing:
                raise ImportError(
                    "Salabim animation requires Pillow."
                    " Install with `pip install Pillow`."
                    " Or use the pyproject extras."
                ) from exc
            if "tk" in missing:
                raise ImportError(
                    "Salabim animation needs Tkinter (_tkinter)."
                    " Install a Python build with Tk support"
                    " (e.g., `brew install python-tk@3.13`)",
                    " or use the python.org installer." " Or rerun without --animate.",
                ) from exc
            raise
        try:
            import tkinter  # noqa: F401
        except ModuleNotFoundError as exc:  # pragma: no cover - env-specific
            raise ImportError(
                "Tkinter is unavailable on this Python build."
                " Install Tk support (python-tk) or run without --animate."
            ) from exc

    def _init_animation_canvas(self) -> None:
        if not self.params.enable_animation:
            return
        env = self.env
        sim.AnimateRectangle(
            spec=(30, 210, 130, 290),
            fillcolor="#fdebd0",
            linecolor="#7f8c8d",
            env=env,
            keep=True,
        )
        sim.AnimateText(
            text="Receiving",
            x=80,
            y=300,
            text_anchor="c",
            fontsize=13,
            env=env,
        )
        sim.AnimateRectangle(
            spec=(210, 210, 310, 290),
            fillcolor="#d6eaf8",
            linecolor="#7f8c8d",
            env=env,
            keep=True,
        )
        sim.AnimateText(
            text="CNC Buffer",
            x=260,
            y=300,
            text_anchor="c",
            fontsize=13,
            env=env,
        )
        sim.AnimateRectangle(
            spec=(470, 210, 570, 290),
            fillcolor="#d5f5e3",
            linecolor="#7f8c8d",
            env=env,
            keep=True,
        )
        sim.AnimateText(
            text="Shipping",
            x=520,
            y=300,
            text_anchor="c",
            fontsize=13,
            env=env,
        )

        sim.AnimateText(
            text=lambda: f"Sim clock: {env.now():.0f}s",
            x=30,
            y=370,
            fontsize=12,
            text_anchor="w",
            env=env,
        )
        sim.AnimateText(
            text=lambda: f"Shipping buffer: {len(env.shipping_buffer)} pallets",
            x=30,
            y=350,
            fontsize=12,
            text_anchor="w",
            env=env,
        )
        sim.AnimateText(
            text=lambda: f"Parts completed: {env.stats.completed_parts}",
            x=30,
            y=330,
            fontsize=12,
            text_anchor="w",
            env=env,
        )
        sim.AnimateText(
            text=lambda: f"Pallets shipped: {env.stats.pallets_shipped}",
            x=30,
            y=310,
            fontsize=12,
            text_anchor="w",
            env=env,
        )

    def _spawn_forklifts(self) -> None:
        self._forklifts = []
        for i in range(self.params.n_forklifts):
            fl = Forklift(env=self.env, name=f"forklift_{i + 1}", idx=i + 1)
            self._forklifts.append(fl)

    def schedule_raw_delivery(self, pallet: Pallet) -> None:
        if self.env.raw_storage_count >= self.params.raw_storage_capacity:
            self.env.raw_wait_queue.append(pallet)
            return
        self.env.raw_storage_count += 1
        params = self.params
        speed = max(1e-6, params.forklift_speed_mps)
        distance = params.receiving_to_cnc_distance_m * params.path_multiplier
        travel_time = distance / speed
        task = ForkliftTask(
            task_type="raw_to_cnc",
            pallet=pallet,
            source="receiving",
            destination="cnc_buffer",
            distance_m=distance,
            travel_time=travel_time,
            pickup_time=params.pick_from_storage_delay,
            dropoff_time=params.put_in_storage_delay,
            description=f"Deliver {pallet.name()} to CNC buffer",
            on_drop=pallet.begin_processing,
            priority=0,
            seq=self.env.task_seq + 1,
        )
        self.env.task_seq += 1
        self.env.forklift_coordinator.add_task(task)

    def schedule_finished_pallet(self, pallet: Pallet) -> None:
        if self.env.finished_storage_count >= self.params.finished_storage_capacity:
            self.env.finished_wait_queue.append(pallet)
            return
        self.env.finished_storage_count += 1
        params = self.params
        speed = max(1e-6, params.forklift_speed_mps)
        distance = params.cnc_to_shipping_distance_m * params.path_multiplier
        travel_time = distance / speed

        task = ForkliftTask(
            task_type="cnc_to_shipping",
            pallet=pallet,
            source="cnc_buffer",
            destination="shipping",
            distance_m=distance,
            travel_time=travel_time,
            pickup_time=params.pick_from_storage_delay,
            dropoff_time=params.put_in_storage_delay,
            description=f"Move {pallet.name()} to shipping",
            on_drop=lambda: self._on_pallet_ready_for_shipping(pallet),
            priority=1,
            seq=self.env.task_seq + 1,
        )
        self.env.task_seq += 1
        self.env.forklift_coordinator.add_task(task)

    def _on_pallet_ready_for_shipping(self, pallet: Pallet) -> None:
        self.env.shipping_buffer.add(pallet)
        traceln(
            f"{pallet.name()} READY at shipping buffer",
            color="orange",
            sim_time=self.env.now(),
            channel="detail",
        )

    def setup(self):
        self._spawn_forklifts()
        RawTruckGenerator(env=self.env, name="raw_truck_gen")
        Reporter(env=self.env, name="reporter",
                 interval=self.report_interval_s)

    def run(self):
        self.setup()
        self.env.run(till=self.params.sim_time)
        return self.env.stats

    def close_tracer(self) -> None:
        if self._tracer:
            self._tracer.close()
            self._tracer = None

    def report(self):
        stats = self.env.stats
        sim_hours = self.params.sim_time / 3600.0
        avg = stats.avg_time_in_system
        th = stats.throughput_per_hour(self.params.sim_time)
        traceln("--- Job Shop (Salabim) Report ---",
                color="yellow", channel="summary")
        print(f"Simulated time: {sim_hours:.2f}h")
        print(f"Completed parts: {stats.completed_parts}")
        print(f"Average time in system: {avg:.2f}s ({avg / 60:.2f}min)")
        print(f"Throughput: {th:.2f} parts/hour")
        print(f"Completed pallets: {stats.completed_pallets}")
        print(f"Pallets shipped: {stats.pallets_shipped}")
        shipping_summary = (
            f"Shipping trucks arrived: {stats.shipping_trucks_arrived} "
            f"(full={stats.shipping_trucks_departed_full}, "
            f"partial={stats.shipping_trucks_departed_partial})"
        )
        print(shipping_summary)
        if stats.pallet_wait_times:
            print(f"Avg pallet wait for truck: {stats.avg_pallet_wait:.2f}s")
        else:
            print("Avg pallet wait for truck: n/a")
        forklift_summary = (
            f"Forklift tasks: {stats.forklift_tasks_completed} "
            f"(distance={stats.forklift_distance_m:.1f}m "
            f"travel_time={stats.forklift_travel_time_s:.1f}s)"
        )
        print(forklift_summary)
        print("Category times (avg minutes per part, share of total):")
        for label, minutes, pct in stats.category_breakdown():
            print(f" - {label}: {minutes:.2f} min ({pct:.0f}%)")
