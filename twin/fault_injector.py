from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


SCENARIO_DEFAULTS: dict[str, dict[str, float]] = {
    "bearing_wear_proxy": {"friction_factor": 2.0},
    "sensor_bias": {"sensor_bias_C": 10.0},
    "sensor_drift": {"sensor_bias_C": 10.0},
    "sensor_freeze": {},
    "cooling": {"cooling_efficiency": 0.40},
    "cooling_failure": {"cooling_efficiency": 0.05},
    "rth_degradation": {"rth_degradation": 2.0},
    "overload": {"load_overload_pu": 0.20},
    "sudden_overload": {"load_increase_pu": 0.50},
    "mechanical_friction": {"friction_factor": 2.0},
    "voltage_imbalance": {"voltage_unbalance_pu": 0.03},
    "supply_degradation": {"supply_degradation_pu": 0.10},
    "frequency_deviation": {"frequency_deviation_pu": 0.02},
    "combined_supported": {
        "sensor_bias_C": 8.0,
        "cooling_efficiency": 0.60,
        "load_overload_pu": 0.10,
        "supply_degradation_pu": 0.05,
    },
}


@dataclass(frozen=True)
class FaultProfile:
    fault_type: str
    start_tick: int
    step_s: float = 0.5
    duration_s: float = 600.0
    parameters: dict[str, float] | None = None


class FaultInjector:
    """Tick-based induction plant injector used identically in batch and live runs."""

    def __init__(self, profile: FaultProfile) -> None:
        if profile.fault_type not in SCENARIO_DEFAULTS:
            raise ValueError(f"Unsupported induction fault scenario: {profile.fault_type}")
        if profile.start_tick < 0 or profile.step_s <= 0.0 or profile.duration_s <= 0.0:
            raise ValueError("start_tick must be non-negative; step and duration must be positive")
        self.profile = profile
        self.parameters = dict(SCENARIO_DEFAULTS[profile.fault_type])
        if profile.parameters:
            self.parameters.update(profile.parameters)

    @property
    def start_tick(self) -> int:
        return self.profile.start_tick

    def elapsed_s(self, tick: int) -> float:
        return max(0.0, (tick - self.profile.start_tick) * self.profile.step_s)

    def progress(self, tick: int) -> float:
        if tick < self.profile.start_tick:
            return 0.0
        return min(1.0, self.elapsed_s(tick) / max(self.profile.duration_s, self.profile.step_s))

    def severity_at(self, tick: int) -> dict[str, float]:
        progress = self.progress(tick)
        params = self.parameters
        elapsed = self.elapsed_s(tick)
        cooling_target = params.get("cooling_efficiency", 1.0)
        cooling_tau = max(self.profile.duration_s / 3.0, self.profile.step_s)
        cooling_efficiency = cooling_target + (1.0 - cooling_target) * math.exp(
            -elapsed / cooling_tau
        )
        overload_truth = (
            min(params.get("load_increase_pu", 0.0) / 0.5, 1.0)
            * float(tick >= self.start_tick)
            if self.profile.fault_type == "sudden_overload"
            else min(params.get("load_overload_pu", 0.0) / 0.5, 1.0) * progress
        )
        values = {
            "sensor_bias": min(abs(params.get("sensor_bias_C", 0.0)) / 10.0, 1.0) * progress,
            "sensor_freeze": float(self.profile.fault_type == "sensor_freeze" and tick >= self.start_tick),
            "cooling": min(max(0.0, 1.0 - cooling_efficiency), 1.0),
            "rth_degradation": min(
                max(0.0, params.get("rth_degradation", 1.0) - 1.0) / 4.0,
                1.0,
            ) * progress,
            "overload": overload_truth,
            "mechanical_friction": min(max(0.0, params.get("friction_factor", 1.0) - 1.0), 1.0) * progress,
            "voltage_imbalance": min(params.get("voltage_unbalance_pu", 0.0) / 0.05, 1.0) * progress,
            "supply_degradation": min(params.get("supply_degradation_pu", 0.0) / 0.2, 1.0) * progress,
            "frequency_deviation": min(abs(params.get("frequency_deviation_pu", 0.0)) / 0.05, 1.0) * progress,
        }
        if self.profile.fault_type == "combined_supported":
            values["sensor_bias"] = min(abs(params["sensor_bias_C"]) / 10.0, 1.0) * progress
            values["cooling"] = min(max(0.0, 1.0 - cooling_efficiency), 1.0)
            values["overload"] = min(params["load_overload_pu"] / 0.5, 1.0) * progress
            values["supply_degradation"] = min(params["supply_degradation_pu"] / 0.2, 1.0) * progress
        values["overall"] = max(values.values(), default=0.0)
        return values

    def apply(self, tick: int, inputs: dict[str, Any]) -> dict[str, Any]:
        values = dict(inputs)
        if tick < self.profile.start_tick:
            return values

        elapsed = self.elapsed_s(tick)
        progress = self.progress(tick)
        params = self.parameters
        fault_type = self.profile.fault_type

        if fault_type in {"sensor_bias", "sensor_drift"}:
            values["f_sensor_bias_C"] = params["sensor_bias_C"] * progress
        elif fault_type == "sensor_freeze":
            values["f_sensor_freeze"] = True
        elif fault_type in {"cooling", "cooling_failure"}:
            target = params["cooling_efficiency"]
            tau = max(self.profile.duration_s / 3.0, self.profile.step_s)
            values["f_cooling_eff"] = target + (1.0 - target) * math.exp(-elapsed / tau)
        elif fault_type == "rth_degradation":
            values["f_rth_degradation"] = 1.0 + (params["rth_degradation"] - 1.0) * progress
        elif fault_type == "overload":
            values["f_load_overload_pu"] = params["load_overload_pu"] * progress
        elif fault_type == "sudden_overload":
            values["u_load_torque_pu"] = min(1.5, float(values.get("u_load_torque_pu", 1.0)) + params["load_increase_pu"])
        elif fault_type in {"mechanical_friction", "bearing_wear_proxy"}:
            values["f_mechanical_friction_factor"] = 1.0 + (params["friction_factor"] - 1.0) * progress
        elif fault_type == "voltage_imbalance":
            values["f_voltage_unbalance_pu"] = params["voltage_unbalance_pu"] * progress
        elif fault_type == "supply_degradation":
            values["f_supply_voltage_degradation_pu"] = params["supply_degradation_pu"] * progress
        elif fault_type == "frequency_deviation":
            values["f_supply_frequency_deviation_pu"] = params["frequency_deviation_pu"] * progress
        elif fault_type == "combined_supported":
            values["f_sensor_bias_C"] = params["sensor_bias_C"] * progress
            target_eff = params["cooling_efficiency"]
            tau = max(self.profile.duration_s / 3.0, self.profile.step_s)
            values["f_cooling_eff"] = target_eff + (1.0 - target_eff) * math.exp(-elapsed / tau)
            values["f_load_overload_pu"] = params["load_overload_pu"] * progress
            values["f_supply_voltage_degradation_pu"] = params["supply_degradation_pu"] * progress

        return values


def injector_from_scenario(
    scenario: str,
    *,
    start_tick: int,
    step_s: float,
    duration_s: float = 600.0,
    parameters: dict[str, float] | None = None,
) -> FaultInjector:
    """Construct a reproducible tick-driven profile for an induction scenario."""
    return FaultInjector(
        FaultProfile(
            fault_type=scenario,
            start_tick=start_tick,
            step_s=step_s,
            duration_s=duration_s,
            parameters=parameters,
        )
    )
