from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _trapz(y: pd.Series, x: pd.Series) -> float:
    if len(y) < 2:
        return 0.0
    return float(np.trapezoid(y.to_numpy(dtype=float), x.to_numpy(dtype=float)))


def _event_count(signal: pd.Series) -> int:
    s = signal.fillna(False).astype(bool).to_numpy()
    return int(np.sum(s[1:] & ~s[:-1])) if len(s) > 1 else int(s[0]) if len(s) else 0


def compute_experiment_metrics(
    df: pd.DataFrame,
    fault_injection_time_s: float,
    safe_temp_threshold_c: float = 120.0,
    nominal_temp_c: float = 100.0,
) -> dict[str, Any]:
    if df.empty:
        raise ValueError("Experiment dataframe is empty.")
    d = df.sort_values("time_s").reset_index(drop=True)

    post = d[d["time_s"] >= fault_injection_time_s]
    pre = d[d["time_s"] < fault_injection_time_s]
    energy_kwh = _trapz(d["P_electrical_W"], d["time_s"]) / 3_600_000.0
    useful_kwh = _trapz(d["P_shaft_W"], d["time_s"]) / 3_600_000.0

    unsafe = d["T_winding_C"] >= safe_temp_threshold_c
    post_unsafe = post["T_winding_C"] >= safe_temp_threshold_c
    unsafe_time_s = _trapz(unsafe.astype(float), d["time_s"])

    alarms = d["fault_alarm"].astype(bool)
    pre_alarm_events = _event_count(alarms[d["time_s"] < fault_injection_time_s])
    post_alarm_events = _event_count(alarms[d["time_s"] >= fault_injection_time_s])

    post_alarm = post[post["fault_alarm"].astype(bool)]
    detection_latency = (
        float(post_alarm.iloc[0]["time_s"] - fault_injection_time_s)
        if not post_alarm.empty
        else float("nan")
    )
    detection_column_by_fault = {
        "sensor_bias": "fault_sensor_bias_detected",
        "sensor_freeze": "fault_sensor_freeze_detected",
        "cooling": "fault_cooling_detected",
        "rth_degradation": "fault_cooling_detected",
        "voltage_imbalance": "fault_voltage_imbalance_detected",
        "supply_degradation": "fault_supply_degradation_detected",
        "frequency_deviation": "fault_frequency_deviation_detected",
        "overload": "fault_overload_detected",
        "mechanical_friction": "fault_mechanical_friction_detected",
        "unbalance": "fault_unbalance_detected",
    }
    fault_name = str(d["fault_type"].iloc[0]) if "fault_type" in d else ""
    detection_column = detection_column_by_fault.get(fault_name)
    if fault_name == "combined_supported":
        detection_columns = [
            detection_column_by_fault[name]
            for name in (
                "sensor_bias",
                "cooling",
                "supply_degradation",
                "overload",
            )
            if detection_column_by_fault[name] in d
        ]
        detected = (
            d[detection_columns].fillna(False).astype(bool).any(axis=1)
            if detection_columns
            else alarms
        )
    elif detection_column and detection_column in d:
        detected = d[detection_column].astype(bool)
    else:
        detected = alarms
    detected_post = d[
        (d["time_s"] >= fault_injection_time_s) & detected
    ]
    specific_detection_latency = (
        float(detected_post.iloc[0]["time_s"] - fault_injection_time_s)
        if not detected_post.empty
        else float("nan")
    )

    ref_speed = d["speed_reference_rad_s"]
    speed_rmse = float(np.sqrt(np.mean((d["omega_rad_s"] - ref_speed) ** 2)))
    if "torque_command_Nm" in d:
        torque_error = d["torque_load_Nm"] - d["torque_command_Nm"]
        torque_command_rmse = float(np.sqrt(np.mean(torque_error**2)))
        torque_command_mae = float(np.mean(np.abs(torque_error)))
    else:
        torque_command_rmse = float("nan")
        torque_command_mae = float("nan")
    useful_work_post = _trapz(post["P_shaft_W"], post["time_s"]) / 3_600_000.0 if len(post) > 1 else 0.0
    energy_post = _trapz(post["P_electrical_W"], post["time_s"]) / 3_600_000.0 if len(post) > 1 else 0.0

    pred30 = d["predicted_30s_C"].to_numpy(dtype=float)
    pred60 = d["predicted_60s_C"].to_numpy(dtype=float)
    true_temp = d["T_winding_C"].to_numpy(dtype=float)
    dt = float(np.median(np.diff(d["time_s"]))) if len(d) > 1 else 0.5
    n30 = max(1, int(round(30.0 / dt)))
    n60 = max(1, int(round(60.0 / dt)))

    pred30_err: list[float] = []
    pred60_err: list[float] = []
    for i in range(len(d)):
        if i + n30 < len(d):
            pred30_err.append(abs(pred30[i] - true_temp[i + n30]))
        if i + n60 < len(d):
            pred60_err.append(abs(pred60[i] - true_temp[i + n60]))

    max_temp = float(d["T_winding_C"].max())
    max_est_temp = float(d["estimated_winding_C"].max())
    mae_state = float(np.mean(np.abs(d["estimated_winding_C"] - d["T_winding_C"])))
    post_alarm_flag = bool(post["fault_alarm"].any()) if not post.empty else False

    mean_loop_ms = float(d["loop_compute_latency_ms"].mean())
    mean_solver_ms = float(d["solver_step_time_s"].mean() * 1000.0)
    sim_dt = float(np.median(np.diff(d["time_s"]))) if len(d) > 1 else 0.0
    real_time_factor = float(sim_dt / max(1e-12, d["solver_step_time_s"].mean())) if len(d) else float("nan")

    return {
        "max_winding_temperature_C": max_temp,
        "max_estimated_temperature_C": max_est_temp,
        "time_above_critical_s": float(unsafe_time_s),
        "unsafe_time_post_fault_s": float(np.sum(post_unsafe.to_numpy(dtype=bool)) * dt) if len(post_unsafe) else 0.0,
        "pre_fault_alarm_events": pre_alarm_events,
        "post_fault_alarm_events": post_alarm_events,
        "detection_latency_s": detection_latency,
        "fault_detection_latency_s": specific_detection_latency,
        "missed_fault": not post_alarm_flag,
        "energy_total_kWh": energy_kwh,
        "useful_work_total_kWh": useful_kwh,
        "energy_to_useful_work_ratio": float(energy_kwh / max(useful_kwh, 1e-12)),
        "energy_post_fault_kWh": energy_post,
        "useful_work_post_fault_kWh": useful_work_post,
        "speed_rmse_rad_s": speed_rmse,
        "torque_command_rmse_Nm": torque_command_rmse,
        "torque_command_mae_Nm": torque_command_mae,
        "state_estimation_mae_C": mae_state,
        "prediction_mae_30s_C": float(np.mean(pred30_err)) if pred30_err else float("nan"),
        "prediction_mae_60s_C": float(np.mean(pred60_err)) if pred60_err else float("nan"),
        "mean_load_command_pu": float(d["u_load_torque_pu"].mean()),
        "post_fault_mean_load_command_pu": float(post["u_load_torque_pu"].mean()) if not post.empty else float("nan"),
        "mean_loop_compute_latency_ms": mean_loop_ms,
        "mean_solver_step_time_ms": mean_solver_ms,
        "real_time_factor": real_time_factor,
        "fault_detection_rate": 0.0 if not post_alarm_flag else 1.0,
        "nominal_threshold_C": nominal_temp_c,
        "critical_threshold_C": safe_temp_threshold_c,
        "minimum_thermal_margin_C": float(
            d["thermal_margin_to_critical_K"].min()
            if "thermal_margin_to_critical_K" in d
            else safe_temp_threshold_c - max_temp
        ),
        "fault_severity_mae": float(
            np.mean(
                np.abs(
                    d["fault_severity_estimated"].to_numpy(dtype=float)
                    - d["fault_severity_true"].to_numpy(dtype=float)
                )
            )
        ) if {"fault_severity_estimated", "fault_severity_true"}.issubset(d.columns) else float("nan"),
        "fault_severity_mae_post_fault": float(
            np.mean(
                np.abs(
                    post["fault_severity_estimated"].to_numpy(dtype=float)
                    - post["fault_severity_true"].to_numpy(dtype=float)
                )
            )
        ) if not post.empty and {"fault_severity_estimated", "fault_severity_true"}.issubset(post.columns) else float("nan"),
    }
