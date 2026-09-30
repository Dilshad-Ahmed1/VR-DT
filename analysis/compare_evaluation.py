from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd


# Populated only for runs with a matching
# <scenario>_<controller>_basyx_basyx_summary.json report.
BASYX_METRIC_COLUMNS = [
    "basyx_summary_file",
    "basyx_update_attempts",
    "basyx_update_success_rate_percent",
    "basyx_update_failures",
    "basyx_update_timeouts",
    "basyx_read_attempts",
    "basyx_read_success_rate_percent",
    "basyx_read_failures",
    "basyx_read_timeouts",
    "basyx_controller_only_mean_latency_ms",
    "basyx_end_to_end_loop_mean_latency_ms",
    "basyx_absolute_overhead_mean_ms",
    "basyx_overhead_share_of_end_to_end_percent",
    "basyx_write_latency_mean_ms",
    "basyx_write_latency_p95_ms",
    "basyx_read_latency_mean_ms",
    "basyx_read_latency_p95_ms",
    "basyx_sync_winding_temperature_C_mae",
    "basyx_sync_frame_temperature_C_mae",
    "basyx_sync_thermal_margin_C_mae",
    "basyx_sync_fault_severity_mae",
    "basyx_sync_cooling_command_pu_mae",
    "basyx_sync_load_command_pu_mae",
]

CONTROLLERS = {"baseline", "adaptive", "constrained"}
_DURATION_TOKEN = re.compile(r"^(?P<seconds>\d+(?:\.\d+)?)s$")


def load_basyx_metrics(summary_path: Path) -> dict:
    """Load one BaSyx report and derive comparable, well-defined metrics.

    ``basyx_overhead_percent`` in legacy reports is deliberately not copied:
    it divides overhead by controller-only compute time, which is sub-millisecond
    and makes the ratio unsuitable as an interoperability KPI. The replacement
    is the BaSyx share of the measured end-to-end loop time:

        100 * (end_to_end_ms - controller_only_ms) / end_to_end_ms
    """
    with summary_path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)

    controller_ms = float(report.get("controller_only_mean_latency_ms", np.nan))
    end_to_end_ms = float(report.get("end_to_end_loop_mean_latency_ms", np.nan))
    overhead_ms = (
        max(0.0, end_to_end_ms - controller_ms)
        if np.isfinite(controller_ms) and np.isfinite(end_to_end_ms)
        else float("nan")
    )
    overhead_share_percent = (
        100.0 * overhead_ms / end_to_end_ms
        if np.isfinite(overhead_ms) and end_to_end_ms > 0.0
        else float("nan")
    )

    return {
        "basyx_summary_file": summary_path.name,
        "basyx_update_attempts": report.get("update_attempts", np.nan),
        "basyx_update_success_rate_percent": report.get(
            "update_success_rate_percent", np.nan
        ),
        "basyx_update_failures": report.get("update_failures", np.nan),
        "basyx_update_timeouts": report.get("update_timeouts", np.nan),
        "basyx_read_attempts": report.get("read_attempts", np.nan),
        "basyx_read_success_rate_percent": report.get(
            "read_success_rate_percent", np.nan
        ),
        "basyx_read_failures": report.get("read_failures", np.nan),
        "basyx_read_timeouts": report.get("read_timeouts", np.nan),
        "basyx_controller_only_mean_latency_ms": controller_ms,
        "basyx_end_to_end_loop_mean_latency_ms": end_to_end_ms,
        "basyx_absolute_overhead_mean_ms": overhead_ms,
        "basyx_overhead_share_of_end_to_end_percent": overhead_share_percent,
        "basyx_write_latency_mean_ms": report.get(
            "aas_write_latency_mean_ms", np.nan
        ),
        "basyx_write_latency_p95_ms": report.get(
            "aas_write_latency_p95_ms", np.nan
        ),
        "basyx_read_latency_mean_ms": report.get(
            "aas_read_latency_mean_ms", np.nan
        ),
        "basyx_read_latency_p95_ms": report.get(
            "aas_read_latency_p95_ms", np.nan
        ),
        "basyx_sync_winding_temperature_C_mae": report.get(
            "sync_winding_temperature_C_mae", np.nan
        ),
        "basyx_sync_frame_temperature_C_mae": report.get(
            "sync_frame_temperature_C_mae", np.nan
        ),
        "basyx_sync_thermal_margin_C_mae": report.get(
            "sync_thermal_margin_C_mae", np.nan
        ),
        "basyx_sync_fault_severity_mae": report.get(
            "sync_fault_severity_mae", np.nan
        ),
        "basyx_sync_cooling_command_pu_mae": report.get(
            "sync_cooling_command_pu_mae", np.nan
        ),
        "basyx_sync_load_command_pu_mae": report.get(
            "sync_load_command_pu_mae", np.nan
        ),
    }


