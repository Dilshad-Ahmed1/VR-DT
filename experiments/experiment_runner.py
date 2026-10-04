from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import yaml
from fmpy import read_model_description

from analysis.experiment_metrics import compute_experiment_metrics
from integration.basyx_bridge import BaSyxBridge
from control.baseline_controller import ControlCommand
from simulation.fmu_runtime import FMURuntime
from server.twin_pipeline import (
    PipelineConfig,
    TwinPipeline,
    adapt_induction_measurement,
    digital_twin_measurement,
    pipeline_config_from_yaml,
)
from twin.fault_injector import SCENARIO_DEFAULTS, FaultInjector, injector_from_scenario
from analysis.basyx_metrics import BaSyxEvaluationMetrics


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, None] = {
    "healthy": None,
    **{name: None for name in SCENARIO_DEFAULTS},
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_project_config() -> dict[str, Any]:
    """
    Load project configuration if available.

    The experiment remains runnable even if the YAML file does not exist.
    """
    path = Path("config/twin_config.yaml")

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------

def _identify_plant_profile(
    fmu_path: Path,
    requested_profile: str,
) -> str:
    if requested_profile not in {"auto", "induction"}:
        raise ValueError(f"Unknown plant profile: {requested_profile}")
    model_name = str(read_model_description(str(fmu_path)).modelName)
    if "InductionMotorDigitalTwin18kW" not in model_name:
        raise ValueError(
            "CGVR runs only the MSL 18.5 kW induction-motor FMU; "
            f"received {model_name!r}."
        )
    return "induction"


def _adapt_measurement(
    measurement: dict[str, float],
    plant_profile: str,
    rated_current_A: float,
    rated_voltage_V: float,
    rated_frequency_Hz: float,
    rated_speed_rpm: float,
    rated_torque_Nm: float,
    rated_output_W: float,
    rated_efficiency: float,
    ambient_C: float,
    winding_loss_fraction: float,
) -> dict[str, float]:
    if plant_profile != "induction":
        raise ValueError("CGVR supports only the 18.5 kW induction-motor profile.")
    config = PipelineConfig(
        ambient_C=ambient_C,
        winding_loss_fraction=winding_loss_fraction,
        rated_current_A=rated_current_A,
        rated_voltage_V=rated_voltage_V,
        rated_frequency_Hz=rated_frequency_Hz,
        rated_speed_rpm=rated_speed_rpm,
        rated_torque_Nm=rated_torque_Nm,
        rated_output_W=rated_output_W,
        rated_efficiency=rated_efficiency,
    )
    return adapt_induction_measurement(measurement, config)


def _digital_twin_measurement(
    measurement: dict[str, float],
    plant_profile: str,
) -> dict[str, float]:
    if plant_profile != "induction":
        raise ValueError("CGVR supports only the 18.5 kW induction-motor profile.")
    return digital_twin_measurement(measurement)


def _true_fault_severities(
    scenario_name: str,
    active: bool,
    injector: FaultInjector | None = None,
    tick: int = 0,
) -> dict[str, float]:
    if injector is not None and active:
        current = injector.severity_at(tick)
        return {
            "sensor_bias": current["sensor_bias"],
            "sensor_freeze": current["sensor_freeze"],
            "cooling": current["cooling"],
            "rth_degradation": current["rth_degradation"],
            "unbalance": 0.0,
            "overload": current["overload"],
            "mechanical_friction": current["mechanical_friction"],
            "voltage_imbalance": current["voltage_imbalance"],
            "supply_degradation": current["supply_degradation"],
            "frequency_deviation": current["frequency_deviation"],
        }
    return {
        "sensor_bias": 0.0,
        "sensor_freeze": 0.0,
        "cooling": 0.0,
        "rth_degradation": 0.0,
        "unbalance": 0.0,
        "overload": 0.0,
        "mechanical_friction": 0.0,
        "voltage_imbalance": 0.0,
        "supply_degradation": 0.0,
        "frequency_deviation": 0.0,
    }


# ---------------------------------------------------------------------------
# DataFrame validation
# ---------------------------------------------------------------------------

REQUIRED_LOG_COLUMNS = {
    # Time / experiment
    "time_s",
    "fault_active",
    "fault_type",
    "fault_severity_true",
    "controller",

    # Control
    "u_load_torque_pu",
    "u_speed_pu",
    "u_cooling_flow_pu",

    # IMPORTANT:
    # experiment_metrics.py explicitly requires this column.
    "speed_reference_pu",
    "speed_reference_rad_s",

    # Twin state estimation
    "estimated_winding_C",
    "estimated_frame_C",
    "estimated_winding_rate_C_s",
    "sensor_residual_C",
    "frame_model_residual_C",
    "frame_innovation_C",

    # Fault detection
    "fault_sensor_bias_detected",
    "fault_cooling_detected",
    "fault_unbalance_detected",
    "fault_alarm",
    "primary_fault",

    # Fault severity
    "fault_severity_sensor_bias",
    "fault_severity_cooling",
    "fault_severity_unbalance",
    "fault_severity_estimated",

    # Prediction
    "predicted_30s_C",
    "predicted_60s_C",

    # Runtime measurements
    "state_estimator_latency_ms",
    "fault_detection_latency_ms",
    "predictor_latency_ms",
    "controller_latency_ms",
    "loop_compute_latency_ms",
    "solver_step_time_s",

    # FMU outputs
    "T_winding_C",
    "T_frame_C",
    "T_sensor_C",
    "omega_rad_s",
    "speed_rpm",
    "torque_load_Nm",
    "torque_motor_Nm",
    "P_electrical_W",
    "P_shaft_W",
    "P_loss_total_W",
    "I_rms_A",
    "vibration_mm_s_out",
    "thermal_margin_to_critical_K",
    "thermal_state",
}


def validate_dataframe(df: pd.DataFrame) -> None:
    """
    Fail immediately with a useful message rather than allowing the
    metrics module to throw a KeyError later.
    """
    missing = sorted(REQUIRED_LOG_COLUMNS - set(df.columns))

    if missing:
        raise KeyError(
            "Experiment log is missing required columns:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )



def build_basyx_snapshot(
    measurement: dict[str, float],
    estimate,
    detection,
    severity: dict[str, float],
    command,
    elapsed_energy_kwh: float,
    useful_work_kwh: float,
    forecast,
    scenario_name: str,
    fault_active: bool,
    true_fault_severities: dict[str, float],
    controller_name: str,
    plant_profile: str,
    simulation_time_s: float,
    snapshot_timestamp_utc: str,
    snapshot_id: str,
    critical_temperature_C: float = 120.0,
) -> dict[str, dict[str, object]]:
    """
    Convert the current Digital Twin state into the project's
    AAS submodel representation.

    IMPORTANT:
    The hidden FMU fault parameters are NOT published here.
    Diagnostic values come from the estimator/detector.
    """

    speed_rad_s = float(
        measurement["omega_rad_s"]
    )

    speed_rpm = float(
        measurement["speed_rpm"]
    )

    thermal_margin_K = (
        critical_temperature_C - float(estimate.estimated_winding_C)
    )
    frequency_Hz = float(measurement.get("supply_frequency_Hz", 50.0))
    synchronous_speed_rpm = float(
        measurement.get("synchronous_speed_rpm", 120.0 * frequency_Hz / 4.0)
    )
    slip_percent = (
        100.0
        * (synchronous_speed_rpm - speed_rpm)
        / max(synchronous_speed_rpm, 1e-9)
    )
    true_fault_severity = max(true_fault_severities.values(), default=0.0)
    load_pu = float(command.load_pu)
    if load_pu >= 0.99:
        operating_mode = "NORMAL"
    elif load_pu > 0.60:
        operating_mode = "ADAPTIVE_DERATE"
    else:
        operating_mode = "PROTECTIVE"

    # --------------------------------------------------------------
    # Operational
    # --------------------------------------------------------------

    operational = {
        "SpeedPu": (
            speed_rad_s
            / max(float(measurement.get("rated_speed_rad_s", 152.890842)), 1e-9)
        ),
        "LoadTorquePu": (
            float(
                measurement[
                    "torque_load_Nm"
                ]
            ) / max(float(measurement.get("rated_torque_Nm", 35.973378)), 1e-9)
        ),
        "PowerLossActualW": float(
            measurement["observed_power_loss_W"]
            if "observed_power_loss_W" in measurement
            else measurement["P_loss_total_W"]
        ),
        "PlantProfile": plant_profile,
        "MotorRatedOutputW": float(measurement.get("rated_output_W", 5500.0)),
    }

    # --------------------------------------------------------------
    # Electrical
    # --------------------------------------------------------------

    electrical = {
        "VoltageRmsV": float(measurement.get("line_voltage_rms_V", 400.0)),

        "CurrentRmsA": float(
            measurement["I_rms_A"]
        ),

        "PowerFactor": float(measurement.get("power_factor", 0.81)),

        "ActivePowerW": float(
            measurement[
                "P_electrical_W"
            ]
        ),

        "ReactivePowerVar": float(measurement.get("reactive_power_var", 0.0)),

        "TotalEnergyConsumedkWh": (
            elapsed_energy_kwh
        ),
        "FrequencyHz": frequency_Hz,
        "VoltageUnbalancePercent": float(
            measurement.get("voltage_unbalance_percent", 0.0)
        ),
        "RatedVoltageRmsV": float(
            measurement.get("rated_voltage_line_line_V", 400.0)
        ),
        "RatedCurrentRmsA": float(
            measurement.get("rated_current_A", 10.9)
        ),
        "Efficiency": (
            float(measurement["P_shaft_W"])
            / float(measurement["P_electrical_W"])
            if float(measurement["P_electrical_W"]) > 0.0
            else 0.0
        ),
    }

    # --------------------------------------------------------------
    # Mechanical
    # --------------------------------------------------------------

    mechanical = {
        "SpeedRpm": speed_rpm,

        "SpeedRadS": speed_rad_s,

        "ElectromagneticTorqueNm": float(
            measurement[
                "torque_motor_Nm"
            ]
        ),

        "LoadTorqueNm": float(
            measurement[
                "torque_load_Nm"
            ]
        ),

        "UsefulOutputWorkkWh": (
            useful_work_kwh
        ),

        "VibrationAmplitudeMmS": float(
            measurement[
                "vibration_mm_s_out"
            ]
        ),

        # Estimated—not hidden truth.
        "UnbalanceSeverity": float(
            severity[
                "mechanical_unbalance"
            ]
        ),
        "SynchronousSpeedRpm": synchronous_speed_rpm,
        "SlipPercent": slip_percent,
        "LoadCommandTorqueNm": (
            load_pu * float(measurement.get("rated_torque_Nm", 0.0))
        ),
    }

    # --------------------------------------------------------------
    # Thermal
    # --------------------------------------------------------------

    thermal = {
        "WindingTemperatureK": (
            float(estimate.estimated_winding_C)
            + 273.15
        ),

        "FrameTemperatureK": (
            float(estimate.estimated_frame_C)
            + 273.15
        ),

        "WindingSensorMeasuredK": (
            float(
                measurement[
                    "T_sensor_C"
                ]
            )
            + 273.15
        ),

        "ThermalMarginK": (
            thermal_margin_K
        ),
        "AmbientTemperatureK": (
            float(measurement.get("T_ambient_C", 20.0)) + 273.15
        ),
        "PredictedTemperature30sK": (
            float(forecast.predicted_30s_C) + 273.15
        ),
        "PredictedTemperature60sK": (
            float(forecast.predicted_60s_C) + 273.15
        ),
    }

    # --------------------------------------------------------------
    # Fault
    # --------------------------------------------------------------

    fault = {
        # Observable sensor/model residual.
        "SensorBiasActiveK": abs(
            float(
                estimate.sensor_residual_C
            )
        ),

        # The present runner does not estimate freeze state.
        "SensorFreezeActive": bool(detection.sensor_freeze),

        # Estimated cooling factor, NOT FMU truth.
        "CoolingEfficiencyFactor": max(
            0.0,
            min(
                1.0,
                1.0
                - float(
                    severity[
                        "cooling_degradation"
                    ]
                ),
            ),
        ),

        "MechanicalUnbalanceActive": bool(
            detection.mechanical_unbalance
        ),

        "EstimatedFaultSeverity": float(
            severity["overall"]
        ),
        "FaultActive": fault_active,
        "FaultType": scenario_name if fault_active else "healthy",
        "PrimaryDetectedFault": detection.primary_fault,
        "TrueFaultSeverity": true_fault_severity if fault_active else 0.0,
        "CoolingFaultActive": bool(detection.cooling_degradation),
        "OverloadFaultActive": bool(detection.load_overload),
        "MechanicalFrictionFaultActive": bool(detection.mechanical_friction),
        "VoltageImbalanceFaultActive": bool(detection.voltage_imbalance),
        "SupplyDegradationFaultActive": bool(detection.supply_degradation),
        "FrequencyDeviationFaultActive": bool(detection.frequency_deviation),
    }

    # --------------------------------------------------------------
    # Control
    # --------------------------------------------------------------

    load_pu = float(
        command.load_pu
    )

    cooling_pu = float(
        command.cooling_flow_pu
    )

    control = {
        "CoolingCommandPu": cooling_pu,

        "LoadDeratingCommandPu": load_pu,

        "OperatingMode": operating_mode,
        "ControllerName": controller_name,
    }

    snapshot = {
        "thermal": thermal,
        "electrical": electrical,
        "mechanical": mechanical,
        "operational": operational,
        "fault": fault,
        "control": control,
    }
    for values in snapshot.values():
        values["SimulationTimeSeconds"] = simulation_time_s
        values["SnapshotTimestampUtc"] = snapshot_timestamp_utc
        values["SnapshotId"] = snapshot_id
    return snapshot


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def run_experiment(
    fmu_path: Path,
    scenario_name: str,
    controller_name: str,
    stop_time: float,
    step: float,
    fault_time: float,
    output: Path,
    basyx_enabled: bool = False,
    basyx_host: str = "http://localhost:8081",
    basyx_period_s: float = 2.0,
    realtime: bool = False,
    plant_profile: str = "auto",
) -> tuple[pd.DataFrame, dict[str, Any]]:

    # -------------------------
    # Validate CLI arguments
    # -------------------------

    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")

    if controller_name not in {
        "baseline",
        "adaptive",
        "constrained",
    }:
        raise ValueError(f"Unknown controller: {controller_name}")

    if stop_time <= 0:
        raise ValueError("stop_time must be > 0")

    if step <= 0:
        raise ValueError("step must be > 0")

    if fault_time < 0:
        raise ValueError("fault_time must be >= 0")

    fmu_path = Path(fmu_path).resolve()
    plant_profile = _identify_plant_profile(fmu_path, plant_profile)

    cfg = load_project_config()
    induction_cfg = cfg.get("induction_motor_digital_twin", {})
    if not induction_cfg:
        raise ValueError(
            "config/twin_config.yaml is missing the active induction-motor profile."
        )
    safety_cfg = induction_cfg.get("safety", {})
    ambient_C = float(induction_cfg.get("ambient_temperature_C", 20.0))
    rated_speed_rpm = float(induction_cfg.get("rated_speed_rpm", 1462.5))
    rated_current_A = float(induction_cfg.get("rated_current_A", 32.85))
    rated_voltage_V = float(induction_cfg.get("rated_voltage_line_line_V", 400.0))
    rated_frequency_Hz = float(induction_cfg.get("frequency_Hz", 50.0))
    rated_output_W = float(induction_cfg.get("rated_output_W", 18500.0))
    rated_efficiency = float(induction_cfg.get("rated_efficiency", 0.9049))
    rated_torque_Nm = float(induction_cfg.get("rated_torque_Nm", 120.794521))
    winding_loss_fraction = float(induction_cfg.get("winding_loss_fraction", 0.644))
    min_load = float(safety_cfg.get("minimum_load_pu", 0.50))
    ref_load = float(safety_cfg.get("reference_load_pu", 1.00))
    warning_C = float(safety_cfg.get("winding_warning_C", 100.0))
    critical_C = float(safety_cfg.get("winding_critical_C", 120.0))
    pipeline = TwinPipeline(
        controller_name,
        pipeline_config_from_yaml(cfg),
    )

    rated_omega_rad_s = (
        2.0
        * math.pi
        * rated_speed_rpm
        / 60.0
    )

    fault_tick = max(0, int(round(fault_time / step)))
    trial_config = cfg.get("vr_trial_scenarios", {})
    injector = (
        None
        if scenario_name == "healthy"
        else injector_from_scenario(
            scenario_name,
            start_tick=fault_tick,
            step_s=step,
            duration_s=float(trial_config.get("profile_duration_s", 600.0)),
            parameters=trial_config.get("scenarios", {}).get(scenario_name),
        )
    )

    # -------------------------
    # Experiment storage
    # -------------------------

    rows: list[dict[str, Any]] = []

    basyx = None

    if basyx_enabled:
        print()
        print("[BaSyx] Initializing AAS synchronization...")

        basyx = BaSyxBridge(
            host=basyx_host
        )

        health = basyx.health_check()

        print(
            f"[BaSyx] Connected "
            f"({health['latency_ms']:.3f} ms)"
        )

    last_basyx_sync_t = -1e9
    aas_run_id = uuid4().hex
    aas_snapshot_sequence = 0

    basyx_sync_count = 0
    basyx_sync_failures = 0
    basyx_latency_ms = []

    basyx_metrics = (
    BaSyxEvaluationMetrics(
            environment_url=basyx_host,
            timeout_s=5.0,
        )
        if basyx_enabled
        else None
    )

    realtime_wall_start = None
    realtime_wall_elapsed_s = None
    realtime_deadline_misses = 0
    realtime_cycle_latencies_ms: list[float] = []

    # -------------------------
    # FMU runtime
    # -------------------------

    with FMURuntime(
        fmu_path,
        stop_time=stop_time,
    ) as runtime:

        if runtime.plant_profile != plant_profile:
            raise RuntimeError(
                f"FMU profile mismatch: selected {plant_profile!r}, "
                f"runtime identified {runtime.plant_profile!r}."
            )
        if runtime.plant_profile != "induction":
            raise RuntimeError("The active CGVR runtime requires the induction FMU.")

        # The runtime pipeline normalizes measurements once and initializes
        # the observer without exposing hidden MSL state to the twin.
        raw_measurement = runtime.initialize()
        measurement = pipeline.reset(raw_measurement)

        # Initial command.
        current_command = ControlCommand(
            load_pu=ref_load,
            speed_pu=1.0,
            cooling_flow_pu=1.0,
        )

        elapsed_energy_kwh = 0.0
        useful_work_kwh = 0.0
        # ---------------------------------------------------------------
        # Closed-loop simulation
        # ---------------------------------------------------------------

        if realtime:
            realtime_wall_start = time.perf_counter()

        while runtime.current_time < stop_time - 1e-12:

            # Current simulation instant.
            t = runtime.current_time
            if realtime and realtime_wall_start is not None:
                scheduled_start = realtime_wall_start + t
                wait_s = scheduled_start - time.perf_counter()
                if wait_s > 0.0:
                    time.sleep(wait_s)
                cycle_wall_start = time.perf_counter()
            else:
                cycle_wall_start = time.perf_counter()

            # Fault state is determined from simulation time.
            tick = int(round(t / step))
            fault_active = injector is not None and tick >= injector.start_tick

            result = pipeline.tick(raw_measurement, current_command, step)
            measurement = result.measurement
            twin_measurement = result.twin_measurement
            estimate = result.estimate
            detection = result.detection
            severity = result.severity
            forecast = result.forecast
            next_command = result.command
            controller_load_command_pu = next_command.load_pu
            controller_cooling_command_pu = next_command.cooling_flow_pu
            controller_operating_mode = result.controller_operating_mode
            controller_derating_fraction = result.controller_derating_fraction
            controller_predicted_temperature_C = result.controller_predicted_temperature_C
            controller_safety_margin_C = result.controller_safety_margin_C
            estimator_latency_ms = result.timings.state_estimator_latency_ms
            detection_latency_ms = result.timings.fault_detection_latency_ms
            predictor_latency_ms = result.timings.predictor_latency_ms
            controller_latency_ms = result.timings.controller_latency_ms

            # -----------------------------------------------------------
            # 5. APPLY FAULT + CONTROL INPUTS
            # -----------------------------------------------------------

            inputs = {
                "u_load_torque_pu": next_command.load_pu,
                "u_speed_pu": next_command.speed_pu,
                "u_cooling_flow_pu": next_command.cooling_flow_pu,
                "f_sensor_bias_C": 0.0,
                "f_sensor_freeze": False,
                "f_cooling_eff": 1.0,
                "f_rth_degradation": 1.0,
                "f_load_overload_pu": 0.0,
                "f_mechanical_friction_factor": 1.0,
                "f_voltage_unbalance_pu": 0.0,
                "f_supply_voltage_degradation_pu": 0.0,
                "f_supply_frequency_deviation_pu": 0.0,
            }
            if injector is not None:
                inputs = injector.apply(tick, inputs)

            # ------------------------------------------------------------
            # 6. SYNCHRONIZE AAS SNAPSHOT AT THE CURRENT TIME
            # ------------------------------------------------------------

            # The measurement, estimate, diagnosis, severity and command
            # all describe the same pre-step simulation instant t.
            if (
                basyx_enabled
                and basyx is not None
                and basyx_metrics is not None
                and (
                    t - last_basyx_sync_t
                    >= basyx_period_s - 1e-12
                )
            ):
                true_fault_severities = _true_fault_severities(
                    scenario_name,
                    fault_active,
                    injector,
                    tick,
                )
                snapshot_timestamp_utc = datetime.now(
                    timezone.utc
                ).isoformat(timespec="milliseconds")
                snapshot_id = (
                    f"{aas_run_id}:{aas_snapshot_sequence}"
                )
                snapshot = build_basyx_snapshot(
                    measurement=measurement,
                    estimate=estimate,
                    detection=detection,
                    severity=severity,
                    command=next_command,
                    elapsed_energy_kwh=elapsed_energy_kwh,
                    useful_work_kwh=useful_work_kwh,
                    forecast=forecast,
                    scenario_name=scenario_name,
                    fault_active=fault_active,
                    true_fault_severities=true_fault_severities,
                    controller_name=controller_name,
                    plant_profile=plant_profile,
                    simulation_time_s=float(t),
                    snapshot_timestamp_utc=snapshot_timestamp_utc,
                    snapshot_id=snapshot_id,
                    critical_temperature_C=critical_C,
                )

                controller_only_latency_ms = float(
                    estimator_latency_ms
                    + detection_latency_ms
                    + predictor_latency_ms
                    + controller_latency_ms
                )

                sync_measurement = basyx_metrics.record_sync(
                    simulation_time_s=float(t),
                    controller_only_latency_ms=controller_only_latency_ms,
                    update_snapshot=lambda: basyx.update_snapshot(
                        **snapshot
                    ),
                    snapshot=snapshot,
                )
                aas_snapshot_sequence += 1

                if sync_measurement["update_success"]:
                    basyx_sync_count += 1
                    basyx_latency_ms.append(
                        sync_measurement["write_latency_ms"]
                    )

                    print(
                        f"[BaSyx] "
                        f"t={t:7.1f}s | "
                        f"write={sync_measurement['write_latency_ms']:.2f} ms | "
                        f"read={sync_measurement['read_latency_ms']:.2f} ms | "
                        f"e2e={sync_measurement['end_to_end_loop_latency_ms']:.2f} ms"
                    )
                else:
                    basyx_sync_failures += 1

                    print(
                        "[BaSyx] Synchronization failed: "
                        f"{sync_measurement['error']}"
                    )

                last_basyx_sync_t = t

            # -----------------------------------------------------------
            # 7. ADVANCE FMU
            # -----------------------------------------------------------

            actual_step = min(
                step,
                stop_time - t,
            )

            elapsed_energy_kwh += (
                max(
                    0.0,
                    float(
                        measurement["P_electrical_W"]
                    ),
                )
                * actual_step
                / 3_600_000.0
            )

            useful_work_kwh += (
                max(
                    0.0,
                    float(
                        measurement["P_shaft_W"]
                    ),
                )
                * actual_step
                / 3_600_000.0
            )

            raw_post_measurement, solver_time_s = runtime.step(
                actual_step,
                inputs,
            )
            post_measurement = pipeline.adapt_measurement(raw_post_measurement)
            raw_measurement = raw_post_measurement

            cycle_wall_end = time.perf_counter()
            realtime_cycle_latency_ms = (
                cycle_wall_end - cycle_wall_start
            ) * 1000.0
            realtime_deadline_ms = actual_step * 1000.0
            realtime_deadline_missed = int(
                realtime
                and realtime_cycle_latency_ms
                > realtime_deadline_ms + 1e-6
            )

            if realtime:
                realtime_cycle_latencies_ms.append(
                    realtime_cycle_latency_ms
                )
                realtime_deadline_misses += (
                    realtime_deadline_missed
                )

                if realtime_wall_start is not None:
                    scheduled_end = (
                        realtime_wall_start
                        + t
                        + actual_step
                    )
                    remaining_s = (
                        scheduled_end - time.perf_counter()
                    )
                    if remaining_s > 0.0:
                        time.sleep(remaining_s)

            # -----------------------------------------------------------
            # 7. LOG STATE AT THE CORRESPONDING SIMULATION TIME
            # -----------------------------------------------------------

            #
            # We log the measurement used by the estimator at time t,
            # not the post-step measurement at t + dt.
            #

            speed_reference_pu = float(
                next_command.speed_pu
            )

            speed_reference_rad_s = (
                speed_reference_pu
                * rated_omega_rad_s
            )
            true_fault_severity = _true_fault_severities(
                scenario_name,
                fault_active,
                injector,
                tick,
            )

            row = {
                # -------------------------------------------------------
                # Time / scenario
                # -------------------------------------------------------

                "time_s": t,

                "fault_active": fault_active,

                "fault_type": scenario_name,

                # Ground truth is logged only for evaluation.
                "plant_profile": plant_profile,
                "fault_severity_true_sensor_bias": (
                    true_fault_severity["sensor_bias"]
                ),
                "fault_severity_true_sensor_freeze": (
                    true_fault_severity["sensor_freeze"]
                ),
                "fault_severity_true_cooling": (
                    true_fault_severity["cooling"]
                ),
                "fault_severity_true_rth_degradation": (
                    true_fault_severity["rth_degradation"]
                ),
                "fault_severity_true_unbalance": (
                    true_fault_severity["unbalance"]
                ),
                "fault_severity_true_overload": (
                    true_fault_severity["overload"]
                ),
                "fault_severity_true_mechanical_friction": (
                    true_fault_severity["mechanical_friction"]
                ),
                "fault_severity_true_voltage_imbalance": (
                    true_fault_severity["voltage_imbalance"]
                ),
                "fault_severity_true_supply_degradation": (
                    true_fault_severity["supply_degradation"]
                ),
                "fault_severity_true_frequency_deviation": (
                    true_fault_severity["frequency_deviation"]
                ),
                "fault_severity_true": max(
                    true_fault_severity.values()
                ),

                "frame_innovation_C": float(
                    estimate.frame_innovation_C
                ),

                "controller": controller_name,

                # -------------------------------------------------------
                # Control
                # -------------------------------------------------------

                "u_load_torque_pu": float(
                    next_command.load_pu
                ),
                "torque_command_Nm": float(
                    next_command.load_pu * rated_torque_Nm
                ),

                "u_speed_pu": float(
                    next_command.speed_pu
                ),

                "u_cooling_flow_pu": float(
                    next_command.cooling_flow_pu
                ),

                "speed_reference_pu": (
                    speed_reference_pu
                ),

                "speed_reference_rad_s": (
                    speed_reference_rad_s
                ),

                # -------------------------------------------------------
                # Constrained controller diagnostics
                # -------------------------------------------------------

                "controller_load_command_pu": (
                    controller_load_command_pu
                ),

                "controller_cooling_command_pu": (
                    controller_cooling_command_pu
                ),

                "controller_operating_mode": (
                    controller_operating_mode
                ),

                "trial_action_label": result.trial_action,
                "severity_band": result.severity_band,
                "correct_action": result.correct_action,

                "controller_derating_fraction": (
                    controller_derating_fraction
                ),

                "controller_predicted_temperature_C": (
                    controller_predicted_temperature_C
                ),

                "controller_safety_margin_C": (
                    controller_safety_margin_C
                ),

                # -------------------------------------------------------
                # Twin state estimate
                # -------------------------------------------------------

                "estimated_winding_C": float(
                    estimate.estimated_winding_C
                ),

                "estimated_frame_C": float(
                    estimate.estimated_frame_C
                ),

                "estimated_winding_rate_C_s": float(
                    estimate.estimated_winding_rate_C_s
                ),

                "sensor_residual_C": float(
                    estimate.sensor_residual_C
                ),

                "frame_model_residual_C": float(
                    estimate.frame_model_residual_C
                ),

                # -------------------------------------------------------
                # Fault detector
                # -------------------------------------------------------

                "fault_sensor_bias_detected": bool(
                    detection.sensor_bias
                ),

                "fault_cooling_detected": bool(
                    detection.cooling_degradation
                ),

                "fault_sensor_freeze_detected": bool(
                    detection.sensor_freeze
                ),
                "fault_overload_detected": bool(
                    detection.load_overload
                ),
                "fault_mechanical_friction_detected": bool(
                    detection.mechanical_friction
                ),
                "fault_supply_degradation_detected": bool(
                    detection.supply_degradation
                ),
                "fault_voltage_imbalance_detected": bool(
                    detection.voltage_imbalance
                ),
                "fault_frequency_deviation_detected": bool(
                    detection.frequency_deviation
                ),

                "fault_unbalance_detected": bool(
                    detection.mechanical_unbalance
                ),

                "fault_alarm": bool(
                    detection.alarm
                ),

                "primary_fault": str(
                    detection.primary_fault
                ),

                # -------------------------------------------------------
                # Fault severity
                # -------------------------------------------------------

                "fault_severity_sensor_bias": float(
                    severity["sensor_bias"]
                ),

                "fault_severity_cooling": float(
                    severity["cooling_degradation"]
                ),
                "fault_severity_sensor_freeze": float(
                    severity["sensor_freeze"]
                ),
                "fault_severity_unbalance": float(
                    severity["mechanical_unbalance"]
                ),
                "fault_severity_overload": float(
                    severity["load_overload"]
                ),
                "fault_severity_mechanical_friction": float(
                    severity["mechanical_friction"]
                ),
                "fault_severity_supply_degradation": float(
                    severity["supply_degradation"]
                ),
                "fault_severity_voltage_imbalance": float(
                    severity["voltage_imbalance"]
                ),
                "fault_severity_frequency_deviation": float(
                    severity["frequency_deviation"]
                ),

                "fault_severity_estimated": float(
                    severity["overall"]
                ),

                # -------------------------------------------------------
                # Prediction
                # -------------------------------------------------------

                "predicted_30s_C": float(
                    forecast.predicted_30s_C
                ),

                "predicted_60s_C": float(
                    forecast.predicted_60s_C
                ),

                # -------------------------------------------------------
                # Runtime timing
                # -------------------------------------------------------

                "state_estimator_latency_ms": float(
                    estimator_latency_ms
                ),

                "fault_detection_latency_ms": float(
                    detection_latency_ms
                ),

                "predictor_latency_ms": float(
                    predictor_latency_ms
                ),

                "controller_latency_ms": float(
                    controller_latency_ms
                ),

                "loop_compute_latency_ms": float(
                    estimator_latency_ms
                    + detection_latency_ms
                    + predictor_latency_ms
                    + controller_latency_ms
                ),

                "solver_step_time_s": float(
                    solver_time_s
                ),

                "realtime_cycle_latency_ms": float(
                    realtime_cycle_latency_ms
                ),

                "realtime_deadline_ms": float(
                    realtime_deadline_ms
                ),

                "realtime_deadline_missed": int(
                    realtime_deadline_missed
                ),
            }

            # -----------------------------------------------------------
            # Add CURRENT FMU measurements
            # -----------------------------------------------------------

            row.update(measurement)

            rows.append(row)

            # -----------------------------------------------------------
            # 8. MOVE TO NEXT CONTROL CYCLE
            # -----------------------------------------------------------

            current_command = next_command
            measurement = post_measurement

        if realtime and realtime_wall_start is not None:
            realtime_wall_elapsed_s = (
                time.perf_counter() - realtime_wall_start
            )

    # -------------------------------------------------------------------
    # Build DataFrame
    # -------------------------------------------------------------------

    if not rows:
        raise RuntimeError(
            "Experiment completed without generating any data rows."
        )

    df = pd.DataFrame(rows)

    # -------------------------------------------------------------------
    # Verify all metric-required columns before writing anything
    # -------------------------------------------------------------------

    validate_dataframe(df)

    # -------------------------------------------------------------------
    # Save time-series data
    # -------------------------------------------------------------------

    output = Path(output).resolve()

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.to_csv(
        output,
        index=False,
    )

    # -------------------------------------------------------------------
    # Calculate metrics
    # -------------------------------------------------------------------

    metrics = compute_experiment_metrics(
        df,
        fault_injection_time_s=fault_time,
        safe_temp_threshold_c=critical_C,
        nominal_temp_c=warning_C,
    )

    if realtime and realtime_wall_start is not None:
        realtime_wall_time_s = float(
            realtime_wall_elapsed_s or 0.0
        )
        latency_series = pd.Series(
            realtime_cycle_latencies_ms,
            dtype=float,
        )
        metrics.update(
            {
                "realtime_enabled": True,
                "realtime_wall_time_s": float(
                    realtime_wall_time_s
                ),
                "realtime_factor": float(
                    stop_time / max(realtime_wall_time_s, 1e-9)
                ),
                "realtime_deadline_ms": float(
                    step * 1000.0
                ),
                "realtime_deadline_misses": int(
                    realtime_deadline_misses
                ),
                "realtime_deadline_miss_rate_percent": (
                    float(realtime_deadline_misses)
                    / max(len(realtime_cycle_latencies_ms), 1)
                    * 100.0
                ),
                "realtime_cycle_latency_mean_ms": float(
                    latency_series.mean()
                ),
                "realtime_cycle_latency_p95_ms": float(
                    latency_series.quantile(0.95)
                ),
                "realtime_cycle_latency_max_ms": float(
                    latency_series.max()
                ),
            }
        )
    else:
        metrics["realtime_enabled"] = False


    if basyx_metrics is not None:
        basyx_detail_csv = output.with_name(
            f"{output.stem}_basyx_detail.csv"
        )

        basyx_summary_json = output.with_name(
            f"{output.stem}_basyx_summary.json"
        )

        basyx_summary = basyx_metrics.save(
            detail_csv=basyx_detail_csv,
            summary_json=basyx_summary_json,
        )

        metrics.update(
            {
                f"basyx_{key}": value
                for key, value in basyx_summary.items()
            }
        )

        print()
        print("BaSyx / AAS evaluation")
        print(
            "AAS write mean / P95        : "
            f"{basyx_summary['aas_write_latency_mean_ms']:.3f} / "
            f"{basyx_summary['aas_write_latency_p95_ms']:.3f} ms"
        )
        print(
            "AAS read mean / P95         : "
            f"{basyx_summary['aas_read_latency_mean_ms']:.3f} / "
            f"{basyx_summary['aas_read_latency_p95_ms']:.3f} ms"
        )
        print(
            "End-to-end DT loop mean     : "
            f"{basyx_summary['end_to_end_loop_mean_latency_ms']:.3f} ms"
        )
        print(
            "BaSyx overhead              : "
            f"{basyx_summary['basyx_overhead_mean_ms']:.3f} ms "
            f"({basyx_summary['basyx_overhead_percent']:.2f}%)"
        )
        print(
            "AAS update success rate     : "
            f"{basyx_summary['update_success_rate_percent']:.2f}%"
        )
        print(
            "Winding synchronization MAE : "
            f"{basyx_summary['sync_winding_temperature_C_mae']:.6f} °C"
        )
        print(
            "Load-command synchronization MAE: "
            f"{basyx_summary['sync_load_command_pu_mae']:.6f} pu"
        )
        print(f"BaSyx detailed log           : {basyx_detail_csv}")
        print(f"BaSyx summary                : {basyx_summary_json}")

    # Add constrained-controller metrics to the returned metric dictionary.
    metrics["controller"] = controller_name

    if "controller_safety_margin_C" in df.columns:
        metrics["minimum_controller_safety_margin_C"] = float(
            df["controller_safety_margin_C"].min()
        )

        metrics["mean_controller_safety_margin_C"] = float(
            df["controller_safety_margin_C"].mean()
        )

    if "controller_derating_fraction" in df.columns:
        metrics["mean_controller_derating_fraction"] = float(
            df["controller_derating_fraction"].mean()
        )

        metrics["max_controller_derating_fraction"] = float(
            df["controller_derating_fraction"].max()
        )

    if "controller_operating_mode" in df.columns:
        metrics["emergency_fraction"] = float(
            df["controller_operating_mode"]
            .isin(
                [
                    "EMERGENCY",
                    "EMERGENCY_DERATING",
                ]
            )
            .mean()
        )

    metrics["maximum_winding_temperature_C"] = float(
        df["T_winding_C"].max()
    )
    metrics["minimum_thermal_margin_C"] = float(
        df["thermal_margin_to_critical_K"].min()
    )
    metrics["fault_severity_mae"] = float(
        (df["fault_severity_estimated"] - df["fault_severity_true"])
        .abs()
        .mean()
    )
    post_fault_rows = df[df["time_s"] >= fault_time]
    metrics["fault_severity_mae_post_fault"] = float(
        (
            post_fault_rows["fault_severity_estimated"]
            - post_fault_rows["fault_severity_true"]
        )
        .abs()
        .mean()
    ) if not post_fault_rows.empty else float("nan")

    metrics_path = output.with_name(f"{output.stem}_metrics.json")
    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file, indent=2, allow_nan=True)

    # -------------------------------------------------------------------
    # Console summary
    # -------------------------------------------------------------------

    print()
    print("=" * 72)
    print("EXPERIMENT COMPLETED")
    print("=" * 72)

    print(f"Scenario                     : {scenario_name}")
    print(f"Controller                   : {controller_name}")
    print(f"Simulation time              : {stop_time:.3f} s")
    print(f"Communication step           : {step:.3f} s")
    print(f"Fault injection time         : {fault_time:.3f} s")
    print(f"Rows                         : {len(df)}")
    print(f"Saved                        : {output}")
    print(f"Metrics                      : {metrics_path}")

    print()

    print(
        "Max true winding temperature : "
        f"{df['T_winding_C'].max():.3f} °C"
    )

    print(
        "Max sensor temperature       : "
        f"{df['T_sensor_C'].max():.3f} °C"
    )

    print(
        "Max estimated temperature    : "
        f"{df['estimated_winding_C'].max():.3f} °C"
    )

    print(
        "Max predicted 30 s temp      : "
        f"{df['predicted_30s_C'].max():.3f} °C"
    )

    print(
        "Max predicted 60 s temp      : "
        f"{df['predicted_60s_C'].max():.3f} °C"
    )

    print(
        "Detection latency            : "
        f"{metrics['fault_detection_latency_s']:.3f} s (fault-specific)"
    )

    print(
        "State estimation MAE         : "
        f"{metrics['state_estimation_mae_C']:.3f} °C"
    )

    print(
        "Prediction MAE (30 s)        : "
        f"{metrics['prediction_mae_30s_C']:.3f} °C"
    )

    print(
        "Prediction MAE (60 s)        : "
        f"{metrics['prediction_mae_60s_C']:.3f} °C"
    )

    print(
        "Speed RMSE                   : "
        f"{metrics['speed_rmse_rad_s']:.6f} rad/s"
    )
    print(
        "Load torque command RMSE     : "
        f"{metrics['torque_command_rmse_Nm']:.6f} N·m"
    )
    print(
        "Fault severity MAE           : "
        f"{metrics['fault_severity_mae']:.6f}"
    )
    print(
        "Minimum thermal margin       : "
        f"{metrics['minimum_thermal_margin_C']:.3f} °C"
    )

    print(
        "Energy / useful work ratio    : "
        f"{metrics['energy_to_useful_work_ratio']:.6f}"
    )

    print(
        "Solver real-time factor      : "
        f"{metrics['real_time_factor']:.3f}"
    )

    if realtime:
        print(
            "Wall-clock real-time factor : "
            f"{metrics['realtime_factor']:.3f}"
        )
        print(
            "Wall-clock elapsed          : "
            f"{metrics['realtime_wall_time_s']:.3f} s"
        )
        print(
            "Wall-clock deadline misses  : "
            f"{metrics['realtime_deadline_misses']}"
        )
        print(
            "Wall-clock cycle mean / P95 : "
            f"{metrics['realtime_cycle_latency_mean_ms']:.3f} / "
            f"{metrics['realtime_cycle_latency_p95_ms']:.3f} ms"
        )

    if controller_name == "constrained":

        print(
            "Minimum safety margin        : "
            f"{metrics['minimum_controller_safety_margin_C']:.3f} °C"
        )

        print(
            "Mean derating fraction       : "
            f"{metrics['mean_controller_derating_fraction']:.4f}"
        )

        print(
            "Max derating fraction        : "
            f"{metrics['max_controller_derating_fraction']:.4f}"
        )

        print(
            "Emergency fraction           : "
            f"{metrics['emergency_fraction']:.4f}"
        )

    print("=" * 72)
    print()

    return df, metrics

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Closed-loop Digital Twin experiment runner "
            "using the shared FMU runtime."
        )
    )

    parser.add_argument(
        "--fmu",
        required=True,
        type=Path,
        help="Path to the FMI 2.0 Co-Simulation FMU.",
    )

    parser.add_argument(
        "--plant-profile",
        choices=["auto", "induction"],
        default="auto",
        help="Plant parameter profile; auto-detected from the FMU by default.",
    )

    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="combined_supported",
    )

    parser.add_argument(
        "--controller",
        choices=["baseline", "adaptive", "constrained"],
        default="constrained",
    )

    parser.add_argument(
        "--stop",
        type=float,
        default=1800.0,
    )

    parser.add_argument(
        "--step",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--fault-time",
        type=float,
        default=600.0,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "results/experiment.csv"
        ),
    )


    parser.add_argument(
        "--basyx",
        action="store_true",
        help="Enable live BaSyx AAS synchronization.",
    )

    parser.add_argument(
        "--basyx-host",
        type=str,
        default="http://localhost:8081",
        help="BaSyx AAS Environment URL.",
    )

    parser.add_argument(
        "--basyx-period",
        type=float,
        default=2.0,
        help=(
            "Simulation-time interval between "
            "BaSyx synchronizations."
        ),
    )

    parser.add_argument(
        "--realtime",
        action="store_true",
        help=(
            "Pace the simulation against wall clock and record "
            "control-cycle deadline misses."
        ),
    )

    args = parser.parse_args()

    print(
        f"Scenario   : {args.scenario}"
    )

    print(
        f"Controller : {args.controller}"
    )

    print(
        f"Stop time  : {args.stop} s"
    )

    print(
        f"Step       : {args.step} s"
    )

    print(
        f"Fault time : {args.fault_time} s"
    )

    run_experiment(
        fmu_path=args.fmu.resolve(),
        scenario_name=args.scenario,
        controller_name=args.controller,
        stop_time=args.stop,
        step=args.step,
        fault_time=args.fault_time,
        output=args.output.resolve(),
        basyx_enabled=args.basyx,
        basyx_host=args.basyx_host,
        basyx_period_s=args.basyx_period,
        realtime=args.realtime,
        plant_profile=args.plant_profile,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())