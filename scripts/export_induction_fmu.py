from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from fmpy import read_model_description


MODEL_CLASS = "MotorDigitalTwin.InductionMotorDigitalTwin18kW"
MODEL_FILE = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "InductionMotorDigitalTwin18kW.mo"
)


def _find_omc(omc: Path | None, omhome: Path | None) -> Path:
    candidates: list[Path] = []
    if omc is not None:
        candidates.append(omc)
    if omhome is not None:
        candidates.extend((omhome / "bin" / "omc.exe", omhome / "bin" / "omc"))
    if os.environ.get("OPENMODELICAHOME"):
        home = Path(os.environ["OPENMODELICAHOME"])
        candidates.extend((home / "bin" / "omc.exe", home / "bin" / "omc"))
    candidates.append(
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "OpenModelica1.27.1-64bit"
        / "bin"
        / "omc.exe"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    found = shutil.which("omc")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError("OpenModelica 1.27.1 executable (omc) not found.")


def _modelica_string(value: str | Path) -> str:
    return '"' + str(value).replace("\\", "/").replace('"', '\\"') + '"'


def export_fmu(omc: Path, output: Path, overwrite: bool) -> Path:
    output = output.resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing FMU: {output}; "
            "pass --overwrite to replace it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="induction_fmu_export_") as tmp:
        tmp_dir = Path(tmp)
        mos = tmp_dir / "export_induction_fmu.mos"
        mos.write_text(
            "\n".join(
                (
                    "loadModel(Modelica);",
                    f'print("MSL_VERSION=" + getVersion(Modelica) + "\\n");',
                    f"loadFile({_modelica_string(MODEL_FILE)});",
                    f"checkModel({MODEL_CLASS});",
                    'setCommandLineOptions("--fmiFlags=s:cvode");',
                    (
                        f"buildModelFMU({MODEL_CLASS}, "
                        'version="2.0", fmuType="cs", '
                        'platforms={"static"});'
                    ),
                    "",
                )
            ),
            encoding="utf-8",
        )
        process = subprocess.run(
            [str(omc), str(mos)],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        output_text = (process.stdout + process.stderr).strip()
        if process.returncode:
            raise RuntimeError(
                f"OpenModelica FMU export failed ({process.returncode}):\n"
                f"{output_text}"
            )
        if "check of " + MODEL_CLASS.lower() + " completed successfully" not in (
            output_text.lower()
        ):
            raise RuntimeError(
                "OpenModelica did not confirm the requested model check.\n"
                f"{output_text}"
            )
        if "msl_version=4.1.0" not in output_text.lower():
            raise RuntimeError(
                "This model requires Modelica Standard Library 4.1.0.\n"
                f"{output_text}"
            )

        generated = list(tmp_dir.glob("InductionMotorDigitalTwin18kW.fmu"))
        if len(generated) != 1:
            raise RuntimeError(
                "Expected exactly one exported FMU in the isolated build "
                f"directory; found {generated}.\n{output_text}"
            )

        shutil.copy2(generated[0], output)

    try:
        description = read_model_description(str(output))
        if description.fmiVersion != "2.0" or description.coSimulation is None:
            raise RuntimeError("Exported artifact is not an FMI 2.0 Co-Simulation FMU.")
        variable_names = {variable.name for variable in description.modelVariables}
        required_outputs = {
            "T_winding_C",
            "T_frame_C",
            "T_ambient_C",
            "thermal_margin_to_critical_K",
            "cooling_effectiveness",
            "P_electrical_W",
            "P_shaft_W",
            "P_loss_total_W",
        }
        missing_outputs = sorted(required_outputs - variable_names)
        if missing_outputs:
            raise RuntimeError(
                f"Exported FMU is missing required outputs: {missing_outputs}"
            )
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the separate MSL induction Digital Twin FMU."
    )
    parser.add_argument("--omhome", type=Path, default=None)
    parser.add_argument("--omc", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "models"
            / "InductionMotorDigitalTwin18kW.fmu"
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    omc = _find_omc(args.omc, args.omhome)
    version = subprocess.run(
        [str(omc), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if "v1.27.1" not in version.stdout + version.stderr:
        raise RuntimeError(
            "FMU export requires OpenModelica 1.27.1; "
            f"found {(version.stdout + version.stderr).strip()}."
        )

    output = export_fmu(omc, args.output, args.overwrite)
    print(f"OpenModelica: {(version.stdout + version.stderr).strip()}")
    print(f"FMU: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
