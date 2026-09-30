from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave


INPUTS = [
    "u_load_torque_pu",
    "u_speed_pu",
    "u_cooling_flow_pu",
    "f_sensor_bias_C",
    "f_sensor_freeze",
    "f_cooling_eff",
    "f_rth_degradation",
    "f_unbalance_severity",
    "f_voltage_imbalance_pu",
]

OUTPUTS = [
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
    "current_ripple_percent",
    "vibration_mm_s_out",
    "thermal_margin_to_critical_K",
    "thermal_state",
]

OPTIONAL_INPUTS = {"f_voltage_imbalance_pu"}
OPTIONAL_OUTPUTS = {"current_ripple_percent"}


class FMURuntime:
    """Single reusable FMI 2.0 Co-Simulation runtime for the project.

    Handles FMU lifecycle, typed FMI I/O, stepping, and solver timing.
    """

    def __init__(self, fmu_path: Path, stop_time: float | None = None) -> None:
        self.fmu_path = Path(fmu_path).resolve()
        self.stop_time = stop_time

        self.md = read_model_description(str(self.fmu_path))
        if self.md.fmiVersion != "2.0":
            raise RuntimeError(f"Expected FMI 2.0, got {self.md.fmiVersion}")
        if self.md.coSimulation is None:
            raise RuntimeError("FMU is not a Co-Simulation FMU.")

        by_name = {v.name: v for v in self.md.modelVariables}
        missing = [
            n for n in INPUTS + OUTPUTS
            if n not in by_name
            and n not in OPTIONAL_INPUTS
            and n not in OPTIONAL_OUTPUTS
        ]
        if missing:
            raise KeyError(f"FMU variables not found: {missing}")

        self.in_var = {n: by_name[n] for n in INPUTS if n in by_name}
        self.out_var = {n: by_name[n] for n in OUTPUTS if n in by_name}

        self.in_vr = {n: v.valueReference for n, v in self.in_var.items()}
        self.out_vr = {n: v.valueReference for n, v in self.out_var.items()}

        self.unzip_dir = Path(extract(str(self.fmu_path)))
        self.fmu = FMU2Slave(
            guid=self.md.guid,
            unzipDirectory=str(self.unzip_dir),
            modelIdentifier=self.md.coSimulation.modelIdentifier,
            instanceName="motorTwin",
        )
        self.initialized = False
        self.current_time = 0.0

    @staticmethod
    def _kind(variable: Any) -> str:
        """Return a normalized FMI variable type name."""
        value = getattr(variable, "type", "")
        return str(getattr(value, "name", value)).strip().lower()

    def initialize(self, inputs: dict[str, Any] | None = None) -> dict[str, float]:
        if self.initialized:
            return self.get_outputs()

        initial: dict[str, Any] = {
            "u_load_torque_pu": 1.0,
            "u_speed_pu": 1.0,
            "u_cooling_flow_pu": 1.0,
            "f_sensor_bias_C": 0.0,
            "f_sensor_freeze": False,
            "f_cooling_eff": 1.0,
            "f_rth_degradation": 1.0,
            "f_unbalance_severity": 0.0,
            "f_voltage_imbalance_pu": 0.0,
        }
        if inputs:
            initial.update(inputs)

        self.fmu.instantiate()
        self.fmu.setupExperiment(startTime=0.0, stopTime=self.stop_time)
        self.fmu.enterInitializationMode()
        self.set_inputs(initial)
        self.fmu.exitInitializationMode()
        self.initialized = True
        self.current_time = 0.0
        return self.get_outputs()

    def set_inputs(self, inputs: dict[str, Any]) -> None:
        """Set inputs using the FMI primitive matching their declared type."""
        real_vr: list[int] = []
        real_val: list[float] = []
        int_vr: list[int] = []
        int_val: list[int] = []
        bool_vr: list[int] = []
        bool_val: list[int] = []

        for name, value in inputs.items():
            if name not in self.in_var:
                continue
            kind = self._kind(self.in_var[name])
            vr = self.in_vr[name]

            if kind == "real":
                real_vr.append(vr)
                real_val.append(float(value))
            elif kind in {"integer", "enumeration"}:
                int_vr.append(vr)
                int_val.append(int(value))
            elif kind == "boolean":
                bool_vr.append(vr)
                # Cast explicitly to integer 1/0 for FMI C-ABI safety
                bool_val.append(1 if value else 0)
            else:
                raise TypeError(f"Unsupported FMU input type for {name}: {kind}")

        if real_vr:
            self.fmu.setReal(real_vr, real_val)
        if int_vr:
            self.fmu.setInteger(int_vr, int_val)
        if bool_vr:
            self.fmu.setBoolean(bool_vr, bool_val)

    def get_outputs(self) -> dict[str, float]:
        """Read outputs using the primitive required by each FMU variable type."""
        real_names, real_vr = [], []
        int_names, int_vr = [], []
        bool_names, bool_vr = [], []

        for name in OUTPUTS:
            if name not in self.out_var:
                continue
            kind = self._kind(self.out_var[name])
            vr = self.out_vr[name]
            if kind == "real":
                real_names.append(name)
                real_vr.append(vr)
            elif kind in {"integer", "enumeration"}:
                int_names.append(name)
                int_vr.append(vr)
            elif kind == "boolean":
                bool_names.append(name)
                bool_vr.append(vr)
            else:
                raise TypeError(f"Unsupported FMU output type for {name}: {kind}")

        result: dict[str, float] = {}

        if real_vr:
            vals = self.fmu.getReal(real_vr)
            for name, val in zip(real_names, vals):
                result[name] = float(val)

        if int_vr:
            vals = self.fmu.getInteger(int_vr)
            for name, val in zip(int_names, vals):
                result[name] = float(val)

        if bool_vr:
            vals = self.fmu.getBoolean(bool_vr)
            for name, val in zip(bool_names, vals):
                result[name] = float(1.0 if val else 0.0)

        return {name: result[name] for name in OUTPUTS if name in result}

    def step(
        self,
        step_size: float,
        inputs: dict[str, Any] | None = None,
    ) -> tuple[dict[str, float], float]:
        """Apply inputs, perform one FMU communication step, then read outputs."""
        if not self.initialized:
            raise RuntimeError("FMU must be initialized before stepping.")
        if step_size <= 0.0:
            raise ValueError("step_size must be > 0")

        if inputs:
            self.set_inputs(inputs)

        t0 = time.perf_counter()
        status = self.fmu.doStep(
            currentCommunicationPoint=self.current_time,
            communicationStepSize=step_size,
        )
        elapsed = time.perf_counter() - t0

        if status not in (None, 0):
            raise RuntimeError(f"FMU doStep returned non-success status: {status}")

        self.current_time += step_size
        return self.get_outputs(), elapsed

    def close(self) -> None:
        """Safely clean up temporary unzipped files without triggering OpenModelica C-heap crashes."""
        if not self.initialized:
            return

        self.initialized = False

        # NOTE: Calling self.fmu.freeInstance() or self.fmu.terminate() on OpenModelica CVODE 
        # FMUs on Windows causes a STATUS_HEAP_CORRUPTION (0xc0000374) crash during exception handling.
        # OS-level process termination handles the DLL memory safely on exit.
        try:
            shutil.rmtree(self.unzip_dir, ignore_errors=True)
        except Exception:
            pass

    def __enter__(self) -> FMURuntime:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def run(
    fmu_path: Path,
    stop_time: float,
    step: float,
    fault_time: float,
    out_csv: Path,
) -> None:
    """Backward-compatible FMU smoke test."""
    with FMURuntime(fmu_path, stop_time=stop_time) as runtime:
        runtime.initialize()
        rows: list[dict[str, Any]] = []
        while runtime.current_time < stop_time - 1e-12:
            fault_on = runtime.current_time >= fault_time
            inputs = {
                "u_load_torque_pu": 1.0,
                "u_speed_pu": 1.0,
                "u_cooling_flow_pu": 1.0,
                "f_sensor_bias_C": 10.0 if fault_on else 0.0,
                "f_sensor_freeze": False,
                "f_cooling_eff": 0.40 if fault_on else 1.0,
                "f_rth_degradation": 1.0,
                "f_unbalance_severity": 0.75 if fault_on else 0.0,
            }
            actual_step = min(step, stop_time - runtime.current_time)
            values, solver_time = runtime.step(actual_step, inputs)
            row = {
                "time_s": runtime.current_time,
                "fault_active": fault_on,
                "solver_step_time_s": solver_time,
            }
            row.update(values)
            rows.append(row)

        df = pd.DataFrame(rows)
        out_csv = Path(out_csv).resolve()
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)
        print(df.head())
        print("Saved:", out_csv)
        print("Max winding temperature:", df["T_winding_C"].max())
        print("Max sensor temperature:", df["T_sensor_C"].max())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a stepped smoke test against a Motor FMU.")
    parser.add_argument("--fmu", required=True, type=Path)
    parser.add_argument("--stop", type=float, default=180.0)
    parser.add_argument("--step", type=float, default=0.5)
    parser.add_argument("--fault-time", type=float, default=60.0)
    parser.add_argument("--output", type=Path, default=Path("results/smoke_test.csv"))
    args = parser.parse_args()
    run(args.fmu.resolve(), args.stop, args.step, args.fault_time, args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())