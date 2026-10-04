# Live Twin Server

`server/twin_pipeline.py` is the shared induction-motor estimator, detector/severity, predictor, controller, and trial-oracle implementation used by both batch and live modes. The live server defaults to `models/InductionMotorDigitalTwin18kW.fmu` and accepts only the MSL 18.5 kW induction FMU.

Run from the repository root after exporting the FMU:

```powershell
.\.venv\Scripts\python.exe -m server.live_server --host 127.0.0.1 --port 8000
```

- `GET /health` reports session state and schema version.
- `POST /trials/start` starts one session with scenario, controller, participant, condition, and duration.
- `WebSocket /ws` broadcasts the versioned payload defined by `schema/twin_state_v1.json`.
- `POST /respond` scores and persists a participant action.

Both Streamlit live-study view and future Unity/WebXR clients must consume this same payload. BaSyx is an optional AAS snapshot path and is not the real-time transport.

The payload separately exposes `controller.operating_mode` and `trial.action_label`. The `shutdown` label is an experimental reinterpretation of `EMERGENCY` for the human-subjects study. It is not a command issued by the automatic controller, which currently derates to its minimum configured load.

The induction model has no radial dynamics. `bearing_wear_proxy` is a friction-only proxy and does not create vibration telemetry.
