from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.fmu_runtime import FMURuntime


DEFAULT_FMU = PROJECT_ROOT / "models" / "InductionMotorDigitalTwin18kW.fmu"
STOP_TIME_S = 30.0
SETTLING_WINDOW_S = 5.0
STEP_S = 0.1

REFERENCE: dict[str, float] = {
    "line_voltage_rms_V": 400.0,
    "line_current_rms_A": 32.85,
    "supply_frequency_Hz": 50.0,
    "speed_rpm": 1462.5,
    "slip_percent": 2.5,
    "shaft_torque_Nm": 18500.0 / (2.0 * math.pi * 1462.5 / 60.0),
    "electrical_input_power_W": 20443.95,
    "mechanical_output_power_W": 18500.0,
    "efficiency_percent": 90.49,
    "power_factor": 0.898,
    "motor_losses_W": 1943.95,
    "motor_lumped_temperature_C": 90.0,
}
_NOMINAL_OMEGA_RAD_S = 2.0 * math.pi * REFERENCE["speed_rpm"] / 60.0
REFERENCE["electromagnetic_torque_Nm"] = (
    REFERENCE["shaft_torque_Nm"] + (180.0 + 102.22) / _NOMINAL_OMEGA_RAD_S
)

_REQUIRED_COLUMNS = {
    "time_s",
    "line_voltage_rms_V",
    "I_rms_A",
    "supply_frequency_Hz",
    "speed_rpm",
    "torque_motor_Nm",
    "torque_load_Nm",
    "P_electrical_W",
    "P_shaft_W",
    "power_factor",
    "P_loss_total_W",
    "T_winding_C",
}

_CHECKS: dict[str, tuple[str, float, str]] = {
    "line_voltage_rms_V": ("line_voltage_rms_V", 0.4, "absolute"),
    "line_current_rms_A": ("line_current_rms_A", 3.0, "relative_percent"),
    "supply_frequency_Hz": ("supply_frequency_Hz", 0.001, "absolute"),
    "speed_rpm": ("speed_rpm", 1.0, "relative_percent"),
    "slip_percent": ("slip_percent", 0.2, "absolute"),
    "shaft_torque_Nm": ("shaft_torque_Nm", 3.0, "relative_percent"),
    "electrical_input_power_W": ("electrical_input_power_W", 3.0, "relative_percent"),
    "mechanical_output_power_W": ("mechanical_output_power_W", 3.0, "relative_percent"),
    "efficiency_percent": ("efficiency_percent", 1.0, "absolute"),
    "power_factor": ("power_factor", 0.03, "absolute"),
    "motor_losses_W": ("motor_losses_W", 5.0, "relative_percent"),
    "motor_lumped_temperature_C": ("motor_lumped_temperature_C", 8.0, "absolute"),
}


def reference_operating_point() -> dict[str, float]:
    return dict(REFERENCE)


