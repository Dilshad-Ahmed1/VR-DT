from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from control.baseline_controller import ControlCommand
from server.state_schema import build_state
from server.trial_logger import TrialLogger
from server.twin_pipeline import TwinPipeline, pipeline_config_from_yaml
from simulation.fmu_runtime import FMURuntime
from twin.fault_injector import SCENARIO_DEFAULTS, injector_from_scenario


class StartTrialRequest(BaseModel):
    participant_id: str = "anonymous"
    condition: Literal["vr", "dashboard"] = "vr"
    trial_id: str | None = None
    scenario: str = "sensor_drift"
    controller: str = "constrained"
    fmu: str = "models/InductionMotorDigitalTwin18kW.fmu"
    step_s: float = 0.5
    stop_s: float = 1800.0


class ResponseRequest(BaseModel):
    participant_id: str
    condition: Literal["dashboard", "vr"]
    trial_id: str
    action: str
    client_timestamp: float


class LiveSession:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.task: asyncio.Task[None] | None = None
        self.runtime: FMURuntime | None = None
        self.pipeline: TwinPipeline | None = None
        self.injector = None
        self.measurement: dict[str, float] | None = None
        self.previous_command = ControlCommand(1.0, 1.0, 1.0)
        self.latest_state: dict[str, Any] | None = None
        self.states: dict[int, dict[str, Any]] = {}
        self.tick = 0
        self.step_s = 0.5
        self.stop_s = 1800.0
        self.scenario = "healthy"
        self.participant_id = "anonymous"
        self.condition = "vr"
        self.trial_id = ""
        self.fault_onset_tick = -1
        self.logger = TrialLogger()
        self.started_at = 0.0

    async def start(self, request: StartTrialRequest) -> dict[str, Any]:
        if self.task and not self.task.done():
            raise RuntimeError("a live trial is already running")
        if request.scenario != "healthy" and request.scenario not in SCENARIO_DEFAULTS:
            raise ValueError(f"unsupported induction scenario: {request.scenario}")
        if request.controller != "constrained":
            raise ValueError(
                "live human-subject trials require the constrained controller "
                "because the trial oracle is tied to its EMERGENCY state."
            )
        if request.step_s <= 0.0 or request.stop_s <= 0.0:
            raise ValueError("step_s and stop_s must be positive")

        config = yaml.safe_load(Path("config/twin_config.yaml").read_text(encoding="utf-8")) or {}
        trial_config = config.get("vr_trial_scenarios", {})
        self.step_s = request.step_s
        self.stop_s = request.stop_s
        self.scenario = request.scenario
        self.participant_id = request.participant_id
        self.condition = request.condition
        self.trial_id = request.trial_id or str(uuid.uuid4())
        self.tick = 0
        self.states.clear()
        self.latest_state = None
        quiet = trial_config.get("quiet_window_s", [30.0, 60.0])
        trial_hash = int.from_bytes(
            hashlib.sha256(self.trial_id.encode("utf-8")).digest()[:8],
            "big",
        )
        seed = int(trial_config.get("random_seed", 0)) ^ trial_hash
        if request.scenario == "healthy":
            self.fault_onset_tick = -1
        else:
            start_s = random.Random(seed).uniform(float(quiet[0]), float(quiet[1]))
            self.fault_onset_tick = int(round(start_s / self.step_s))
            if self.stop_s <= start_s:
                raise ValueError("trial duration must extend beyond the randomized fault onset")
        self.injector = None if request.scenario == "healthy" else injector_from_scenario(
            request.scenario,
            start_tick=self.fault_onset_tick,
            step_s=self.step_s,
            duration_s=float(trial_config.get("profile_duration_s", 600.0)),
            parameters=trial_config.get("scenarios", {}).get(request.scenario),
        )
        self.pipeline = TwinPipeline(request.controller, pipeline_config_from_yaml(config))
        self.runtime = FMURuntime(Path(request.fmu), stop_time=self.stop_s)
        self.started_at = time.monotonic()
        self.task = asyncio.create_task(self._run(config))
        return {
            "trial_id": self.trial_id,
            "scenario": self.scenario,
            "fault_onset_tick": self.fault_onset_tick,
            "step_s": self.step_s,
        }

    async def _run(self, config: dict[str, Any]) -> None:
        assert self.runtime is not None
        assert self.pipeline is not None
        simulation = config.get("simulation", {})
        inputs: dict[str, Any] = {
            "u_load_torque_pu": float(simulation.get("default_load_pu", 1.0)),
            "u_speed_pu": float(simulation.get("default_speed_pu", 1.0)),
            "u_cooling_flow_pu": float(simulation.get("default_cooling_flow_pu", 1.0)),
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
        try:
            self.measurement = self.runtime.initialize(inputs)
            self.pipeline.reset(self.measurement)
            while self.runtime.current_time < self.stop_s - 1e-12:
                cycle_start = time.perf_counter()
                assert self.measurement is not None
                inputs.update({
                    "u_load_torque_pu": self.previous_command.load_pu,
                    "u_speed_pu": self.previous_command.speed_pu,
                    "u_cooling_flow_pu": self.previous_command.cooling_flow_pu,
                })
                if self.injector is not None:
                    inputs = self.injector.apply(self.tick, inputs)
                result = self.pipeline.tick(self.measurement, self.previous_command, self.step_s)
                state = build_state(
                    self.tick,
                    self.runtime.current_time,
                    self.scenario,
                    result.twin_measurement,
                    result,
                )
                state["trial"].update({
                    "trial_id": self.trial_id,
                    "fault_onset_tick": self.fault_onset_tick,
                    "tick_to_client_build_ms": (time.perf_counter() - cycle_start) * 1000.0,
                })
                self.latest_state = state
                self.states[self.tick] = state
                await self._broadcast(state)
                actual_step = min(self.step_s, self.stop_s - self.runtime.current_time)
                self.measurement, _ = self.runtime.step(actual_step, inputs)
                self.previous_command = result.command
                self.tick += 1
                await asyncio.sleep(max(0.0, self.step_s - (time.perf_counter() - cycle_start)))
        finally:
            self.runtime.close()

    async def _broadcast(self, state: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(state)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)

    def respond(self, request: ResponseRequest) -> dict[str, Any]:
        if request.trial_id != self.trial_id:
            raise ValueError("unknown trial_id")
        if request.participant_id != self.participant_id or request.condition != self.condition:
            raise ValueError("response participant or condition does not match the active trial")
        if not self.states:
            raise ValueError("the trial has not produced a state")
        state = self.latest_state or self.states[max(self.states)]
        response_tick = int(state["tick"])
        medium_ticks = [tick for tick, value in self.states.items() if value["severity"]["band"] in {"medium", "high"}]
        detection_tick = min(medium_ticks) if medium_ticks else None
        result = self.logger.record_response(
            participant_id=request.participant_id,
            condition=request.condition,
            trial_id=request.trial_id,
            scenario=self.scenario,
            fault_onset_tick=self.fault_onset_tick,
            detection_tick=detection_tick,
            response_tick=response_tick,
            step_s=self.step_s,
            client_timestamp=request.client_timestamp,
            participant_action=request.action,
            correct_action=state["trial"]["correct_action"],
            controller_operating_mode=state["controller"]["operating_mode"],
            trial_action_label=state["trial"]["action_label"],
            severity_at_response=state["severity"]["overall"],
            severity_band_at_response=state["severity"]["band"],
        )
        self.logger.save(f"{self.trial_id}_responses")
        return result


app = FastAPI(title="CGVR Live Twin Server", version="1.0.0")
session = LiveSession()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"running": bool(session.task and not session.task.done()), "tick": session.tick, "schema_version": "twin_state_v1"}


@app.post("/trials/start")
async def start_trial(request: StartTrialRequest) -> dict[str, Any]:
    try:
        return await session.start(request)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/respond")
async def respond(request: ResponseRequest) -> dict[str, Any]:
    try:
        return session.respond(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session.clients.add(websocket)
    if session.latest_state is not None:
        await websocket.send_json(session.latest_state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        session.clients.discard(websocket)
    except Exception:
        session.clients.discard(websocket)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the CGVR live twin server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()