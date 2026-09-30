from __future__ import annotations

import argparse
from pathlib import Path

from OMPython import OMCSessionZMQ


MODEL_CLASS = (
    "MotorDigitalTwin."
    "MotorElectroThermalMechanicalFaultable"
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--omhome",
        default=None,
        help="OpenModelica installation directory",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    model_file = (
        project_root
        / "models"
        / "MotorElectroThermalMechanicalFaultable.mo"
    )

    omc = (
        OMCSessionZMQ(omhome=args.omhome)
        if args.omhome
        else OMCSessionZMQ()
    )

    try:
        if not omc.sendExpression(
            f'cd("{project_root.as_posix()}")'
        ):
            raise RuntimeError(
                "Could not set OpenModelica working directory."
            )

        loaded = omc.sendExpression(
            f'loadFile("{model_file.as_posix()}")'
        )

        if not loaded:
            raise RuntimeError(
                "OpenModelica failed to load Modelica file."
            )

        # Use CVODE for FMI 2.0 Co-Simulation.
        result = omc.sendExpression(
            'setCommandLineOptions("--fmiFlags=s:cvode")'
        )

        if not result:
            raise RuntimeError(
                "Failed to enable CVODE for FMU export."
            )

        check = omc.sendExpression(
            f"checkModel({MODEL_CLASS})"
        )

        print("checkModel:")
        print(check)

        generated = omc.sendExpression(
            f'buildModelFMU('
            f'{MODEL_CLASS},'
            f' version="2.0",'
            f' fmuType="cs",'
            f' platforms={{"static"}}'
            f')'
        )

        print()
        print("Generated FMU:")
        print(generated)

        if not generated:
            raise RuntimeError(
                "OpenModelica did not generate an FMU."
            )

        return 0

    finally:
        try:
            omc.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())