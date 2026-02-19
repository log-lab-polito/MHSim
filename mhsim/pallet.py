from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Pallet:
    id: int
    created_at: float
    attributes: Dict[str, object] = field(default_factory=dict)
