from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from plant.evaluation import SimulationEvaluation
from plant.interface import ControlCommand, PlantInterface, PlantState
from simulation.fmu_runtime import FMURuntime


InputModifier = Callable[[float, dict[str, Any]], dict[str, Any]]


class FMUPlant(PlantInterface):
    """Plant adapter that hides FMI details behind PlantInterface."""

    def __init__(
        self,
        fmu_path: Path,
        stop_time_s: float | None = None,
        input_modifier: InputModifier | None = None,
    ) -> None:
        self.fmu_path = Path(fmu_path).resolve()
        self.stop_time_s = stop_time_s
        self.input_modifier = input_modifier
        self._runtime: FMURuntime | None = None
        self._command = ControlCommand(timestamp_s=0.0)
        self._measurement: dict[str, float] | None = None
        self._evaluation: SimulationEvaluation | None = None

    @property
    def current_time_s(self) -> float:
        return self._runtime.current_time if self._runtime else 0.0

    def start(self) -> PlantState:
        if self._runtime is None:
            self._runtime = FMURuntime(self.fmu_path, stop_time=self.stop_time_s)
        self._measurement = self._runtime.initialize()
        self._record_evaluation()
        return self.read_state()

    def stop(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
        self._runtime = None
        self._measurement = None

    def reset(self) -> None:
        self.stop()
        self._command = ControlCommand(timestamp_s=0.0)
        self._evaluation = None

    def read_state(self) -> PlantState:
        if self._measurement is None:
            raise RuntimeError("Plant must be started before reading state.")
        measurement = self._measurement
        vibration_supported = bool(
            measurement.get("mechanical_unbalance_supported", 0.0)
        )
        return PlantState(
            timestamp_s=self.current_time_s,
            speed_rpm=float(measurement["speed_rpm"]),
            temperature_C=float(measurement["T_sensor_C"]),
            current_A=float(measurement["I_rms_A"]),
            voltage_V=float(measurement["line_voltage_rms_V"]),
            electrical_power_W=float(measurement["P_electrical_W"]),
            load_torque_Nm=float(measurement["torque_load_Nm"]),
            vibration_mm_s=(
                float(measurement["vibration_mm_s_out"])
                if vibration_supported
                else None
            ),
            frame_temperature_C=float(measurement["T_frame_C"]),
            shaft_power_W=float(measurement["P_shaft_W"]),
            motor_torque_Nm=float(measurement["torque_motor_Nm"]),
            motor_status="running" if float(measurement["speed_rpm"]) > 1.0 else "stopped",
            ambient_temperature_C=float(measurement["T_ambient_C"]),
            supply_frequency_Hz=float(measurement["supply_frequency_Hz"]),
            power_factor=float(measurement["power_factor"]),
            reactive_power_var=float(measurement["reactive_power_var"]),
            voltage_unbalance_percent=float(measurement["voltage_unbalance_percent"]),
            current_pu=float(measurement["current_pu"]),
            load_torque_pu=float(measurement["load_torque_pu"]),
        )

    def send_command(self, command: ControlCommand) -> None:
        if self._runtime is None:
            raise RuntimeError("Plant must be started before sending commands.")
        self._command = command

    def step(self, step_s: float) -> PlantState:
        if self._runtime is None or self._measurement is None:
            raise RuntimeError("Plant must be started before stepping.")
        if step_s <= 0.0:
            raise ValueError("step_s must be > 0")

        inputs = self._command.as_inputs()
        if self.input_modifier is not None:
            inputs = self.input_modifier(self.current_time_s, inputs)

        self._measurement, solver_time_s = self._runtime.step(step_s, inputs)
        self._record_evaluation(solver_time_s=solver_time_s)
        return self.read_state()

    def read_simulation_evaluation(self) -> SimulationEvaluation:
        """Return truth for metrics only; absent from PlantInterface."""
        if self._evaluation is None:
            raise RuntimeError("Plant has not produced an evaluation snapshot.")
        return self._evaluation

    def read_observation(self) -> dict[str, float]:
        """Return observable channels in the legacy twin format."""
        return self.read_state().as_measurement()

    def _record_evaluation(self, solver_time_s: float = 0.0) -> None:
        if self._measurement is None:
            return
        outputs = dict(self._measurement)
        outputs["solver_step_time_s"] = solver_time_s
        self._evaluation = SimulationEvaluation(self.current_time_s, outputs)

    def __enter__(self) -> FMUPlant:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()