from control.constrained_adaptive_controller import (
    ConstrainedAdaptiveController,
)


def test_healthy_preserves_load():
    controller = ConstrainedAdaptiveController()
    controller.reset()

    result = controller.update(
        commanded_load_pu=1.0,
        estimated_temperature_C=80.0,
        predicted_temperature_30s_C=82.0,
        predicted_temperature_60s_C=84.0,
        fault_severity=0.0,
        cooling_efficiency=1.0,
        sensor_reliability=1.0,
    )

    assert result.load_command_pu >= 0.99
    assert result.cooling_command_pu == 0.5
    assert result.operating_mode == "NORMAL"


def test_hot_motor_derates():
    controller = ConstrainedAdaptiveController()
    controller.reset()

    result = controller.update(
        commanded_load_pu=1.0,
        estimated_temperature_C=105.0,
        predicted_temperature_30s_C=108.0,
        predicted_temperature_60s_C=110.0,
        fault_severity=0.2,
        cooling_efficiency=0.8,
        sensor_reliability=1.0,
    )

    assert result.load_command_pu < 1.0
    assert result.cooling_command_pu == 1.0
    assert result.operating_mode == "ADAPTIVE_DERATING"


def test_emergency_derating():
    controller = ConstrainedAdaptiveController()
    controller.reset()

    result = controller.update(
        commanded_load_pu=1.0,
        estimated_temperature_C=114.0,
        predicted_temperature_30s_C=117.0,
        predicted_temperature_60s_C=118.0,
        fault_severity=0.8,
        cooling_efficiency=0.5,
        sensor_reliability=0.8,
    )

    assert result.load_command_pu < 1.0
    assert result.cooling_command_pu == 1.0
    assert result.operating_mode == "EMERGENCY_DERATING"
    assert result.safety_margin_C <= 5.0


def test_minimum_service_constraint():
    controller = ConstrainedAdaptiveController()
    controller.reset()

    result = controller.update(
        commanded_load_pu=1.0,
        estimated_temperature_C=120.0,
        predicted_temperature_30s_C=125.0,
        predicted_temperature_60s_C=130.0,
        fault_severity=1.0,
        cooling_efficiency=0.2,
        sensor_reliability=0.5,
    )

    assert result.load_command_pu >= 0.70
    assert result.cooling_command_pu == 1.0
    assert result.operating_mode == "EMERGENCY"