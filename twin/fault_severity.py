from __future__ import annotations

from .fault_detector import FaultDetection
from .state_estimator import StateEstimate


def _clip01(value: float) -> float:
    return max(
        0.0,
        min(
            1.0,
            float(value),
        ),
    )


def estimate_fault_severity(
    estimate: StateEstimate,
    detection: FaultDetection,
    measurement: dict[str, float],
) -> dict[str, float]:
    """
    Estimate continuous fault/anomaly severity from observable signals.

    These values are controller inputs.
    Ground-truth FMU fault parameters are never used.
    """

    vibration = float(
        measurement.get(
            "vibration_mm_s_out",
            1.0,
        )
    )

    # -------------------------------------------------------------
    # Sensor bias severity
    #
    # 10 °C residual corresponds to severity ~= 1.
    # -------------------------------------------------------------

    sensor_severity = _clip01(
        abs(estimate.sensor_residual_C)
        / 10.0
    )

    # -------------------------------------------------------------
    # Cooling degradation severity
    #
    # Positive frame innovation means the real/observed frame is
    # warmer than predicted by the nominal twin.
    # -------------------------------------------------------------

    cooling_from_innovation = _clip01(
        max(
            0.0,
            estimate.frame_innovation_C,
        )
        / 5.0
    )

    # Thermal growth is a secondary observable indicator.
    cooling_from_rate = _clip01(
        max(
            0.0,
            estimate.estimated_winding_rate_C_s,
        )
        / 0.05
    )

    cooling_severity = max(
        cooling_from_innovation,
        0.5 * cooling_from_rate,
    )

    # -------------------------------------------------------------
    # Mechanical unbalance severity
    #
    # Healthy vibration = approximately 1 mm/s.
    # At nominal load, severity 0.75 produces approximately 4 mm/s.
    # -------------------------------------------------------------

    unbalance_severity = _clip01(
        max(
            0.0,
            vibration - 1.0,
        )
        / 4.0
    )

    # Suppress component estimates when detection has not persisted.
    # We still keep the diagnostic signals available to avoid
    # artificially forcing exact zeros in transitional periods.
    if not detection.sensor_bias:
        sensor_severity *= 0.50

    if not detection.cooling_degradation:
        cooling_severity *= 0.50

    if not detection.mechanical_unbalance:
        unbalance_severity *= 0.50

    overall = max(
        sensor_severity,
        cooling_severity,
        unbalance_severity,
    )

    return {
        "sensor_bias": _clip01(
            sensor_severity
        ),

        "cooling_degradation": _clip01(
            cooling_severity
        ),

        "mechanical_unbalance": _clip01(
            unbalance_severity
        ),

        "overall": _clip01(
            overall
        ),
    }