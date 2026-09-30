from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analysis.experiment_metrics import (
    compute_experiment_metrics,
    print_metrics,
)
from experiments.experiment_runner import (
    SCENARIOS,
    run_one_experiment,
)


def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--fmu",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--stop",
        type=float,
        default=1800.0,
    )

    parser.add_argument(
        "--step",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--fault-time",
        type=float,
        default=600.0,
    )

    parser.add_argument(
        "--scenario",
        choices=["all"] + sorted(SCENARIOS.keys()),
        default="all",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    results_dir = (
        project_root / "results" / "experiments"
    )

    results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if args.scenario == "all":
        scenario_names = list(
            SCENARIOS.keys()
        )
    else:
        scenario_names = [
            args.scenario
        ]

    summary_rows = []

    for scenario_name in scenario_names:

        scenario = SCENARIOS[
            scenario_name
        ]

        for controller_name in (
            "baseline",
            "adaptive",
            "constrained",
        ):

            print()
            print(
                "=" * 70
            )
            print(
                f"{scenario_name.upper()} / "
                f"{controller_name.upper()}"
            )
            print(
                "=" * 70
            )

            output_path = (
                results_dir
                / (
                    f"{scenario_name}_"
                    f"{controller_name}.csv"
                )
            )

            df = run_one_experiment(
                fmu_path=args.fmu.resolve(),
                scenario=scenario,
                controller_name=controller_name,
                stop_time_s=args.stop,
                step_s=args.step,
                fault_time_s=args.fault_time,
                output_path=output_path,
            )

            metrics = compute_experiment_metrics(
                output_path,
                fault_time_s=args.fault_time,
            )

            print_metrics(metrics)

            summary_rows.append(
                metrics
            )

    summary_df = pd.DataFrame(
        summary_rows
    )

    summary_csv = (
        results_dir
        / "experiment_summary.csv"
    )

    summary_json = (
        results_dir
        / "experiment_summary.json"
    )

    summary_df.to_csv(
        summary_csv,
        index=False,
    )

    summary_json.write_text(
        json.dumps(
            summary_rows,
            indent=2,
            allow_nan=True,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "============================================================"
    )
    print(
        "EXPERIMENT SUITE COMPLETE"
    )
    print(
        "============================================================"
    )

    print(
        f"Summary CSV : {summary_csv}"
    )

    print(
        f"Summary JSON: {summary_json}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())