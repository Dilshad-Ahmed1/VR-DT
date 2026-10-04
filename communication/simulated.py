from __future__ import annotations

from communication.interface import PlantCommunication
from plant.interface import PlantInterface


class SimulatedCommunication(PlantCommunication):
    """In-process transport for the FMU-backed simulation."""

    def __init__(self, plant: PlantInterface) -> None:
        super().__init__(plant)