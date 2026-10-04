from __future__ import annotations

from dataclasses import dataclass

from .state_estimator import ThermalStateEstimator


@dataclass
class ThermalForecast:
    predicted_30s_C: float
    predicted_60s_C: float


class ThermalPredictor:
    """Forward thermal trajectory predictor using the same reduced-order DT model."""

    def __init__(self, estimator: ThermalStateEstimator) -> None:
        self.estimator = estimator

    def _rollout(
        self,
        horizon_s: float,
        measurement: dict[str, float],
        cooling_flow_pu: float,
        cooling_effectiveness: float,
    ) -> float:
        Tw = self.estimator.Tw_C
        Tf = self.estimator.Tf_C
        dt = 0.5
        steps = max(1, int(round(horizon_s / dt)))
        ambient = self.estimator.ambient_C
        rwf = self.estimator.rwf
        rfa = self.estimator.rfa
        cw = self.estimator.cw
        cf = self.estimator.cf

        pw, pf = self.estimator._losses(measurement)
        cooling_flow = max(0.0, min(1.0, cooling_flow_pu))
        cooling_denominator = max(
            0.05,
            self.estimator.cooling_flow_offset
            + self.estimator.cooling_flow_gain * cooling_flow,
        ) * max(0.05, min(1.0, cooling_effectiveness))
        rfa_actual = rfa / cooling_denominator

        for _ in range(steps):
            q_wf = (Tw - Tf) / rwf
            q_fa = (Tf - ambient) / rfa_actual
            Tw += ((pw - q_wf) / cw) * dt
            Tf += ((pf + q_wf - q_fa) / cf) * dt
        return Tw

    def predict(
        self,
        measurement: dict[str, float],
        cooling_flow_pu: float,
        cooling_effectiveness: float = 1.0,
    ) -> ThermalForecast:
        return ThermalForecast(
            predicted_30s_C=self._rollout(
                30.0,
                measurement,
                cooling_flow_pu,
                cooling_effectiveness,
            ),
            predicted_60s_C=self._rollout(
                60.0,
                measurement,
                cooling_flow_pu,
                cooling_effectiveness,
            ),
        )
