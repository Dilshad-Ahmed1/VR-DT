# Cybersecurity-Ready Motor Digital Twin Architecture

This repository currently implements a simulation foundation for a future
cyber-resilient industrial motor control project. The only plant is the 18.5
kW MSL 4.1.0 squirrel-cage induction benchmark. Attack logic, network
monitoring, anomaly response, risk scoring, ML, and hardware connectivity are
intentionally not implemented.

## Runtime boundary

```text
Controller / digital twin
          |
          v
CommunicationInterface
          |
SimulatedCommunication       future industrial transport
          |                   (PLC / Modbus TCP / VFD)
          v
      PlantInterface
          |
      FMUPlant                future HardwarePlant
          |                   (real sensors and drive)
          v
OpenModelica FMI 2.0 FMU
```

`plant.interface.PlantInterface` is the application-facing plant contract.
Controllers and future security code should use `PlantState` and
`ControlCommand`, not FMI variables or hardware-specific APIs.

`PlantState` contains observable motor/drive channels: timestamp, speed,
sensor and frame temperatures, current, line voltage, power, torque, frequency,
power factor, and voltage imbalance. The current motor has no radial vibration
model, so vibration is unavailable rather than reported as measured zero. The
contract deliberately omits hidden FMU fault inputs, true winding temperature,
and true thermal margin.

`ControlCommand` contains timestamp, speed/load/cooling requests, command ID,
source metadata, and optional metadata. The plant adapter translates it into
FMU inputs or, later, device-protocol values.

## Current implementation

- `plant/simulated/fmu_plant.py` owns the FMU-backed plant adapter.
- `simulation/fmu_runtime.py` remains the low-level FMI lifecycle wrapper.
- `communication/simulated.py` provides the current in-process transport.
- `plant/hardware/interface.py` is the explicit future hardware boundary and
  does not pretend that hardware exists.
- `faults/physical.py` owns induction physical degradation profiles and FMU
  fault injection. These profiles are not cybersecurity attacks.
- `estimation/thermal_state.py` exposes the retained model-based observer.
- `prediction/thermal.py` exposes the retained thermal predictor.
- `faults/diagnostics.py` exposes the retained physical diagnostic logic.
- `control/` retains the baseline, adaptive, and constrained controllers.
- `experiments/experiment_runner.py` and `server/live_server.py` both run
  through `SimulatedCommunication -> FMUPlant -> FMURuntime`.

The FMU adapter has a simulation-only `read_simulation_evaluation()` method.
This is intentionally outside `PlantInterface` and is used only for offline
metrics and result files. It must not be passed to controllers, estimators,
diagnostics, the live state schema, AAS snapshots, or future cybersecurity
logic.

## Future cybersecurity insertion point

The future security layer should be a `SecurityAwareCommunication` adapter
that wraps the existing `CommunicationInterface`. It can observe or validate
`PlantState` and `ControlCommand`, compare measurements against the digital
twin, and eventually decide whether a command is allowed, modified, blocked,
or replaced with a safe-state command. The plant model and controller should
not need to know whether those decisions came from a security layer.

The intended future flow is:

```text
PlantState -> communication/security boundary -> controller/twin
Controller command -> security decision -> communication boundary -> plant
```

Attack simulation, network protocol implementation, anomaly detection, risk
assessment, and prevention are deliberately deferred.

## Replacing simulation with hardware

When the motor, VFD, PLC, and sensors become available, implement the concrete
`HardwarePlant` and PLC/VFD `CommunicationInterface` adapter. Replace
`FMUPlant` and `SimulatedCommunication`; the existing controllers, estimator,
predictor, diagnostics, experiment coordination, and future security adapter
should continue to use the same `PlantState` and `ControlCommand` contracts.