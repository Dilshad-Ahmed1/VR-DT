from __future__ import annotations

import base64
import csv
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests


# These identifiers must match config/motor_aas_definition.json.
SUBMODEL_IDS = {
    "thermal": "https://rvce.edu.in/aas/submodels/ThermalState",
    "fault": "https://rvce.edu.in/aas/submodels/FaultState",
    "control": "https://rvce.edu.in/aas/submodels/ControlInterface",
}


def _aas_id_url(identifier: str) -> str:
    """Encode an AAS identifier for BaSyx AAS Repository REST paths."""
    return base64.urlsafe_b64encode(
        identifier.encode("utf-8")
    ).decode("ascii").rstrip("=")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return float("nan")

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    return (
        ordered[lower]
        + (ordered[upper] - ordered[lower])
        * (position - lower)
    )


def _summary(values: list[float], prefix: str) -> dict[str, float]:
    if not values:
        return {
            f"{prefix}_mean_ms": float("nan"),
            f"{prefix}_median_ms": float("nan"),
            f"{prefix}_p95_ms": float("nan"),
            f"{prefix}_p99_ms": float("nan"),
            f"{prefix}_max_ms": float("nan"),
        }

    return {
        f"{prefix}_mean_ms": statistics.mean(values),
        f"{prefix}_median_ms": statistics.median(values),
        f"{prefix}_p95_ms": _percentile(values, 95.0),
        f"{prefix}_p99_ms": _percentile(values, 99.0),
        f"{prefix}_max_ms": max(values),
    }


