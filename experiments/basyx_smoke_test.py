from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from integration.basyx_bridge import (
    BaSyxBridge,
)


def main() -> int:

    print()
    print("=" * 72)
    print("MOTOR DIGITAL TWIN - BASYX CONNECTIVITY TEST")
    print("=" * 72)

    try:

        with BaSyxBridge() as basyx:

            # ----------------------------------------------------------
            # 1. Connectivity
            # ----------------------------------------------------------

            print()
            print("[1] Checking BaSyx Environment...")

            health = (
                basyx.health_check()
            )

            print(
                f"    Healthy       : "
                f"{health['healthy']}"
            )

            print(
                f"    Health latency: "
                f"{health['latency_ms']:.3f} ms"
            )

            # ----------------------------------------------------------
            # 2. AAS identity
            # ----------------------------------------------------------

            print()
            print("[2] AAS identity")

            print(
                f"    AAS idShort : "
                f"{basyx.aas_id_short}"
            )

            print(
                f"    AAS ID      : "
                f"{basyx.aas_id}"
            )

            # ----------------------------------------------------------
            # 3. Expected submodels
            # ----------------------------------------------------------

            required = [
                "OperationalState",
                "ElectricalState",
                "MechanicalState",
                "ThermalState",
                "FaultState",
                "ControlInterface",
            ]

            print()
            print("[3] Checking project submodels...")

            for name in required:

                sm = basyx.get_submodel_definition(
                    name
                )

                print(
                    f"    ✓ {name:20s}"
                    f"  {sm['id']}"
                )

            # ----------------------------------------------------------
            # 4. Existing values
            # ----------------------------------------------------------

            print()
            print("[4] Reading existing AAS values...")

            checks = [
                (
                    "ThermalState",
                    "WindingTemperatureK",
                ),
                (
                    "ThermalState",
                    "FrameTemperatureK",
                ),
                (
                    "ThermalState",
                    "WindingSensorMeasuredK",
                ),
                (
                    "FaultState",
                    "EstimatedFaultSeverity",
                ),
                (
                    "ControlInterface",
                    "LoadDeratingCommandPu",
                ),
            ]

            for submodel, prop in checks:

                value = basyx.read_property(
                    submodel,
                    prop,
                )

                print(
                    f"    {submodel:20s}."
                    f"{prop:32s}"
                    f" = {value}"
                )

            # ----------------------------------------------------------
            # 5. Test update
            # ----------------------------------------------------------

            print()
            print("[5] Testing Property update...")

            test_value = 315.15

            result = basyx.update_property(
                "ThermalState",
                "WindingTemperatureK",
                test_value,
            )

            print(
                f"    HTTP status : "
                f"{result['status_code']}"
            )

            print(
                f"    Latency     : "
                f"{result['latency_ms']:.3f} ms"
            )

            # ----------------------------------------------------------
            # 6. Read-back
            # ----------------------------------------------------------

            print()
            print("[6] Verifying read-back...")

            passed = basyx.verify_property(
                "ThermalState",
                "WindingTemperatureK",
                test_value,
            )

            print(
                f"    Verification: "
                f"{'PASS' if passed else 'FAIL'}"
            )

            # ----------------------------------------------------------
            # 7. Restore initial value
            # ----------------------------------------------------------

            print()
            print(
                "[7] Restoring initial "
                "WindingTemperatureK..."
            )

            basyx.update_property(
                "ThermalState",
                "WindingTemperatureK",
                298.15,
            )

            restored = basyx.verify_property(
                "ThermalState",
                "WindingTemperatureK",
                298.15,
            )

            print(
                f"    Restore: "
                f"{'PASS' if restored else 'FAIL'}"
            )

            # ----------------------------------------------------------
            # Result
            # ----------------------------------------------------------

            print()
            print("=" * 72)

            if passed and restored:

                print(
                    "BaSyx connectivity and "
                    "read/write verification PASSED."
                )

                print("=" * 72)
                print()

                return 0

            print(
                "BaSyx verification FAILED."
            )

            print("=" * 72)
            print()

            return 1

    except Exception as exc:

        print()
        print("=" * 72)
        print("BaSyx test FAILED")
        print("=" * 72)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        print()
        print(
            "Make sure Docker Desktop is running "
            "and the BaSyx containers are started."
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())