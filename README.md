# CGVR Induction Motor Digital Twin

This repository is the Python/Modelica foundation for a Computer Graphics and VR course project. It runs one 18.5 kW MSL squirrel-cage induction-motor digital twin, provides batch and live execution, records operator responses, and supports the future Unity or WebXR client.

The human-subjects study compares a conventional 2D dashboard with an immersive VR interface. Both interfaces must receive the same live state from the Python server; neither client should reproduce the estimator, fault detector, severity calculation, predictor, or controller.

## Model Choice and Scope

The sole runtime plant is `MotorDigitalTwin.InductionMotorDigitalTwin18kW`, implemented in [models/InductionMotorDigitalTwin18kW.mo](models/InductionMotorDigitalTwin18kW.mo). It composes the Modelica Standard Library 4.1.0 `IM_SquirrelCage` machine using the MSL `IMC_withLosses` 18.5 kW, 400 V, 50 Hz benchmark data. MSL does not identify a manufacturer or commercial product for this benchmark.

The thermal network, fault amplitudes, diagnostic thresholds, load slew, and the inherited 100/120 C controller envelope include explicit modeling assumptions. They are not manufacturer ratings. See [INDUCTION_MOTOR_REFERENCE.md](INDUCTION_MOTOR_REFERENCE.md) for parameter provenance and limitations.

There is no second 5.5 kW WEG model or fallback runtime profile. The induction plant has rotational mechanics but no radial dynamics; it does not simulate mechanical unbalance or vibration. `bearing_wear_proxy` injects increased mechanical friction only and must not be presented as a radial bearing/vibration model. Voltage imbalance uses a negative-sequence phase-voltage proxy and the FMU's filtered phase-RMS diagnostic; it is not a detailed faulted-machine winding model.

## Architecture

```text
models/InductionMotorDigitalTwin18kW.mo
          | OpenModelica FMI 2.0 Co-Simulation export
          v
models/InductionMotorDigitalTwin18kW.fmu
          |
          v
simulation/fmu_runtime.py
          |
          v
server/twin_pipeline.py  (single shared runtime pipeline)
  measurement normalization -> observer -> detector/severity
  -> thermal predictor -> controller -> trial action oracle
          |
          +--> experiments/experiment_runner.py -> batch CSV + metrics
          +--> server/live_server.py -> HTTP + WebSocket state stream
          +--> server/trial_logger.py -> participant response CSV/JSON
          +--> integration/basyx_bridge.py -> optional AAS snapshot sync
```

`server/twin_pipeline.py` is the shared implementation for batch and live execution. It removes hidden MSL state and component-loss truth before the estimator/controller inputs are formed. `server/state_schema.py` builds the versioned `twin_state_v1` payload used by the live WebSocket and Streamlit live-study view.

## Setup After Clone

Prerequisites:

- Windows PowerShell (commands below use Windows paths)
- Python 3.12 or newer; this project has been tested with Python 3.13
- OpenModelica 1.27.1 with Modelica Standard Library 4.1.0 when regenerating the FMU
- Docker Desktop only if using optional BaSyx services
- Unity or WebXR only for the separate VR client project

Create an environment and install dependencies from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If activation is blocked or the machine has multiple Python installations, call the environment executable explicitly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

The `.fmu` is a generated build artifact and may not be included in a clone. Build it before running the experiment, test, UI, or live server commands below.

## Build and Validate the FMU

Open `models/InductionMotorDigitalTwin18kW.mo` in OMEdit and run `Check -> Check Model`. Export the FMI 2.0 Co-Simulation FMU:

```powershell
.\.venv\Scripts\python.exe scripts\export_induction_fmu.py --overwrite
```

If OpenModelica is not on the expected install path, supply it explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\export_induction_fmu.py `
  --omhome "C:/Program Files/OpenModelica1.27.1-64bit" `
  --overwrite
```

The exporter checks the Modelica class and MSL 4.1.0, uses CVODE, exports FMI 2.0 Co-Simulation, verifies the interface, and writes `models/InductionMotorDigitalTwin18kW.fmu`.

Run the nominal FMU validation and then automated tests:

```powershell
.\.venv\Scripts\python.exe scripts\validate_induction_motor_nominal.py
.\.venv\Scripts\python.exe -m pytest -q
```

The nominal validator steps the same FMU used by the Twin and writes a new timestamped validation directory under `results/induction_motor_nominal/`. It does not build or simulate a parallel plant model.

For a short faulted FMU smoke test:

```powershell
.\.venv\Scripts\python.exe simulation\fmu_runtime.py `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --scenario voltage_imbalance `
  --stop 30 `
  --step 0.5 `
  --fault-time 5 `
  --output results\fmu_smoke.csv
```

