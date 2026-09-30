"""Interactive frontend for the Industry 5.0 Motor Digital Twin.

This module is intentionally a frontend only. It invokes the existing command
line experiment and comparison modules and visualizes their generated files;
it contains no controller, FMU, or analysis implementation logic.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "results"
DEFAULT_FMU = PROJECT_ROOT / "MotorElectroThermalMechanicalFaultable.fmu"
SCENARIOS = ["healthy", "sensor_bias", "cooling", "unbalance", "combined"]
CONTROLLERS = ["baseline", "adaptive", "constrained"]

st.set_page_config(page_title="Motor Digital Twin | Industry 5.0", page_icon="⚙️", layout="wide")


def inject_style() -> None:
    st.markdown("""<style>
    .stApp {background:radial-gradient(circle at 20% 0%,#18365e 0,#08111f 42%,#050a12 100%);color:#eaf3ff}
    [data-testid="stSidebar"] {background:linear-gradient(180deg,#102846,#091524)}
    .hero{padding:1.6rem 2rem;border:1px solid #31567e;border-radius:22px;background:linear-gradient(110deg,rgba(26,65,104,.88),rgba(15,28,49,.78));box-shadow:0 14px 44px rgba(0,0,0,.30);margin-bottom:1.2rem}
    .hero h1{margin:0;font-size:2.25rem;color:#f6fbff}.hero p{margin:.45rem 0 0;color:#b6d5ef;font-size:1.05rem}
    [data-testid="stMetric"]{background:rgba(9,23,40,.80);padding:.75rem;border:1px solid #294969;border-radius:14px}
    .legend{display:flex;gap:1rem;flex-wrap:wrap;color:#c8dbee;font-size:.88rem}.dot{display:inline-block;width:.7rem;height:.7rem;border-radius:50%;margin-right:.3rem}
    </style>""", unsafe_allow_html=True)


def temperature_color(value: float) -> str:
    if not np.isfinite(value): return "#65758a"
    if value >= 120: return "#a40016"
    if value >= 100: return "#f22f3d"
    if value >= 80: return "#ff9f1c"
    if value >= 60: return "#f8d34f"
    return "#20d7c7"


def vibration_color(value: float) -> str:
    if not np.isfinite(value): return "#65758a"
    if value >= 8: return "#f22f3d"
    if value >= 5: return "#ff9f1c"
    return "#7ddf64"


def motor_svg(row: pd.Series) -> str:
    winding = float(row.get("T_winding_C", np.nan)); frame = float(row.get("T_frame_C", np.nan))
    power = float(row.get("P_electrical_W", np.nan)); vibration = float(row.get("vibration_mm_s_out", np.nan)); speed = float(row.get("speed_rpm", np.nan))
    power_width = int(np.clip(6 + (0 if not np.isfinite(power) else power / 1200), 6, 22))
    rotation = 0 if not np.isfinite(speed) else int(speed % 360)
    return f'''<svg viewBox="0 0 740 370" width="100%" role="img" aria-label="Live motor state">
    <defs><linearGradient id="housing" x1="0" x2="1"><stop stop-color="#365b7a"/><stop offset=".5" stop-color="#18334f"/><stop offset="1" stop-color="#244763"/></linearGradient><filter id="glow"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <rect x="68" y="80" width="510" height="210" rx="45" fill="url(#housing)" stroke="#84b7d8" stroke-width="4"/><rect x="560" y="122" width="105" height="126" rx="20" fill="#294b67" stroke="#84b7d8" stroke-width="3"/><path d="M665 185 H720" stroke="#c5d7e8" stroke-width="16" stroke-linecap="round"/>
    <circle cx="323" cy="185" r="95" fill="#0b1827" stroke="{temperature_color(frame)}" stroke-width="10" filter="url(#glow)"/><circle cx="323" cy="185" r="69" fill="#172d40" stroke="{temperature_color(winding)}" stroke-width="24" filter="url(#glow)"/><circle cx="323" cy="185" r="42" fill="#8ca7ba" stroke="#dcecf6" stroke-width="4"/>
    <g transform="rotate({rotation} 323 185)" stroke="#eaf6ff" stroke-width="7" stroke-linecap="round"><path d="M323 145 V225"/><path d="M283 185 H363"/><path d="M295 157 L351 213"/><path d="M351 157 L295 213"/></g>
    <path d="M42 142 H92" stroke="#44b9ff" stroke-width="{power_width}" stroke-linecap="round" filter="url(#glow)"/><path d="M58 112 l-22 30 h19 l-16 30" fill="none" stroke="#8de9ff" stroke-width="5"/><g fill="{vibration_color(vibration)}" filter="url(#glow)"><circle cx="620" cy="100" r="8"/><circle cx="645" cy="84" r="5"/><circle cx="673" cy="102" r="6"/></g>
    <text x="110" y="325" fill="#b8d2e8" font-family="sans-serif" font-size="18">Electrical input</text><text x="263" y="350" fill="#b8d2e8" font-family="sans-serif" font-size="18">Winding &amp; rotor</text><text x="555" y="280" fill="#b8d2e8" font-family="sans-serif" font-size="18">Mechanical output</text></svg>'''


def result_files() -> list[Path]:
    return sorted(RESULTS_ROOT.rglob("*.csv"), key=lambda file: file.stat().st_mtime, reverse=True) if RESULTS_ROOT.exists() else []


def run_command(command: list[str], title: str) -> bool:
    st.code(" ".join(f'"{part}"' if " " in part else part for part in command), language="powershell")
    log, lines = st.empty(), []
    try:
        with st.spinner(f"{title}…"):
            process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line.rstrip()); log.code("\n".join(lines[-120:]), language="text")
            exit_code = process.wait()
    except OSError as error:
        st.error(f"Could not start the existing project command: {error}"); return False
    if exit_code == 0:
        st.success(f"{title} completed."); return True
    st.error(f"{title} failed (exit code {exit_code})."); return False


def download_buttons(dataframe: pd.DataFrame, stem: str) -> None:
    first, second = st.columns(2)
    first.download_button("Download CSV", dataframe.to_csv(index=False).encode("utf-8"), f"{stem}.csv", "text/csv", use_container_width=True)
    second.download_button("Download JSON", dataframe.to_json(orient="records", indent=2).encode("utf-8"), f"{stem}.json", "application/json", use_container_width=True)


def show_motor(dataframe: pd.DataFrame) -> None:
    if dataframe.empty or "time_s" not in dataframe.columns:
        st.info("Select a time-series result to inspect the motor state."); return
    index = st.slider("Simulation sample", 0, len(dataframe) - 1, len(dataframe) - 1)
    row = dataframe.iloc[index]
    left, right = st.columns([1.55, 1])
    with left:
        st.markdown(motor_svg(row), unsafe_allow_html=True)
        st.markdown("<div class='legend'><span><i class='dot' style='background:#20d7c7'></i>normal</span><span><i class='dot' style='background:#ff9f1c'></i>warning</span><span><i class='dot' style='background:#f22f3d'></i>critical</span></div>", unsafe_allow_html=True)
    with right:
        st.markdown("#### Live component state"); st.caption(f"Simulation time: {float(row['time_s']):.2f} s")
        for label, column, unit in [("Winding", "T_winding_C", "°C"), ("Frame", "T_frame_C", "°C"), ("Electrical power", "P_electrical_W", "W"), ("Speed", "speed_rpm", "rpm"), ("Vibration", "vibration_mm_s_out", "mm/s"), ("Load command", "u_load_torque_pu", "pu")]:
            value = row.get(column, np.nan); st.metric(label, "—" if pd.isna(value) else f"{float(value):,.2f} {unit}")


def main() -> None:
    inject_style()
    st.markdown("""<div class='hero'><h1>⚙️ Motor Digital Twin Studio</h1><p>Run the existing FMU experiments, inspect a living motor view, and compare controller or BaSyx results from one workspace.</p></div>""", unsafe_allow_html=True)
    if "selected_result" not in st.session_state: st.session_state.selected_result = None
    with st.sidebar:
        st.header("Experiment launcher")
        scenario = st.selectbox("Scenario", SCENARIOS, index=SCENARIOS.index("combined")); controller = st.selectbox("Controller", CONTROLLERS, index=CONTROLLERS.index("constrained"))
        stop = st.number_input("Stop time (s)", min_value=1.0, value=1800.0, step=60.0); step = st.number_input("Communication step (s)", min_value=0.01, value=0.5, step=0.1, format="%.2f"); fault = st.number_input("Fault injection time (s)", min_value=0.0, value=600.0, step=30.0)
        basyx = st.toggle("Enable BaSyx AAS synchronization"); host = st.text_input("AAS environment URL", "http://localhost:8081", disabled=not basyx); period = st.number_input("BaSyx synchronization period (s)", min_value=0.1, value=2.0, step=0.5, disabled=not basyx)
        output_name = f"{scenario}_{controller}_{stop:g}s{'_basyx' if basyx else ''}.csv"; st.caption(f"Output: results/{output_name}")
        if st.button("▶ Run experiment", type="primary", use_container_width=True):
            command = [sys.executable, "-m", "experiments.experiment_runner", "--fmu", str(DEFAULT_FMU), "--scenario", scenario, "--controller", controller, "--stop", str(stop), "--step", str(step), "--fault-time", str(fault), "--output", str(RESULTS_ROOT / output_name)]
            if basyx: command += ["--basyx", "--basyx-host", host, "--basyx-period", str(period)]
            if run_command(command, "Experiment"): st.session_state.selected_result = str(RESULTS_ROOT / output_name); st.rerun()
        st.divider(); st.header("Comparison launcher")
        input_dir = st.text_input("Results directory", str(RESULTS_ROOT)); compare_name = st.text_input("Comparison filename", "ui_comparison.csv")
        if st.button("▦ Compare evaluations", use_container_width=True):
            output = Path(input_dir) / compare_name
            if run_command([sys.executable, "-m", "analysis.compare_evaluation", "--input-dir", input_dir, "--output", str(output)], "Comparison"): st.session_state.selected_result = str(output); st.rerun()
    files = result_files(); mapping = {str(file.relative_to(PROJECT_ROOT)): file for file in files}
    label = st.selectbox("Open a result", list(mapping) or ["No CSV results found"]); path = mapping.get(label)
    if st.session_state.selected_result and Path(st.session_state.selected_result).exists(): path = Path(st.session_state.selected_result); st.session_state.selected_result = None
    if path is None: st.info("No result CSV is available yet. Use the launcher to create one."); return
    try: dataframe = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as error: st.error(f"Could not read {path.name}: {error}"); return
    st.markdown(f"### {path.name}")
    motor_tab, plot_tab, table_tab, download_tab = st.tabs(["Motor view", "Plots", "Structured results", "Downloads"])
    with motor_tab: show_motor(dataframe)
    with plot_tab:
        signals = [column for column in ["T_winding_C", "T_frame_C", "T_sensor_C", "speed_rpm", "P_electrical_W", "vibration_mm_s_out", "u_load_torque_pu"] if column in dataframe.columns]
        if "time_s" in dataframe and signals:
            chosen = st.multiselect("Signals", signals, default=signals[:3])
            if chosen: st.line_chart(dataframe.set_index("time_s")[chosen], height=420)
        else: st.info("This comparison table has no time-series signals to plot.")
    with table_tab:
        if {"scenario", "controller", "run_variant"}.issubset(dataframe.columns):
            columns = [column for column in ["scenario", "controller", "run_variant", "duration_s", "max_winding_temp_C", "time_above_100C_s", "electrical_energy_kWh", "basyx_end_to_end_loop_mean_latency_ms", "basyx_absolute_overhead_mean_ms"] if column in dataframe.columns]; st.dataframe(dataframe[columns], use_container_width=True, hide_index=True)
        else: st.dataframe(dataframe, use_container_width=True, hide_index=True, height=420)
    with download_tab: st.caption("Download the currently displayed table."); download_buttons(dataframe, path.stem)


if __name__ == "__main__":
    main()
