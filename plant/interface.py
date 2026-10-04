from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlantState:
    """Observable plant state shared by simulation and future hardware."""

    timestamp_s: float
    speed_rpm: float
    temperature_C: float
    current_A: float
    voltage_V: float
    electrical_power_W: float
    load_torque_Nm: float
    vibration_mm_s: float | None = None
    frame_temperature_C: float | None = None
    shaft_power_W: float | None = None
    motor_torque_Nm: float | None = None
    motor_status: str = "unknown"
    ambient_temperature_C: float | None = None
    supply_frequency_Hz: float | None = None
    power_factor: float | None = None
    reactive_power_var: float | None = None
    voltage_unbalance_percent: float | None = None
    current_pu: float | None = None
    load_torque_pu: float | None = None

    def as_measurement(self) -> dict[str, float]:
        """Adapt standard observations to the existing twin APIs."""
        shaft_power = self.shaft_power_W or 0.0
        values = {
            "timestamp_s": self.timestamp_s,
            "T_sensor_C": self.temperature_C,
            "T_frame_C": self.frame_temperature_C
            if self.frame_temperature_C is not None
            else self.temperature_C,
            "speed_rpm": self.speed_rpm,
            "omega_rad_s": self.speed_rpm * 2.0 * 3.141592653589793 / 60.0,
            "I_rms_A": self.current_A,
            "P_electrical_W": self.electrical_power_W,
            "torque_load_Nm": self.load_torque_Nm,
            "torque_motor_Nm": self.motor_torque_Nm or self.load_torque_Nm,
            "P_shaft_W": shaft_power,
            "P_loss_total_W": max(0.0, self.electrical_power_W - shaft_power),
        }
        optional = {
            "T_ambient_C": self.ambient_temperature_C,
            "supply_frequency_Hz": self.supply_frequency_Hz,
            "power_factor": self.power_factor,
            "reactive_power_var": self.reactive_power_var,
            "voltage_unbalance_percent": self.voltage_unbalance_percent,
            "current_pu": self.current_pu,
            "load_torque_pu": self.load_torque_pu,
            "vibration_mm_s_out": self.vibration_mm_s,
        }
        values.update(
            {name: value for name, value in optional.items() if value is not None}
        )
        return {key: float(value) for key, value in values.items()}


@dataclass(frozen=True)
class ControlCommand:
    """Command sent across the plant/communication boundary."""

    load_torque_pu: float = 1.0
    requested_speed_pu: float = 1.0
    cooling_flow_pu: float = 1.0
    timestamp_s: float = 0.0
    command_id: str = ""
    source: str = "controller"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_inputs(self) -> dict[str, float]:
        return {
            "u_speed_pu": float(self.requested_speed_pu),
            "u_load_torque_pu": float(self.load_torque_pu),
            "u_cooling_flow_pu": float(self.cooling_flow_pu),
        }

    @property
    def load_pu(self) -> float:
        return self.load_torque_pu

    @property
    def speed_pu(self) -> float:
        return self.requested_speed_pu


class PlantInterface(ABC):
    """Lifecycle and I/O contract implemented by simulation and hardware."""

    @abstractmethod
    def start(self) -> PlantState:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_state(self) -> PlantState:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command: ControlCommand) -> None:
        raise NotImplementedError

    @abstractmethod
    def step(self, step_s: float) -> PlantState:
        raise NotImplementedError