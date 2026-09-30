# Live Twin Server

`server/twin_pipeline.py` is the single estimator, detector, severity,
predictor, and controller implementation used by batch and live execution.
`server/state_schema.py` builds the versioned `twin_state_v1` payload shared by
VR and dashboard clients.

The payload deliberately exposes both `controller.operating_mode` and
`trial.action_label`. The `shutdown` action is an experimental
reinterpretation of the controller's `EMERGENCY` state for the human-subjects
study. It is not a command issued by the automatic controller, which currently
derates to its minimum configured load instead.

Run the live server with:

```powershell
python -m server.live_server --host 127.0.0.1 --port 8000
```

Clients connect to `ws://127.0.0.1:8000/ws`, start a trial with
`POST /trials/start`, and submit participant actions with `POST /respond`.