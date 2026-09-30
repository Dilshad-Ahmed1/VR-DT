from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


SUPPORTED_FAULTS = {
    "bearing_wear",
    "sudden_overload",
    "cooling_failure",
    "voltage_imbalance",
    "sensor_drift",
}


@dataclass(frozen=True)
class FaultProfile:
    fault_type: str
    start_tick: int
    step_s: float = 0.5
    duration_s: float = 600.0
    target: float = 1.0


class FaultInjector:
    """One fault-injection path shared by batch and live execution."""

    def __init__(self, profile: FaultProfile) -> None:
        if profile.fault_type not in SUPPORTED_FAULTS:
            raise ValueError(f"Unsupported fault type: {profile.fault_type}")
        if profile.start_tick < 0 or profile.step_s <= 0.0:
            raise ValueError("start_tick must be non-negative and step_s positive")
        self.profile = profile

    @property
    def start_tick(self) -> int:
        return self.profile.start_tick

    def _elapsed_s(self, tick: int) -> float:
        return max(0.0, (tick - self.profile.start_tick) * self.profile.step_s)

    def _ramp(self, elapsed_s: float) -> float:
        return min(1.0, elapsed_s / max(self.profile.duration_s, self.profile.step_s))

    def _accelerating_cooling(self, elapsed_s: float) -> float:
        tau = max(self.profile.duration_s / 3.0, self.profile.step_s)
        return max(0.05, math.exp(-elapsed_s / tau))

    def apply(self, tick: int, inputs: dict[str, Any]) -> dict[str, Any]:
        values = dict(inputs)
        if tick < self.profile.start_tick:
            return values

        elapsed_s = self._elapsed_s(tick)
        progress = self._ramp(elapsed_s)
        target = self.profile.target

        if self.profile.fault_type == "bearing_wear":
            values["f_unbalance_severity"] = target * progress
            # Reduced-order thermal coupling for bearing-adjacent heating.
            values["f_rth_degradation"] = 1.0 + 0.5 * progress
        elif self.profile.fault_type == "sudden_overload":
            values["u_load_torque_pu"] = min(1.5, 1.0 + 0.5 * target)
        elif self.profile.fault_type == "cooling_failure":
            values["f_cooling_eff"] = self._accelerating_cooling(elapsed_s)
        elif self.profile.fault_type == "voltage_imbalance":
            values["f_voltage_imbalance_pu"] = target * progress
        elif self.profile.fault_type == "sensor_drift":
            values["f_sensor_bias_C"] = target * progress

        return values


def injector_from_scenario(
    scenario: str,
    *,
    start_tick: int,
    step_s: float,
    duration_s: float = 600.0,
    target: float | None = None,
) -> FaultInjector:
    defaults = {
        "bearing_wear": 0.75,
        "sudden_overload": 1.0,
        "cooling_failure": 1.0,
        "voltage_imbalance": 0.08,
        "sensor_drift": 10.0,
    }
    if scenario not in SUPPORTED_FAULTS:
        raise ValueError(f"Unsupported scenario: {scenario}")
    return FaultInjector(
        FaultProfile(
            fault_type=scenario,
            start_tick=start_tick,
            step_s=step_s,
            duration_s=duration_s,
            target=defaults[scenario] if target is None else target,
        )
    )