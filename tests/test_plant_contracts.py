from pathlib import Path

import pytest

from communication.simulated import SimulatedCommunication
from plant.interface import ControlCommand, PlantInterface, PlantState
from plant.simulated.fmu_plant import FMUPlant
from server.twin_pipeline import TwinPipeline


FMU_PATH = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "InductionMotorDigitalTwin18kW.fmu"
)


class FakePlant(PlantInterface):
    def __init__(self):
        self.state = PlantState(
            timestamp_s=0.0,
            speed_rpm=1460.0,
            temperature_C=45.0,
            current_A=10.0,
            voltage_V=400.0,
            electrical_power_W=6000.0,
            load_torque_Nm=35.0,
        )
        self.last_command = None

    def start(self):
        return self.state

    def stop(self):
        return None

    def reset(self):
        return None

    def read_state(self):
        return self.state

    def send_command(self, command):
        self.last_command = command

    def step(self, step_s):
        return self.state


def test_state_model_contains_observations_only():
    state = PlantState(
        timestamp_s=1.0,
        speed_rpm=1460.0,
        temperature_C=50.0,
        current_A=10.0,
        voltage_V=400.0,
        electrical_power_W=6000.0,
        load_torque_Nm=35.0,
    )

    measurement = state.as_measurement()

    assert measurement["T_sensor_C"] == 50.0
    assert "f_sensor_bias_C" not in measurement
    assert "T_winding_C" not in measurement


def test_simulated_transport_delegates_to_any_plant():
    plant = FakePlant()
    transport = SimulatedCommunication(plant)
    command = ControlCommand(load_torque_pu=0.8, command_id="test-1")

    transport.send_command(command)

    assert plant.last_command is command
    assert transport.read_state().speed_rpm == 1460.0


@pytest.mark.skipif(not FMU_PATH.is_file(), reason="Induction FMU is not available")
def test_fmu_plant_maps_measured_channels_without_truth_leakage():
    plant = FMUPlant(FMU_PATH, stop_time_s=0.2)
    try:
        state = plant.start()
        observation = state.as_measurement()

        assert state.voltage_V == pytest.approx(400.0, rel=0.02)
        assert state.supply_frequency_Hz == pytest.approx(50.0)
        assert state.vibration_mm_s is None
        assert "T_winding_C" not in observation
        assert "thermal_margin_to_critical_K" not in observation
        assert "f_sensor_bias_C" not in observation
        assert observation["P_loss_total_W"] == pytest.approx(
            max(0.0, state.electrical_power_W - (state.shaft_power_W or 0.0))
        )
    finally:
        plant.stop()


def test_twin_pipeline_stamps_commands_with_observation_identity():
    measurement = {
        "timestamp_s": 0.0,
        "T_sensor_C": 90.0,
        "T_frame_C": 78.0,
        "T_ambient_C": 20.0,
        "P_electrical_W": 20000.0,
        "P_shaft_W": 18500.0,
        "P_loss_total_W": 1500.0,
        "I_rms_A": 32.85,
        "speed_rpm": 1462.5,
        "omega_rad_s": 1462.5 * 2.0 * 3.141592653589793 / 60.0,
        "torque_load_Nm": 120.8,
        "torque_motor_Nm": 123.0,
        "line_voltage_rms_V": 400.0,
        "supply_frequency_Hz": 50.0,
        "power_factor": 0.898,
        "voltage_unbalance_percent": 0.0,
        "current_pu": 1.0,
        "load_torque_pu": 1.0,
        "vibration_mm_s_out": 0.0,
        "mechanical_unbalance_supported": 0.0,
    }
    pipeline = TwinPipeline(controller_name="baseline")
    pipeline.reset(measurement)

    first = pipeline.tick(
        measurement,
        ControlCommand(load_torque_pu=1.0),
        0.5,
    ).command
    measurement["timestamp_s"] = 0.5
    second = pipeline.tick(
        measurement,
        first,
        0.5,
    ).command

    assert first.timestamp_s == 0.0
    assert second.timestamp_s == 0.5
    assert first.command_id
    assert second.command_id != first.command_id
    assert first.source == "controller:baseline"