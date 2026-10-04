from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from control.adaptive_controller import FaultAwareAdaptiveController
from control.baseline_controller import BaselineThresholdController
from control.constrained_adaptive_controller import ConstrainedAdaptiveController
from twin.fault_detector import FaultDetection, FaultDetector
from twin.fault_severity import estimate_fault_severity
from twin.predictor import ThermalForecast, ThermalPredictor
from twin.state_estimator import StateEstimate, ThermalStateEstimator
from plant.interface import ControlCommand


@dataclass(frozen=True)
class PipelineConfig:
    ambient_C: float = 20.0
    winding_frame_Rth: float = 0.010
    frame_ambient_Rth: float = 0.0296652
    winding_capacitance: float = 15000.0
    frame_capacitance: float = 35000.0
    winding_loss_fraction: float = 0.644
    minimum_load_pu: float = 0.50
    reference_load_pu: float = 1.00
    warning_temperature_C: float = 100.0
    critical_temperature_C: float = 120.0
    vibration_warning_mm_s: float = 2.8
    cooling_flow_offset: float = 0.0
    cooling_flow_gain: float = 1.0
    cooling_residual_threshold_C: float = 0.02
    cooling_residual_clear_C: float = 0.015
    cooling_severity_scale_C: float = 0.10
    rated_current_A: float = 32.85
    rated_voltage_V: float = 400.0
    rated_frequency_Hz: float = 50.0
    rated_speed_rpm: float = 1462.5
    rated_torque_Nm: float = 120.794521
    rated_output_W: float = 18500.0
    rated_efficiency: float = 0.9049
    safety_buffer_C: float = 5.0


@dataclass
class PipelineTimings:
    state_estimator_latency_ms: float = 0.0
    fault_detection_latency_ms: float = 0.0
    predictor_latency_ms: float = 0.0
    controller_latency_ms: float = 0.0

    @property
    def compute_latency_ms(self) -> float:
        return (
            self.state_estimator_latency_ms
            + self.fault_detection_latency_ms
            + self.predictor_latency_ms
            + self.controller_latency_ms
        )


@dataclass
class PipelineResult:
    measurement: dict[str, float]
    twin_measurement: dict[str, float]
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
    cooling_effectiveness_estimate: float
    timings: PipelineTimings


def trial_action_for_mode(mode: str) -> str:
    """Map controller modes to the study response oracle."""
    if mode == "EMERGENCY":
        # Shutdown is the study's interpretation of EMERGENCY; the automatic
        # controller still only derates to its minimum load command.
        return "shutdown"
    if mode in {
        "EMERGENCY_DERATING",
        "ADAPTIVE_DERATING",
        "ADAPTIVE_DERATE",
        "THERMAL_PREVENTION",
        "FAULT_AWARE",
        "PROTECTIVE",
    }:
        return "derate"
    return "continue"


def pipeline_config_from_yaml(config: dict[str, Any]) -> PipelineConfig:
    motor = config.get("induction_motor_digital_twin", {})
    safety = motor.get("safety", {})
    return PipelineConfig(
        ambient_C=float(motor.get("ambient_temperature_C", 20.0)),
        winding_frame_Rth=float(motor.get("winding_frame_Rth_K_per_W", 0.010)),
        frame_ambient_Rth=float(motor.get("frame_ambient_Rth_K_per_W", 0.0296652)),
        winding_capacitance=float(motor.get("winding_thermal_capacitance_J_per_K", 15000.0)),
        frame_capacitance=float(motor.get("frame_thermal_capacitance_J_per_K", 35000.0)),
        winding_loss_fraction=float(motor.get("winding_loss_fraction", 0.644)),
        minimum_load_pu=float(safety.get("minimum_load_pu", 0.50)),
        reference_load_pu=float(safety.get("reference_load_pu", 1.00)),
        warning_temperature_C=float(safety.get("winding_warning_C", 100.0)),
        critical_temperature_C=float(safety.get("winding_critical_C", 120.0)),
        vibration_warning_mm_s=float(config.get("safety", {}).get("vibration_warning_mm_s", 2.8)),
        cooling_flow_offset=float(motor.get("cooling_flow_offset", 0.0)),
        cooling_flow_gain=float(motor.get("cooling_flow_gain", 1.0)),
        cooling_residual_threshold_C=float(motor.get("cooling_residual_threshold_C", 0.02)),
        cooling_residual_clear_C=float(motor.get("cooling_residual_clear_C", 0.015)),
        cooling_severity_scale_C=float(motor.get("cooling_severity_scale_C", 0.10)),
        rated_current_A=float(motor.get("rated_current_A", 32.85)),
        rated_voltage_V=float(motor.get("rated_voltage_line_line_V", 400.0)),
        rated_frequency_Hz=float(motor.get("frequency_Hz", 50.0)),
        rated_speed_rpm=float(motor.get("rated_speed_rpm", 1462.5)),
        rated_torque_Nm=float(motor.get("rated_torque_Nm", 120.794521)),
        rated_output_W=float(motor.get("rated_output_W", 18500.0)),
        rated_efficiency=float(motor.get("rated_efficiency", 0.9049)),
    )