The induction FMU has been observed to fail with large OpenModelica CVODE communication steps during transients. `FMURuntime.step()` subdivides Twin cycles into at-most-0.1-second FMI steps while holding commands fixed; the controller cycle may remain 0.5 seconds.

## Batch Experiments

Run one batch experiment through the shared pipeline:

```powershell
.\.venv\Scripts\python.exe -m experiments.experiment_runner `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --plant-profile induction `
  --scenario cooling `
  --controller constrained `
  --stop 800 `
  --step 0.5 `
  --fault-time 350 `
  --output results\cooling_constrained.csv
```

Controllers are `baseline`, `adaptive`, and `constrained`. Supported induction scenarios are:

- `healthy`
- `sensor_bias` and `sensor_drift` (additive temperature sensor bias; drift uses a ramp)
- `sensor_freeze`
- `cooling` and `cooling_failure` (accelerating cooling-effectiveness degradation)
- `rth_degradation`
- `overload` and `sudden_overload` (the latter is a commanded load increase through the FMU load input)
- `mechanical_friction`
- `bearing_wear_proxy` (friction-only proxy; no radial vibration channel exists)
- `voltage_imbalance`
- `supply_degradation`
- `frequency_deviation`
- `combined_supported`

Faults are driven by [twin/fault_injector.py](twin/fault_injector.py) in both batch and live modes. The CLI `--fault-time` selects a reproducible onset time; each fault then follows its configured step, ramp, or accelerating profile. Profiles are configured in `config/twin_config.yaml`.

The runner writes time-aligned FMU observations, estimated state, detected faults, severity, forecasts, raw controller mode, trial action label, solver/controller timings, and evaluation metrics. MSL component losses and winding state are retained only as named simulation truth for evaluation; they are not sent to the observer or controller.

Run a timestamped matrix over all scenarios/controllers:

```powershell
.\.venv\Scripts\python.exe -m experiments.run_evaluation_suite `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --scenario all `
  --controller all `
  --stop 800 `
  --fault-time 350 `
  --step 0.5
```

Each campaign receives a new UTC directory under `results/induction_campaigns/` with per-run CSV, metrics JSON, logs, and aggregate `comparison.csv`/`campaign.json`. Add `--with-basyx` only when the BaSyx services are running; the campaign enables it for the combined constrained case.

## Live Server

Start the server from the repository root:

```powershell
.\.venv\Scripts\python.exe -m server.live_server --host 127.0.0.1 --port 8000
```

The server defaults to the induction FMU, runs one live session at a time, and emits a WebSocket state every Twin tick. BaSyx is not the real-time transport.

Check server status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Start a trial. Fault onset is randomized within the quiet window from config and the returned onset tick is recorded for analysis:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/trials/start `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{
    "participant_id": "p001",
    "condition": "vr",
    "trial_id": "p001-vr-001",
    "scenario": "cooling_failure",
    "controller": "constrained",
    "fmu": "models/InductionMotorDigitalTwin18kW.fmu",
    "step_s": 0.5,
    "stop_s": 900
  }'
```

The conventional dashboard condition uses `"condition": "dashboard"`; VR uses `"condition": "vr"`.

Connect clients to the shared state endpoint:

```text
ws://127.0.0.1:8000/ws
```

The contract is [schema/twin_state_v1.json](schema/twin_state_v1.json). It carries raw observable FMU telemetry, estimated thermal state, fault flags, severity and band, 30/60-second forecasts, controller identity/operating mode/commands, trial action, tick, and monotonic timestamp. Unity/WebXR and the 2D study dashboard must display this state without separately recalculating it.

Submit a response:

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
    "client_timestamp": 1791111111.123
  }'
```

Allowed actions are `continue`, `derate`, and `shutdown`. Responses are scored against the controller state/action oracle and saved as CSV/JSON under `results/trials/`. The record includes participant, condition, scenario, onset/detection/response ticks, response time, response action, correct action, raw controller mode, trial action label, severity, correctness, and client timestamp.

### Trial Oracle Semantics

The raw controller mode and human-study action label are distinct fields. `NORMAL` maps to `continue`; intervention modes map to `derate`; `EMERGENCY` maps to `shutdown` for the study. That `shutdown` label is an experimental reinterpretation of `EMERGENCY`; the automatic controller itself does not issue shutdown and currently limits load to its configured minimum.

The constrained controller's emergency condition is based on the maximum of estimated winding temperature and the 30/60-second predictions reaching 120 C. Its buffered `EMERGENCY_DERATING` state begins at 115 C with the current 5 C safety buffer. Medium severity also includes the existing controller intervention/fault-aware condition, including severity at or above 0.50 where relevant.

## Streamlit Dashboard

Start the 2D application:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui\app.py
```

