from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from control.adaptive_controller import FaultAwareAdaptiveController
from control.baseline_controller import ControlCommand, BaselineThresholdController
from control.constrained_adaptive_controller import ConstrainedAdaptiveController
from twin.fault_detector import FaultDetection, FaultDetector
from twin.fault_severity import estimate_fault_severity
from twin.predictor import ThermalForecast, ThermalPredictor
from twin.state_estimator import StateEstimate, ThermalStateEstimator


@dataclass(frozen=True)
class PipelineConfig:
    ambient_C: float = 25.0
    winding_frame_Rth: float = 0.0400
    frame_ambient_Rth: float = 0.086672
    winding_capacitance: float = 1500.0
    frame_capacitance: float = 9000.0
    minimum_load_pu: float = 0.50
    reference_load_pu: float = 1.00
    warning_temperature_C: float = 100.0
    critical_temperature_C: float = 120.0
    vibration_warning_mm_s: float = 2.8
    safety_buffer_C: float = 5.0


@dataclass
class PipelineResult:
    estimate: StateEstimate
    detection: FaultDetection
    severity: dict[str, float]
    forecast: ThermalForecast
    command: ControlCommand
    controller_name: str
    controller_operating_mode: str
    trial_action: str
    severity_band: str
    correct_action: str
    controller_predicted_temperature_C: float
    controller_safety_margin_C: float
    controller_derating_fraction: float
    sensor_reliability: float


def severity_band(result: PipelineResult) -> str:
    """Map the active controller condition to the trial's three bands."""
    if result.controller_operating_mode == "EMERGENCY":
        return "high"
    if result.controller_operating_mode in {
        "EMERGENCY_DERATING",
        "ADAPTIVE_DERATING",
        "THERMAL_PREVENTION",
        "FAULT_AWARE",
        "PROTECTIVE",
    } or result.severity["overall"] >= 0.50:
        return "medium"
    return "low"


def trial_action_for_mode(mode: str) -> str:
    """Return the participant oracle while preserving the raw mode."""
    if mode == "EMERGENCY":
        # Experimental reinterpretation: human operators are expected to
        # choose shutdown for EMERGENCY, although the automatic controller
        # only derates to its minimum load and never issues shutdown itself.
        return "shutdown"
    if mode in {
        "EMERGENCY_DERATING",
        "ADAPTIVE_DERATING",
        "THERMAL_PREVENTION",
        "FAULT_AWARE",
        "PROTECTIVE",
    }:
        return "derate"
    return "continue"


