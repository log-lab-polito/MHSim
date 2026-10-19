"""Storage slot inventory, reservation, and store/retrieve selection policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Literal, Tuple

import simpy

from .movement import Position3D
from .spatial import Storage


@dataclass(frozen=True)
class StorageSlot:
    """One addressable cell in a storage rack.

    Slots are created once at construction and thereafter only move between the
    manager's available, reserved, and occupied collections. They are frozen so
    they can live in sets.

    Attributes:
        shelf_id: Identifier of the owning shelf.
        level: Zero-based level index, counting upwards from the floor.
        position: Zero-based bay index along the shelf.
        ground_pos: Floor-level approach coordinate for this cell, that is the
            cell centre with `z` set to zero. A forklift drives here and then
            lifts to the cell's own height.
    """

    shelf_id: str
    level: int
    position: int
    ground_pos: Position3D


class StorageSlotManager:
    """Tracks slot occupancy and applies store and retrieve selection policies.

    The manager owns three disjoint collections — available, reserved, and
    occupied — and moves slots between them in two phases. A reservation takes
    a slot out of circulation immediately, so two forklifts dispatched in the
    same instant can never be sent to the same cell; the matching `complete_`
    call then commits the move once the travel and lift have actually happened.

    Attributes:
        available_slots: Empty slots free to be reserved for storage.
        occupied_slots: Slots holding a pallet, available for retrieval.
        store_policy: `FIRST`, `BEST` or `LOWEST`, upper-cased at construction.
        retrieve_policy: One of `FIFO`, `LIFO`, or `BEST`,
            upper-cased at construction.
    """

    def __init__(
        self,
        storage: Storage,
        store_policy: Literal["FIRST", "BEST", "LOWEST"] = "FIRST",
        retrieve_policy: Literal["FIFO", "LIFO", "BEST"] = "LIFO",
    ) -> None:
        """Enumerate every cell in the storage and set the selection policies.

        Args:
            storage: Storage whose shelves are walked to build the slot list.
                Every level and bay of every shelf becomes one `StorageSlot`,
                all initially available.
            store_policy: `FIRST` takes the lowest-indexed free slot;
                `BEST` minimises a caller-supplied cost function; `LOWEST`
                takes the lowest free level of the first bay with room, as
                AnyLogic's Store does.
            retrieve_policy: `FIFO` takes the longest-stored pallet,
                `LIFO` the most recent, and `BEST` minimises a
                caller-supplied cost function.

        Raises:
            ValueError: If either policy is not one of its permitted values.
        """
        self.available_slots: List[StorageSlot] = []
        self.occupied_slots: List[StorageSlot] = []
        self._reserved_store: set[StorageSlot] = set()
        self._reserved_retrieve: set[StorageSlot] = set()
        self.store_policy = store_policy.upper()
        self.retrieve_policy = retrieve_policy.upper()
        self._bay_access: Dict[Tuple[float, float], simpy.Resource] = {}
        if self.store_policy not in ("FIRST", "BEST", "LOWEST"):
            raise ValueError(f"Unsupported store_policy: {store_policy}")
        if self.retrieve_policy not in ("FIFO", "LIFO", "BEST"):
            raise ValueError(f"Unsupported retrieve_policy: {retrieve_policy}")

        for shelf in storage.shelves:
            for level in range(shelf.levels):
                for position in range(shelf.positions_per_level):
                    cell_pos = shelf.get_cell_position(level, position)
                    ground_pos = Position3D(cell_pos.x, cell_pos.y, 0)
                    self.available_slots.append(
                        StorageSlot(
                            shelf_id=shelf.id,
                            level=level,
                            position=position,
                            ground_pos=ground_pos,
                        )
                    )

    def _reserve_first(
        self,
        source: List[StorageSlot],
        reserved: set[StorageSlot],
    ) -> Optional[StorageSlot]:
        if not source:
            return None
        slot = source.pop(0)
        reserved.add(slot)
        return slot

    def _reserve_best(
        self,
        source: List[StorageSlot],
        reserved: set[StorageSlot],
        cost_fn: Callable[[StorageSlot], float],
    ) -> Optional[StorageSlot]:
        if not source:
            return None
        best_slot = None
        best_cost = None
        for slot in source:
            cost = cost_fn(slot)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_slot = slot
        if best_slot is None:
            return None
        source.remove(best_slot)
        reserved.add(best_slot)
        return best_slot

    def _reserve_last(
        self,
        source: List[StorageSlot],
        reserved: set[StorageSlot],
    ) -> Optional[StorageSlot]:
        if not source:
            return None
        slot = source.pop()
        reserved.add(slot)
        return slot

    def bay_access(self, env: simpy.Environment, slot: StorageSlot) -> simpy.Resource:
        """The bay a slot is served from takes one rack transfer at a time (R5).

        AnyLogic makes a transporter that reaches the bay while another is in the rack
        wait at the path exit until that one comes out; transfers go first come, first
        served. Slots sharing a ground position share the bay.
        """
        key = (round(slot.ground_pos.x, 6), round(slot.ground_pos.y, 6))
        if key not in self._bay_access:
            self._bay_access[key] = simpy.Resource(env, capacity=1)
        return self._bay_access[key]

    def reserve_for_store(
        self,
        cost_fn: Callable[[StorageSlot], float],
    ) -> Optional[StorageSlot]:
        """Reserve an empty slot for an incoming pallet.

        The slot leaves `available_slots` immediately and is held until
        `complete_store` commits it.

        Args:
            cost_fn: Cost of travelling to a candidate slot, minimised under
                the `BEST` policy and ignored under `FIRST`.

        Returns:
            The reserved slot, or `None` if the storage is full.
        """
        if self.store_policy == "BEST":
            return self._reserve_best(self.available_slots, self._reserved_store, cost_fn)
        if self.store_policy == "LOWEST":
            # AnyLogic Store fills the first bay from its lowest free shelf upwards
            # (docs/forklift_rules/R5_rack_handling_and_slots.md).
            return self._reserve_best(
                self.available_slots,
                self._reserved_store,
                lambda slot: (slot.shelf_id, slot.position, slot.level),
            )
        return self._reserve_first(self.available_slots, self._reserved_store)

    def reserve_for_retrieve(
        self,
        cost_fn: Callable[[StorageSlot], float],
    ) -> Optional[StorageSlot]:
        """Reserve an occupied slot for an outbound pallet.

        The slot leaves `occupied_slots` immediately and is held until
        `complete_retrieve` commits it. Reserved slots still count as
        occupied for display purposes; see `occupancy_grid`.

        Args:
            cost_fn: Cost of travelling to a candidate slot, minimised under
                the `BEST` policy and ignored under `FIFO` and `LIFO`.

        Returns:
            The reserved slot, or `None` if the storage is empty.
        """
        if self.retrieve_policy == "FIFO":
            return self._reserve_first(self.occupied_slots, self._reserved_retrieve)
        if self.retrieve_policy == "BEST":
            return self._reserve_best(self.occupied_slots, self._reserved_retrieve, cost_fn)
        return self._reserve_last(self.occupied_slots, self._reserved_retrieve)

    def complete_store(self, slot: StorageSlot) -> None:
        """Commit a storage reservation once the pallet is physically in place.

        Args:
            slot: Slot previously returned by `reserve_for_store`. Calls
                with an unreserved slot are ignored, which makes the operation
                idempotent.
        """
        if slot in self._reserved_store:
            self._reserved_store.remove(slot)
            self.occupied_slots.append(slot)

    def complete_retrieve(self, slot: StorageSlot) -> None:
        """Commit a retrieval once the pallet has physically left the cell.

        Args:
            slot: Slot previously returned by `reserve_for_retrieve`. Calls
                with an unreserved slot are ignored, which makes the operation
                idempotent.
        """
        if slot in self._reserved_retrieve:
            self._reserved_retrieve.remove(slot)
            self.available_slots.append(slot)

    def occupancy_grid(self, storage: Storage) -> List[List[str]]:
        """Summarise occupancy per shelf and bay as display strings.

        Args:
            storage: Storage to lay out. Must be the one the manager was built
                from, since shelf identifiers and bay counts are read from it.

        Returns:
            One row per shelf, one entry per bay, each a comma-separated list
            of **one-based** occupied level numbers, or an empty string for an
            empty bay. Slots reserved for retrieval still read as occupied,
            because the pallet has not physically left yet.
        """
        occupancy: dict[tuple[str, int], list[int]] = {}
        for shelf in storage.shelves:
            for position in range(shelf.positions_per_level):
                occupancy[(shelf.id, position)] = []

        for slot in self.occupied_slots:
            occupancy[(slot.shelf_id, slot.position)].append(slot.level)
        for slot in self._reserved_retrieve:
            occupancy[(slot.shelf_id, slot.position)].append(slot.level)

        grid: List[List[str]] = []
        for shelf in storage.shelves:
            row: List[str] = []
            for position in range(shelf.positions_per_level):
                levels = sorted(occupancy[(shelf.id, position)])
                if levels:
                    row.append(",".join(str(level + 1) for level in levels))
                else:
                    row.append("")
            grid.append(row)
        return grid
