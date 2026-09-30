from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


TRIAL_COLUMNS = [
    "participant_id",
    "condition",
    "trial_id",
    "scenario",
    "fault_onset_tick",
    "detection_tick",
    "response_tick",
    "response_time_s",
    "client_timestamp",
    "participant_action",
    "correct_action",
    "controller_operating_mode",
    "trial_action_label",
    "severity_at_response",
    "severity_band_at_response",
    "correct",
]


class TrialLogger:
    """Collect and persist human-response records beside experiment results."""

    def __init__(self, output_dir: str | Path = "results/trials") -> None:
        self.output_dir = Path(output_dir)
        self.rows: list[dict[str, Any]] = []

    def record_response(
        self,
        *,
        participant_id: str,
        condition: str,
        trial_id: str,
        scenario: str,
        fault_onset_tick: int,
        detection_tick: int | None,
        response_tick: int,
        step_s: float,
        client_timestamp: float,
        participant_action: str,
        correct_action: str,
        controller_operating_mode: str,
        trial_action_label: str,
        severity_at_response: float,
        severity_band_at_response: str,
    ) -> dict[str, Any]:
        if condition not in {"dashboard", "vr"}:
            raise ValueError("condition must be 'dashboard' or 'vr'")
        if participant_action not in {"continue", "derate", "shutdown"}:
            raise ValueError("unsupported participant action")

        row = {
            "participant_id": participant_id,
            "condition": condition,
            "trial_id": trial_id,
            "scenario": scenario,
            "fault_onset_tick": int(fault_onset_tick),
            "detection_tick": detection_tick,
            "response_tick": int(response_tick),
            "response_time_s": max(0.0, (response_tick - fault_onset_tick) * step_s),
            "client_timestamp": float(client_timestamp),
            "participant_action": participant_action,
            "correct_action": correct_action,
            "controller_operating_mode": controller_operating_mode,
            "trial_action_label": trial_action_label,
            "severity_at_response": float(severity_at_response),
            "severity_band_at_response": severity_band_at_response,
            "correct": bool(participant_action == correct_action),
        }
        self.rows.append(row)
        return row

    def save(self, stem: str = "trial_responses") -> tuple[Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        normalized = [
            {column: row.get(column) for column in TRIAL_COLUMNS}
            for row in self.rows
        ]
        csv_path = self.output_dir / f"{stem}.csv"
        json_path = self.output_dir / f"{stem}.json"
        pd.DataFrame(normalized, columns=TRIAL_COLUMNS).to_csv(csv_path, index=False)
        json_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
        return csv_path, json_path