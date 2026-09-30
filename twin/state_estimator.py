from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StateEstimate:
    estimated_winding_C: float
    estimated_frame_C: float
    estimated_winding_rate_C_s: float

    # Sensor measurement innovation.
    sensor_residual_C: float

    # Frame-model innovation BEFORE observer correction.
    frame_innovation_C: float

    # Residual AFTER observer correction.
    frame_model_residual_C: float


class ThermalStateEstimator:
    """
    Reduced-order model-based thermal observer.

    Important design rule:
    the observer never receives hidden FMU fault parameters such as
    cooling efficiency, Rth degradation, sensor bias, or unbalance.
    """

    def __init__(
        self,
        ambient_C: float = 25.0,
        r_winding_frame_K_W: float = 0.0400,
        r_frame_ambient_K_W: float = 0.086672,
        c_winding_J_K: float = 1500.0,
        c_frame_J_K: float = 9000.0,
        winding_loss_fraction: float = 0.60,
        fixed_loss_fraction: float = 0.40,
        initial_winding_C: float = 30.0,
        initial_frame_C: float = 27.0,
        correction_gain: float = 0.35,
    ) -> None:

        self.ambient_C = ambient_C

        self.rwf = r_winding_frame_K_W
        self.rfa = r_frame_ambient_K_W

        self.cw = c_winding_J_K
        self.cf = c_frame_J_K

        self.winding_loss_fraction = winding_loss_fraction
        self.fixed_loss_fraction = fixed_loss_fraction

        self.correction_gain = correction_gain

        self.Tw_C = initial_winding_C
        self.Tf_C = initial_frame_C

        self.prev_Tw_C = initial_winding_C

        self.initialized = False

    def initialize_from_measurement(
        self,
        measurement: dict[str, float],
    ) -> None:
        """
        Align the observer once during healthy startup.
        """

        self.Tw_C = float(
            measurement["T_sensor_C"]
        )

        self.Tf_C = float(
            measurement["T_frame_C"]
        )

        self.prev_Tw_C = self.Tw_C

        self.initialized = True

    @staticmethod
    def _losses(
        measurement: dict[str, float],
    ) -> tuple[float, float]:

        p_electrical = max(
            0.0,
            float(
                measurement.get(
                    "P_electrical_W",
                    0.0,
                )
            ),
        )

        p_shaft = max(
            0.0,
            float(
                measurement.get(
                    "P_shaft_W",
                    0.0,
                )
            ),
        )

        total_loss = max(
            0.0,
            p_electrical - p_shaft,
        )

        return (
            total_loss * 0.60,
            total_loss * 0.40,
        )

    def update(
        self,
        measurement: dict[str, float],
        cooling_flow_pu: float,
        dt_s: float,
    ) -> StateEstimate:

        if dt_s <= 0.0:
            raise ValueError(
                "dt_s must be > 0"
            )

        if not self.initialized:
            raise RuntimeError(
                "Estimator must be initialized first."
            )

        sensor_C = float(
            measurement["T_sensor_C"]
        )

        frame_measured_C = float(
            measurement["T_frame_C"]
        )

        winding_loss_W, fixed_loss_W = (
            self._losses(measurement)
        )

        # -------------------------------------------------------------
        # Nominal thermal model
        # -------------------------------------------------------------

        flow = max(
            0.0,
            min(
                1.0,
                float(cooling_flow_pu),
            ),
        )

        cooling_denominator = max(
            0.10,
            0.10 + 0.90 * flow,
        )

        rfa_actual = (
            self.rfa /
            cooling_denominator
        )

        q_wf = (
            self.Tw_C - self.Tf_C
        ) / self.rwf

        q_fa = (
            self.Tf_C - self.ambient_C
        ) / rfa_actual

        dTw = (
            winding_loss_W - q_wf
        ) / self.cw

        dTf = (
            fixed_loss_W
            + q_wf
            - q_fa
        ) / self.cf

        # -------------------------------------------------------------
        # Observer prediction
        # -------------------------------------------------------------

        previous_Tw = self.Tw_C

        predicted_Tw = (
            self.Tw_C
            + dTw * dt_s
        )

        predicted_Tf = (
            self.Tf_C
            + dTf * dt_s
        )

        # -------------------------------------------------------------
        # Innovations
        # -------------------------------------------------------------

        sensor_residual = (
            sensor_C
            - predicted_Tw
        )

        frame_innovation = (
            frame_measured_C
            - predicted_Tf
        )

        # -------------------------------------------------------------
        # Correct observable frame state only
        # -------------------------------------------------------------

        corrected_Tf = (
            predicted_Tf
            + self.correction_gain
            * frame_innovation
        )

        # Keep winding state model-based.
        self.Tw_C = predicted_Tw
        self.Tf_C = corrected_Tf

        rate = (
            self.Tw_C
            - previous_Tw
        ) / dt_s

        frame_post_correction_residual = (
            frame_measured_C
            - self.Tf_C
        )

        return StateEstimate(
            estimated_winding_C=self.Tw_C,
            estimated_frame_C=self.Tf_C,
            estimated_winding_rate_C_s=rate,
            sensor_residual_C=sensor_residual,
            frame_innovation_C=frame_innovation,
            frame_model_residual_C=frame_post_correction_residual,
        )