def evaluate_nominal_results(
    frame: pd.DataFrame,
    stop_time_s: float = STOP_TIME_S,
    settling_window_s: float = SETTLING_WINDOW_S,
) -> dict[str, Any]:
    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise KeyError(f"Simulation result is missing columns: {missing}")
    if frame.empty or stop_time_s <= 0.0 or settling_window_s <= 0.0:
        raise ValueError("Provide non-empty samples and positive simulation windows.")

    numeric = frame.loc[:, sorted(_REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    if not numeric.notna().all().all():
        raise ValueError("Simulation result contains non-numeric or missing values.")
    if not math.isclose(float(numeric["time_s"].iloc[-1]), stop_time_s, abs_tol=1e-8):
        raise ValueError(f"Simulation ended at {numeric['time_s'].iloc[-1]} s, expected {stop_time_s} s.")

    tail = numeric[numeric["time_s"] >= stop_time_s - settling_window_s]
    if len(tail) < 2:
        raise ValueError("Steady-state window contains fewer than two samples.")
    actual: dict[str, float] = {
        "line_voltage_rms_V": float(tail["line_voltage_rms_V"].mean()),
        "line_current_rms_A": float(tail["I_rms_A"].mean()),
        "supply_frequency_Hz": float(tail["supply_frequency_Hz"].mean()),
        "speed_rpm": float(tail["speed_rpm"].mean()),
        "slip_percent": float(((1500.0 - tail["speed_rpm"]) / 1500.0 * 100.0).mean()),
        "electromagnetic_torque_Nm": float(tail["torque_motor_Nm"].mean()),
        "shaft_torque_Nm": float(tail["torque_load_Nm"].mean()),
        "electrical_input_power_W": float(tail["P_electrical_W"].mean()),
        "mechanical_output_power_W": float(tail["P_shaft_W"].mean()),
        "efficiency_percent": float((tail["P_shaft_W"] / tail["P_electrical_W"] * 100.0).mean()),
        "power_factor": float(tail["power_factor"].mean()),
        "motor_losses_W": float(tail["P_loss_total_W"].mean()),
        "motor_lumped_temperature_C": float(tail["T_winding_C"].mean()),
    }
    checks: dict[str, dict[str, float | bool | str | None]] = {}
    for name, (actual_name, tolerance, mode) in _CHECKS.items():
        measured = actual[actual_name]
        reference = REFERENCE[name]
        deviation = measured - reference
        relative = abs(deviation) / abs(reference) * 100.0 if reference else None
        passed = abs(deviation) <= tolerance if mode == "absolute" else relative is not None and relative <= tolerance
        checks[name] = {
            "actual": measured,
            "reference": reference,
            "absolute_deviation": deviation,
            "relative_deviation_percent": relative,
            "tolerance": tolerance,
            "tolerance_type": mode,
            "passed": passed,
        }

    speed_range = float(tail["speed_rpm"].max() - tail["speed_rpm"].min())
    current_range = float(tail["I_rms_A"].max() - tail["I_rms_A"].min())
    temp_range = float(numeric["T_winding_C"].max() - numeric["T_winding_C"].min())
    stability_checks = {
        "speed_rpm_peak_to_peak": {"actual": speed_range, "maximum": 0.2, "passed": speed_range <= 0.2},
        "line_current_rms_A_peak_to_peak": {"actual": current_range, "maximum": 0.1, "passed": current_range <= 0.1},
    }
    return {
        "passed": all(item["passed"] for item in checks.values())
        and all(item["passed"] for item in stability_checks.values())
        and temp_range > 1e-9,
        "steady_state_window_s": {
            "start": stop_time_s - settling_window_s,
            "stop": stop_time_s,
            "samples": len(tail),
        },
        "operating_point": actual,
        "reference_point": reference_operating_point(),
        "deviation_checks": checks,
        "stability_checks": stability_checks,
        "thermal_response": {
            "temperature_range_C": temp_range,
            "changed_during_simulation": temp_range > 1e-9,
        },
    }


def run_fmu_simulation(fmu_path: Path, output_path: Path) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    with FMURuntime(fmu_path, stop_time=STOP_TIME_S) as runtime:
        measurement = runtime.initialize()
        while runtime.current_time < STOP_TIME_S - 1e-12:
            step = min(STEP_S, STOP_TIME_S - runtime.current_time)
            measurement, _ = runtime.step(
                step,
                {
                    "u_load_torque_pu": 1.0,
                    "u_speed_pu": 1.0,
                    "u_cooling_flow_pu": 1.0,
                },
            )
            row = {"time_s": runtime.current_time}
            row.update(measurement)
            rows.append(row)
    frame = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the active induction Twin FMU against the MSL nominal benchmark."
    )
    parser.add_argument("--fmu", type=Path, default=DEFAULT_FMU)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "induction_motor_nominal",
    )
    args = parser.parse_args()
    fmu_path = args.fmu.resolve()
    if not fmu_path.is_file():
        raise FileNotFoundError(f"Induction FMU not found: {fmu_path}. Export it first.")

    run_dir = args.output_dir.resolve() / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    csv_path = run_dir / "motor_nominal.csv"
    frame = run_fmu_simulation(fmu_path, csv_path)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fmu": str(fmu_path),
        "model_name": "MotorDigitalTwin.InductionMotorDigitalTwin18kW",
        "reference_source": "Modelica Standard Library 4.1.0 IMC_withLosses",
        "stop_time_s": STOP_TIME_S,
        "settling_window_s": SETTLING_WINDOW_S,
        "result_csv": str(csv_path),
        **evaluate_nominal_results(frame),
    }
    report_path = run_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
