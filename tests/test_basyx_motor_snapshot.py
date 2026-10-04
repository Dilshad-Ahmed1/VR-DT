from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from experiments.experiment_runner import build_basyx_snapshot


ROOT = Path(__file__).resolve().parents[1]


def test_aas_definition_contains_the_required_motor_telemetry() -> None:
    definition = json.loads(
        (ROOT / "config" / "motor_aas_definition.json").read_text(
            encoding="utf-8"
        )
    )
    submodels = {
        submodel["idShort"]: {
            element["idShort"] for element in submodel["submodelElements"]
        }
        for submodel in definition["submodels"]
    }

    assert set(submodels) == {
        "OperationalState",
        "ElectricalState",
        "MechanicalState",
        "ThermalState",
        "FaultState",
        "ControlInterface",
    }
    assert {
        "VoltageRmsV",
        "CurrentRmsA",
        "ActivePowerW",
        "PowerFactor",
        "FrequencyHz",
    } <= submodels["ElectricalState"]
    assert {
        "SpeedRpm",
        "SlipPercent",
        "ElectromagneticTorqueNm",
        "LoadTorqueNm",
    } <= submodels["MechanicalState"]
    assert "VibrationAmplitudeMmS" not in submodels["MechanicalState"]
    assert "UnbalanceSeverity" not in submodels["MechanicalState"]
    assert "MechanicalUnbalanceActive" not in submodels["FaultState"]
    assert {
        "WindingTemperatureK",
        "FrameTemperatureK",
        "ThermalMarginK",
        "PredictedTemperature30sK",
        "PredictedTemperature60sK",
    } <= submodels["ThermalState"]
    assert {
        "FaultType",
        "FaultActive",
        "EstimatedFaultSeverity",
    } <= submodels["FaultState"]
    assert "TrueFaultSeverity" not in submodels["FaultState"]
    assert {
        "LoadDeratingCommandPu",
        "CoolingCommandPu",
        "OperatingMode",
    } <= submodels["ControlInterface"]


def test_snapshot_values_and_identity_share_one_simulation_instant() -> None:
    measurement = {
        "omega_rad_s": 150.0,
        "speed_rpm": 1432.4,
        "rated_speed_rad_s": 153.15,
        "rated_torque_Nm": 120.8,
        "rated_voltage_line_line_V": 400.0,
        "rated_current_A": 32.85,
        "rated_output_W": 18500.0,
        "rated_frequency_Hz": 50.0,
        "line_voltage_rms_V": 390.0,
        "I_rms_A": 31.0,
        "power_factor": 0.87,
        "P_electrical_W": 18000.0,
        "P_shaft_W": 16000.0,
        "reactive_power_var": 5000.0,
        "supply_frequency_Hz": 49.5,
        "voltage_unbalance_percent": 2.5,
        "observed_power_loss_W": 2000.0,
        "T_sensor_C": 96.0,
        "T_ambient_C": 20.0,
        "torque_motor_Nm": 110.0,
        "torque_load_Nm": 100.0,
        "thermal_margin_to_critical_K": 30.0,
    }
    estimate = SimpleNamespace(
        estimated_winding_C=95.0,
        estimated_frame_C=82.0,
        sensor_residual_C=1.0,
    )
    detection = SimpleNamespace(
        sensor_bias=False,
        sensor_freeze=False,
        cooling_degradation=True,
        load_overload=False,
        mechanical_friction=False,
        voltage_imbalance=False,
        supply_degradation=False,
        frequency_deviation=False,
        any_fault=True,
        primary_fault="cooling_degradation",
    )
    forecast = SimpleNamespace(
        predicted_30s_C=99.0,
        predicted_60s_C=104.0,
    )
    severity = {
        "overall": 0.4,
        "cooling_degradation": 0.4,
    }
    snapshot = build_basyx_snapshot(
        measurement=measurement,
        estimate=estimate,
        detection=detection,
        severity=severity,
        command=SimpleNamespace(load_pu=0.8, cooling_flow_pu=1.0),
        elapsed_energy_kwh=1.2,
        useful_work_kwh=1.0,
        forecast=forecast,
        controller_name="constrained",
        plant_profile="induction",
        simulation_time_s=351.0,
        snapshot_timestamp_utc="2026-10-03T10:00:00.000+00:00",
        snapshot_id="test-run:702",
        critical_temperature_C=125.0,
    )

    assert set(snapshot) == {
        "thermal",
        "electrical",
        "mechanical",
        "operational",
        "fault",
        "control",
    }
    assert {
        values["SnapshotId"] for values in snapshot.values()
    } == {"test-run:702"}
    assert {
        values["SnapshotTimestampUtc"] for values in snapshot.values()
    } == {"2026-10-03T10:00:00.000+00:00"}
    assert {values["SimulationTimeSeconds"] for values in snapshot.values()} == {
        351.0
    }
    assert snapshot["thermal"]["WindingTemperatureK"] == 368.15
    assert snapshot["thermal"]["PredictedTemperature60sK"] == 377.15
    assert snapshot["electrical"]["FrequencyHz"] == 49.5
    assert snapshot["mechanical"]["SlipPercent"] > 0.0
    assert snapshot["fault"]["FaultType"] == "cooling_degradation"
    assert "TrueFaultSeverity" not in snapshot["fault"]
    assert snapshot["fault"]["EstimatedFaultSeverity"] == 0.4
    assert snapshot["control"]["ControllerName"] == "constrained"