def adapt_induction_measurement(
    raw: dict[str, float],
    config: PipelineConfig,
) -> dict[str, float]:
    """Normalize FMU telemetry and preserve plant truth under explicit names."""
    values = dict(raw)
    values.setdefault("T_ambient_C", config.ambient_C)
    values.setdefault("supply_frequency_Hz", config.rated_frequency_Hz)
    values.setdefault("line_voltage_rms_V", config.rated_voltage_V)
    values.setdefault("voltage_unbalance_percent", 0.0)
    values.setdefault("rated_voltage_line_line_V", config.rated_voltage_V)
    values.setdefault("rated_frequency_Hz", config.rated_frequency_Hz)
    values.setdefault("rated_current_A", config.rated_current_A)
    values.setdefault("rated_torque_Nm", config.rated_torque_Nm)
    values.setdefault("rated_output_W", config.rated_output_W)
    values.setdefault("rated_speed_rpm", config.rated_speed_rpm)
    values.setdefault("rated_speed_rad_s", 2.0 * math.pi * config.rated_speed_rpm / 60.0)
    values.setdefault("rated_efficiency", config.rated_efficiency)
    values.setdefault("mechanical_unbalance_supported", 0.0)
    values.setdefault("current_pu", float(values["I_rms_A"]) / max(config.rated_current_A, 1e-9))
    values.setdefault("load_torque_pu", float(values.get("load_torque_pu", 0.0)))
    values.setdefault("P_motor_losses_W", float(values["P_loss_total_W"]))
    values.setdefault("P_winding_losses_W", float(values["P_motor_losses_W"]) * config.winding_loss_fraction)
    values.setdefault("P_fixed_losses_W", float(values["P_motor_losses_W"]) - float(values["P_winding_losses_W"]))

    for name in (
        "P_motor_losses_W",
        "P_winding_losses_W",
        "P_fixed_losses_W",
        "P_loss_total_W",
        "T_winding_C",
        "T_winding_K",
        "thermal_margin_to_critical_K",
        "thermal_state",
    ):
        if name in values:
            values[f"truth_{name}"] = float(values[name])

    observed_loss = max(0.0, float(values["P_electrical_W"]) - float(values["P_shaft_W"]))
    values["observed_power_loss_W"] = observed_loss
    values["P_motor_losses_W"] = observed_loss
    values["P_winding_losses_W"] = observed_loss * config.winding_loss_fraction
    values["P_fixed_losses_W"] = observed_loss * (1.0 - config.winding_loss_fraction)
    values["P_loss_total_W"] = observed_loss
    values["cooling_severity_scale_C"] = config.cooling_severity_scale_C
    values["expected_loss_estimate_W"] = max(
        0.0,
        config.rated_output_W
        * (1.0 / max(config.rated_efficiency, 1e-6) - 1.0)
        * (
            config.winding_loss_fraction
            * (float(values["I_rms_A"]) / max(config.rated_current_A, 1e-9)) ** 2
            + (1.0 - config.winding_loss_fraction)
            * (abs(float(values["speed_rpm"])) / max(config.rated_speed_rpm, 1e-9)) ** 2
        ),
    )
    values["friction_excess_estimate_W"] = max(
        0.0,
        observed_loss - values["expected_loss_estimate_W"],
    )
    return values


