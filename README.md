# CGVR: Live Motor Digital Twin and VR Study Base

This repository is the shared software base for two linked course projects:

1. An Industry 5.0 fault-aware adaptive digital twin for a WEG W22 IE3 5.5 kW, four-pole industrial motor.
2. A Computer Graphics and VR study comparing an immersive VR interface with a conventional 2D dashboard while both consume exactly the same live twin state.

The VR client is not included yet. This repository provides the FMU, twin pipeline, live server, trial-response logging, batch experiments, BaSyx integration, analysis tools, and Streamlit result viewer that the future Unity or WebXR client will use.

## Project Architecture

```text
OpenModelica motor model
        |
        v
FMI 2.0 Co-Simulation FMU
        |
        v
simulation/fmu_runtime.py
        |
        v
server/twin_pipeline.py
  estimator -> detector -> severity -> predictor -> controller
        |
        +--> server/state_schema.py -> WebSocket /ws -> Unity/WebXR/2D client
        |
        +--> experiments/experiment_runner.py -> CSV batch results
        |
        +--> integration/basyx_bridge.py -> optional BaSyx snapshot sync
        |
        +--> server/trial_logger.py -> participant response CSV/JSON
```

The live and batch modes use the same `TwinPipeline` implementation. Do not create a second estimator, detector, predictor, or controller implementation in the VR client or in a new experiment script.

## Requirements

- Windows PowerShell is the currently documented environment.
- Python 3.12 or newer is recommended. The project has been validated with the repository-local Python 3.13 virtual environment.
- OpenModelica 1.27.x is required only when checking or regenerating the FMU.
- Docker Desktop is required only for BaSyx integration.
- Unity or WebXR is required only for the future VR client; it is not needed to run the Python twin server.

## Clone and Configure

From the cloned repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On a system where PowerShell blocks activation, use the virtual environment interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The important dependencies are:

- `fmpy`: FMI 2.0 FMU loading and stepping
- `OMPython`: OpenModelica automation for FMU export
- `numpy`, `pandas`, `scipy`, `matplotlib`: numerical work and analysis
- `fastapi`, `uvicorn`: live HTTP/WebSocket server
- `streamlit`: existing 2D result viewer
- `pytest`: automated tests
- `requests`: BaSyx REST bridge

Always confirm that commands use `.venv` when multiple Python installations are present:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

## Validate and Regenerate the FMU

The committed `MotorElectroThermalMechanicalFaultable.fmu` is the normal runtime asset. Regenerate it after changing the Modelica source or FMU interface.

First validate the reference calculations:

```powershell
.\.venv\Scripts\python.exe scripts\validate_reference_motor.py
```

Open `models/MotorElectroThermalMechanicalFaultable.mo` in OMEdit and run `Check -> Check Model`.

Export the FMI 2.0 Co-Simulation FMU with CVODE:

```powershell
.\.venv\Scripts\python.exe scripts\export_fmu.py --omhome "C:/Program Files/OpenModelica1.27.1-64bit"
```

The exporter currently enables CVODE internally. It accepts `--omhome`; it does not accept the old documented `--cvode` option.

The Modelica model is intentionally reduced-order. It represents motor mechanics, electrical losses, two-node winding/frame thermal dynamics, sensor faults, cooling degradation, thermal-resistance degradation, unbalance, and a reduced-order voltage-imbalance observable. It is not a full induction-machine, phase-resolved electrical, or rotor-dynamics model.

After export, inspect the FMU interface:

```powershell
.\.venv\Scripts\python.exe -c "from fmpy import read_model_description; md=read_model_description('MotorElectroThermalMechanicalFaultable.fmu'); print(md.fmiVersion, md.coSimulation is not None); print([v.name for v in md.modelVariables if 'voltage_imbalance' in v.name or 'current_ripple' in v.name])"
```

## FMU Smoke Test

Run a short stepped test before running a long experiment:

```powershell
.\.venv\Scripts\python.exe simulation\fmu_runtime.py `
  --fmu MotorElectroThermalMechanicalFaultable.fmu `
  --stop 180 `
  --step 0.5 `
  --fault-time 60 `
  --output results\smoke_test.csv
