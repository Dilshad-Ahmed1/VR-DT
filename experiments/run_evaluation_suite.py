from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any

from experiments.experiment_runner import SCENARIOS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FMU = ROOT / "models" / "InductionMotorDigitalTwin18kW.fmu"
CONTROLLERS = ("baseline", "adaptive", "constrained")
METRICS = (
    "maximum_winding_temperature_C",
    "time_above_critical_s",
    "fault_detection_latency_s",
    "fault_severity_mae",
    "prediction_mae_30s_C",
    "prediction_mae_60s_C",
    "energy_total_kWh",
    "useful_work_total_kWh",
    "mean_load_command_pu",
    "mean_solver_step_time_ms",
    "real_time_factor",
)


def _run_case(
    *,
    fmu: Path,
    scenario: str,
    controller: str,
    stop_s: float,
    step_s: float,
    fault_time_s: float,
    output_dir: Path,
    basyx: bool,
    basyx_host: str,
    basyx_period_s: float,
) -> dict[str, Any]:
    name = f"{scenario}_{controller}"
    csv_path = output_dir / f"{name}.csv"
    command = [
        sys.executable,
        "-m",
        "experiments.experiment_runner",
        "--fmu",
        str(fmu),
        "--plant-profile",
        "induction",
        "--scenario",
        scenario,
        "--controller",
        controller,
        "--stop",
        str(stop_s),
        "--step",
        str(step_s),
        "--fault-time",
        str(fault_time_s),
        "--output",
        str(csv_path),
    ]
    if basyx:
        command.extend(
            ["--basyx", "--basyx-host", basyx_host, "--basyx-period", str(basyx_period_s)]
        )
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    log_path = output_dir / f"{name}.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    metrics_path = csv_path.with_name(f"{csv_path.stem}_metrics.json")
    metrics: dict[str, Any] = {}
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    return {
        "scenario": scenario,
        "controller": controller,
        "return_code": completed.returncode,
        "csv": str(csv_path),
        "log": str(log_path),
        "metrics": str(metrics_path),
        "results": metrics,
        "error": "" if completed.returncode == 0 else completed.stderr[-4000:],
    }


def _write_campaign(output_dir: Path, runs: list[dict[str, Any]]) -> None:
    (output_dir / "campaign.json").write_text(
        json.dumps(runs, indent=2, allow_nan=True),
        encoding="utf-8",
    )
    columns = ["scenario", "controller", "return_code", *METRICS]
    with (output_dir / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for run in runs:
            values = run.get("results", {})
            writer.writerow({
                "scenario": run["scenario"],
                "controller": run["controller"],
                "return_code": run["return_code"],
                **{name: values.get(name, "") for name in METRICS},
            })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a timestamped scenario/controller campaign for the CGVR induction Twin."
    )
    parser.add_argument("--fmu", type=Path, default=DEFAULT_FMU)
    parser.add_argument("--scenario", choices=["all", *sorted(SCENARIOS)], default="all")
    parser.add_argument("--controller", choices=["all", *CONTROLLERS], default="all")
    parser.add_argument("--stop", type=float, default=800.0)
    parser.add_argument("--step", type=float, default=0.5)
    parser.add_argument("--fault-time", type=float, default=350.0)
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "induction_campaigns")
    parser.add_argument("--with-basyx", action="store_true")
    parser.add_argument("--basyx-host", default="http://localhost:8081")
    parser.add_argument("--basyx-period", type=float, default=10.0)
    args = parser.parse_args()

    fmu = args.fmu.resolve()
    if not fmu.is_file():
        parser.error(f"Induction FMU not found: {fmu}; export it first.")
    if args.stop <= args.fault_time or args.fault_time < 0 or args.step <= 0:
        parser.error("Require stop > fault-time >= 0 and step > 0.")

    scenarios = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    controllers = CONTROLLERS if args.controller == "all" else [args.controller]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output_root / stamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    runs: list[dict[str, Any]] = []
    total = len(scenarios) * len(controllers)
    for index, (scenario, controller) in enumerate(
        ((scenario, controller) for scenario in scenarios for controller in controllers),
        start=1,
    ):
        aas_enabled = args.with_basyx and scenario == "combined_supported" and controller == "constrained"
        print(f"[{index}/{total}] {scenario}/{controller}" + (" + BaSyx" if aas_enabled else ""), flush=True)
        runs.append(_run_case(
            fmu=fmu,
            scenario=scenario,
            controller=controller,
            stop_s=args.stop,
            step_s=args.step,
            fault_time_s=args.fault_time,
            output_dir=output_dir,
            basyx=aas_enabled,
            basyx_host=args.basyx_host,
            basyx_period_s=args.basyx_period,
        ))
        _write_campaign(output_dir, runs)
    failed = sum(run["return_code"] != 0 for run in runs)
    print(f"Campaign: {output_dir}")
    print(f"Completed: {len(runs) - failed}/{len(runs)}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