def digital_twin_measurement(measurement: dict[str, float]) -> dict[str, float]:
    """Exclude hidden MSL truth and direct winding-state observations."""
    values = {
        name: value
        for name, value in measurement.items()
        if not name.startswith("truth_")
        and name not in {
            "P_loss_total_W",
            "T_winding_C",
            "T_winding_K",
            "thermal_margin_to_critical_K",
            "thermal_state",
        }
    }
    values["P_loss_total_W"] = float(measurement["observed_power_loss_W"])
    return values


class TwinPipeline:
    """Shared MSL induction-motor observer, diagnostics, forecast, and control."""

    def __init__(
        self,
        controller_name: str = "constrained",
        config: PipelineConfig | None = None,
    ) -> None:
        if controller_name not in {"baseline", "adaptive", "constrained"}:
            raise ValueError(f"Unknown controller: {controller_name}")
        self.controller_name = controller_name
        self.command_namespace = uuid4().hex
        self.command_sequence = 0
        self.config = config or PipelineConfig()
        self.estimator = ThermalStateEstimator(
            ambient_C=self.config.ambient_C,
            r_winding_frame_K_W=self.config.winding_frame_Rth,
            r_frame_ambient_K_W=self.config.frame_ambient_Rth,
            c_winding_J_K=self.config.winding_capacitance,
            c_frame_J_K=self.config.frame_capacitance,
            winding_loss_fraction=self.config.winding_loss_fraction,
            fixed_loss_fraction=1.0 - self.config.winding_loss_fraction,
            initial_winding_C=90.0,
            initial_frame_C=77.4827,
            cooling_flow_offset=self.config.cooling_flow_offset,
            cooling_flow_gain=self.config.cooling_flow_gain,
        )
        self.predictor = ThermalPredictor(self.estimator)
        self.detector = self._new_detector()
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
            maximum_cooling_pu=1.0,
            safety_buffer_C=self.config.safety_buffer_C,
        )
        self.cooling_effectiveness_estimate = 1.0

    def _new_detector(self) -> FaultDetector:
        return FaultDetector(
            sensor_bias_threshold_C=6.0,
            cooling_residual_threshold_C=self.config.cooling_residual_threshold_C,
            cooling_clear_C=self.config.cooling_residual_clear_C,
            vibration_warning_mm_s=self.config.vibration_warning_mm_s,
            estimated_temp_warning_C=self.config.warning_temperature_C,
        )

    def adapt_measurement(self, raw: dict[str, float]) -> dict[str, float]:
        """Normalize the induction FMU data and keep hidden plant truth separate."""
        return adapt_induction_measurement(raw, self.config)

    @staticmethod
    def twin_measurement(measurement: dict[str, float]) -> dict[str, float]:
        """Remove model truth and measured hidden thermal state from twin inputs."""
        return digital_twin_measurement(measurement)

    def reset(self, raw_measurement: dict[str, float]) -> dict[str, float]:
        measurement = self.adapt_measurement(raw_measurement)
        twin_values = self.twin_measurement(measurement)
        self.estimator.initialize_from_measurement(twin_values)
        self.detector = self._new_detector()
        self.adaptive.previous_load = self.config.reference_load_pu
        self.constrained.reset()
        self.cooling_effectiveness_estimate = 1.0
        return measurement

    def tick(
        self,
        raw_measurement: dict[str, float],
        previous_command: ControlCommand,
        dt_s: float,
    ) -> PipelineResult:
        measurement = self.adapt_measurement(raw_measurement)
        twin_values = self.twin_measurement(measurement)
        timings = PipelineTimings()

        started = time.perf_counter()
        estimate = self.estimator.update(
            twin_values,
            previous_command.cooling_flow_pu,
            dt_s,
            cooling_effectiveness=self.cooling_effectiveness_estimate,
        )
        timings.state_estimator_latency_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        detection = self.detector.detect(estimate, twin_values)
        severity = estimate_fault_severity(estimate, detection, twin_values)
        self.cooling_effectiveness_estimate = max(
            0.05,
            min(1.0, 1.0 - float(severity["cooling_degradation"])),
        )
        timings.fault_detection_latency_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        forecast = self.predictor.predict(
            twin_values,
            previous_command.cooling_flow_pu,
            cooling_effectiveness=self.cooling_effectiveness_estimate,
        )
        timings.predictor_latency_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        sensor_reliability = 0.5 if detection.sensor_bias or detection.sensor_freeze else 1.0
        if self.controller_name == "baseline":
            command = self.baseline.compute(
                twin_values,
                sensor_reliable=not (detection.sensor_bias or detection.sensor_freeze),
            )
            mode = "NORMAL" if command.load_pu >= 0.99 else "PROTECTIVE"
            predicted_temperature = max(forecast.predicted_30s_C, forecast.predicted_60s_C)
            safety_margin = self.config.critical_temperature_C - predicted_temperature
            derating = max(0.0, min(1.0, 1.0 - command.load_pu / max(self.config.reference_load_pu, 1e-9)))
        elif self.controller_name == "adaptive":
            command = self.adaptive.compute(estimate, detection, severity, forecast)
            mode = "NORMAL" if command.load_pu >= 0.99 else "ADAPTIVE_DERATING"
            predicted_temperature = max(forecast.predicted_30s_C, forecast.predicted_60s_C)
            safety_margin = self.config.critical_temperature_C - predicted_temperature
            derating = max(0.0, min(1.0, 1.0 - command.load_pu / max(self.config.reference_load_pu, 1e-9)))
        else:
            cooling_efficiency_for_control = (
                self.cooling_effectiveness_estimate
                if detection.cooling_degradation
                else 1.0
            )
            output = self.constrained.update(
                commanded_load_pu=self.config.reference_load_pu,
                estimated_temperature_C=estimate.estimated_winding_C,
                predicted_temperature_30s_C=forecast.predicted_30s_C,
                predicted_temperature_60s_C=forecast.predicted_60s_C,
                fault_severity=severity["overall"],
                cooling_efficiency=cooling_efficiency_for_control,
                sensor_reliability=sensor_reliability,
            )
            command = ControlCommand(
                load_torque_pu=output.load_command_pu,
                requested_speed_pu=1.0,
                cooling_flow_pu=output.cooling_command_pu,
            )
            mode = output.operating_mode
            predicted_temperature = output.predicted_temperature_C
            safety_margin = output.safety_margin_C
            derating = output.derating_fraction
        self.command_sequence += 1
        command = replace(
            command,
            timestamp_s=float(measurement.get("timestamp_s", 0.0)),
            command_id=(
                f"{self.command_namespace}:{self.command_sequence}"
            ),
            source=f"controller:{self.controller_name}",
        )
        timings.controller_latency_ms = (time.perf_counter() - started) * 1000.0

        if mode == "EMERGENCY":
            band = "high"
        elif mode in {
            "EMERGENCY_DERATING",
            "ADAPTIVE_DERATING",
            "THERMAL_PREVENTION",
            "FAULT_AWARE",
            "ADAPTIVE_DERATING",
            "ADAPTIVE_DERATE",
            "PROTECTIVE",
        } or severity["overall"] >= 0.50:
            band = "medium"
        else:
            band = "low"
        action = trial_action_for_mode(mode)
        return PipelineResult(
            measurement=measurement,
            twin_measurement=twin_values,
            estimate=estimate,
            detection=detection,
            severity=severity,
            forecast=forecast,
            command=command,
            controller_name=self.controller_name,
            controller_operating_mode=mode,
            trial_action=action,
            severity_band=band,
            correct_action=action,
            controller_predicted_temperature_C=predicted_temperature,
            controller_safety_margin_C=safety_margin,
            controller_derating_fraction=derating,
            sensor_reliability=sensor_reliability,
            cooling_effectiveness_estimate=self.cooling_effectiveness_estimate,
            timings=timings,
        )
