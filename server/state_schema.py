from __future__ import annotations

import time
from typing import Any

from .twin_pipeline import PipelineResult


SCHEMA_VERSION = "twin_state_v1"


def build_state(
    tick: int,
    simulation_time_s: float,
    scenario: str,
    measurement: dict[str, float],
    result: PipelineResult,
) -> dict[str, Any]:
    """Build the one payload shared by WebSocket, VR, and live UI clients."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tick": int(tick),
        "monotonic_tick_timestamp_ns": time.monotonic_ns(),
        "simulation_time_s": float(simulation_time_s),
        "scenario": scenario,
        "measurements": {key: float(value) for key, value in measurement.items()},
        "estimated_thermal": {
            "winding_C": result.estimate.estimated_winding_C,
            "frame_C": result.estimate.estimated_frame_C,
            "winding_rate_C_s": result.estimate.estimated_winding_rate_C_s,
            "sensor_residual_C": result.estimate.sensor_residual_C,
            "frame_innovation_C": result.estimate.frame_innovation_C,
            "frame_model_residual_C": result.estimate.frame_model_residual_C,
        },
        "faults": {
            "sensor_bias": result.detection.sensor_bias,
            "cooling_degradation": result.detection.cooling_degradation,
            "mechanical_unbalance": result.detection.mechanical_unbalance,
            "thermal_warning": result.detection.thermal_warning,
            "alarm": result.detection.alarm,
            "primary_fault": result.detection.primary_fault,
        },
        "severity": {
            "sensor_bias": result.severity["sensor_bias"],
            "cooling_degradation": result.severity["cooling_degradation"],
            "mechanical_unbalance": result.severity["mechanical_unbalance"],
            "overall": result.severity["overall"],
            "band": result.severity_band,
        },
        "prediction": {
            "winding_30s_C": result.forecast.predicted_30s_C,
            "winding_60s_C": result.forecast.predicted_60s_C,
        },
        "controller": {
            "name": result.controller_name,
            "operating_mode": result.controller_operating_mode,
            "load_command_pu": result.command.load_pu,
            "speed_command_pu": result.command.speed_pu,
            "cooling_command_pu": result.command.cooling_flow_pu,
            "predicted_temperature_C": result.controller_predicted_temperature_C,
            "safety_margin_C": result.controller_safety_margin_C,
            "derating_fraction": result.controller_derating_fraction,
        },
        "trial": {
            "action_label": result.trial_action,
            "correct_action": result.correct_action,
            "experimental_shutdown_reinterpretation": (
                result.controller_operating_mode == "EMERGENCY"
            ),
        },
    }