from __future__ import annotations

from plant.interface import ControlCommand, PlantInterface, PlantState


class HardwarePlant(PlantInterface):
    """Explicit future hardware boundary; no hardware is assumed today."""

    def _not_implemented(self) -> None:
        raise NotImplementedError(
            "HardwarePlant requires a PLC/VFD and sensor transport implementation."
        )

    def start(self) -> PlantState:
        self._not_implemented()

    def stop(self) -> None:
        self._not_implemented()

    def reset(self) -> None:
        self._not_implemented()

    def read_state(self) -> PlantState:
        self._not_implemented()

    def send_command(self, command: ControlCommand) -> None:
        self._not_implemented()

    def step(self, step_s: float) -> PlantState:
        self._not_implemented()