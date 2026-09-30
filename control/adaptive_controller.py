from __future__ import annotations

from .baseline_controller import ControlCommand
from twin.fault_detector import FaultDetection
from twin.fault_severity import _clip01
from twin.predictor import ThermalForecast
from twin.state_estimator import StateEstimate


class FaultAwareAdaptiveController:
    """
    Fault-aware predictive controller.

    Primary objective:
        keep the estimated/predicted winding temperature within the
        safe operating envelope.

    Secondary objectives:
        reduce unnecessary load under detected degradation.

    Sensor bias by itself does NOT trigger aggressive derating because
    the controller relies on the model-based estimated plant state.
    """

    def __init__(
        self,
        minimum_load_pu: float = 0.50,
        reference_load_pu: float = 1.00,
        warning_C: float = 100.0,
        critical_C: float = 120.0,
        max_load_change_per_step_pu: float = 0.05,
    ) -> None:

        self.minimum_load_pu = (
            minimum_load_pu
        )

        self.reference_load_pu = (
            reference_load_pu
        )

        self.warning_C = warning_C
        self.critical_C = critical_C

        self.max_delta = (
            max_load_change_per_step_pu
        )

        self.previous_load = (
            reference_load_pu
        )

    @staticmethod
    def _thermal_risk(
        temperature_C: float,
        warning_C: float,
        critical_C: float,
    ) -> float:

        return _clip01(
            (
                temperature_C
                - warning_C
            )
            / (
                critical_C
                - warning_C
            )
        )

    def compute(
        self,
        estimate: StateEstimate,
        detection: FaultDetection,
        severity: dict[str, float],
        forecast: ThermalForecast,
    ) -> ControlCommand:

        # -------------------------------------------------------------
        # 1. Predictive thermal risk
        # -------------------------------------------------------------

        risk_current = self._thermal_risk(
            estimate.estimated_winding_C,
            self.warning_C,
            self.critical_C,
        )

        risk_30 = self._thermal_risk(
            forecast.predicted_30s_C,
            self.warning_C,
            self.critical_C,
        )

        risk_60 = self._thermal_risk(
            forecast.predicted_60s_C,
            self.warning_C,
            self.critical_C,
        )

        thermal_risk = max(
            risk_current,
            risk_30,
            risk_60,
        )

        # Give the 60 s prediction additional influence because it
        # represents longer-term thermal risk.
        predictive_risk = max(
            risk_current,
            0.85 * risk_30,
            0.95 * risk_60,
        )

        # -------------------------------------------------------------
        # 2. Thermal-risk-driven derating
        # -------------------------------------------------------------

        # Near 120 °C -> strong derating.
        thermal_derate = (
            0.80 * predictive_risk
        )

        # -------------------------------------------------------------
        # 3. Cooling degradation penalty
        # -------------------------------------------------------------

        cooling_severity = (
            severity.get(
                "cooling_degradation",
                0.0,
            )
        )

        cooling_penalty = (
            0.12 * cooling_severity
        )

        # -------------------------------------------------------------
        # 4. Mechanical unbalance penalty
        # -------------------------------------------------------------

        unbalance_severity = (
            severity.get(
                "mechanical_unbalance",
                0.0,
            )
        )

        unbalance_penalty = (
            0.08 * unbalance_severity
        )

        # -------------------------------------------------------------
        # 5. Sensor bias
        # -------------------------------------------------------------

        #
        # IMPORTANT:
        #
        # A sensor bias is a sensing fault, not automatically a
        # thermal plant fault.
        #
        # If estimated/forecast temperature is safe, don't throw away
        # useful production merely because T_sensor is offset.
        #

        sensor_penalty = 0.0

        # In a sensor-bias + thermal-risk situation, we still let the
        # thermal risk dominate.
        if (
            detection.sensor_bias
            and predictive_risk > 0.0
        ):
            sensor_penalty = (
                0.03 * predictive_risk
            )

        # -------------------------------------------------------------
        # 6. Combined target
        # -------------------------------------------------------------

        total_derate = (
            thermal_derate
            + cooling_penalty
            + unbalance_penalty
            + sensor_penalty
        )

        target_load = (
            self.reference_load_pu
            - total_derate
        )

        target_load = max(
            self.minimum_load_pu,
            min(
                self.reference_load_pu,
                target_load,
            ),
        )

        # -------------------------------------------------------------
        # 7. Emergency condition
        # -------------------------------------------------------------

        if (
            forecast.predicted_60s_C
            >= self.critical_C
        ):

            target_load = (
                self.minimum_load_pu
            )

        # -------------------------------------------------------------
        # 8. Rate limiting
        # -------------------------------------------------------------

        delta = max(
            -self.max_delta,
            min(
                self.max_delta,
                target_load
                - self.previous_load,
            ),
        )

        commanded_load = (
            self.previous_load
            + delta
        )

        commanded_load = max(
            self.minimum_load_pu,
            min(
                self.reference_load_pu,
                commanded_load,
            ),
        )

        self.previous_load = (
            commanded_load
        )

        return ControlCommand(
            load_pu=commanded_load,
            speed_pu=1.0,
            cooling_flow_pu=1.0,
        )