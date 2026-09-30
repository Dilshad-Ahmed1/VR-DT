from __future__ import annotations

from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
OUT = ROOT / 'docs' / 'publication_tables.md'

compare = pd.read_csv(RESULTS / 'compare.csv')

# Prefer the current combined BaSyx row with final updated timing values.
basyx = pd.read_csv(RESULTS / 'compare_basyx_metrics.csv')

motor_params = [
    ('Rated power', '5.5 kW'),
    ('Rated voltage', '400 V'),
    ('Rated current', '10.9 A'),
    ('Frequency', '50 Hz'),
    ('Rated speed', '1460 rpm'),
    ('Rated speed (rad/s)', '152.89 rad/s'),
    ('Efficiency', '89.7%'),
    ('Power factor', '0.81'),
    ('Rotor inertia', '0.0491 kg m^2'),
    ('Thermal safety threshold', '120 C'),
    ('Model thermal state bands', 'normal < 100 C, elevated 100–120 C, critical >= 120 C'),
]

fault_scenarios = [
    ('healthy', 'No active degradation', 'baseline operation'),
    ('cooling', 'Cooling effectiveness degradation, f_cooling_eff = 0.40', 'Thermal transfer reduction'),
    ('sensor_bias', 'Sensor bias = +10 C', 'Measurement corruption'),
    ('sensor_freeze', 'Sensor freeze input active', 'Stale measurement'),
    ('rth_degradation', 'Thermal-resistance degradation factor = 2.0', 'Frame-to-ambient resistance increase'),
    ('unbalance', 'Mechanical unbalance = 0.75', 'Vibration/severity increase'),
    ('combined', 'Sensor bias + cooling degradation + unbalance', 'Compound degradation conditions'),
]

controllers = [
    ('baseline', 'Reference operating policy; no fault-aware supervisory adaptation'),
    ('adaptive', 'Condition-aware adjustment based on estimated severity and thermal risk'),
    ('constrained', 'Thermal-risk-aware supervisory controller with cooling escalation and progressive derating; final paper controller'),
]

main_rows = []
for scenario in ['healthy', 'cooling', 'sensor_bias', 'sensor_freeze', 'rth_degradation', 'unbalance', 'combined']:
    subset = compare[(compare['scenario'] == scenario) & (compare['controller'] == 'constrained')]
    if subset.empty:
        continue
    r = subset.iloc[0]
    main_rows.append(
        [scenario, f"{r['max_winding_temp_C']:.3f}", f"{r['time_above_100C_s']:.2f}", f"{r['time_above_120C_s']:.2f}",
         f"{r['minimum_controller_safety_margin_C']:.3f}", f"{r['mean_derating_fraction']:.4f}", f"{r['energy_per_useful_work']:.4f}"]
    )

predict_rows = []
for scenario in ['healthy', 'cooling', 'sensor_bias', 'sensor_freeze', 'rth_degradation', 'unbalance', 'combined']:
    subset = compare[(compare['scenario'] == scenario) & (compare['controller'] == 'constrained')]
    if subset.empty:
        continue
    r = subset.iloc[0]
    predict_rows.append(
        [scenario, f"{r['prediction_30s_mae_C']:.3f}", f"{r['prediction_60s_mae_C']:.3f}"]
    )

basyx_rows = []
for _, row in basyx.iterrows():
    basyx_rows.append([
        row['scenario'],
        row['controller'],
        f"{row['basyx_update_success_rate_percent']:.1f}",
        f"{row['basyx_read_success_rate_percent']:.1f}",
        f"{row['basyx_end_to_end_loop_mean_latency_ms']:.2f}",
        f"{row['basyx_controller_only_mean_latency_ms']:.3f}",
        f"{row['basyx_write_latency_mean_ms']:.2f}",
        f"{row['basyx_read_latency_mean_ms']:.2f}",
        f"{row['basyx_sync_winding_temperature_C_mae']:.3e}",
        f"{row['basyx_sync_frame_temperature_C_mae']:.3e}",
    ])

lines = []
lines.append('# Publication Tables')
lines.append('')
lines.append('## Motor parameters')
lines.append('')
lines.append('| Parameter | Value |')
lines.append('|---|---|')
for param, value in motor_params:
    lines.append(f'| {param} | {value} |')
lines.append('')

lines.append('## Fault scenarios')
lines.append('')
lines.append('| Scenario | Fault condition | Interpretation |')
lines.append('|---|---|---|')
for scenario, condition, interpretation in fault_scenarios:
    lines.append(f'| {scenario} | {condition} | {interpretation} |')
lines.append('')

lines.append('## Controller definitions')
lines.append('')
lines.append('| Controller | Definition |')
lines.append('|---|---|')
for name, description in controllers:
    lines.append(f'| {name} | {description} |')
lines.append('')

lines.append('## Main experimental results (constrained controller)')
lines.append('')
lines.append('| Scenario | Max winding temp (C) | Time >100 C (s) | Time >120 C (s) | Min safety margin (C) | Mean derating | Energy / useful work |')
lines.append('|---|---:|---:|---:|---:|---:|---:|')
for row in main_rows:
    lines.append('| ' + ' | '.join(row) + ' |')
lines.append('')

lines.append('## Prediction results (constrained controller)')
lines.append('')
lines.append('| Scenario | 30 s prediction MAE (C) | 60 s prediction MAE (C) |')
lines.append('|---|---:|---:|')
for row in predict_rows:
    lines.append('| ' + ' | '.join(row) + ' |')
lines.append('')

lines.append('## BaSyx / AAS metrics')
lines.append('')
lines.append('| Scenario | Controller | Update success (%) | Read success (%) | End-to-end latency mean (ms) | Controller-only latency mean (ms) | Write latency mean (ms) | Read latency mean (ms) | Sync winding MAE (C) | Sync frame MAE (C) |')
lines.append('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|')
for row in basyx_rows:
    lines.append('| ' + ' | '.join(row) + ' |')
lines.append('')

OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f'Wrote publication tables to {OUT}')
