from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SimulationEvaluation:
    """Simulation-only truth used for offline evaluation, never control."""

    timestamp_s: float
    outputs: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.outputs)