@dataclass
class BaSyxEvaluationMetrics:
    """
    Measures the AAS communication part of the Digital Twin loop.

    A sync operation is measured as:

        FMU/controller state -> BaSyx write -> AAS read-back verification

    The existing BaSyxBridge remains responsible for writing the complete
    project snapshot. This class adds independent REST read-back timing,
    synchronization-error measurement, reliability counts, and CSV/JSON output.
    """

    environment_url: str = "http://localhost:8081"
    timeout_s: float = 5.0

    write_latency_ms: list[float] = field(default_factory=list)
    read_latency_ms: list[float] = field(default_factory=list)
    update_latency_ms: list[float] = field(default_factory=list)
    end_to_end_latency_ms: list[float] = field(default_factory=list)
    controller_only_latency_ms: list[float] = field(default_factory=list)

    attempted_updates: int = 0
    successful_updates: int = 0
    failed_updates: int = 0
    timeout_updates: int = 0

    attempted_reads: int = 0
    successful_reads: int = 0
    failed_reads: int = 0
    timeout_reads: int = 0

    sync_errors: dict[str, list[float]] = field(
        default_factory=lambda: {
            "winding_temperature_C": [],
            "frame_temperature_C": [],
            "thermal_margin_C": [],
            "fault_severity": [],
            "cooling_command_pu": [],
            "load_command_pu": [],
        }
    )

    rows: list[dict[str, Any]] = field(default_factory=list)

    def _value_url(
        self,
        submodel_id: str,
        property_id_short: str,
    ) -> str:
        encoded_submodel_id = _aas_id_url(submodel_id)

        return (
            f"{self.environment_url.rstrip('/')}"
            f"/submodels/{encoded_submodel_id}"
            f"/submodel-elements/{property_id_short}/$value"
        )

    def _read_value(
        self,
        submodel_id: str,
        property_id_short: str,
    ) -> tuple[bool, Any, float, str | None, bool]:
        """
        Returns:
            success, value, latency_ms, error_message, timed_out
        """
        started = time.perf_counter()

        try:
            response = requests.get(
                self._value_url(
                    submodel_id,
                    property_id_short,
                ),
                timeout=self.timeout_s,
            )

            latency_ms = (
                time.perf_counter() - started
            ) * 1000.0

            response.raise_for_status()

            try:
                value = response.json()
            except ValueError:
                value = response.text.strip()

            return True, value, latency_ms, None, False

        except requests.Timeout as exc:
            latency_ms = (
                time.perf_counter() - started
            ) * 1000.0

            return (
                False,
                None,
                latency_ms,
                f"timeout: {exc}",
                True,
            )

        except requests.RequestException as exc:
            latency_ms = (
                time.perf_counter() - started
            ) * 1000.0

            return (
                False,
                None,
                latency_ms,
                str(exc),
                False,
            )

    @staticmethod
    def _float_value(value: Any) -> float:
        if isinstance(value, dict) and "value" in value:
            value = value["value"]

        return float(value)

    def _read_and_compare(
        self,
        *,
        label: str,
        submodel_id: str,
        property_id_short: str,
        expected_value: float,
        expected_unit_offset: float = 0.0,
    ) -> tuple[float | None, float | None, str | None]:
        """
        expected_unit_offset is used for values published in Kelvin while
        the FMU/controller source values are represented in degrees Celsius.
        """
        self.attempted_reads += 1

        (
            success,
            actual_value,
            latency_ms,
            error,
            timed_out,
        ) = self._read_value(
            submodel_id,
            property_id_short,
        )

        self.read_latency_ms.append(latency_ms)

        if not success:
            self.failed_reads += 1

            if timed_out:
                self.timeout_reads += 1

            return None, latency_ms, error

        self.successful_reads += 1

        try:
            actual_float = self._float_value(actual_value)
            actual_in_source_unit = (
                actual_float - expected_unit_offset
            )

            absolute_error = abs(
                actual_in_source_unit - expected_value
            )

            self.sync_errors[label].append(absolute_error)

            return absolute_error, latency_ms, None

        except (TypeError, ValueError) as exc:
            self.failed_reads += 1

            return (
                None,
                latency_ms,
                f"cannot parse AAS value {actual_value!r}: {exc}",
            )

    def record_sync(
        self,
        *,
        simulation_time_s: float,
        controller_only_latency_ms: float,
        update_snapshot: Callable[[], dict[str, Any]],
        snapshot: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        """
        Execute one existing BaSyxBridge update, then independently read
        important AAS values back and compare them with the sent snapshot.
        """
        self.attempted_updates += 1

        cycle_started = time.perf_counter()
        write_started = time.perf_counter()

        try:
            update_result = update_snapshot()

            write_elapsed_ms = (
                time.perf_counter() - write_started
            ) * 1000.0

            # Prefer the bridge's own aggregate latency if it provides one.
            write_latency_ms = float(
                update_result.get(
                    "total_latency_ms",
                    write_elapsed_ms,
                )
            )

            self.write_latency_ms.append(write_latency_ms)
            self.update_latency_ms.append(write_latency_ms)

            update_success = bool(
                update_result.get("success", False)
            )

            if not update_success:
                self.failed_updates += 1

                errors = update_result.get("errors", [])
                error_text = " | ".join(
                    str(error) for error in errors
                )

                if "timeout" in error_text.lower():
                    self.timeout_updates += 1

                cycle_latency_ms = (
                    time.perf_counter() - cycle_started
                ) * 1000.0

                self.end_to_end_latency_ms.append(
                    cycle_latency_ms
                )

                self.controller_only_latency_ms.append(
                    controller_only_latency_ms
                )

                row = {
                    "simulation_time_s": simulation_time_s,
                    "update_success": False,
                    "write_latency_ms": write_latency_ms,
                    "read_latency_ms": float("nan"),
                    "end_to_end_loop_latency_ms": (
                        cycle_latency_ms
                    ),
                    "controller_only_latency_ms": (
                        controller_only_latency_ms
                    ),
                    "error": error_text,
                }

                self.rows.append(row)

                return row

            self.successful_updates += 1

        except requests.Timeout as exc:
            write_latency_ms = (
                time.perf_counter() - write_started
            ) * 1000.0

            self.write_latency_ms.append(write_latency_ms)
            self.update_latency_ms.append(write_latency_ms)
            self.failed_updates += 1
            self.timeout_updates += 1

            cycle_latency_ms = (
                time.perf_counter() - cycle_started
            ) * 1000.0

            self.end_to_end_latency_ms.append(
                cycle_latency_ms
            )

            self.controller_only_latency_ms.append(
                controller_only_latency_ms
            )

            row = {
                "simulation_time_s": simulation_time_s,
                "update_success": False,
                "write_latency_ms": write_latency_ms,
                "read_latency_ms": float("nan"),
                "end_to_end_loop_latency_ms": cycle_latency_ms,
                "controller_only_latency_ms": (
                    controller_only_latency_ms
                ),
                "error": f"timeout: {exc}",
            }

            self.rows.append(row)

            return row

        except Exception as exc:
            write_latency_ms = (
                time.perf_counter() - write_started
            ) * 1000.0

            self.write_latency_ms.append(write_latency_ms)
            self.update_latency_ms.append(write_latency_ms)
            self.failed_updates += 1

            cycle_latency_ms = (
                time.perf_counter() - cycle_started
            ) * 1000.0

            self.end_to_end_latency_ms.append(
                cycle_latency_ms
            )

            self.controller_only_latency_ms.append(
                controller_only_latency_ms
            )

            row = {
                "simulation_time_s": simulation_time_s,
                "update_success": False,
                "write_latency_ms": write_latency_ms,
                "read_latency_ms": float("nan"),
                "end_to_end_loop_latency_ms": cycle_latency_ms,
                "controller_only_latency_ms": (
                    controller_only_latency_ms
                ),
                "error": str(exc),
            }

            self.rows.append(row)

            return row

        # Values chosen for validation represent physical state, fault state,
        # and controller decisions. Temperatures are converted K -> C.
        checks = [
            (
                "winding_temperature_C",
                SUBMODEL_IDS["thermal"],
                "WindingTemperatureK",
                float(snapshot["thermal"]["WindingTemperatureK"])
                - 273.15,
                273.15,
            ),
            (
                "frame_temperature_C",
                SUBMODEL_IDS["thermal"],
                "FrameTemperatureK",
                float(snapshot["thermal"]["FrameTemperatureK"])
                - 273.15,
                273.15,
            ),
            (
                "thermal_margin_C",
                SUBMODEL_IDS["thermal"],
                "ThermalMarginK",
                float(snapshot["thermal"]["ThermalMarginK"]),
                0.0,
            ),
            (
                "fault_severity",
                SUBMODEL_IDS["fault"],
                "EstimatedFaultSeverity",
                float(
                    snapshot["fault"]["EstimatedFaultSeverity"]
                ),
                0.0,
            ),
            (
                "cooling_command_pu",
                SUBMODEL_IDS["control"],
                "CoolingCommandPu",
                float(
                    snapshot["control"]["CoolingCommandPu"]
                ),
                0.0,
            ),
            (
                "load_command_pu",
                SUBMODEL_IDS["control"],
                "LoadDeratingCommandPu",
                float(
                    snapshot["control"][
                        "LoadDeratingCommandPu"
                    ]
                ),
                0.0,
            ),
        ]

        row: dict[str, Any] = {
            "simulation_time_s": simulation_time_s,
            "update_success": True,
            "write_latency_ms": write_latency_ms,
            "controller_only_latency_ms": (
                controller_only_latency_ms
            ),
            "error": "",
        }

        read_errors: list[str] = []
        this_read_latencies: list[float] = []

        for (
            label,
            submodel_id,
            property_id_short,
            expected_value,
            unit_offset,
        ) in checks:
            error, latency_ms, error_text = (
                self._read_and_compare(
                    label=label,
                    submodel_id=submodel_id,
                    property_id_short=property_id_short,
                    expected_value=expected_value,
                    expected_unit_offset=unit_offset,
                )
            )

            row[f"{label}_absolute_error"] = error

            if latency_ms is not None:
                this_read_latencies.append(latency_ms)

            if error_text:
                read_errors.append(
                    f"{property_id_short}: {error_text}"
                )

        row["read_latency_ms"] = (
            statistics.mean(this_read_latencies)
            if this_read_latencies
            else float("nan")
        )

        row["end_to_end_loop_latency_ms"] = (
            time.perf_counter() - cycle_started
        ) * 1000.0

        row["error"] = " | ".join(read_errors)

        self.end_to_end_latency_ms.append(
            row["end_to_end_loop_latency_ms"]
        )

        self.controller_only_latency_ms.append(
            controller_only_latency_ms
        )

        self.rows.append(row)

        return row

    def summary(self) -> dict[str, Any]:
        controller_mean = (
            statistics.mean(self.controller_only_latency_ms)
            if self.controller_only_latency_ms
            else float("nan")
        )

        end_to_end_mean = (
            statistics.mean(self.end_to_end_latency_ms)
            if self.end_to_end_latency_ms
            else float("nan")
        )

        overhead_ms = (
            end_to_end_mean - controller_mean
            if not math.isnan(controller_mean)
            and not math.isnan(end_to_end_mean)
            else float("nan")
        )

        overhead_percent = (
            100.0 * overhead_ms / controller_mean
            if not math.isnan(overhead_ms)
            and controller_mean > 0.0
            else float("nan")
        )

        result: dict[str, Any] = {
            "aas_environment_url": self.environment_url,
            "aas_registry_url": "http://localhost:8080",
            "submodel_registry_url": "http://localhost:8082",
            "update_attempts": self.attempted_updates,
            "update_successes": self.successful_updates,
            "update_failures": self.failed_updates,
            "update_timeouts": self.timeout_updates,
            "update_success_rate_percent": (
                100.0
                * self.successful_updates
                / self.attempted_updates
                if self.attempted_updates
                else float("nan")
            ),
            "read_attempts": self.attempted_reads,
            "read_successes": self.successful_reads,
            "read_failures": self.failed_reads,
            "read_timeouts": self.timeout_reads,
            "read_success_rate_percent": (
                100.0
                * self.successful_reads
                / self.attempted_reads
                if self.attempted_reads
                else float("nan")
            ),
            "controller_only_mean_latency_ms": controller_mean,
            "end_to_end_loop_mean_latency_ms": (
                end_to_end_mean
            ),
            "basyx_overhead_mean_ms": overhead_ms,
            "basyx_overhead_percent": overhead_percent,
        }

        result.update(
            _summary(self.write_latency_ms, "aas_write_latency")
        )

        result.update(
            _summary(self.update_latency_ms, "aas_update_latency")
        )

        result.update(
            _summary(self.read_latency_ms, "aas_read_latency")
        )

        result.update(
            _summary(
                self.end_to_end_latency_ms,
                "end_to_end_loop_latency",
            )
        )

        for name, values in self.sync_errors.items():
            result[f"sync_{name}_mae"] = (
                statistics.mean(values)
                if values
                else float("nan")
            )

            result[f"sync_{name}_max_error"] = (
                max(values)
                if values
                else float("nan")
            )

        return result

    def save(
        self,
        *,
        detail_csv: Path,
        summary_json: Path,
    ) -> dict[str, Any]:
        detail_csv.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        summary_json.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fieldnames = sorted(
            {
                key
                for row in self.rows
                for key in row.keys()
            }
        )

        with detail_csv.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
            )

            writer.writeheader()
            writer.writerows(self.rows)

        result = self.summary()

        with summary_json.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                result,
                file,
                indent=2,
                allow_nan=True,
            )

        return result