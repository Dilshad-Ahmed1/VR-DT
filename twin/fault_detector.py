from __future__ import annotations

from dataclasses import dataclass

from .state_estimator import StateEstimate


@dataclass
class FaultDetection:
    sensor_bias: bool
    cooling_degradation: bool
    mechanical_unbalance: bool

    thermal_warning: bool

    any_fault: bool
    primary_fault: str

    alarm: bool


class FaultDetector:
    """
    Stateful rule-based diagnostic layer.

    Detection requires persistence across multiple control cycles.
    Hysteresis prevents alarm chatter.
    """

    def __init__(
        self,
        sensor_bias_threshold_C: float = 6.0,
        sensor_bias_clear_C: float = 4.0,
        cooling_residual_threshold_C: float = 3.0,
        cooling_clear_C: float = 1.5,
        vibration_warning_mm_s: float = 2.8,
        vibration_clear_mm_s: float = 2.4,
        estimated_temp_warning_C: float = 100.0,
        persistence_cycles: int = 2,
    ) -> None:

        self.sensor_bias_threshold_C = (
            sensor_bias_threshold_C
        )

        self.sensor_bias_clear_C = (
            sensor_bias_clear_C
        )

        self.cooling_residual_threshold_C = (
            cooling_residual_threshold_C
        )

        self.cooling_clear_C = (
            cooling_clear_C
        )

        self.vibration_warning_mm_s = (
            vibration_warning_mm_s
        )

        self.vibration_clear_mm_s = (
            vibration_clear_mm_s
        )

        self.estimated_temp_warning_C = (
            estimated_temp_warning_C
        )

        self.persistence_cycles = max(
            1,
            int(persistence_cycles),
        )

        self._sensor_counter = 0
        self._cooling_counter = 0
        self._unbalance_counter = 0

        self._sensor_active = False
        self._cooling_active = False
        self._unbalance_active = False

    @staticmethod
    def _persistent_update(
        condition: bool,
        clear_condition: bool,
        counter: int,
        active: bool,
        required_cycles: int,
    ) -> tuple[int, bool]:

        if active:

            if clear_condition:
                counter = 0
                active = False

            return counter, active

        if condition:

            counter += 1

            if counter >= required_cycles:
                active = True
                counter = 0

        else:
            counter = 0

        return counter, active

    def detect(
        self,
        estimate: StateEstimate,
        measurement: dict[str, float],
    ) -> FaultDetection:

        vibration = float(
            measurement.get(
                "vibration_mm_s_out",
                0.0,
            )
        )

        # -------------------------------------------------------------
        # Sensor bias
        # -------------------------------------------------------------

        abs_sensor_residual = abs(
            estimate.sensor_residual_C
        )

        sensor_condition = (
            abs_sensor_residual
            >= self.sensor_bias_threshold_C
        )

        sensor_clear = (
            abs_sensor_residual
            < self.sensor_bias_clear_C
        )

        (
            self._sensor_counter,
            self._sensor_active,
        ) = self._persistent_update(
            sensor_condition,
            sensor_clear,
            self._sensor_counter,
            self._sensor_active,
            self.persistence_cycles,
        )

        # -------------------------------------------------------------
        # Cooling degradation
        #
        # Use the PRE-CORRECTION frame innovation.
        # -------------------------------------------------------------

        frame_innovation = (
            estimate.frame_innovation_C
        )

        cooling_condition = (
            frame_innovation
            >= self.cooling_residual_threshold_C
        )

        cooling_clear = (
            frame_innovation
            < self.cooling_clear_C
        )

        (
            self._cooling_counter,
            self._cooling_active,
        ) = self._persistent_update(
            cooling_condition,
            cooling_clear,
            self._cooling_counter,
            self._cooling_active,
            self.persistence_cycles,
        )

        # -------------------------------------------------------------
        # Mechanical unbalance
        # -------------------------------------------------------------

        unbalance_condition = (
            vibration
            >= self.vibration_warning_mm_s
        )

        unbalance_clear = (
            vibration
            < self.vibration_clear_mm_s
        )

        (
            self._unbalance_counter,
            self._unbalance_active,
        ) = self._persistent_update(
            unbalance_condition,
            unbalance_clear,
            self._unbalance_counter,
            self._unbalance_active,
            self.persistence_cycles,
        )

        # -------------------------------------------------------------
        # Thermal safety state
        # -------------------------------------------------------------

        thermal_warning = (
            estimate.estimated_winding_C
            >= self.estimated_temp_warning_C
        )

        any_fault = (
            self._sensor_active
            or self._cooling_active
            or self._unbalance_active
        )

        # Safety alarm is allowed to exist because of either:
        #   diagnostic fault
        #   thermal warning
        alarm = any_fault or thermal_warning

        if self._cooling_active:
            primary = "cooling_degradation"

        elif self._unbalance_active:
            primary = "mechanical_unbalance"

        elif self._sensor_active:
            primary = "sensor_bias"

        elif thermal_warning:
            primary = "thermal_risk"

        else:
            primary = "healthy"

        return FaultDetection(
            sensor_bias=self._sensor_active,
            cooling_degradation=self._cooling_active,
            mechanical_unbalance=self._unbalance_active,
            thermal_warning=thermal_warning,
            any_fault=any_fault,
            primary_fault=primary,
            alarm=alarm,
        )