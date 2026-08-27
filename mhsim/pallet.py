"""The minimal entity passed between MHSim process blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Pallet:
    """A unit load moving through a model.

    `Pallet` carries no domain behaviour of its own. Blocks read and write
    `attributes` to attach whatever state a particular flow needs — a forklift
    assignment, a conveyor location, a cycle start timestamp — which keeps the
    entity type stable across case studies that model very different things.

    Attributes:
        id: Identifier unique within a run, assigned by the source block in
            creation order starting at 1.
        created_at: Simulation time in seconds at which the pallet entered the
            model. Cycle time is measured from this value.
        attributes: Free-form per-entity state, keyed by string. Blocks that
            store here document the key they use; see
            `mhsim.blocks` for forklift assignments and `mhsim.conveyor` for
            conveyor locations.
    """

    id: int
    created_at: float
    attributes: Dict[str, object] = field(default_factory=dict)
