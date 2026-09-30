from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCENARIOS = [
    "healthy",
    "cooling",
    "sensor_bias",
    "sensor_freeze",
    "rth_degradation",
    "unbalance",
    "combined",
]

CONTROLLERS = [
    "baseline",
    "adaptive",
    "constrained",
]


def run_one(
    fmu: Path,
    scenario: str,
    controller: str,
    stop: float,
    step: float,
    fault_time: float,
    output_dir: Path,
    realtime: bool = False,
) -> Path:

    output_dir.mkdir(parents=True, exist_ok=True)

    output = (
        output_dir
        / f"{scenario}_{controller}_{int(stop)}s.csv"
    )

    print("\n" + "=" * 72)
    print(f"Running scenario   : {scenario}")
    print(f"Controller         : {controller}")
    print(f"Simulation time    : {stop:.1f} s")
    print(f"Communication step : {step:.3f} s")
    print(f"Fault time         : {fault_time:.1f} s")
    print(f"Output             : {output}")
    print("=" * 72)

    cmd = [
        sys.executable,
        "-m",
        "experiments.experiment_runner",
        "--fmu",
        str(fmu.resolve()),
        "--scenario",
        scenario,
        "--controller",
        controller,
        "--stop",
        str(stop),
        "--step",
        str(step),
        "--fault-time",
        str(fault_time),
        "--output",
        str(output.resolve()),
    ]

    if realtime:
        cmd.append("--realtime")

    result = subprocess.run(cmd)

    if result.returncode != 0:
        raise RuntimeError(
            f"Experiment failed: "
            f"scenario={scenario}, controller={controller}, "
            f"returncode={result.returncode}"
        )

    if not output.exists():
        raise FileNotFoundError(
            f"Experiment reported success but output file does not exist:\n"
            f"{output}"
        )

    print(f"\n[SUCCESS] {output}")

    return output


def main() -> int:

    parser = argparse.ArgumentParser(
        description="Run the complete Motor Digital Twin evaluation suite."
    )

    parser.add_argument(
        "--fmu",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--stop",
        type=float,
        default=1800.0,
        help="Simulation duration in seconds.",
    )

    parser.add_argument(
        "--step",
        type=float,
        default=0.5,
        help="FMI communication step in seconds.",
    )

    parser.add_argument(
        "--fault-time",
        type=float,
        default=600.0,
        help="Fault injection time in seconds.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/evaluation"),
    )

    parser.add_argument(
        "--scenario",
        choices=["all"] + SCENARIOS,
        default="all",
    )

    parser.add_argument(
        "--controller",
        choices=["all"] + CONTROLLERS,
        default="all",
    )

    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Pace every case against wall clock and record deadline metrics.",
    )

    args = parser.parse_args()

    if not args.fmu.exists():
        raise FileNotFoundError(
            f"FMU not found:\n{args.fmu}"
        )

    scenarios = (
        SCENARIOS
        if args.scenario == "all"
        else [args.scenario]
    )

    controllers = (
        CONTROLLERS
        if args.controller == "all"
        else [args.controller]
    )

    total = len(scenarios) * len(controllers)

    print()
    print("=" * 72)
    print("MOTOR DIGITAL TWIN - EVALUATION SUITE")
    print("=" * 72)
    print(f"FMU          : {args.fmu}")
    print(f"Scenarios    : {scenarios}")
    print(f"Controllers  : {controllers}")
    print(f"Experiments  : {total}")
    print(f"Stop time    : {args.stop} s")
    print(f"Step         : {args.step} s")
    print(f"Fault time   : {args.fault_time} s")
    print(f"Output dir   : {args.output_dir.resolve()}")
    print(f"Realtime     : {args.realtime}")
    print("=" * 72)

    completed = []

    for scenario in scenarios:
        for controller in controllers:

            output = run_one(
                fmu=args.fmu,
                scenario=scenario,
                controller=controller,
                stop=args.stop,
                step=args.step,
                fault_time=args.fault_time,
                output_dir=args.output_dir,
                realtime=args.realtime,
            )

            completed.append(output)

    print()
    print("=" * 72)
    print("EVALUATION SUITE COMPLETED")
    print("=" * 72)
    print(f"Completed experiments : {len(completed)}/{total}")

    for path in completed:
        print(f"  ✓ {path}")

    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())