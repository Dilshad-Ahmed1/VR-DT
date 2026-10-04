# Cyber-Resilient Industrial Motor Control Foundation

This repository is the simulation and digital-twin foundation for the future
project **Cyber-Resilient Industrial Motor Control Using a Physics-Informed
Digital Twin**. It currently contains one 18.5 kW MSL squirrel-cage induction
motor plant, its FMU runtime, physical-fault experiments, the existing twin
and controllers, optional BaSyx AAS synchronization, and a live operator-study
server/UI.

Cyberattacks, Modbus monitoring, anomaly detection, cyber-versus-physical
diagnosis, risk scoring, command prevention, and ML are not implemented. Do not
interpret physical fault profiles as cyberattack scenarios.

## Motor and Scope

The sole plant is `MotorDigitalTwin.InductionMotorDigitalTwin18kW` in
`models/InductionMotorDigitalTwin18kW.mo`, built from the MSL 4.1.0
`IM_SquirrelCage` and the `IMC_withLosses` benchmark. MSL does not identify a
manufacturer or commercial motor product for this benchmark. Thermal RC
values, actuator slew, fault magnitudes, and 100/120 C controller limits are
model or study assumptions, not verified nameplate or insulation limits.

The model has rotational mechanics, but no radial vibration/unbalance model.
`bearing_wear_proxy` means added rotational friction only. Voltage imbalance is
a phase-voltage negative-sequence proxy, not a faulted winding model. See
[INDUCTION_MOTOR_REFERENCE.md](INDUCTION_MOTOR_REFERENCE.md) for parameter
provenance and limitations.

## Architecture

```text
Twin pipeline / controller
          |
          v
CommunicationInterface  <- future SecurityAwareCommunication wrapper
          |
SimulatedCommunication  <- future PLC / Modbus TCP transport
          |
PlantInterface
          |
FMUPlant                <- future HardwarePlant
          |
MSL induction FMU
```

The primary contracts are in `plant/interface.py`:

- `PlantState` carries observed motor/drive channels: timestamp, sensor
  temperature, frame temperature, speed, current, measured line voltage,
  electrical/shaft power, torque, frequency, power factor, and voltage
  imbalance. Unsupported vibration is absent (`None`). FMU winding truth,
  hidden fault inputs, and true thermal margin are not part of this interface.
- `ControlCommand` carries requested load, speed, and cooling, timestamp,
  command ID, source, and metadata.
- `PlantInterface` defines start, stop, reset, read, command, and step behavior.

`FMUPlant` wraps `simulation/fmu_runtime.py`. Batch experiments and the live
server both pass through `SimulatedCommunication`; physical fault injection
is owned by `faults/physical.py`. `plant/evaluation.py` is an explicitly
simulation-only channel for offline comparison metrics. It must never be
passed to the twin pipeline or future cybersecurity layer. The AAS snapshot
publishes diagnosed/estimated state, not injected scenario truth.

Core source locations:

- `models/`: sole Modelica induction plant and generated FMU.
- `plant/`, `communication/`: hardware-independent interfaces and adapters.
- `faults/`: physical-fault injection and retained diagnostic entry points.
- `server/twin_pipeline.py`: shared observer, detector/severity, predictor,
  and controller pipeline.
- `control/`, `twin/`: controller and existing estimator/diagnostic logic.
- `experiments/experiment_runner.py`: batch experiment orchestration.
- `server/live_server.py`, `server/state_schema.py`: live trial API and
  versioned state payload for the UI/client.
- `integration/`, `config/motor_aas_definition.json`: optional BaSyx AAS path.
- `analysis/`: experiment and AAS metrics/comparison.
- `ui/app.py`: batch viewer and live-study client.

## Setup

Use Python 3.12+ and the local environment. OpenModelica is needed only to
check or regenerate the FMU. Docker Desktop is needed only for BaSyx.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
\.venv\Scripts\python.exe -m pip install --upgrade pip
\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Confirm the selected interpreter if the machine has multiple Python installs:

```powershell
\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

The `.fmu` is generated and ignored by Git. A fresh clone must export it before
running integration tests or experiments.

## Export and Validate the Plant

Install OpenModelica 1.27.1 with Modelica Standard Library 4.1.0, open the
Modelica source in OMEdit, and run `Check -> Check Model`. Then export:

```powershell
\.venv\Scripts\python.exe scripts\export_induction_fmu.py --overwrite
```

If OpenModelica is installed outside the default location:

```powershell
\.venv\Scripts\python.exe scripts\export_induction_fmu.py `
  --omhome "C:/Program Files/OpenModelica1.27.1-64bit" `
  --overwrite
