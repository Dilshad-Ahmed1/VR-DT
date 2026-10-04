# MSL Squirrel-Cage Induction Motor Reference

## Active Plant

`models/InductionMotorDigitalTwin18kW.mo` is the repository's only Modelica
plant and is the source for the runtime FMU
`models/InductionMotorDigitalTwin18kW.fmu`. It composes the unmodified
`Modelica.Electrical.Machines.BasicMachines.InductionMachines.IM_SquirrelCage`
from Modelica Standard Library (MSL) 4.1.0 and adds the thermal network,
observable fault inputs, and Digital Twin interface. Nominal validation steps
this same FMU; the repository does not retain a separate validation plant.

The selected benchmark is the MSL `IMC_withLosses` example. MSL describes its
machine as a *standard 18.5 kW, 400 V, 50 Hz motor* and states that simulation
results are compared with measurements. It publishes nominal performance,
losses, an equivalent circuit parameter set, and a load-dependent measured
curve. This complete, traceable set is preferable to guessing missing
equivalent-circuit values for a 5–7.5 kW unit. The benchmark is therefore
larger than the preferred rating. It is not represented as a specific
manufacturer or model: MSL does not identify one.

A published 5.5 kW, 230/400 V motor study was also checked (Nguyen Phuc et
al., *Energies* 13(1), 37 (2020), [doi:10.3390/en13010037](https://doi.org/10.3390/en13010037)).
Its reported ratings do not provide the stator/rotor resistances, leakage and
magnetizing parameters, inertia, and loss breakdown needed to parameterize this
model without assumptions. Its 50 Hz supply is not explicitly specified in the
reported motor data. It therefore does not supply a more complete, verifiable
parameter set than the MSL benchmark and is not used here.

## Source and parameter provenance

The categories below distinguish reference data from modeler choices. Values
described as “MSL reference data” are published in the MSL example; they are
not claimed to be manufacturer nameplate data for an identified product.

| Parameter or value | Value used | Provenance and treatment |
|---|---:|---|
| Rated shaft output, `P_nominal_W` | 18,500 W | MSL reference data (`PNominal`, `Ptable`) |
| Line-to-line RMS voltage, `V_line_nominal_V` | 400 V | MSL reference data (`VNominal`) |
| Nominal line RMS current, `I_line_nominal_A` | 32.85 A | MSL reference data (`INominal`, `Itable`) |
| Nominal power factor, `pf_nominal` | 0.898 | MSL reference data (`pfNominal`) |
| Nominal frequency, `f_nominal_Hz` | 50 Hz | MSL reference data (`fNominal`) |
| Nominal speed, `n_nominal_rpm` | 1462.5 rpm | MSL reference data (`wNominal`) |
| Pole pairs, `pole_pairs` / MSL `p` | 2 (4 poles) | MSL parameter-record default and four-pole synchronous-speed relationship |
| Nominal efficiency | 90.49% | MSL reference data (`etaNominal`) |
| Nominal operating temperature | 90 °C | MSL reference data (`TempNominal`) |
| Stator resistance, `Rs` | 0.56 Ω/phase | MSL reference data |
| Stator resistance reference temperature, `TsRef` | 20 °C | MSL reference data; MSL parameter-record default |
| Stator temperature coefficient, `alpha20s` | 0.003920 1/K | MSL copper constant (`Constants.alpha20Copper`) |
| Stator leakage reactance at 50 Hz | 1.52 Ω | MSL reference data |
| Stator leakage inductance, `Lssigma` | 1.52/(2π·50) = 4.838 mH | Calculated from the documented reactance and frequency |
| Stator zero-sequence inductance, `Lszero` | `Lssigma` | Inherited MSL parameter-record default |
| Main-field reactance at 50 Hz | 66.40 Ω | MSL reference data |
| Main-field inductance, `Lm` | 66.40/(2π·50) = 211.35 mH | Calculated from the documented reactance and frequency |
| Rotor leakage reactance at 50 Hz | 2.31 Ω | MSL reference data |
| Rotor leakage inductance, `Lrsigma` | 2.31/(2π·50) = 7.353 mH | Calculated from the documented reactance and frequency |
| Rotor resistance, `Rr` | 0.42 Ω/phase | MSL reference data |
| Rotor resistance reference temperature, `TrRef` | 20 °C | MSL parameter-record default, consistent with MSL reference table |
| Rotor temperature coefficient, `alpha20r` | 0.004000 1/K | MSL aluminium constant (`Constants.alpha20Aluminium`) |
| Rotor inertia, `Jr` | 0.12 kg·m² | MSL reference data |
| Stator inertia, `Js` | 0.12 kg·m² | Inherited MSL default `Js=Jr`; not a separately measured stator inertia |
| Phase count, `m` | 3 | MSL parameter-record default |
| Effective stator turns | 1 | Inherited MSL parameter-record default |
| Common stator leakage ratio | 1 | Inherited MSL parameter-record default |
| Stator core loss reference, `PRef` | 410 W | MSL reference data |
| Stator core reference voltage, `VRef` | 387.9 V | MSL reference data |
| Stator core reference speed | 2π·50 rad/s | MSL parameter-record default for the 50 Hz machine |
| Core-loss hysteresis ratio | 0 | Inherited MSL default; its source notes hysteresis loss is not implemented |
| Friction reference loss, `PRef` | 180 W | MSL reference data |
| Friction reference speed, `wRef` | 2π·1462.5/60 rad/s | Calculated from MSL nominal speed |
| Friction speed exponent | 2 | Inherited MSL `FrictionParameters` default |
| Friction low-speed linear range | 0.001 of reference speed | Inherited MSL `FrictionParameters` default |
| Stray-load reference loss, `PRef` | 0.005·`P_input_nominal` = 102.19 W | MSL reference formulation; the 0.5% factor is the documented model assumption. The MSL nominal table separately lists 102.22 W. |
| Stray-load reference current, `IRef` | 32.85/√3 A | MSL reference formulation for the delta-connected winding |
| Stray-load reference speed, `wRef` | 2π·1462.5/60 rad/s | Calculated from MSL nominal speed |
| Stray-load speed exponent | 1 | Inherited MSL `StrayLoadParameters` default |
| Ambient temperature | 20 °C | Explicit environmental assumption; not specified by the MSL machine reference |
| External load inertia | 0.12 kg·m² | MSL `IMC_withLosses` example setup uses `loadInertia(J=aimcData.Jr)`; benchmark setup, not a verified application load |
| Initial rotor speed and flux conditions | Rotor initialized at synchronous speed; stator/rotor currents initialized to zero | MSL example initialization convention |

The inductance conversions above use `X=2πfL`. The reference quantities derived
for validation use:

- Synchronous speed: `60 f/p = 1500 rpm`.
- Nominal slip: `(1500 − 1462.5)/1500 = 2.5%`.
- Nominal shaft torque: `18500/(2π·1462.5/60) = 120.79 N·m`.
- MSL's published nominal electrical input and total loss: 20,443.95 W and
  1,943.95 W, respectively; both are directly listed in its nominal table.
- Applying `√3·400·32.85·0.898` to the separately rounded nominal quantities
  gives 20,437.71 W, 6.24 W below the listed input. The model follows the MSL
  example's formula for `P_input_nominal`, `P_loss_nominal`, and the 0.5% stray
  loss reference (102.19 W). The validation uses the explicitly published
  table values, including its 102.22 W stray-loss value. These small source
  rounding discrepancies are disclosed rather than silently reconciled.
- Nominal electromagnetic torque: shaft torque plus MSL friction and stray-load
  loss torque at nominal speed. This is calculated, not a separately published
  MSL nameplate value.

MSL's load curve contains measured samples as well as the nominal parameter
table. At 18.5 kW its measured row reports 1462 rpm, power factor 0.896, and
efficiency 0.9044, while the explicitly designated nominal parameters are
1462.5 rpm, power factor 0.898, and efficiency 0.9049. The nominal validation
uses the nominal parameter table consistently; the measured-curve difference
is retained here rather than silently blended into that operating point.

## Thermal-Model Interpretation and Limitations

The active Twin connects winding losses to a lumped winding thermal mass and
the remaining machine losses to a frame thermal mass. A winding-to-frame
resistance couples the two nodes, and the frame-to-ambient path uses a
configurable conductance. The thermal capacitances and resistances are explicit
model assumptions, not values supplied by the MSL example or an identified
manufacturer.

MSL 4.1.0 documents limitations in its machine-loss thermal implementation:
stator-core losses are not fully implemented in the thermal coupling and
rotor-core losses are not connected/implemented; only winding ohmic losses are
documented as linearly temperature-dependent. The benchmark reports zero rotor
core loss. No verified manufacturer-specific cooling method, thermal
resistance, thermal capacitance, winding temperature rise, insulation class,
or ambient condition is available from this source.

## Active Digital Twin Integration

`models/InductionMotorDigitalTwin18kW.mo` contains the MSL electrical,
electromagnetic, rotational, and loss models, and splits the thermal coupling
into winding and frame masses. Its corresponding isolated FMI 2.0 Co-Simulation
FMU is exported by `scripts/export_induction_fmu.py`. It is the only FMU profile
supported by `simulation/fmu_runtime.py` and the experiment/live-server paths.

| Integration parameter | Value | Provenance |
|---|---:|---|
| Winding thermal capacitance | 15,000 J/K | Explicit lumped-model assumption |
| Frame thermal capacitance | 35,000 J/K | Explicit lumped-model assumption |
| Winding-to-frame resistance | 0.010 K/W | Explicit lumped-model assumption |
| Frame-to-ambient conductance | 33.71 W/K | Calculated to balance MSL reference losses at 90 °C winding and assumed 20 °C ambient, given the winding-frame resistance |
| Initial winding/frame temperatures | 90.0/77.48 °C | Winding value is MSL nominal reference; frame initial condition is calculated from nominal winding losses and the assumed winding-frame resistance |
| Load-torque slew rate / smoothing | 0.2 pu/s / 0.01 pu | Explicit startup/actuator assumptions; a smooth slew limiter ramps commanded load from zero to avoid imposing full shaft load before the unenergized machine develops flux and to avoid a nonsmooth solver event at the target |
| Phase-voltage squared-signal filter | 0.2 s | Explicit diagnostic filter assumption, long enough to suppress the 100 Hz ripple in the filtered squared phase voltages |
| Cooling residual threshold / clear / severity scale | 0.02 / 0.015 / 0.10 °C | Explicit calibration for the noiseless simulated frame-temperature channel; separates the healthy residual seen in the nominal FMU run from the cooling-fault residual. Real sensor noise/accuracy was not verified and these thresholds must be recalibrated for physical sensors. |
| Warning/critical temperatures | 100/120 °C | Inherited controller limits; not verified ratings for this unidentified benchmark motor |
| Nominal winding-loss allocation | 0.644 | Calculated from MSL nominal stator-plus-rotor copper losses divided by total losses; only used to apportion the measured total loss in the reduced-order Twin |

The Twin estimates total losses from current electrical input power minus
current shaft power, then apportions that measured balance into winding and
fixed losses using the documented nominal fraction. The exact MSL component
loss channels are logged under `truth_*` names for simulation validation and
are not passed to the estimator, fault detector, predictor, or controllers.
The observer initializes from present sensor/frame readings and thereafter
uses current measurements and prior observer state; predictions roll that
observer state forward and do not query future FMU values. AAS winding/frame
temperatures and safety margin are observer estimates; the measured winding
sensor channel remains separate.

The injected faults alter specific physical or measurement channels:

| Fault | Mechanism / affected signal |
|---|---|
| Cooling degradation | Reduces frame-to-ambient thermal conductance; also accepts a conductance-resistance multiplier and cooling-flow command |
| Temperature-sensor bias | Adds a bias only to `T_sensor_C`; winding/frame physical states are unchanged |
| Temperature-sensor drift | Ramps an additive bias on `T_sensor_C`; other measured electrical/mechanical channels remain the negative-control signals |
| Sensor freeze | Latches the current winding temperature in the sensor channel on activation; physical temperatures continue evolving |
| Load overload | Scales commanded shaft-load torque before the explicit slew limiter |
| Sudden overload | Steps the commanded `u_load_torque_pu`; the model's slew limiter still bounds the physical torque transient |
| Mechanical friction | Adds speed-opposing torque based on the MSL reference friction torque; it affects rotor dynamics and measured power |
| Bearing-wear proxy | Ramps added mechanical friction only; no bearing geometry, radial vibration, or bearing-adjacent temperature state is modeled |
| Supply voltage degradation | Scales all three phase-source voltage amplitudes |
| Voltage imbalance | Raises phase-A amplitude as a negative-sequence proxy; filtered phase RMS values drive the imbalance measurement |
| Frequency deviation | Multiplies the supply frequency by the requested deviation |
| Mechanical unbalance | Unsupported: this model has rotational rather than radial mechanics; no vibration/unbalance fault is synthesized |

The scenario amplitudes and profile shapes are configured in
`config/twin_config.yaml` and applied by `twin/fault_injector.py`. They are
explicit stress-test inputs, not manufacturer fault limits or statistically
calibrated degradation levels. `sudden_overload` is a commanded load increase,
not a hidden electrical fault parameter.

The induction FMU's OpenModelica 1.27.1 CVODE solver fails for communication
steps above 0.1 s during the tested load transient. `FMURuntime.step()`
therefore subdivides larger Twin control cycles into at-most-0.1-second FMI
steps while holding the current command constant. This is a solver/interface
constraint, not a claim that the motor's physical dynamics are limited to that
interval.

## Validation and reproduction

Run nominal validation against the same generated Twin FMU used by batch and
live execution:

```powershell
.\.venv\Scripts\python.exe scripts\validate_induction_motor_nominal.py
```

The validator reports tail-window deviations and stability checks for the
active Twin FMU. Each run writes a new
`results/induction_motor_nominal/run_*` directory containing `motor_nominal.csv`
and `validation.json`; it does not overwrite prior evaluation results. Export
the FMU first if it is missing. Evaluator unit tests are in
`tests/test_induction_motor_validation.py`.

For the Digital Twin FMU and closed-loop runtime:

```powershell
.\.venv\Scripts\python.exe scripts\export_induction_fmu.py --overwrite
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m experiments.experiment_runner `
  --fmu models\InductionMotorDigitalTwin18kW.fmu `
  --scenario cooling --controller constrained `
  --stop 1800 --step 0.5 --fault-time 600 `
  --output $env:TEMP\induction_motor_cooling.csv
```

Use `experiments/run_evaluation_suite.py` for a timestamped scenario/controller
campaign. The campaign runs only the active induction FMU and stores aggregate
metrics with each run's CSV and log. Run `python -m pytest -q` after modifying
the Twin, its controllers, or fault profiles.

## References

1. Modelica Standard Library 4.1.0,
   [`IMC_withLosses.mo`](https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/Examples/InductionMachines/IMC_withLosses.mo).
   The example attributes its machine parameters to a standard 18.5 kW, 400 V,
   50 Hz motor and compares its simulation with measurements.
2. A. Haumer, C. Kral, H. Kapeller, T. Bäuml, and J. V. Gragger,
   “The AdvancedMachines Library: Loss Models for Electric Machines,”
   *7th International Modelica Conference*, 2009,
   [paper](https://2009.international.conference.modelica.org/proceedings/pages/papers/0103/0103_FI.pdf).
3. Modelica Standard Library 4.1.0,
   [`IM_SquirrelCage`](https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/BasicMachines/InductionMachines/IM_SquirrelCage.mo),
   [`IM_SquirrelCageData`](https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/Utilities/ParameterRecords/IM_SquirrelCageData.mo),
   [`InductionMachineData`](https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/Utilities/ParameterRecords/InductionMachineData.mo),
   and [machine thermal documentation](https://github.com/modelica/ModelicaStandardLibrary/blob/v4.1.0/Modelica/Electrical/Machines/Thermal/package.mo).
