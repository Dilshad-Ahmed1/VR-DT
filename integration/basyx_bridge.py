from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import requests


class BaSyxBridge:
    """
    BaSyx v2 REST bridge for the Motor Digital Twin.

    Architecture:

        FMU / Python DT
              |
              v
        BaSyxBridge
              |
              v
        BaSyx AAS Environment :8081

    The bridge uses the project's motor_aas_definition.json as the
    authoritative AAS schema.

    Important:
        - No FMU simulation logic here.
        - No controller logic here.
        - No artificial sleep.
        - Synchronization latency is measured.
    """

    def __init__(
        self,
        host: str = "http://localhost:8081",
        config_path: str | Path = "config/motor_aas_definition.json",
        timeout_s: float = 3.0,
    ) -> None:

        self.base_url = host.rstrip("/")
        self.timeout_s = float(timeout_s)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        self.config_path = Path(
            config_path
        ).resolve()

        if not self.config_path.exists():
            raise FileNotFoundError(
                "BaSyx AAS definition not found:\n"
                f"{self.config_path}"
            )

        with self.config_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            self.aas_definition = json.load(f)

        self.aas_id = self.aas_definition["id"]
        self.aas_id_short = self.aas_definition[
            "idShort"
        ]

        self.submodels: dict[str, dict[str, Any]] = {}

        for sm in self.aas_definition.get(
            "submodels",
            [],
        ):
            self.submodels[sm["idShort"]] = copy.deepcopy(
                sm
            )

        self.last_sync_latency_ms = 0.0
        self.total_syncs = 0
        self.successful_syncs = 0
        self.failed_syncs = 0

    # ------------------------------------------------------------------
    # Identifier encoding
    # ------------------------------------------------------------------

    @staticmethod
    def encode_identifier(
        identifier: str,
    ) -> str:
        """
        BaSyx/AAS Base64URL identifier encoding.

        Padding is removed.
        """

        import base64

        return (
            base64.urlsafe_b64encode(
                identifier.encode("utf-8")
            )
            .decode("ascii")
            .rstrip("=")
        )

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _submodel_url(
        self,
        submodel_id: str,
    ) -> str:

        encoded = self.encode_identifier(
            submodel_id
        )

        return (
            f"{self.base_url}"
            f"/submodels/{encoded}"
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:

        return self.session.request(
            method=method,
            url=url,
            timeout=self.timeout_s,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        Check BaSyx Environment accessibility.
        """

        t0 = time.perf_counter()

        shells_response = self._request(
            "GET",
            f"{self.base_url}/shells",
        )

        submodels_response = self._request(
            "GET",
            f"{self.base_url}/submodels",
        )

        elapsed_ms = (
            time.perf_counter() - t0
        ) * 1000.0

        shells_response.raise_for_status()
        submodels_response.raise_for_status()

        shells = shells_response.json()
        submodels = submodels_response.json()

        return {
            "healthy": True,
            "latency_ms": elapsed_ms,
            "shells": shells,
            "submodels": submodels,
        }

    # ------------------------------------------------------------------
    # Definition access
    # ------------------------------------------------------------------

    def get_submodel_definition(
        self,
        id_short: str,
    ) -> dict[str, Any]:

        if id_short not in self.submodels:
            raise KeyError(
                f"Unknown project submodel: "
                f"{id_short}"
            )

        return self.submodels[id_short]

    # ------------------------------------------------------------------
    # Find Property inside local definition
    # ------------------------------------------------------------------

    def _find_property_template(
        self,
        submodel: str,
        id_short: str,
    ) -> dict[str, Any]:

        sm = self.get_submodel_definition(
            submodel
        )

        for element in sm.get(
            "submodelElements",
            [],
        ):

            if (
                element.get("idShort")
                == id_short
            ):

                return element

        raise KeyError(
            f"Property "
            f"{submodel}.{id_short} "
            f"not found in motor_aas_definition.json"
        )

    # ------------------------------------------------------------------
    # Value conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _value_string(
        value: Any,
    ) -> str:

        if isinstance(value, bool):
            return (
                "true"
                if value
                else "false"
            )

        if isinstance(value, float):
            return f"{value:.12g}"

        return str(value)

    # ------------------------------------------------------------------
    # Property update
    # ------------------------------------------------------------------

    def update_property(
        self,
        submodel: str,
        id_short: str,
        value: Any,
    ) -> dict[str, Any]:

        template = copy.deepcopy(
            self._find_property_template(
                submodel,
                id_short,
            )
        )

        template["value"] = (
            self._value_string(value)
        )

        sm = self.get_submodel_definition(
            submodel
        )

        encoded_id = self.encode_identifier(
            sm["id"]
        )

        url = (
            f"{self.base_url}"
            f"/submodels/{encoded_id}"
            f"/submodel-elements/{id_short}"
        )

        t0 = time.perf_counter()

        response = self._request(
            "PUT",
            url,
            json=template,
        )

        elapsed_ms = (
            time.perf_counter() - t0
        ) * 1000.0

        if response.status_code not in {
            200,
            204,
        }:

            raise RuntimeError(
                "BaSyx Property update failed:\n"
                f"  URL       : {url}\n"
                f"  Status    : {response.status_code}\n"
                f"  Response  : {response.text[:1000]}"
            )

        return {
            "success": True,
            "latency_ms": elapsed_ms,
            "status_code": response.status_code,
            "submodel": submodel,
            "property": id_short,
            "value": value,
        }

    # ------------------------------------------------------------------
    # Read Property
    # ------------------------------------------------------------------

    def read_property(
        self,
        submodel: str,
        id_short: str,
    ) -> Any:

        sm = self.get_submodel_definition(
            submodel
        )

        encoded_id = self.encode_identifier(
            sm["id"]
        )

        url = (
            f"{self.base_url}"
            f"/submodels/{encoded_id}"
            f"/submodel-elements/{id_short}"
        )

        response = self._request(
            "GET",
            url,
        )

        response.raise_for_status()

        payload = response.json()

        return payload.get(
            "value"
        )

    # ------------------------------------------------------------------
    # Read entire submodel
    # ------------------------------------------------------------------

    def read_submodel(
        self,
        submodel: str,
    ) -> dict[str, Any]:

        sm = self.get_submodel_definition(
            submodel
        )

        encoded_id = self.encode_identifier(
            sm["id"]
        )

        response = self._request(
            "GET",
            (
                f"{self.base_url}"
                f"/submodels/{encoded_id}"
            ),
        )

        response.raise_for_status()

        return response.json()

    # ------------------------------------------------------------------
    # Whole-submodel synchronization
    # ------------------------------------------------------------------

    def update_submodel(
        self,
        submodel: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update multiple Properties with ONE HTTP request.

        This is much more appropriate for telemetry than making a
        separate request for every Property.
        """

        sm = copy.deepcopy(
            self.get_submodel_definition(
                submodel
            )
        )

        value_map = dict(values)

        for element in sm.get(
            "submodelElements",
            [],
        ):

            id_short = element.get(
                "idShort"
            )

            if id_short in value_map:

                element["value"] = (
                    self._value_string(
                        value_map[id_short]
                    )
                )

        encoded_id = self.encode_identifier(
            sm["id"]
        )

        url = (
            f"{self.base_url}"
            f"/submodels/{encoded_id}"
        )

        t0 = time.perf_counter()

        response = self._request(
            "PUT",
            url,
            json=sm,
        )

        elapsed_ms = (
            time.perf_counter() - t0
        ) * 1000.0

        if response.status_code not in {
            200,
            204,
        }:

            raise RuntimeError(
                "BaSyx submodel synchronization failed:\n"
                f"  Submodel : {submodel}\n"
                f"  Status   : {response.status_code}\n"
                f"  Response : {response.text[:1000]}"
            )

        self.total_syncs += 1
        self.successful_syncs += 1
        self.last_sync_latency_ms = (
            elapsed_ms
        )

        return {
            "success": True,
            "latency_ms": elapsed_ms,
            "status_code": response.status_code,
            "submodel": submodel,
        }

    # ------------------------------------------------------------------
    # Entire Digital Twin snapshot
    # ------------------------------------------------------------------

    def update_snapshot(
        self,
        *,
        thermal: dict[str, Any],
        electrical: dict[str, Any],
        mechanical: dict[str, Any],
        operational: dict[str, Any],
        fault: dict[str, Any],
        control: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Synchronize the complete current Digital Twin state.

        Returns aggregate synchronization statistics.
        """

        payloads = {
            "ThermalState": thermal,
            "ElectricalState": electrical,
            "MechanicalState": mechanical,
            "OperationalState": operational,
            "FaultState": fault,
            "ControlInterface": control,
        }

        started = time.perf_counter()

        results = {}

        successful = 0
        failed = 0

        errors: list[str] = []

        for submodel, values in payloads.items():

            try:

                result = self.update_submodel(
                    submodel,
                    values,
                )

                results[submodel] = result
                successful += 1

            except Exception as exc:

                failed += 1
                errors.append(
                    f"{submodel}: {exc}"
                )

        total_latency_ms = (
            time.perf_counter()
            - started
        ) * 1000.0

        if failed > 0:

            self.failed_syncs += failed

        return {
            "success": failed == 0,
            "submodels_successful": successful,
            "submodels_failed": failed,
            "total_latency_ms": total_latency_ms,
            "results": results,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Read-back verification
    # ------------------------------------------------------------------

    def verify_property(
        self,
        submodel: str,
        id_short: str,
        expected: Any,
        tolerance: float = 1e-6,
    ) -> bool:

        actual = self.read_property(
            submodel,
            id_short,
        )

        if isinstance(
            expected,
            bool,
        ):

            if isinstance(actual, bool):
                return actual == expected

            return (
                str(actual).lower()
                == str(expected).lower()
            )

        if isinstance(
            expected,
            (int, float),
        ):

            try:

                return (
                    abs(
                        float(actual)
                        - float(expected)
                    )
                    <= tolerance
                )

            except (
                TypeError,
                ValueError,
            ):

                return False

        return str(actual) == str(
            expected
        )

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close(self) -> None:

        self.session.close()

    def __enter__(
        self,
    ) -> BaSyxBridge:

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:

        self.close()