class TwinPipeline:
    """Single estimator, diagnosis, prediction, and control implementation."""

    def __init__(self, controller_name: str = "constrained", config: PipelineConfig | None = None) -> None:
        if controller_name not in {"baseline", "adaptive", "constrained"}:
            raise ValueError(f"Unknown controller: {controller_name}")

        self.controller_name = controller_name
        self.config = config or PipelineConfig()
        self.estimator = ThermalStateEstimator(
            ambient_C=self.config.ambient_C,
            r_winding_frame_K_W=self.config.winding_frame_Rth,
            r_frame_ambient_K_W=self.config.frame_ambient_Rth,
            c_winding_J_K=self.config.winding_capacitance,
            c_frame_J_K=self.config.frame_capacitance,
        )
        self.predictor = ThermalPredictor(self.estimator)
        self.detector = FaultDetector(
            sensor_bias_threshold_C=6.0,
            cooling_residual_threshold_C=3.0,
            vibration_warning_mm_s=self.config.vibration_warning_mm_s,
            estimated_temp_warning_C=self.config.warning_temperature_C,
        )
        self.baseline = BaselineThresholdController(
            self.config.minimum_load_pu,
            self.config.reference_load_pu,
            self.config.warning_temperature_C,
            self.config.critical_temperature_C,
        )
        self.adaptive = FaultAwareAdaptiveController(
            self.config.minimum_load_pu,
            self.config.reference_load_pu,
            self.config.warning_temperature_C,
            self.config.critical_temperature_C,
        )
        self.constrained = ConstrainedAdaptiveController(
            critical_temperature_C=self.config.critical_temperature_C,
            warning_temperature_C=self.config.warning_temperature_C,
            minimum_load_pu=0.70,
            maximum_load_pu=self.config.reference_load_pu,
            minimum_cooling_pu=0.50,
            maximum_cooling_pu=1.00,
            safety_buffer_C=self.config.safety_buffer_C,
        )

    def reset(self, measurement: dict[str, float]) -> None:
        self.estimator.initialize_from_measurement(measurement)
        self.detector = FaultDetector(
            sensor_bias_threshold_C=6.0,
            cooling_residual_threshold_C=3.0,
            vibration_warning_mm_s=self.config.vibration_warning_mm_s,
            estimated_temp_warning_C=self.config.warning_temperature_C,
        )
        self.adaptive.previous_load = self.config.reference_load_pu
        self.constrained.reset()

    def tick(
        self,
        measurement: dict[str, float],
        previous_command: ControlCommand,
        dt_s: float,
    ) -> PipelineResult:
        estimate = self.estimator.update(
            measurement,
            previous_command.cooling_flow_pu,
            dt_s,
        )
        detection = self.detector.detect(estimate, measurement)
        severity = estimate_fault_severity(estimate, detection, measurement)
        forecast = self.predictor.predict(
            measurement,
            previous_command.cooling_flow_pu,
        )

        if self.controller_name == "baseline":
            command = self.baseline.compute(measurement)
            mode = "NORMAL" if command.load_pu >= 0.99 else "PROTECTIVE"
            predicted = max(forecast.predicted_30s_C, forecast.predicted_60s_C)
            margin = self.config.critical_temperature_C - predicted
            derating = max(0.0, min(1.0, 1.0 - command.load_pu / max(self.config.reference_load_pu, 1e-9)))
            reliability = 0.5 if detection.sensor_bias else 1.0
        elif self.controller_name == "adaptive":
            command = self.adaptive.compute(estimate, detection, severity, forecast)
            mode = "NORMAL" if command.load_pu >= 0.99 else "ADAPTIVE_DERATING"
            predicted = max(forecast.predicted_30s_C, forecast.predicted_60s_C)
            margin = self.config.critical_temperature_C - predicted
            derating = max(0.0, min(1.0, 1.0 - command.load_pu / max(self.config.reference_load_pu, 1e-9)))
            reliability = 0.5 if detection.sensor_bias else 1.0
        else:
            reliability = 0.5 if detection.sensor_bias else 1.0
            # A normal startup temperature ramp contributes to the raw rate
            # severity signal, but must not become a cooling fault before the
            # detector's persistence and hysteresis rules have fired.
            cooling_efficiency = (
                max(0.05, min(1.0, 1.0 - severity["cooling_degradation"]))
                if detection.cooling_degradation
                else 1.0
            )
            output = self.constrained.update(
                commanded_load_pu=self.config.reference_load_pu,
                estimated_temperature_C=estimate.estimated_winding_C,
                predicted_temperature_30s_C=forecast.predicted_30s_C,
                predicted_temperature_60s_C=forecast.predicted_60s_C,
                fault_severity=severity["overall"],
                cooling_efficiency=cooling_efficiency,
                sensor_reliability=reliability,
            )
            command = ControlCommand(
                load_pu=output.load_command_pu,
                speed_pu=1.0,
                cooling_flow_pu=output.cooling_command_pu,
            )
            mode = output.operating_mode
            predicted = output.predicted_temperature_C
            margin = output.safety_margin_C
            derating = output.derating_fraction

        result = PipelineResult(
            estimate=estimate,
            detection=detection,
            severity=severity,
            forecast=forecast,
            command=command,
            controller_name=self.controller_name,
            controller_operating_mode=mode,
            trial_action="continue",
            severity_band="low",
            correct_action="continue",
            controller_predicted_temperature_C=predicted,
            controller_safety_margin_C=margin,
            controller_derating_fraction=derating,
            sensor_reliability=reliability,
        )
        result.severity_band = severity_band(result)
        result.trial_action = trial_action_for_mode(mode)
        result.correct_action = result.trial_action
        return result


def pipeline_config_from_yaml(config: dict[str, Any]) -> PipelineConfig:
    thermal = config.get("thermal_model", {})
    safety = config.get("safety", {})
    return PipelineConfig(
        ambient_C=float(thermal.get("ambient_temperature_C", 25.0)),
        winding_frame_Rth=float(thermal.get("winding_frame_Rth_K_per_W", 0.0400)),
        frame_ambient_Rth=float(thermal.get("frame_ambient_Rth_K_per_W", 0.086672)),
        winding_capacitance=float(thermal.get("winding_thermal_capacitance_J_per_K", 1500.0)),
        frame_capacitance=float(thermal.get("frame_thermal_capacitance_J_per_K", 9000.0)),
        minimum_load_pu=float(safety.get("minimum_load_pu", 0.50)),
        reference_load_pu=float(safety.get("reference_load_pu", 1.00)),
        warning_temperature_C=float(safety.get("winding_warning_C", 100.0)),
        critical_temperature_C=float(safety.get("winding_critical_C", 120.0)),
        vibration_warning_mm_s=float(safety.get("vibration_warning_mm_s", 2.8)),
    )