```

`simulation/fmu_runtime.py` owns FMI lifecycle management, typed FMI input and output handling, communication-step execution, and solver timing. The default communication interval is 0.5 seconds.

## Shared Twin Pipeline

`server/twin_pipeline.py` is the only implementation of the control loop. Each tick performs:

1. Forward-Euler thermal state estimation.
2. Persistent fault detection with hysteresis.
3. Normalized observable fault-severity estimation.
4. 30-second and 60-second thermal prediction.
5. Baseline, adaptive, or constrained controller computation.
6. Trial action-oracle derivation.

The estimator and predictor deliberately use nominal thermal parameters and do not receive hidden FMU fault parameters. This model mismatch is intentional and must remain visible in reports.

The constrained controller exposes a raw operating mode separately from the human-study action label:

```text
controller_operating_mode: NORMAL, FAULT_AWARE, THERMAL_PREVENTION,
                            ADAPTIVE_DERATING, EMERGENCY_DERATING, EMERGENCY
trial_action:              continue, derate, shutdown
```

The `shutdown` label is an experimental reinterpretation of the controller's `EMERGENCY` state for the human-subjects study. The automatic controller itself does not issue a shutdown command; at `EMERGENCY` it currently derates to its minimum configured load.

The high/emergency condition is:

```text
max(estimated_winding_C, predicted_30s_C, predicted_60s_C) >= 120 C
```

The buffered emergency-derating condition begins at 115 C because the critical temperature is 120 C and the safety buffer is 5 C.

## Batch Experiments

Run one batch experiment through the same pipeline used by the live server:

```powershell
.\.venv\Scripts\python.exe -m experiments.experiment_runner `
  --fmu MotorElectroThermalMechanicalFaultable.fmu `
  --scenario sensor_drift `
  --controller constrained `
  --stop 1800 `
  --step 0.5 `
  --fault-time 600 `
  --output results\sensor_drift_constrained.csv
```

Supported scenarios are:

- `healthy`: no injected fault
- `bearing_wear`: gradual unbalance increase plus reduced-order thermal resistance increase
- `sudden_overload`: 50% load-torque step through the existing FMU load input
- `cooling_failure`: accelerating first-order cooling-efficiency degradation
- `voltage_imbalance`: gradual reduced-order electrical loss/current-ripple approximation; vibration remains near baseline
- `sensor_drift`: gradual temperature sensor bias while physical state remains nominal

Supported controllers are:

- `baseline`: raw temperature threshold controller
- `adaptive`: predictive fault-aware controller
- `constrained`: stateful predictive controller with cooling escalation, safety buffer, and rate-limited load commands

The `--fault-time` option specifies a deterministic onset for batch studies. If it is omitted, the runner randomizes the onset in the configured quiet window from `config/twin_config.yaml`. Use `--seed` for reproducible randomized runs.

The batch runner writes a CSV containing raw FMU measurements, twin estimates, fault flags, severity, predictions, controller mode/action, timing, and a serialized `twin_state_v1` payload.

The old `scripts/run_experiment_suite.py` and `experiments/run_evaluation_suite.py` contain stale references to the previous runner API. Do not use them as the live execution path; update them separately if a publication-scale matrix is needed.

## Live Server for VR and 2D Clients

Start the server from the repository root:

```powershell
.\.venv\Scripts\python.exe -m server.live_server --host 127.0.0.1 --port 8000
```

The server runs the FMU at the configured communication step and broadcasts one state payload per tick. BaSyx is not used for real-time VR streaming; BaSyx remains an optional REST snapshot integration for the Industry 5.0 deliverable.

### Health Check

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

### Start a Trial

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/trials/start `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{
    "participant_id": "p001",
    "condition": "vr",
    "trial_id": "p001-vr-001",
    "scenario": "bearing_wear",
    "controller": "constrained",
    "fmu": "MotorElectroThermalMechanicalFaultable.fmu",
    "step_s": 0.5,
    "stop_s": 1800
  }'
```

`condition` must be either `vr` or `dashboard`. The server randomizes fault onset in the configured 30--60 second quiet window. The returned `fault_onset_tick` identifies the planned onset tick.

### Consume Twin State

Connect the Unity or WebXR client to:

```text
ws://127.0.0.1:8000/ws
```

The canonical payload schema is `schema/twin_state_v1.json`. Both the VR client and the future 2D experimental dashboard must consume this same payload rather than recomputing severity or temperature predictions independently.

The payload contains:

- `measurements`: raw FMU measurements, including temperature, speed, torque, power, current, vibration, thermal margin, and current ripple when available
- `estimated_thermal`: estimated winding/frame state and residuals
- `faults`: detector flags, alarm, and primary fault
- `severity`: component severity, overall normalized severity, and `low`, `medium`, or `high` band
- `prediction`: 30-second and 60-second winding-temperature predictions
- `controller`: controller name, raw operating mode, commands, predicted temperature, safety margin, and derating fraction
- `trial`: derived participant action, correct action, trial ID, fault onset, and timing metadata

### Submit a Participant Response

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/respond `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{
    "participant_id": "p001",
    "condition": "vr",
    "trial_id": "p001-vr-001",
    "action": "derate",
    "client_timestamp": 1727690000.123
  }'
```

