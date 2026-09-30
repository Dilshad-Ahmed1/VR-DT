from dataclasses import dataclass


@dataclass
class ControllerOutput:
    load_command_pu: float
    cooling_command_pu: float
    operating_mode: str
    derating_fraction: float
    predicted_temperature_C: float
    safety_margin_C: float


class ConstrainedAdaptiveController:
    """
    Safety-constrained adaptive controller for the motor Digital Twin.

    Design principles:
    1. Preserve nominal 1.0 pu operation when the motor is thermally safe.
    2. Do not derate merely because a fault is detected.
    3. Use predicted thermal trajectory as the primary intervention signal.
    4. Use fault severity to increase conservatism only when thermal risk exists.
    5. Increase cooling before unnecessarily reducing useful load.
    6. Apply progressive load derating as the predicted temperature approaches
       the critical operating limit.
    7. Maintain a minimum service load during emergency operation.
    """

    def __init__(
        self,
        critical_temperature_C: float = 120.0,
        warning_temperature_C: float = 100.0,
        intervention_temperature_C: float = 90.0,
        minimum_load_pu: float = 0.70,
        maximum_load_pu: float = 1.00,
        minimum_cooling_pu: float = 0.50,
        maximum_cooling_pu: float = 1.00,
        safety_buffer_C: float = 5.0,
        severity_gain: float = 0.10,
        temperature_gain: float = 0.05,
        recovery_rate: float = 0.025,
        derating_rate: float = 0.08,
    ):
        self.critical_temperature_C = critical_temperature_C
        self.warning_temperature_C = warning_temperature_C
        self.intervention_temperature_C = intervention_temperature_C

        self.minimum_load_pu = minimum_load_pu
        self.maximum_load_pu = maximum_load_pu

        self.minimum_cooling_pu = minimum_cooling_pu
        self.maximum_cooling_pu = maximum_cooling_pu

        self.safety_buffer_C = safety_buffer_C

        self.severity_gain = severity_gain
        self.temperature_gain = temperature_gain

        self.recovery_rate = recovery_rate
        self.derating_rate = derating_rate

        self.current_load_command_pu = maximum_load_pu
        self.current_cooling_command_pu = minimum_cooling_pu

    def reset(self):
        self.current_load_command_pu = self.maximum_load_pu
        self.current_cooling_command_pu = self.minimum_cooling_pu

    @staticmethod
    def _clip(value, lower, upper):
        return max(lower, min(upper, value))

    def update(
        self,
        commanded_load_pu: float,
        estimated_temperature_C: float,
        predicted_temperature_30s_C: float,
        predicted_temperature_60s_C: float,
        fault_severity: float,
        cooling_efficiency: float,
        sensor_reliability: float = 1.0,
    ) -> ControllerOutput:

        commanded_load_pu = self._clip(
            commanded_load_pu,
            self.minimum_load_pu,
            self.maximum_load_pu,
        )

        fault_severity = self._clip(
            fault_severity,
            0.0,
            1.0,
        )

        cooling_efficiency = self._clip(
            cooling_efficiency,
            0.05,
            1.0,
        )

        sensor_reliability = self._clip(
            sensor_reliability,
            0.0,
            1.0,
        )

        # ------------------------------------------------------------
        # 1. Conservative thermal prediction
        # ------------------------------------------------------------
        predicted_temperature_C = max(
            estimated_temperature_C,
            predicted_temperature_30s_C,
            predicted_temperature_60s_C,
        )

        safety_limit_C = (
            self.critical_temperature_C
            - self.safety_buffer_C
        )

        safety_margin_C = (
            self.critical_temperature_C
            - predicted_temperature_C
        )

        # ------------------------------------------------------------
        # 2. Determine whether intervention is actually required
        # ------------------------------------------------------------
        thermal_risk = max(
            0.0,
            (
                predicted_temperature_C
                - self.intervention_temperature_C
            )
            / (
                self.critical_temperature_C
                - self.intervention_temperature_C
            ),
        )

        thermal_risk = self._clip(
            thermal_risk,
            0.0,
            1.0,
        )

        # ------------------------------------------------------------
        # 3. Nominal operation
        #
        # Fault detection alone must NOT cause aggressive derating.
        # This prevents cases such as sensor-bias causing unnecessary
        # load reduction while the actual winding temperature is safe.
        # ------------------------------------------------------------
        target_load = commanded_load_pu

        # ------------------------------------------------------------
        # 4. Thermal-risk-based derating
        #
        # No derating below intervention temperature.
        # Progressive derating above intervention temperature.
        # ------------------------------------------------------------
        if predicted_temperature_C > self.intervention_temperature_C:

            temperature_excess = (
                predicted_temperature_C
                - self.intervention_temperature_C
            )

            temperature_span = (
                safety_limit_C
                - self.intervention_temperature_C
            )

            temperature_derating = (
                temperature_excess
                / max(temperature_span, 1e-9)
            )

            temperature_derating = self._clip(
                temperature_derating,
                0.0,
                1.0,
            )

            # Progressive thermal derating.
            target_load *= (
                1.0
                - self.temperature_gain
                * temperature_derating
                * 10.0
            )

        # ------------------------------------------------------------
        # 5. Fault severity contribution
        #
        # Severity contributes only when there is already measurable
        # thermal risk. This avoids unnecessary derating in healthy
        # operation and prevents sensor faults from dominating control.
        # ------------------------------------------------------------
        if thermal_risk > 0.0:

            severity_factor = (
                self.severity_gain
                * fault_severity
                * thermal_risk
            )

            target_load *= (
                1.0 - severity_factor
            )

        # ------------------------------------------------------------
        # 6. Sensor reliability contribution
        #
        # Reduced sensor confidence slightly increases conservatism,
        # but only when thermal risk already exists.
        # ------------------------------------------------------------
        if thermal_risk > 0.0:

            reliability_penalty = (
                1.0 - sensor_reliability
            )

            reliability_factor = (
                0.05
                * reliability_penalty
                * thermal_risk
            )

            target_load *= (
                1.0 - reliability_factor
            )

        # ------------------------------------------------------------
        # 7. Cooling degradation
        #
        # Cooling degradation primarily causes increased cooling
        # command. It should not immediately cause load derating.
        # ------------------------------------------------------------
        cooling_degraded = cooling_efficiency < 0.80

        # ------------------------------------------------------------
        # 8. Safety constraint
        #
        # Once predicted temperature reaches the buffered critical
        # limit, progressively enforce stronger derating.
        # ------------------------------------------------------------
        emergency = (
            predicted_temperature_C
            >= safety_limit_C
        )

        critical = (
            predicted_temperature_C
            >= self.critical_temperature_C
        )

        if critical:

            target_load = self.minimum_load_pu

        elif emergency:

            emergency_excess = max(
                0.0,
                predicted_temperature_C
                - self.warning_temperature_C,
            )

            emergency_range = (
                safety_limit_C
                - self.warning_temperature_C
            )

            emergency_derating = self._clip(
                emergency_excess
                / max(emergency_range, 1e-9),
                0.0,
                1.0,
            )

            target_load = (
                self.minimum_load_pu
                + (
                    self.maximum_load_pu
                    - self.minimum_load_pu
                )
                * (1.0 - emergency_derating)
            )

        target_load = self._clip(
            target_load,
            self.minimum_load_pu,
            self.maximum_load_pu,
        )

        # ------------------------------------------------------------
        # 9. Rate-limit load changes
        # ------------------------------------------------------------
        if target_load < self.current_load_command_pu:

            self.current_load_command_pu = max(
                target_load,
                self.current_load_command_pu
                - self.derating_rate,
            )

        else:

            self.current_load_command_pu = min(
                target_load,
                self.current_load_command_pu
                + self.recovery_rate,
            )

        self.current_load_command_pu = self._clip(
            self.current_load_command_pu,
            self.minimum_load_pu,
            self.maximum_load_pu,
        )

        # ------------------------------------------------------------
        # 10. Cooling control
        #
        # Healthy / thermally safe:
        #     minimum cooling.
        #
        # Thermal risk / degraded cooling:
        #     maximum cooling.
        #
        # Emergency:
        #     maximum cooling.
        # ------------------------------------------------------------
        if (
            predicted_temperature_C
            >= self.intervention_temperature_C
            or cooling_degraded
            or fault_severity >= 0.50
        ):
            cooling_command = self.maximum_cooling_pu
        else:
            cooling_command = self.minimum_cooling_pu

        if emergency:
            cooling_command = self.maximum_cooling_pu

        self.current_cooling_command_pu = self._clip(
            cooling_command,
            self.minimum_cooling_pu,
            self.maximum_cooling_pu,
        )

        # ------------------------------------------------------------
        # 11. Operating mode
        # ------------------------------------------------------------
        if critical:

            operating_mode = "EMERGENCY"

        elif emergency:

            operating_mode = "EMERGENCY_DERATING"

        elif predicted_temperature_C >= self.warning_temperature_C:

            operating_mode = "ADAPTIVE_DERATING"

        elif predicted_temperature_C >= self.intervention_temperature_C:

            operating_mode = "THERMAL_PREVENTION"

        elif cooling_degraded or fault_severity >= 0.50:

            operating_mode = "FAULT_AWARE"

        else:

            operating_mode = "NORMAL"

        # ------------------------------------------------------------
        # 12. Actual derating fraction
        # ------------------------------------------------------------
        derating_fraction = self._clip(
            1.0
            - (
                self.current_load_command_pu
                / max(commanded_load_pu, 1e-9)
            ),
            0.0,
            1.0,
        )

        return ControllerOutput(
            load_command_pu=self.current_load_command_pu,
            cooling_command_pu=self.current_cooling_command_pu,
            operating_mode=operating_mode,
            derating_fraction=derating_fraction,
            predicted_temperature_C=predicted_temperature_C,
            safety_margin_C=safety_margin_C,
        )