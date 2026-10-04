from __future__ import annotations

import math
from pathlib import Path

import pytest

from control.adaptive_controller import FaultAwareAdaptiveController
from control.baseline_controller import BaselineThresholdController
from control.constrained_adaptive_controller import ConstrainedAdaptiveController
from experiments.experiment_runner import (
    _adapt_measurement,
    _digital_twin_measurement,
)
from simulation.fmu_runtime import FMURuntime
from twin.fault_detector import FaultDetector
from twin.fault_severity import estimate_fault_severity
from twin.predictor import ThermalForecast, ThermalPredictor
from twin.state_estimator import StateEstimate, ThermalStateEstimator


FMU_PATH = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "InductionMotorDigitalTwin18kW.fmu"
)


def _assert_finite(values: dict[str, float]) -> None:
    assert all(math.isfinite(value) for value in values.values())


def test_induction_loss_estimates_do_not_expose_hidden_fmu_losses() -> None:
    measurement = _adapt_measurement(
        {
            "T_winding_C": 90.0,
            "T_winding_K": 363.15,
            "T_frame_C": 77.5,
            "T_sensor_C": 90.0,
            "T_ambient_C": 20.0,
            "P_electrical_W": 1200.0,
            "P_shaft_W": 1000.0,
            "P_loss_total_W": 170.0,
            "P_motor_losses_W": 150.0,
            "P_winding_losses_W": 100.0,
            "P_fixed_losses_W": 50.0,
            "I_rms_A": 10.0,
            "speed_rpm": 1450.0,
            "torque_load_Nm": 50.0,
        },
        "induction",
        rated_current_A=32.85,
        rated_voltage_V=400.0,
        rated_frequency_Hz=50.0,
        rated_speed_rpm=1462.5,
        rated_torque_Nm=120.79,
        rated_output_W=18500.0,
        rated_efficiency=0.9049,
        ambient_C=20.0,
        winding_loss_fraction=0.644,
    )
    twin_inputs = _digital_twin_measurement(measurement, "induction")

    assert measurement["truth_P_motor_losses_W"] == 150.0
    assert twin_inputs["P_loss_total_W"] == pytest.approx(200.0)
    assert twin_inputs["P_winding_losses_W"] == pytest.approx(128.8)
    assert twin_inputs["P_fixed_losses_W"] == pytest.approx(71.2)
    assert not any(name.startswith("truth_") for name in twin_inputs)
    assert "T_winding_C" not in twin_inputs
    assert "thermal_margin_to_critical_K" not in twin_inputs


def test_induction_fmu_nominal_operation_is_finite_and_physical() -> None:
    if not FMU_PATH.is_file():
        pytest.skip("Export the induction-motor FMU to run this integration test.")

    with FMURuntime(FMU_PATH, stop_time=1.0) as runtime:
        initial = runtime.initialize()
        _assert_finite(initial)
        assert initial["supply_frequency_Hz"] == pytest.approx(50.0)
        assert initial["line_voltage_rms_V"] == pytest.approx(400.0, rel=0.02)

        loaded, _ = runtime.step(
            0.5,
            {
                "u_load_torque_pu": 1.0,
                "u_speed_pu": 1.0,
                "u_cooling_flow_pu": 1.0,
            },
        )
        assert loaded["load_torque_pu"] == pytest.approx(0.1, abs=1e-6)
        measurement, _ = runtime.step(
            2.0,
            {
                "u_load_torque_pu": 1.0,
                "u_speed_pu": 1.0,
                "u_cooling_flow_pu": 1.0,
            },
        )

    _assert_finite(measurement)
    assert runtime.current_time == pytest.approx(2.5)
    assert 0.0 < measurement["speed_rpm"] < 1500.0
    assert measurement["I_rms_A"] > 0.0
    assert measurement["P_electrical_W"] > 0.0
    assert measurement["P_loss_total_W"] >= 0.0
    assert measurement["T_winding_C"] >= measurement["T_ambient_C"]
    assert measurement["T_frame_C"] >= measurement["T_ambient_C"]
    assert measurement["voltage_unbalance_percent"] < 2.0
    assert measurement["mechanical_unbalance_supported"] == 0.0


def test_supported_fault_inputs_affect_only_physical_channels() -> None:
    if not FMU_PATH.is_file():
        pytest.skip("Export the induction-motor FMU to run this integration test.")

    with FMURuntime(FMU_PATH, stop_time=1.0) as runtime:
        runtime.initialize()
        biased, _ = runtime.step(
            0.1,
            {
                "u_load_torque_pu": 1.0,
                "u_speed_pu": 1.0,
                "u_cooling_flow_pu": 1.0,
                "f_sensor_bias_C": 8.0,
                "f_cooling_eff": 0.4,
                "f_rth_degradation": 2.0,
                "f_load_overload_pu": 0.2,
                "f_mechanical_friction_factor": 2.0,
                "f_voltage_unbalance_pu": 0.03,
                "f_supply_voltage_degradation_pu": 0.1,
                "f_supply_frequency_deviation_pu": 0.02,
            },
        )
        _assert_finite(biased)
        assert biased["T_sensor_C"] - biased["T_winding_C"] == pytest.approx(8.0)
        assert biased["cooling_effectiveness"] == pytest.approx(0.2)
        assert biased["supply_frequency_Hz"] == pytest.approx(51.0)
        assert 340.0 < biased["line_voltage_rms_V"] < 380.0
        assert biased["voltage_unbalance_percent"] > 0.0
        assert biased["load_torque_pu"] > 0.0

        frozen, _ = runtime.step(
            0.1,
            {
                "u_load_torque_pu": 1.0,
                "u_speed_pu": 1.0,
                "u_cooling_flow_pu": 1.0,
                "f_sensor_bias_C": 0.0,
                "f_sensor_freeze": True,
                "f_cooling_eff": 1.0,
                "f_rth_degradation": 1.0,
                "f_load_overload_pu": 0.0,
                "f_mechanical_friction_factor": 1.0,
                "f_voltage_unbalance_pu": 0.0,
                "f_supply_voltage_degradation_pu": 0.0,
                "f_supply_frequency_deviation_pu": 0.0,
            },
        )

    _assert_finite(frozen)
    assert frozen["T_sensor_C"] == pytest.approx(biased["T_winding_C"], abs=1e-5)
    assert frozen["cooling_effectiveness"] == pytest.approx(1.0)
    assert frozen["supply_frequency_Hz"] == pytest.approx(50.0)


