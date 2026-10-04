from __future__ import annotations

from dataclasses import dataclass

from .state_estimator import StateEstimate


@dataclass
class FaultDetection:
    sensor_bias: bool
    sensor_freeze: bool
    cooling_degradation: bool
    mechanical_unbalance: bool
    load_overload: bool
    mechanical_friction: bool
    supply_degradation: bool
    voltage_imbalance: bool
    frequency_deviation: bool

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
        voltage_imbalance_warning_percent: float = 2.0,
        frequency_deviation_warning_Hz: float = 0.25,
        overload_current_pu: float = 1.05,
        overload_torque_pu: float = 1.05,
        friction_excess_warning_W: float = 100.0,
        supply_voltage_minimum_pu: float = 0.95,
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
        self._freeze_counter = 0
        self._overload_counter = 0
        self._friction_counter = 0
        self._supply_counter = 0
        self._voltage_unbalance_counter = 0
        self._frequency_counter = 0

        self._sensor_active = False
        self._freeze_active = False
        self._cooling_active = False
        self._unbalance_active = False
        self._overload_active = False
        self._friction_active = False
        self._supply_active = False
        self._voltage_unbalance_active = False
        self._frequency_active = False
        self._previous_sensor_C: float | None = None

        self.voltage_imbalance_warning_percent = (
            voltage_imbalance_warning_percent
        )
        self.frequency_deviation_warning_Hz = (
            frequency_deviation_warning_Hz
        )
        self.overload_current_pu = overload_current_pu
        self.overload_torque_pu = overload_torque_pu
        self.friction_excess_warning_W = friction_excess_warning_W
        self.supply_voltage_minimum_pu = supply_voltage_minimum_pu

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

        sensor_C = float(measurement["T_sensor_C"])
        sensor_unchanged = (
            self._previous_sensor_C is not None
            and abs(sensor_C - self._previous_sensor_C) <= 1e-9
        )
        self._previous_sensor_C = sensor_C

        estimated_rate = abs(estimate.estimated_winding_rate_C_s)
        freeze_condition = sensor_unchanged and estimated_rate >= 1e-4
        freeze_clear = not sensor_unchanged or estimated_rate < 1e-5
        self._freeze_counter, self._freeze_active = self._persistent_update(
            freeze_condition,
            freeze_clear,
            self._freeze_counter,
            self._freeze_active,
            max(3, self.persistence_cycles),
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

        current_pu = float(measurement.get("current_pu", 0.0))
        load_torque_pu = float(measurement.get("load_torque_pu", 0.0))
        overload_condition = (
            current_pu >= self.overload_current_pu
            and load_torque_pu >= self.overload_torque_pu
        )
        self._overload_counter, self._overload_active = self._persistent_update(
            overload_condition,
            current_pu < 1.02 or load_torque_pu < 1.01,
            self._overload_counter,
            self._overload_active,
            self.persistence_cycles,
        )

        friction_excess_W = float(
            measurement.get("friction_excess_estimate_W", 0.0)
        )
        friction_condition = (
            friction_excess_W >= self.friction_excess_warning_W
        )
        self._friction_counter, self._friction_active = self._persistent_update(
            friction_condition,
            friction_excess_W < 0.5 * self.friction_excess_warning_W,
            self._friction_counter,
            self._friction_active,
            self.persistence_cycles,
        )

        rated_voltage = float(measurement.get("rated_voltage_line_line_V", 0.0))
        voltage = float(measurement.get("line_voltage_rms_V", rated_voltage))
        supply_voltage_pu = (
            voltage / rated_voltage if rated_voltage > 0.0 else 1.0
        )
        supply_condition = supply_voltage_pu < self.supply_voltage_minimum_pu
        self._supply_counter, self._supply_active = self._persistent_update(
            supply_condition,
            supply_voltage_pu > self.supply_voltage_minimum_pu + 0.02,
            self._supply_counter,
            self._supply_active,
            self.persistence_cycles,
        )

        voltage_unbalance = float(
            measurement.get("voltage_unbalance_percent", 0.0)
        )
        voltage_unbalance_condition = (
            voltage_unbalance >= self.voltage_imbalance_warning_percent
        )
        self._voltage_unbalance_counter, self._voltage_unbalance_active = (
            self._persistent_update(
                voltage_unbalance_condition,
                voltage_unbalance
                < 0.75 * self.voltage_imbalance_warning_percent,
                self._voltage_unbalance_counter,
                self._voltage_unbalance_active,
                self.persistence_cycles,
            )
        )

        frequency = float(
            measurement.get(
                "supply_frequency_Hz",
                measurement.get("rated_frequency_Hz", 50.0),
            )
        )
        rated_frequency = float(
            measurement.get("rated_frequency_Hz", 50.0)
        )
        frequency_error = abs(frequency - rated_frequency)
        frequency_condition = (
            frequency_error >= self.frequency_deviation_warning_Hz
        )
        self._frequency_counter, self._frequency_active = (
            self._persistent_update(
                frequency_condition,
                frequency_error
                < 0.5 * self.frequency_deviation_warning_Hz,
                self._frequency_counter,
                self._frequency_active,
                self.persistence_cycles,
            )
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
            or self._freeze_active
            or self._cooling_active
            or self._unbalance_active
            or self._overload_active
            or self._friction_active
            or self._supply_active
            or self._voltage_unbalance_active
            or self._frequency_active
        )

        # Safety alarm is allowed to exist because of either:
        #   diagnostic fault
        #   thermal warning
        alarm = any_fault or thermal_warning

        if self._cooling_active:
            primary = "cooling_degradation"

        elif self._overload_active:
            primary = "load_overload"

        elif self._friction_active:
            primary = "mechanical_friction"

        elif self._voltage_unbalance_active:
            primary = "voltage_imbalance"

        elif self._frequency_active:
            primary = "frequency_deviation"

        elif self._supply_active:
            primary = "supply_degradation"

        elif self._unbalance_active:
            primary = "mechanical_unbalance"

        elif self._freeze_active:
            primary = "sensor_freeze"

        elif self._sensor_active:
            primary = "sensor_bias"

        elif thermal_warning:
            primary = "thermal_risk"

        else:
            primary = "healthy"

        return FaultDetection(
            sensor_bias=self._sensor_active,
            sensor_freeze=self._freeze_active,
            cooling_degradation=self._cooling_active,
            mechanical_unbalance=self._unbalance_active,
            load_overload=self._overload_active,
            mechanical_friction=self._friction_active,
            supply_degradation=self._supply_active,
            voltage_imbalance=self._voltage_unbalance_active,
            frequency_deviation=self._frequency_active,
            thermal_warning=thermal_warning,
            any_fault=any_fault,
            primary_fault=primary,
            alarm=alarm,
        )