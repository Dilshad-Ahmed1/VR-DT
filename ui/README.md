# Motor Digital Twin Studio

This standalone Streamlit frontend does not modify or duplicate the motor controller, FMU, experiment runner, or evaluation logic. It runs the existing commands and visualizes their CSV/JSON results.

Install Streamlit once from the project root:

```powershell
.venv\Scripts\python -m pip install streamlit
```

Start the frontend:

```powershell
.venv\Scripts\python -m streamlit run ui\app.py
```

It exposes the existing experiment CLI settings (scenario, controller, duration, step, fault time, and optional BaSyx settings), runs the existing comparison command, provides an interactive motor visualization, time-series plots, comparison tables, and CSV/JSON downloads.
