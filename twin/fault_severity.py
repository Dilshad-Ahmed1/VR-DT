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
    if detection.sensor_freeze:
        sensor_severity *= 0.25

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
        / max(
            1e-9,
            float(measurement.get("cooling_severity_scale_C", 5.0)),
        )
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

    unbalance_supported = bool(
        measurement.get("mechanical_unbalance_supported", True)
    )
    unbalance_severity = (
        _clip01(max(0.0, vibration - 1.0) / 4.0)
        if unbalance_supported
        else 0.0
    )

    overload_severity = _clip01(
        max(
            float(measurement.get("current_pu", 1.0)) - 1.0,
            float(measurement.get("load_torque_pu", 1.0)) - 1.0,
        )
        / 0.5
    )

    rated_output_W = max(
        1.0,
        float(measurement.get("rated_output_W", 1.0)),
    )
    friction_severity = _clip01(
        max(0.0, float(measurement.get("friction_excess_estimate_W", 0.0)))
        / (0.05 * rated_output_W)
    )

    rated_voltage = float(
        measurement.get("rated_voltage_line_line_V", 0.0)
    )
    line_voltage = float(
        measurement.get("line_voltage_rms_V", rated_voltage)
    )
    supply_severity = (
        _clip01(max(0.0, 1.0 - line_voltage / rated_voltage) / 0.10)
        if rated_voltage > 0.0
        else 0.0
    )

    voltage_unbalance_severity = _clip01(
        max(0.0, float(measurement.get("voltage_unbalance_percent", 0.0)))
        / 5.0
    )

    rated_frequency = float(
        measurement.get("rated_frequency_Hz", 50.0)
    )
    measured_frequency = float(
        measurement.get("supply_frequency_Hz", rated_frequency)
    )
    frequency_severity = _clip01(
        abs(measured_frequency - rated_frequency) / 1.0
    )

    freeze_severity = (
        1.0 if detection.sensor_freeze else 0.0
    )
    cooling_degradation_severity = (
        cooling_severity if detection.cooling_degradation else cooling_severity * 0.5
    )
    overload_severity = (
        overload_severity if detection.load_overload else overload_severity * 0.5
    )
    friction_severity = (
        friction_severity
        if detection.mechanical_friction
        else friction_severity * 0.5
    )
    supply_severity = (
        supply_severity
        if detection.supply_degradation
        else supply_severity * 0.5
    )
    voltage_unbalance_severity = (
        voltage_unbalance_severity
        if detection.voltage_imbalance
        else voltage_unbalance_severity * 0.5
    )
    frequency_severity = (
        frequency_severity
        if detection.frequency_deviation
        else frequency_severity * 0.5
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
        freeze_severity,
        cooling_degradation_severity,
        unbalance_severity,
        overload_severity,
        friction_severity,
        supply_severity,
        voltage_unbalance_severity,
        frequency_severity,
    )

    return {
        "sensor_bias": _clip01(
            sensor_severity
        ),

        "cooling_degradation": _clip01(
            cooling_degradation_severity
        ),

        "mechanical_unbalance": _clip01(
            unbalance_severity
        ),

        "sensor_freeze": _clip01(freeze_severity),
        "load_overload": _clip01(overload_severity),
        "mechanical_friction": _clip01(friction_severity),
        "supply_degradation": _clip01(supply_severity),
        "voltage_imbalance": _clip01(voltage_unbalance_severity),
        "frequency_deviation": _clip01(frequency_severity),
        "overall": _clip01(
            overall
        ),
    }