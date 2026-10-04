from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ControlCommand:
    load_pu: float
    speed_pu: float = 1.0
    cooling_flow_pu: float = 1.0


class BaselineThresholdController:
    """Conventional temperature-threshold controller using raw sensor data."""

    def __init__(
        self,
        minimum_load_pu: float = 0.50,
        reference_load_pu: float = 1.00,
        warning_C: float = 100.0,
        critical_C: float = 120.0,
    ) -> None:
        self.minimum_load_pu = minimum_load_pu
        self.reference_load_pu = reference_load_pu
        self.warning_C = warning_C
        self.critical_C = critical_C

    def compute(
        self,
        measurement: dict[str, float],
        sensor_reliable: bool = True,
    ) -> ControlCommand:
        T = float(measurement["T_sensor_C"])
        if not sensor_reliable:
            load = self.minimum_load_pu
        elif T >= self.critical_C:
            load = self.minimum_load_pu
        elif T >= self.warning_C:
            alpha = (T - self.warning_C) / (self.critical_C - self.warning_C)
            load = self.reference_load_pu - alpha * (self.reference_load_pu - self.minimum_load_pu)
        else:
            load = self.reference_load_pu
        return ControlCommand(load_pu=max(self.minimum_load_pu, min(self.reference_load_pu, load)))
