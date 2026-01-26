from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .movement import Position3D
from .spatial import Storage


@dataclass(frozen=True)
class StorageSlot:
    shelf_id: str
    level: int
    position: int
    ground_pos: Position3D


class StorageSlotManager:
    def __init__(self, storage: Storage):
        self.available_slots: List[StorageSlot] = []
        self.occupied_slots: List[StorageSlot] = []
        self._reserved_store: set[StorageSlot] = set()
        self._reserved_retrieve: set[StorageSlot] = set()

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

    def reserve_for_store(
        self,
        cost_fn: Callable[[StorageSlot], float],
    ) -> Optional[StorageSlot]:
        return self._reserve_best(self.available_slots, self._reserved_store, cost_fn)

    def reserve_for_retrieve(
        self,
        cost_fn: Callable[[StorageSlot], float],
    ) -> Optional[StorageSlot]:
        return self._reserve_best(self.occupied_slots, self._reserved_retrieve, cost_fn)

    def complete_store(self, slot: StorageSlot) -> None:
        if slot in self._reserved_store:
            self._reserved_store.remove(slot)
            self.occupied_slots.append(slot)

    def complete_retrieve(self, slot: StorageSlot) -> None:
        if slot in self._reserved_retrieve:
            self._reserved_retrieve.remove(slot)
            self.available_slots.append(slot)

    def occupancy_grid(self, storage: Storage) -> List[List[str]]:
        """Return occupied shelf levels per rack/bay as display strings."""
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
