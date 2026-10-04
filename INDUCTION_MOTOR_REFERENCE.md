# MSL Squirrel-Cage Induction Motor Reference

## Active Plant

`models/InductionMotorDigitalTwin18kW.mo` is the sole Modelica plant. It
composes the Modelica Standard Library (MSL) 4.1.0 `IM_SquirrelCage` machine
using the `IMC_withLosses` 18.5 kW benchmark and adds the thermal network,
fault inputs, and FMI interface. The corresponding runtime FMU is
`models/InductionMotorDigitalTwin18kW.fmu`; it is generated locally and
ignored by Git. Nominal validation steps this same FMU, not a separate
validation plant.

MSL describes the benchmark as a standard 18.5 kW, 400 V, 50 Hz motor and
compares its simulation with measurements. It does not identify a manufacturer
or commercial product. Do not describe this model as a specific manufacturer
motor.

## Reference Data and Provenance

| Quantity | Value | Source/interpretation |
|---|---:|---|
| Rated shaft output | 18,500 W | MSL `IMC_withLosses` benchmark |
| Line voltage | 400 V RMS | MSL benchmark |
| Line current | 32.85 A RMS | MSL benchmark |
| Supply frequency | 50 Hz | MSL benchmark |
| Pole pairs | 2 (4 poles) | MSL machine setup |
| Rated speed | 1462.5 rpm | MSL nominal parameters |
| Synchronous speed | 1500 rpm | 50 Hz, four-pole relationship |
| Rated slip | 2.5% | Derived from nominal and synchronous speeds |
| Power factor | 0.898 | MSL nominal parameters |
| Efficiency | 90.49% | MSL nominal parameters |
| Nominal input power | 20,443.95 W | MSL nominal table |
| Nominal total losses | 1,943.95 W | MSL nominal table |
| Nominal winding temperature | 90 C | MSL benchmark parameter |
| Shaft torque | 120.795 N m | Derived from output power and nominal speed |

The electrical machine uses MSL benchmark equivalent-circuit values, including
stator resistance 0.56 ohm/phase, rotor resistance 0.42 ohm/phase, stator
leakage reactance 1.52 ohm, main-field reactance 66.40 ohm, and rotor leakage
reactance 2.31 ohm at 50 Hz. Corresponding inductances are derived using
`X = 2*pi*f*L`. Rotor inertia is 0.12 kg m^2; the MSL parameter record also
uses that value for stator inertia by default. See the model's `machineData`
record and the MSL 4.1.0 `IMC_withLosses` source for the full parameter set.

MSL's nominal table and its measured load curve differ slightly because the
values are rounded and represent different sources. The nominal validation
uses the nominal parameter table consistently. The validator records those
reference values and tolerances in `scripts/validate_induction_motor_nominal.py`.

## Modeler Assumptions

The following are not manufacturer or MSL thermal ratings:

- Winding thermal capacitance: 15,000 J/K.
- Frame thermal capacitance: 35,000 J/K.
- Winding-to-frame thermal resistance: 0.010 K/W.
- Frame-to-ambient conductance: approximately 33.71 W/K, calculated to
  balance nominal losses at the 90 C winding condition and assumed 20 C ambient.
- Ambient temperature: 20 C.
- Load-torque ramp/smoothing and phase-RMS diagnostic filter settings.
- Fault magnitudes, profile shapes, diagnostic thresholds, and 100/120 C
  controller thresholds.

MSL documents limitations in its machine-loss/thermal coupling. The extra
lumped thermal network is a reduced-order integration assumption, not a
validated winding hot-spot model. The inherited controller temperature limits
must not be represented as verified limits for a physical asset.

## Supported Physical Phenomena

The plant accepts temperature-sensor bias/freeze, cooling degradation,
frame-to-ambient resistance degradation, overload, sudden load increase,
mechanical friction increase, supply-voltage degradation, phase-voltage
imbalance proxy, and supply-frequency deviation. Scenario profiles are defined
in `config/twin_config.yaml` and applied by `faults/physical.py`.

The machine is rotational-only. It has no radial dynamics, vibration sensor,
or mechanical-unbalance model. `bearing_wear_proxy` adds friction only; it is
not a bearing geometry or vibration simulation. Voltage imbalance is a
negative-sequence phase-voltage proxy based on one phase's amplitude and
filtered phase RMS values, not a detailed winding-fault model.

Physical fault values are injected into the simulated plant and separately
recorded for offline evaluation. They are not included in `PlantState`, the
twin estimator/controller input, or the AAS snapshot. The plant's observable
temperature is the sensor channel; true winding temperature and true thermal
margin are available only through simulation evaluation output.

## Nominal FMU Validation

Run:

```powershell
.venv\Scripts\python.exe scripts\validate_induction_motor_nominal.py
```

The current local FMU passed all nominal deviation and stability checks over a
30-second run. The 25-30 second mean was 400.000 V, 32.856 A, 1462.920 rpm,
18,505.314 W shaft power, 90.518% efficiency, 0.8981 power factor, and
89.767 C lumped winding temperature. This is numerical agreement with the MSL
benchmark under the validator tolerances, not hardware validation.

The generated FMU uses OpenModelica 1.27.1 with MSL 4.1.0 and FMI 2.0
Co-Simulation. In the current environment its CVODE solver is stepped in
subintervals no longer than 0.1 s during a Twin communication cycle.

## References

1. Modelica Standard Library 4.1.0, `IMC_withLosses` example:
   https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/Examples/InductionMachines/IMC_withLosses.mo
2. A. Haumer et al., "The AdvancedMachines Library: Loss Models for Electric
   Machines," 7th International Modelica Conference, 2009:
   https://2009.international.conference.modelica.org/proceedings/pages/papers/0103/0103_FI.pdf
3. Modelica Standard Library 4.1.0 `IM_SquirrelCage` and machine parameter
   records:
   https://github.com/modelica/ModelicaStandardLibrary/tree/v4.1.0/Modelica/Electrical/Machines