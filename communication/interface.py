from __future__ import annotations

from abc import ABC, abstractmethod

from plant.interface import ControlCommand, PlantInterface, PlantState


class CommunicationInterface(ABC):
    """Replaceable controller-to-device transport boundary."""

    @abstractmethod
    def read_state(self) -> PlantState:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command: ControlCommand) -> None:
        raise NotImplementedError

    @abstractmethod
    def step(self, step_s: float) -> PlantState:
        raise NotImplementedError


class PlantCommunication(CommunicationInterface):
    """Internal transport used by the current simulation."""

    def __init__(self, plant: PlantInterface) -> None:
        self.plant = plant

    def read_state(self) -> PlantState:
        return self.plant.read_state()

    def send_command(self, command: ControlCommand) -> None:
        self.plant.send_command(command)

    def step(self, step_s: float) -> PlantState:
        return self.plant.step(step_s)