def safe_max(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return float("nan")
    return float(df[column].max())


def safe_mean(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return float("nan")
    return float(df[column].mean())


def safe_integral(
    df: pd.DataFrame,
    column: str,
) -> float:

    if column not in df.columns:
        return float("nan")

    if "time_s" not in df.columns:
        return float("nan")

    x = df["time_s"].to_numpy(dtype=float)
    y = df[column].to_numpy(dtype=float)

    if len(x) < 2:
        return 0.0

    return float(np.trapezoid(y, x))


def compute_metrics(
    df: pd.DataFrame,
    scenario: str,
    controller: str,
) -> dict:

    metrics = {
        "scenario": scenario,
        "controller": controller,
        "duration_s": safe_max(df, "time_s"),
    }

    # ---------------------------------------------------------
    # Thermal safety
    # ---------------------------------------------------------

    metrics["max_winding_temp_C"] = safe_max(
        df,
        "T_winding_C",
    )

    metrics["max_sensor_temp_C"] = safe_max(
        df,
        "T_sensor_C",
    )

    if "T_winding_C" in df.columns:

        metrics["time_above_100C_s"] = float(
            np.trapezoid(
                (
                    df["T_winding_C"].to_numpy(dtype=float)
                    >= 100.0
                ).astype(float),
                df["time_s"].to_numpy(dtype=float),
            )
        )

        metrics["time_above_120C_s"] = float(
            np.trapezoid(
                (
                    df["T_winding_C"].to_numpy(dtype=float)
                    >= 120.0
                ).astype(float),
                df["time_s"].to_numpy(dtype=float),
            )
        )

    else:
        metrics["time_above_100C_s"] = float("nan")
        metrics["time_above_120C_s"] = float("nan")

    # ---------------------------------------------------------
    # Energy
    # ---------------------------------------------------------

    electrical_energy_ws = safe_integral(
        df,
        "P_electrical_W",
    )

    useful_work_ws = safe_integral(
        df,
        "P_shaft_W",
    )

    metrics["electrical_energy_kWh"] = (
        electrical_energy_ws / 3_600_000.0
    )

    metrics["useful_work_kWh"] = (
        useful_work_ws / 3_600_000.0
    )

    if useful_work_ws > 1e-9:

        metrics["energy_per_useful_work"] = (
            electrical_energy_ws / useful_work_ws
        )

    else:

        metrics["energy_per_useful_work"] = float("nan")

    # ---------------------------------------------------------
    # Performance
    # ---------------------------------------------------------

    if (
        "omega_rad_s" in df.columns
        and "speed_reference_rad_s" in df.columns
    ):

        error = (
            df["omega_rad_s"].to_numpy(dtype=float)
            - df["speed_reference_rad_s"].to_numpy(dtype=float)
        )

        metrics["speed_rmse_rad_s"] = float(
            np.sqrt(np.mean(error ** 2))
        )

        metrics["speed_mae_rad_s"] = float(
            np.mean(np.abs(error))
        )

    else:

        metrics["speed_rmse_rad_s"] = float("nan")
        metrics["speed_mae_rad_s"] = float("nan")

    metrics["mean_load_command_pu"] = safe_mean(
        df,
        "u_load_torque_pu",
    )

    # ---------------------------------------------------------
    # Fault detection
    # ---------------------------------------------------------

    if "fault_alarm" in df.columns:

        alarm = (
            df["fault_alarm"]
            .fillna(False)
            .astype(bool)
            .to_numpy()
        )

        metrics["alarm_active_fraction"] = float(
            np.mean(alarm)
        )

        transitions = np.sum(
            alarm[1:] & ~alarm[:-1]
        )

        metrics["alarm_events"] = int(transitions)

    else:

        metrics["alarm_active_fraction"] = float("nan")
        metrics["alarm_events"] = float("nan")

    # ---------------------------------------------------------
    # Estimation
    # ---------------------------------------------------------

    if (
        "estimated_winding_C" in df.columns
        and "T_winding_C" in df.columns
    ):

        estimation_error = (
            df["estimated_winding_C"].to_numpy(dtype=float)
            - df["T_winding_C"].to_numpy(dtype=float)
        )

        metrics["state_estimation_mae_C"] = float(
            np.mean(np.abs(estimation_error))
        )

        metrics["state_estimation_rmse_C"] = float(
            np.sqrt(np.mean(estimation_error ** 2))
        )

    else:

        metrics["state_estimation_mae_C"] = float("nan")
        metrics["state_estimation_rmse_C"] = float("nan")

    # ---------------------------------------------------------
    # Prediction
    # ---------------------------------------------------------

    for horizon in [30, 60]:

        pred_col = f"predicted_{horizon}s_C"

        if (
            pred_col in df.columns
            and "T_winding_C" in df.columns
        ):

            prediction_error = (
                df[pred_col].to_numpy(dtype=float)
                - df["T_winding_C"].to_numpy(dtype=float)
            )

            metrics[
                f"prediction_{horizon}s_mae_C"
            ] = float(
                np.mean(np.abs(prediction_error))
            )

        else:

            metrics[
                f"prediction_{horizon}s_mae_C"
            ] = float("nan")

    # ---------------------------------------------------------
    # Fault severity
    # ---------------------------------------------------------

    if "fault_severity_estimated" in df.columns:

        metrics["mean_fault_severity"] = safe_mean(
            df,
            "fault_severity_estimated",
        )

        metrics["max_fault_severity"] = safe_max(
            df,
            "fault_severity_estimated",
        )

    else:

        metrics["mean_fault_severity"] = float("nan")
        metrics["max_fault_severity"] = float("nan")

    # ---------------------------------------------------------
    # Computational performance
    # ---------------------------------------------------------

    if "solver_step_time_s" in df.columns:

        simulated_time = float(
            df["time_s"].iloc[-1]
        )

        wall_time = float(
            df["solver_step_time_s"].sum()
        )

        if wall_time > 0:

            metrics["solver_real_time_factor"] = (
                simulated_time / wall_time
            )

        else:

            metrics["solver_real_time_factor"] = float("nan")

    else:

        metrics["solver_real_time_factor"] = float("nan")

    # ---------------------------------------------------------
    # BaSyx synchronization
    # ---------------------------------------------------------

    if "basyx_sync_latency_s" in df.columns:

        metrics["mean_basyx_latency_ms"] = (
            safe_mean(
                df,
                "basyx_sync_latency_s",
            ) * 1000.0
        )

        metrics["max_basyx_latency_ms"] = (
            safe_max(
                df,
                "basyx_sync_latency_s",
            ) * 1000.0
        )

    else:

        metrics["mean_basyx_latency_ms"] = float("nan")
        metrics["max_basyx_latency_ms"] = float("nan")



        # ---------------------------------------------------------
        # Controller safety behavior
        # ---------------------------------------------------------

        if "controller_safety_margin_C" in df.columns:

            metrics["minimum_controller_safety_margin_C"] = (
                float(
                    df["controller_safety_margin_C"].min()
                )
            )

        else:

            metrics["minimum_controller_safety_margin_C"] = float(
                "nan"
            )

        if "controller_derating_fraction" in df.columns:

            metrics["mean_derating_fraction"] = (
                float(
                    df["controller_derating_fraction"].mean()
                )
            )

            metrics["max_derating_fraction"] = (
                float(
                    df["controller_derating_fraction"].max()
                )
            )

        else:

            metrics["mean_derating_fraction"] = float("nan")
            metrics["max_derating_fraction"] = float("nan")

        if "controller_operating_mode" in df.columns:

            emergency = (
                df["controller_operating_mode"]
                == "EMERGENCY_DERATING"
            )

            metrics["emergency_derating_fraction"] = (
                float(emergency.mean())
            )

        else:

            metrics["emergency_derating_fraction"] = float("nan")

    return metrics


def parse_filename(path: Path) -> tuple[str | None, str | None, str | None, float]:
    """Parse standard, BaSyx, and controller-only result filenames.

    Accepted examples (duration is optional):
    - combined_constrained_1800s.csv
    - combined_constrained_basyx.csv
    - combined_constrained_controller_only.csv
    - sensor_bias_adaptive_600s_basyx.csv
    - healthy_constrained_1800s.csv
    """
    stem = path.stem

    for controller in sorted(CONTROLLERS, key=len, reverse=True):
        marker = f"_{controller}_"
        if marker not in stem:
            continue

        prefix, suffix = stem.split(marker, 1)
        if not prefix:
            continue

        tail = suffix.split("_")
        run_variant = "standard"

        if tail[-2:] == ["controller", "only"]:
            run_variant = "controller_only"
            tail = tail[:-2]
        elif tail[-1:] == ["basyx"]:
            run_variant = "basyx"
            tail = tail[:-1]

        declared_duration_s = float("nan")
        if tail:
            duration_match = _DURATION_TOKEN.fullmatch(tail[-1])
            if duration_match:
                declared_duration_s = float(duration_match.group("seconds"))
                tail = tail[:-1]

        # Do not mistake detail/summary/other auxiliary files for experiments.
        if tail:
            continue

        return prefix, controller, run_variant, declared_duration_s

    return None, None, None, float("nan")


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Compare Motor Digital Twin evaluation runs."
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("results/evaluation_test"),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/evaluation_summary.csv"),
    )

    parser.add_argument(
        "--basyx-output",
        type=Path,
        default=None,
        help=(
            "Optional CSV containing only rows with a BaSyx summary. "
            "Defaults beside --output."
        ),
    )

    args = parser.parse_args()

    # Filename parsing filters non-experiment CSVs, while accepting any
    # duration and the standard, BaSyx, and controller-only run variants.
    files = sorted(args.input_dir.glob("*.csv"))

    if not files:

        raise FileNotFoundError(
            f"No CSV files found in:\n"
            f"{args.input_dir.resolve()}"
        )

    rows = []

    for path in files:

        scenario, controller, run_variant, declared_duration_s = parse_filename(path)

        if scenario is None:
            print(
                f"[SKIP] Cannot parse filename: {path.name}"
            )
            continue

        print(f"Reading: {path.name}")

        df = pd.read_csv(path)

        row = compute_metrics(df, scenario, controller)
        row["run_variant"] = run_variant
        row["declared_duration_s"] = declared_duration_s
        row["source_file"] = path.name

        # A summary describes only its BaSyx-enabled CSV, not the matching
        # standard or controller-only simulation.
        basyx_summary = path.with_name(f"{path.stem}_basyx_summary.json")
        if run_variant == "basyx" and basyx_summary.is_file():
            row.update(load_basyx_metrics(basyx_summary))
        rows.append(row)

    summary = pd.DataFrame(rows)

    summary = summary.sort_values(
        ["scenario", "controller", "duration_s", "run_variant"]
    ).reset_index(drop=True)

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary.to_csv(
        args.output,
        index=False,
    )

    basyx_output = args.basyx_output or args.output.with_name(
        f"{args.output.stem}_basyx_metrics.csv"
    )
    if "basyx_summary_file" in summary.columns:
        basyx_rows = summary.loc[
            summary["basyx_summary_file"].notna(),
            [
                "scenario",
                "controller",
                "run_variant",
                "duration_s",
                "declared_duration_s",
                "source_file",
                *BASYX_METRIC_COLUMNS,
            ],
        ]
    else:
        basyx_rows = pd.DataFrame(
            columns=[
                "scenario",
                "controller",
                "run_variant",
                "duration_s",
                "declared_duration_s",
                "source_file",
                *BASYX_METRIC_COLUMNS,
            ]
        )
    basyx_output.parent.mkdir(parents=True, exist_ok=True)
    basyx_rows.to_csv(basyx_output, index=False)

    print()
    print("=" * 72)
    print("EVALUATION SUMMARY")
    print("=" * 72)

    display_columns = [
        "scenario",
        "controller",
        "run_variant",
        "duration_s",
        "declared_duration_s",
        "max_winding_temp_C",
        "time_above_100C_s",
        "time_above_120C_s",
        "electrical_energy_kWh",
        "useful_work_kWh",
        "energy_per_useful_work",
        "speed_rmse_rad_s",
        "state_estimation_mae_C",
        "prediction_30s_mae_C",
        "prediction_60s_mae_C",
        "mean_load_command_pu",
        "minimum_controller_safety_margin_C",
        "mean_derating_fraction",
        "max_derating_fraction",
        "emergency_derating_fraction",
    ]

    available = [
        c for c in display_columns
        if c in summary.columns
    ]

    print(
        summary[available].to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}",
        )
    )

    if not basyx_rows.empty:
        print()
        print("BASYX INTEROPERABILITY SUMMARY")
        print("=" * 72)
        basyx_display_columns = [
            "scenario",
            "controller",
            "basyx_update_attempts",
            "basyx_update_success_rate_percent",
            "basyx_read_attempts",
            "basyx_read_success_rate_percent",
            "basyx_write_latency_mean_ms",
            "basyx_write_latency_p95_ms",
            "basyx_read_latency_mean_ms",
            "basyx_read_latency_p95_ms",
            "basyx_end_to_end_loop_mean_latency_ms",
            "basyx_absolute_overhead_mean_ms",
            "basyx_overhead_share_of_end_to_end_percent",
        ]
        print(
            basyx_rows[basyx_display_columns].to_string(
                index=False,
                float_format=lambda x: f"{x:.4f}",
            )
        )

    print()
    print(f"Saved summary: {args.output.resolve()}")
    print(f"Saved BaSyx metrics: {basyx_output.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
