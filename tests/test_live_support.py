from __future__ import annotations

from control.baseline_controller import ControlCommand
from server.trial_logger import TrialLogger
from server.twin_pipeline import trial_action_for_mode
from twin.fault_injector import injector_from_scenario


def test_trial_oracle_preserves_emergency_reinterpretation():
    assert trial_action_for_mode("NORMAL") == "continue"
    assert trial_action_for_mode("FAULT_AWARE") == "derate"
    assert trial_action_for_mode("EMERGENCY_DERATING") == "derate"
    assert trial_action_for_mode("EMERGENCY") == "shutdown"


def test_fault_profiles_share_one_input_path():
    base = {
        "u_load_torque_pu": 1.0,
        "f_cooling_eff": 1.0,
        "f_unbalance_severity": 0.0,
        "f_voltage_unbalance_pu": 0.0,
        "f_sensor_bias_C": 0.0,
    }
    assert injector_from_scenario("sudden_overload", start_tick=2, step_s=0.5).apply(2, base)["u_load_torque_pu"] > 1.0
    assert injector_from_scenario("cooling_failure", start_tick=2, step_s=0.5).apply(20, base)["f_cooling_eff"] < 1.0
    assert injector_from_scenario("voltage_imbalance", start_tick=2, step_s=0.5).apply(20, base)["f_voltage_unbalance_pu"] > 0.0


def test_ground_truth_severity_tracks_injected_profile():
    drift = injector_from_scenario(
        "sensor_drift",
        start_tick=10,
        step_s=0.5,
        duration_s=20.0,
    )
    assert drift.severity_at(9)["sensor_bias"] == 0.0
    assert drift.severity_at(10)["sensor_bias"] == 0.0
    assert 0.0 < drift.severity_at(20)["sensor_bias"] < 1.0

    overload = injector_from_scenario("sudden_overload", start_tick=10, step_s=0.5)
    assert overload.severity_at(9)["overload"] == 0.0
    assert overload.severity_at(10)["overload"] == 1.0

    cooling = injector_from_scenario(
        "cooling_failure",
        start_tick=10,
        step_s=0.5,
        duration_s=20.0,
    )
    assert cooling.severity_at(10)["cooling"] == 0.0
    assert cooling.severity_at(20)["cooling"] > cooling.severity_at(15)["cooling"]


def test_trial_logger_records_mode_and_action(tmp_path):
    logger = TrialLogger(tmp_path)
    row = logger.record_response(
        participant_id="p1",
        condition="vr",
        trial_id="t1",
        scenario="sensor_drift",
        fault_onset_tick=10,
        detection_tick=20,
        response_tick=25,
        step_s=0.5,
        client_timestamp=123.0,
        participant_action="continue",
        correct_action="continue",
        controller_operating_mode="NORMAL",
        trial_action_label="continue",
        severity_at_response=0.1,
        severity_band_at_response="low",
    )
    assert row["controller_operating_mode"] == "NORMAL"
    assert row["trial_action_label"] == "continue"
    csv_path, json_path = logger.save("trial")
    assert csv_path.exists()
    assert json_path.exists()