def test_estimator_predictor_and_existing_controllers_accept_induction_signals() -> None:
    measurement = {
        "T_sensor_C": 90.0,
        "T_winding_C": 90.0,
        "T_frame_C": 77.5,
        "T_ambient_C": 20.0,
        "P_winding_losses_W": 74.0,
        "P_fixed_losses_W": 640.0,
        "P_motor_losses_W": 714.0,
        "P_electrical_W": 1000.0,
        "P_shaft_W": 200.0,
        "P_loss_total_W": 800.0,
        "I_rms_A": 10.0,
        "current_pu": 0.3,
        "load_torque_pu": 0.5,
        "vibration_mm_s_out": 0.0,
        "mechanical_unbalance_supported": 0.0,
        "rated_output_W": 18500.0,
        "rated_voltage_line_line_V": 400.0,
        "line_voltage_rms_V": 400.0,
        "rated_frequency_Hz": 50.0,
        "supply_frequency_Hz": 50.0,
        "voltage_unbalance_percent": 0.0,
        "friction_excess_estimate_W": 0.0,
    }
    estimator = ThermalStateEstimator(
        ambient_C=20.0,
        r_winding_frame_K_W=0.010,
        r_frame_ambient_K_W=0.02957,
        c_winding_J_K=15000.0,
        c_frame_J_K=35000.0,
        winding_loss_fraction=0.644,
        fixed_loss_fraction=0.356,
        initial_winding_C=90.0,
        initial_frame_C=77.5,
        cooling_flow_offset=0.0,
        cooling_flow_gain=1.0,
    )
    estimator.initialize_from_measurement(measurement)
    estimate = estimator.update(measurement, 1.0, 0.5, 0.8)
    forecast = ThermalPredictor(estimator).predict(measurement, 1.0, 0.8)
    assert all(
        math.isfinite(value)
        for value in (
            estimate.estimated_winding_C,
            estimate.estimated_frame_C,
            forecast.predicted_30s_C,
            forecast.predicted_60s_C,
        )
    )

    detector = FaultDetector(persistence_cycles=1)
    detection = detector.detect(estimate, measurement)
    severity = estimate_fault_severity(estimate, detection, measurement)
    adaptive = FaultAwareAdaptiveController()
    fault_command = adaptive.compute(
        estimate,
        detection,
        {**severity, "cooling_degradation": 1.0},
        ThermalForecast(110.0, 115.0),
    )
    baseline = BaselineThresholdController().compute(
        {**measurement, "T_sensor_C": 130.0},
        sensor_reliable=False,
    )
    constrained = ConstrainedAdaptiveController()
    constrained.reset()
    constrained_command = constrained.update(
        commanded_load_pu=1.0,
        estimated_temperature_C=105.0,
        predicted_temperature_30s_C=110.0,
        predicted_temperature_60s_C=115.0,
        fault_severity=severity["overall"],
        cooling_efficiency=0.5,
        sensor_reliability=0.5,
    )

    assert fault_command.load_pu < 1.0
    assert baseline.load_pu == pytest.approx(0.5)
    assert constrained_command.load_command_pu < 1.0
    assert 0.0 <= constrained_command.cooling_command_pu <= 1.0


def test_induction_cooling_residual_detection_and_severity_are_persistent() -> None:
    detector = FaultDetector(
        cooling_residual_threshold_C=0.02,
        cooling_clear_C=0.015,
        persistence_cycles=2,
    )
    estimate = StateEstimate(
        estimated_winding_C=95.0,
        estimated_frame_C=85.0,
        estimated_winding_rate_C_s=0.01,
        sensor_residual_C=0.0,
        frame_innovation_C=0.03,
        frame_model_residual_C=0.02,
    )
    measurement = {
        "T_sensor_C": 95.0,
        "vibration_mm_s_out": 0.0,
        "mechanical_unbalance_supported": 0.0,
        "current_pu": 0.9,
        "load_torque_pu": 0.9,
        "friction_excess_estimate_W": 0.0,
        "rated_voltage_line_line_V": 400.0,
        "line_voltage_rms_V": 400.0,
        "voltage_unbalance_percent": 0.0,
        "supply_frequency_Hz": 50.0,
        "rated_frequency_Hz": 50.0,
        "cooling_severity_scale_C": 0.10,
    }

    assert not detector.detect(estimate, measurement).cooling_degradation
    detection = detector.detect(estimate, measurement)
    severity = estimate_fault_severity(estimate, detection, measurement)

    assert detection.cooling_degradation
    assert severity["cooling_degradation"] == pytest.approx(0.3)