```

The exporter checks the model/MSL version, generates FMI 2.0 Co-Simulation,
and validates the exported variables. It writes
`models/InductionMotorDigitalTwin18kW.fmu`.

Run nominal validation against this same FMU:

```powershell
\.venv\Scripts\python.exe scripts\validate_induction_motor_nominal.py
```

The validator writes a timestamped CSV and JSON report below
`results/induction_motor_nominal/`. Its current acceptance result is based on
the explicit MSL nominal benchmark; it is not validation against an identified
physical motor.

For a short FMU/fault-injection smoke run:

```powershell
\.venv\Scripts\python.exe simulation\fmu_runtime.py `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --scenario voltage_imbalance `
  --stop 30 `
  --step 0.5 `
  --fault-time 5 `
  --output results\fmu_smoke.csv
```

The CVODE FMU is stepped internally at no more than 0.1 s per FMI call; the
controller communication cycle may remain 0.5 s.

## Run Experiments

Run one scenario/controller case:

```powershell
\.venv\Scripts\python.exe -m experiments.experiment_runner `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --plant-profile induction `
  --scenario cooling `
  --controller constrained `
  --stop 800 `
  --step 0.5 `
  --fault-time 350 `
  --output results\cooling_constrained.csv
```

Controllers are `baseline`, `adaptive`, and `constrained`. Supported physical
scenarios are `healthy`, `sensor_bias`, `sensor_drift`, `sensor_freeze`,
`cooling`, `cooling_failure`, `rth_degradation`, `overload`,
`sudden_overload`, `mechanical_friction`, `bearing_wear_proxy`,
`voltage_imbalance`, `supply_degradation`, `frequency_deviation`, and
`combined_supported`. Scenario parameters/profile durations are in
`config/twin_config.yaml`; injection behavior is in `faults/physical.py`.

Run the full scenario/controller campaign into a timestamped results folder:

```powershell
\.venv\Scripts\python.exe -m experiments.run_evaluation_suite `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --scenario all `
  --controller all `
  --stop 800 `
  --fault-time 350 `
  --step 0.5
```

Each campaign contains per-run CSV, metrics JSON, logs, `comparison.csv`, and
`campaign.json` under `results/induction_campaigns/`. Use `--with-basyx` only
when the Docker services are up. Add `--realtime` to an individual experiment
to pace it against wall time and record missed software deadlines; this is not
hard-real-time certification.

Run tests and compare existing result CSVs:

```powershell
\.venv\Scripts\python.exe -m pytest -q
\.venv\Scripts\python.exe analysis\compare_evaluation.py `
  --input-dir results `
  --output results\compare.csv
```

## Live Server and UI

Start the shared live study API:

```powershell
\.venv\Scripts\python.exe -m server.live_server --host 127.0.0.1 --port 8000
```

Start the Streamlit client in another terminal:

```powershell
\.venv\Scripts\python.exe -m streamlit run ui\app.py
```

The server exposes `/health`, `/trials/start`, `/respond`, and the WebSocket
`/ws`. Its current payload contract is `schema/twin_state_v1.json`. Batch and
live paths use the same `server/twin_pipeline.py`; client code must display the
shared state rather than reimplement estimation, diagnosis, prediction, or
control.

## Optional BaSyx AAS

```powershell
docker compose -f docker\docker-compose.yml up -d
\.venv\Scripts\python.exe scripts\seed_basyx.py
\.venv\Scripts\python.exe experiments\basyx_smoke_test.py
```

BaSyx is an optional REST snapshot integration, not the control/network
transport. AAS snapshots include estimated/detected fault state and omit
simulation-only injected severity.

## Cybersecurity Work Starts Here

The intended first cybersecurity component is a `SecurityAwareCommunication`
adapter implementing `CommunicationInterface` and wrapping the transport used
by the experiment/server. It can observe `PlantState` and `ControlCommand`
without changing the FMU, estimator, or controller interfaces. Later work may
add Modbus/device adapters, cyber-vs-physical diagnosis, what-if simulation,
risk policy, and `ALLOW`/`MODIFY`/`BLOCK`/`SAFE-STATE` decisions. None of those
algorithms or attack scenarios are present yet.

When hardware is available, implement `HardwarePlant` and a PLC/VFD
communication adapter that satisfy the existing contracts. Replace
`FMUPlant`/`SimulatedCommunication`; keep the shared plant state, commands,
twin pipeline, experiment metrics, and future security adapter.

## Current Limitations

- The benchmark is not an identified manufacturer's motor.
- Thermal RC parameters and several fault amplitudes are explicit assumptions.
- The 100 C and 120 C values are controller/evaluation thresholds, not verified
  thermal limits for a physical asset.
- No radial vibration or mechanical-unbalance behavior is modeled.
- BaSyx uses in-memory development services and is not a real-time channel.
- The server/UI live trial includes an operator response oracle; it is separate
  from plant state and is not a cybersecurity prevention engine.
- `results/` and FMU binaries are ignored by Git; retain external copies of
  reproducibility evidence when required.