The sidebar offers two distinct modes:

- **Batch results** launches induction experiments and views CSV outputs.
- **Live operator study** starts a server trial, reads the shared `/ws` payload, displays it, and submits participant responses to `/respond`.

The live page is a client of the canonical schema, not a second twin implementation. For a controlled study, the VR client should use the same trial ID, server, state payload, and response endpoint.

## Optional BaSyx AAS

BaSyx remains an optional snapshot integration for the Industry 5.0/AAS deliverable. It is intentionally not used for VR real-time streaming. Docker services are in `docker/docker-compose.yml` and use in-memory persistence.

```powershell
docker compose -f docker\docker-compose.yml up -d
.\.venv\Scripts\python.exe scripts\seed_basyx.py
.\.venv\Scripts\python.exe experiments\basyx_smoke_test.py
```

Endpoints:

- AAS registry: `http://localhost:8080`
- AAS environment: `http://localhost:8081`
- Submodel registry: `http://localhost:8082`

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover controllers, the shared trial oracle/logger, induction FMU inputs and outputs, estimator/predictor/controller compatibility, AAS snapshots, and nominal benchmark evaluation. FMU integration tests skip when the generated FMU is absent; export it first for full validation.

## Where to Continue VR Work

- Add the Unity/WebXR client in its own project; connect to `/ws` and parse `schema/twin_state_v1.json`.
- Keep the 2D and VR conditions on identical server state and trial IDs.
- Send exactly one action response per participant response to `/respond` and retain client input/render timestamps in client logs for latency analysis.
- Do not route real-time visual state through BaSyx.
- Add participant scheduling, balanced condition order, trial reset/stop lifecycle, authentication, and study data governance before a human-subject deployment.
- Measure client/network/render latency on the actual study hardware; the Python/FMU loop is not a hard real-time system.

## Limitations to Preserve

- MSL benchmark is 18.5 kW, not an identified commercial product; the parameter source and assumptions are in `INDUCTION_MOTOR_REFERENCE.md`.
- Thermal RC values and fault amplitudes are modeling/study assumptions.
- 100 C and 120 C are inherited controller evaluation thresholds, not verified insulation limits for the benchmark motor.
- The observer and predictor use observable measurements and nominal parameters; hidden FMU component-loss truth is evaluation-only.
- Mechanical radial vibration/unbalance is not represented. Do not display the zero vibration output as a measured physical vibration value.
- Voltage imbalance is a phase-voltage negative-sequence proxy, not a phase-resolved fault model.
- `bearing_wear_proxy` means added rotational friction only; it does not simulate bearing geometry, radial vibration, or bearing temperature.
- BaSyx is REST snapshot sync with in-memory services; it is not a persistence layer or real-time transport.
- The experimental `shutdown` answer is an operator-study action label, not an automatic controller command.

## Main Files

```text
models/InductionMotorDigitalTwin18kW.mo  sole Modelica plant and Twin
models/InductionMotorDigitalTwin18kW.fmu generated FMI runtime artifact
scripts/export_induction_fmu.py          Modelica check and FMU export
scripts/validate_induction_motor_nominal.py nominal validation using the Twin FMU
simulation/fmu_runtime.py                typed FMI I/O, lifecycle, and stepping
twin/fault_injector.py                   shared batch/live induction fault profiles
server/twin_pipeline.py                  shared induction estimator/control pipeline
server/live_server.py                    FastAPI REST and WebSocket trial server
server/state_schema.py                   state payload builder
server/trial_logger.py                   participant response CSV/JSON
schema/twin_state_v1.json                dashboard and VR client schema
experiments/experiment_runner.py         batch experiment and AAS snapshot orchestration
experiments/run_evaluation_suite.py      induction scenario/controller campaign
control/                                  baseline, adaptive, constrained controllers
twin/                                     observer, detector, severity, prediction
config/twin_config.yaml                  active motor, safety, simulation, trial, AAS settings
config/motor_aas_definition.json          six induction-motor AAS submodels
integration/basyx_bridge.py              optional BaSyx REST bridge
analysis/                                 experiment and AAS metrics/comparison
ui/app.py                                 batch viewer and live dashboard client
tests/                                    controller, FMU, pipeline, AAS, and nominal tests
```
