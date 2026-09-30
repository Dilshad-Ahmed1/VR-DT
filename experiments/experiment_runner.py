from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from control.baseline_controller import ControlCommand
from simulation.fmu_runtime import FMURuntime
from server.state_schema import build_state
from server.twin_pipeline import TwinPipeline, pipeline_config_from_yaml
from twin.fault_injector import SUPPORTED_FAULTS, injector_from_scenario


def load_config() -> dict[str, Any]:
    path = Path("config/twin_config.yaml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def run_batch(
    *,
    fmu_path: Path,
    scenario: str,
    controller: str,
    stop: float,
    step: float,
    fault_time: float | None,
    output: Path,
    seed: int | None = None,
) -> pd.DataFrame:
    config = load_config()
    pipeline = TwinPipeline(controller, pipeline_config_from_yaml(config))
    simulation = config.get("simulation", {})
    trial_config = config.get("vr_trial_scenarios", {})
    quiet = trial_config.get("quiet_window_s", [30.0, 60.0])

    rng = random.Random(seed)
    if scenario == "healthy":
        injector = None
        start_tick = -1
    else:
        start_s = float(fault_time) if fault_time is not None else rng.uniform(float(quiet[0]), float(quiet[1]))
        start_tick = max(0, int(round(start_s / step)))
        injector = injector_from_scenario(
            scenario,
            start_tick=start_tick,
            step_s=step,
            duration_s=float(trial_config.get("profile_duration_s", 600.0)),
        )

    base_inputs: dict[str, Any] = {
        "u_load_torque_pu": float(simulation.get("default_load_pu", 1.0)),
        "u_speed_pu": float(simulation.get("default_speed_pu", 1.0)),
        "u_cooling_flow_pu": float(simulation.get("default_cooling_flow_pu", 1.0)),
        "f_sensor_bias_C": 0.0,
        "f_sensor_freeze": False,
        "f_cooling_eff": 1.0,
        "f_rth_degradation": 1.0,
        "f_unbalance_severity": 0.0,
        "f_voltage_imbalance_pu": 0.0,
    }
    rows: list[dict[str, Any]] = []
    previous_command = ControlCommand(1.0, 1.0, 1.0)

    with FMURuntime(fmu_path, stop_time=stop) as runtime:
        measurement = runtime.initialize(base_inputs)
        pipeline.reset(measurement)
        tick = 0
        while runtime.current_time < stop - 1e-12:
            tick_start = time.perf_counter()
            inputs = dict(base_inputs)
            inputs.update({
                "u_load_torque_pu": previous_command.load_pu,
                "u_speed_pu": previous_command.speed_pu,
                "u_cooling_flow_pu": previous_command.cooling_flow_pu,
            })
            if injector is not None:
                inputs = injector.apply(tick, inputs)

            result = pipeline.tick(measurement, previous_command, step)
            state = build_state(tick, runtime.current_time, scenario, measurement, result)
            actual_step = min(step, stop - runtime.current_time)
            next_measurement, solver_time = runtime.step(actual_step, inputs)
            row: dict[str, Any] = {
                "tick": tick,
                "time_s": runtime.current_time,
                "scenario": scenario,
                "fault_onset_tick": start_tick,
                "controller": controller,
                "controller_operating_mode": result.controller_operating_mode,
                "trial_action_label": result.trial_action,
                "correct_action": result.correct_action,
                "severity_band": result.severity_band,
                "fault_severity_estimated": result.severity["overall"],
                "fault_sensor_bias_detected": result.detection.sensor_bias,
                "fault_cooling_detected": result.detection.cooling_degradation,
                "fault_unbalance_detected": result.detection.mechanical_unbalance,
                "fault_alarm": result.detection.alarm,
                "primary_fault": result.detection.primary_fault,
                "estimated_winding_C": result.estimate.estimated_winding_C,
                "estimated_frame_C": result.estimate.estimated_frame_C,
                "estimated_winding_rate_C_s": result.estimate.estimated_winding_rate_C_s,
                "sensor_residual_C": result.estimate.sensor_residual_C,
                "frame_innovation_C": result.estimate.frame_innovation_C,
                "predicted_30s_C": result.forecast.predicted_30s_C,
                "predicted_60s_C": result.forecast.predicted_60s_C,
                "u_load_torque_pu": result.command.load_pu,
                "u_speed_pu": result.command.speed_pu,
                "u_cooling_flow_pu": result.command.cooling_flow_pu,
                "controller_latency_ms": (time.perf_counter() - tick_start) * 1000.0,
                "solver_step_time_s": solver_time,
                "state_json": state,
            }
            row.update(measurement)
            rows.append(row)
            previous_command = result.command
            measurement = next_measurement
            tick += 1

    dataframe = pd.DataFrame(rows)
    dataframe["state_json"] = dataframe["state_json"].map(json.dumps)
    output.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output, index=False)
    return dataframe


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a batch experiment through the shared live twin pipeline.")
    parser.add_argument("--fmu", required=True, type=Path)
    parser.add_argument("--scenario", choices=["healthy", *sorted(SUPPORTED_FAULTS)], default="healthy")
    parser.add_argument("--controller", choices=["baseline", "adaptive", "constrained"], default="constrained")
    parser.add_argument("--stop", type=float, default=1800.0)
    parser.add_argument("--step", type=float, default=0.5)
    parser.add_argument("--fault-time", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("results/experiment.csv"))
    args = parser.parse_args()
    run_batch(
        fmu_path=args.fmu.resolve(),
        scenario=args.scenario,
        controller=args.controller,
        stop=args.stop,
        step=args.step,
        fault_time=args.fault_time,
        output=args.output.resolve(),
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
