import pandas as pd
import pytest

from scripts.validate_induction_motor_nominal import (
    evaluate_nominal_results,
    reference_operating_point,
)


def _reference_frame() -> pd.DataFrame:
    reference = reference_operating_point()
    return pd.DataFrame(
        {
            "time_s": [7.0, 7.5, 8.0],
            "line_voltage_rms_V": [reference["line_voltage_rms_V"]] * 3,
            "I_rms_A": [reference["line_current_rms_A"]] * 3,
            "supply_frequency_Hz": [reference["supply_frequency_Hz"]] * 3,
            "speed_rpm": [reference["speed_rpm"]] * 3,
            "torque_motor_Nm": [reference["electromagnetic_torque_Nm"]] * 3,
            "torque_load_Nm": [reference["shaft_torque_Nm"]] * 3,
            "P_electrical_W": [reference["electrical_input_power_W"]] * 3,
            "P_shaft_W": [reference["mechanical_output_power_W"]] * 3,
            "power_factor": [reference["power_factor"]] * 3,
            "P_loss_total_W": [reference["motor_losses_W"]] * 3,
            "T_winding_C": [89.98, 90.0, 90.02],
        }
    )


def test_reference_point_uses_documented_msl_benchmark_values() -> None:
    reference = reference_operating_point()
    assert reference["line_voltage_rms_V"] == 400.0
    assert reference["supply_frequency_Hz"] == 50.0
    assert reference["speed_rpm"] == 1462.5
    assert reference["slip_percent"] == 2.5
    assert reference["mechanical_output_power_W"] == 18500.0
    assert reference["efficiency_percent"] == 90.49
    assert reference["electromagnetic_torque_Nm"] > reference["shaft_torque_Nm"]


def test_fmu_nominal_reference_frame_passes() -> None:
    result = evaluate_nominal_results(
        _reference_frame(),
        stop_time_s=8.0,
        settling_window_s=1.0,
    )
    assert result["passed"]
    assert all(check["passed"] for check in result["deviation_checks"].values())
    assert all(check["passed"] for check in result["stability_checks"].values())
    assert result["steady_state_window_s"]["samples"] == 3


def test_nominal_validation_rejects_unstable_speed() -> None:
    frame = _reference_frame()
    frame.loc[frame.index[-1], "speed_rpm"] += 0.3
    result = evaluate_nominal_results(frame, stop_time_s=8.0, settling_window_s=1.0)
    assert not result["passed"]
    assert not result["stability_checks"]["speed_rpm_peak_to_peak"]["passed"]


def test_nominal_validation_requires_thermal_response() -> None:
    frame = _reference_frame()
    frame["T_winding_C"] = 90.0
    result = evaluate_nominal_results(frame, stop_time_s=8.0, settling_window_s=1.0)
    assert not result["passed"]
    assert not result["thermal_response"]["changed_during_simulation"]


def test_nominal_validation_rejects_missing_measurement() -> None:
    frame = _reference_frame().drop(columns=["power_factor"])
    with pytest.raises(KeyError, match="power_factor"):
        evaluate_nominal_results(frame, stop_time_s=8.0, settling_window_s=1.0)