Allowed actions are `continue`, `derate`, and `shutdown`. The server compares the participant action with the shared pipeline oracle and writes response logs to `results/trials/` as both CSV and JSON.

Trial records include participant and condition identifiers, scenario, fault onset tick, first medium/high detection tick, response tick, response time, participant action, correct action, raw controller mode, derived action label, severity at response, client timestamp, and correctness.

## VR Client Work Remaining

The future Unity/WebXR project should:

1. Connect to `/ws` and deserialize `schema/twin_state_v1.json`.
2. Display raw motor state, fault identity, severity band, and prediction horizon without changing the values.
3. Present operator actions exactly as `continue`, `derate`, and `shutdown`.
4. Send one `/respond` request per trial response with the client timestamp.
5. Keep the VR and 2D dashboard clients on the same state stream and trial identifiers.
6. Avoid using BaSyx as the real-time transport.
7. Record client-side render/input timestamps separately if reaction-time analysis needs sub-tick latency correction.

The Python server currently supports one active live session at a time. A later study runner should add participant scheduling, trial randomization across conditions, session authentication, and explicit session stop/reset handling.

## Streamlit Result Viewer

The existing Streamlit application is a batch-result viewer and launcher. It is not the VR client and should not become a second twin implementation.

Start it with:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui\app.py
```

It reads result CSV files, displays motor state and plots, launches batch commands, and provides downloads. The live WebSocket state path is owned by `server/live_server.py` and `schema/twin_state_v1.json`.

## Optional BaSyx Integration

BaSyx is an optional snapshot-based AAS integration for the Industry 5.0 deliverable. It is not the VR streaming transport.

Start the local services:

```powershell
docker compose -f docker\docker-compose.yml up -d
.\.venv\Scripts\python.exe scripts\seed_basyx.py
.\.venv\Scripts\python.exe experiments\basyx_smoke_test.py
```

Services are exposed on:

- AAS registry: `http://localhost:8080`
- AAS environment: `http://localhost:8081`
- Submodel registry: `http://localhost:8082`

The services use in-memory storage. Restarting Docker removes their state.

## Tests and Validation

Run all tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The current tests cover the constrained controller, oracle mapping, fault profiles, and trial logging. FMU tests require the regenerated FMU and the local `.venv` dependencies.

Useful checks:

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  server\live_server.py `
  server\twin_pipeline.py `
  server\state_schema.py `
  server\trial_logger.py `
  experiments\experiment_runner.py `
  simulation\fmu_runtime.py `
  twin\fault_injector.py
```

## Important Scientific and Engineering Caveats

- The motor model is reduced-order and calibrated, not a full physical motor simulation.
- The observer and predictor do not receive hidden fault parameters.
- The 100 C warning and 120 C critical values are model evaluation thresholds, not independently validated insulation limits.
- Voltage imbalance is explicitly a reduced-order electrical approximation. It exposes a scalar imbalance input, increased modeled loss, and a current-ripple indicator; it is not phase-resolved electrical simulation.
- Sensor drift is intentionally a negative-control scenario. The physical motor state should remain nominal while the temperature sensor becomes biased.
- BaSyx synchronization is REST snapshot synchronization and is too slow to be the VR real-time transport.
- The `shutdown` trial action is a human-study label for the controller's `EMERGENCY` state. It is not an automatic zero-load command.
- Do not claim hard real-time guarantees from the Python/FMU software loop. Measure actual client, network, and rendering latency for the VR study.

## Main Files

```text
models/MotorElectroThermalMechanicalFaultable.mo  OpenModelica plant model
MotorElectroThermalMechanicalFaultable.fmu        FMI runtime artifact
simulation/fmu_runtime.py                          FMI lifecycle and stepping
server/twin_pipeline.py                            shared twin/control pipeline
server/live_server.py                              FastAPI/WebSocket server
server/state_schema.py                             twin_state_v1 payload builder
schema/twin_state_v1.json                          client contract
twin/fault_injector.py                             batch/live fault profiles
server/trial_logger.py                             participant response logs
experiments/experiment_runner.py                   thin batch wrapper
twin/state_estimator.py                             thermal observer
twin/fault_detector.py                              persistent fault rules
twin/fault_severity.py                              normalized severity
twin/predictor.py                                   thermal forecasts
control/                                             three controllers
config/twin_config.yaml                             motor and VR trial settings
integration/basyx_bridge.py                         optional AAS REST bridge
analysis/                                            metrics and publication tools
ui/app.py                                            Streamlit batch viewer
tests/                                               automated tests
```
