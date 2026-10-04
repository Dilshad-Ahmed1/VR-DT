within ;
package MotorDigitalTwin
  model VariableThermalConductance
    "Two-port thermal element with an externally controlled conductance"
    parameter Modelica.Units.SI.ThermalConductance G_min=1e-6;

    Modelica.Thermal.HeatTransfer.Interfaces.HeatPort_a port_a;
    Modelica.Thermal.HeatTransfer.Interfaces.HeatPort_b port_b;
    Modelica.Blocks.Interfaces.RealInput G(unit="W/K");

  equation
    port_a.Q_flow =
      max(G_min, G)*(port_a.T - port_b.T);
    port_b.Q_flow = -port_a.Q_flow;
  end VariableThermalConductance;

  model InductionMotorDigitalTwin18kW
    "MSL induction-motor plant adapted to the Digital Twin FMI contract"

    import Modelica.Constants.pi;
    import Modelica.Units.SI;
    import Modelica.Electrical.Machines.Thermal.Constants;
    import Modelica.Electrical.Machines.Utilities.ParameterRecords
      .IM_SquirrelCageData;

    parameter SI.Power P_nominal_W=18500;
    parameter SI.Voltage V_line_nominal_V=400;
    parameter SI.Current I_line_nominal_A=32.85;
    parameter Real pf_nominal=0.898;
    parameter SI.Frequency f_nominal_Hz=50;
    parameter Real n_nominal_rpm=1462.5;
    parameter Integer pole_pairs=2;

    parameter SI.Temperature T_ambient_nominal=293.15;
    parameter SI.Temperature T_winding_start=363.15;
    parameter SI.HeatCapacity C_winding=15000
      "Lumped winding heat capacity; explicit model assumption";
    parameter SI.HeatCapacity C_frame=35000
      "Lumped frame heat capacity; explicit model assumption";
    parameter SI.ThermalResistance R_winding_frame=0.010
      "Winding-to-frame thermal resistance; explicit model assumption";
    parameter SI.Temperature T_critical_C=120
      "Inherited controller safety threshold; not a verified motor limit";
    parameter SI.Time phase_rms_filter_time=0.2
      "Filter time constant for phase RMS voltage diagnostics";
    parameter Real load_torque_ramp_rate_pu_s=0.2
      "Torque-actuator slew-rate assumption used for energized startup";
    parameter Real load_torque_ramp_smoothing_pu=0.01
      "Smooths the load-actuator slew limiter near its target";

    final parameter SI.AngularVelocity omega_nominal =
      2*pi*n_nominal_rpm/60;
    final parameter SI.AngularVelocity omega_synchronous =
      2*pi*f_nominal_Hz/pole_pairs;
    final parameter SI.Torque T_shaft_nominal =
      P_nominal_W/omega_nominal;
    final parameter SI.Power P_input_nominal =
      sqrt(3)*V_line_nominal_V*I_line_nominal_A*pf_nominal;
    final parameter SI.Power P_loss_nominal =
      P_input_nominal-P_nominal_W;
    final parameter SI.Power P_winding_loss_nominal =
      770.13+481.60;
    final parameter SI.Temperature T_frame_nominal =
      T_winding_start-P_winding_loss_nominal*R_winding_frame;
    final parameter SI.ThermalConductance G_frame_ambient_nominal =
      P_loss_nominal/(T_frame_nominal-T_ambient_nominal);

    parameter IM_SquirrelCageData machineData(
        statorCoreParameters(PRef=410, VRef=387.9),
        Jr=0.12,
        Rs=0.56,
        alpha20s=Constants.alpha20Copper,
        Lssigma=1.52/(2*pi*f_nominal_Hz),
        frictionParameters(PRef=180, wRef=omega_nominal),
        strayLoadParameters(
          PRef=0.005*P_input_nominal,
          IRef=I_line_nominal_A/sqrt(3),
          wRef=omega_nominal),
        Lm=66.4/(2*pi*f_nominal_Hz),
        Lrsigma=2.31/(2*pi*f_nominal_Hz),
        Rr=0.42,
        alpha20r=Constants.alpha20Aluminium);

    input Real u_load_torque_pu(min=0, max=1.5)=1.0;
    input Real u_speed_pu(min=0.5, max=1.1)=1.0
      "V/f supply command retained for Digital Twin compatibility";
    input Real u_cooling_flow_pu(min=0, max=1)=1.0;
    input Real u_ambient_C(min=-20, max=60)=20;

    input Real f_sensor_bias_C=0;
    input Boolean f_sensor_freeze=false;
    input Real f_cooling_eff(min=0.05, max=1)=1;
    input Real f_rth_degradation(min=1, max=5)=1;
    input Real f_load_overload_pu(min=0, max=0.5)=0;
    input Real f_mechanical_friction_factor(min=1, max=10)=1;
    input Real f_voltage_unbalance_pu(min=0, max=0.1)=0
      "Negative-sequence proxy: phase-A amplitude increases by 3 times this value";
    input Real f_supply_voltage_degradation_pu(min=0, max=0.2)=0;
    input Real f_supply_frequency_deviation_pu(min=-0.1, max=0.1)=0;

    Modelica.Electrical.Machines.BasicMachines.InductionMachines.IM_SquirrelCage
      motor(
        p=pole_pairs,
        fsNominal=f_nominal_Hz,
        Rs=machineData.Rs,
        TsRef=machineData.TsRef,
        alpha20s=machineData.alpha20s,
        Lszero=machineData.Lszero,
        Lssigma=machineData.Lssigma,
        Jr=machineData.Jr,
        Js=machineData.Js,
        frictionParameters=machineData.frictionParameters,
        statorCoreParameters=machineData.statorCoreParameters,
        strayLoadParameters=machineData.strayLoadParameters,
        Lm=machineData.Lm,
        Lrsigma=machineData.Lrsigma,
        Rr=machineData.Rr,
        TrRef=machineData.TrRef,
        alpha20r=machineData.alpha20r,
        TsOperational=T_winding_start,
        TrOperational=T_winding_start,
        useThermalPort=true,
        phiMechanical(fixed=true),
        wMechanical(fixed=true, start=omega_synchronous));

    Modelica.Electrical.Machines.Utilities.TerminalBox terminalBox(
      terminalConnection="D");
    Modelica.Electrical.Machines.Sensors.CurrentQuasiRMSSensor currentSensor;
    Modelica.Electrical.Machines.Sensors.ElectricalPowerSensor
      electricalPowerSensor;
    Modelica.Electrical.Machines.Sensors.VoltageQuasiRMSSensor voltageSensor;
    Modelica.Electrical.Polyphase.Sources.SignalVoltage supply(final m=3);
    Modelica.Electrical.Polyphase.Basic.Star neutral(final m=3);
    Modelica.Electrical.Analog.Basic.Ground ground;
    Modelica.Electrical.Polyphase.Sensors.VoltageSensor phaseVoltageSensor(
      final m=3);

    Modelica.Mechanics.Rotational.Sensors.PowerSensor shaftPowerSensor;
    Modelica.Mechanics.Rotational.Components.Inertia loadInertia(
      J=machineData.Jr);
    Modelica.Mechanics.Rotational.Sources.Torque loadTorque(useSupport=false);
    Modelica.Mechanics.Rotational.Sources.Torque degradationFriction(
      useSupport=false);

    Modelica.Thermal.HeatTransfer.Components.HeatCapacitor windingThermalMass(
      C=C_winding,
      T(start=T_winding_start, fixed=true));
    Modelica.Thermal.HeatTransfer.Components.HeatCapacitor frameThermalMass(
      C=C_frame,
      T(start=T_frame_nominal, fixed=true));
    Modelica.Thermal.HeatTransfer.Components.ThermalConductor windingToFrame(
      G=1/R_winding_frame);
    VariableThermalConductance frameToAmbient;
    Modelica.Thermal.HeatTransfer.Sources.PrescribedTemperature ambient;
    Modelica.Blocks.Sources.RealExpression ambientCommand(
      y=u_ambient_C+273.15);
    Modelica.Blocks.Sources.RealExpression frameConductanceCommand(
      y=G_frame_ambient_nominal*cooling_effectiveness);
    Modelica.Blocks.Sources.RealExpression loadTorqueCommand(
      y=-T_shaft_nominal*load_torque_pu);
    Modelica.Blocks.Sources.RealExpression degradationFrictionCommand(
      y=-extra_friction_torque_Nm);

    Real phase_voltage_mean_square[3](
      each start=(V_line_nominal_V/sqrt(3))^2/2,
      each fixed=true);
    Real phase_voltage_rms_V[3];
    Real phase_voltage_mean_V;
    SI.Angle supply_phase(start=0, fixed=true);
    Real load_torque_target_pu;
    Real load_torque_pu(
      start=0,
      fixed=true,
      stateSelect=StateSelect.always);
    Real supply_voltage_pu;
    SI.Torque extra_friction_torque_Nm;
    SI.Power extra_friction_loss_W;
    discrete SI.Temperature frozen_sensor_temperature(
      start=T_winding_start,
      fixed=true);

    output SI.Temperature T_winding_K=windingThermalMass.T;
    output SI.Temperature T_frame_K=frameThermalMass.T;
    output SI.Temperature T_ambient_K=ambient.T;
    output Real T_winding_C=T_winding_K-273.15;
    output Real T_frame_C=T_frame_K-273.15;
    output Real T_ambient_C=T_ambient_K-273.15;
    output Real T_sensor_C;
    output SI.AngularVelocity omega_rad_s=motor.wMechanical;
    output Real speed_rpm=omega_rad_s*60/(2*pi);
    output Real torque_load_Nm=load_torque_pu*T_shaft_nominal;
    output SI.Torque torque_motor_Nm=motor.tauElectrical;
    output SI.Power P_electrical_W=electricalPowerSensor.P;
    output SI.Power P_shaft_W=shaftPowerSensor.power;
    output SI.Power P_motor_losses_W=motor.powerBalance.lossPowerTotal;
    output SI.Power P_winding_losses_W=
      motor.powerBalance.lossPowerStatorWinding
        +motor.powerBalance.lossPowerRotorWinding;
    output SI.Power P_fixed_losses_W=
      motor.powerBalance.lossPowerTotal
        -motor.powerBalance.lossPowerStatorWinding
        -motor.powerBalance.lossPowerRotorWinding;
    output SI.Power P_loss_total_W=P_motor_losses_W+extra_friction_loss_W;
    output SI.Current I_rms_A=currentSensor.I;
    output Real current_pu=I_rms_A/I_line_nominal_A;
    output Real power_factor=
      if noEvent(abs(electricalPowerSensor.P)>Modelica.Constants.small)
      then electricalPowerSensor.P/
        sqrt(electricalPowerSensor.P^2+electricalPowerSensor.Q^2)
      else 0;
    output SI.Power reactive_power_var=electricalPowerSensor.Q;
    output SI.Frequency supply_frequency_Hz=
      f_nominal_Hz*min(1.1, max(0.5, u_speed_pu))
        *(1+f_supply_frequency_deviation_pu);
    output SI.Voltage line_voltage_rms_V=sqrt(3)*voltageSensor.V;
    output Real voltage_unbalance_percent=
      100*max(abs(phase_voltage_rms_V[1]-phase_voltage_mean_V),
        max(abs(phase_voltage_rms_V[2]-phase_voltage_mean_V),
          abs(phase_voltage_rms_V[3]-phase_voltage_mean_V)))
        /max(phase_voltage_mean_V, Modelica.Constants.small);
    output Real cooling_effectiveness=
      min(1, max(0.05,
        u_cooling_flow_pu*f_cooling_eff/f_rth_degradation));
    output Real thermal_margin_to_critical_K=
      T_critical_C-T_winding_C;
    output Integer thermal_state=
      if T_winding_C>=T_critical_C then 2
      elseif T_winding_C>=100 then 1
      else 0;
    output Real vibration_mm_s_out=0
      "Unavailable: this rotational-only plant has no radial vibration model";
    output Boolean mechanical_unbalance_supported=false;

  initial equation
    motor.i_0_s=0.0;
    der(motor.idq_sr)=fill(0.0, 2);
    der(motor.idq_rr)=fill(0.0, 2);
    frozen_sensor_temperature=T_winding_K;

  equation
    load_torque_target_pu=min(1.5,
      max(0, u_load_torque_pu*(1+f_load_overload_pu)));
    der(load_torque_pu)=load_torque_ramp_rate_pu_s
      *tanh((load_torque_target_pu-load_torque_pu)
        /load_torque_ramp_smoothing_pu);
    supply_voltage_pu=
      min(1.1, max(0.5, u_speed_pu))
        *(1-min(0.2, max(0, f_supply_voltage_degradation_pu)));
    extra_friction_torque_Nm=
      max(0, f_mechanical_friction_factor-1)
        *machineData.frictionParameters.tauRef
        *Modelica.Math.tanh(motor.wMechanical/0.1);
    extra_friction_loss_W=
      extra_friction_torque_Nm*abs(motor.wMechanical);
    der(supply_phase)=2*pi*supply_frequency_Hz;
    supply.v={
      sqrt(2/3)*V_line_nominal_V*supply_voltage_pu
        *(1+3*min(0.1, max(0, f_voltage_unbalance_pu)))
        *sin(supply_phase),
      sqrt(2/3)*V_line_nominal_V*supply_voltage_pu
        *sin(supply_phase-2*pi/3),
      sqrt(2/3)*V_line_nominal_V*supply_voltage_pu
        *sin(supply_phase+2*pi/3)};

    for phase in 1:3 loop
      der(phase_voltage_mean_square[phase])=
        (phaseVoltageSensor.v[phase]^2
          -phase_voltage_mean_square[phase])
          /phase_rms_filter_time;
      phase_voltage_rms_V[phase]=
        sqrt(2*max(0, phase_voltage_mean_square[phase]));
    end for;
    phase_voltage_mean_V=
      sum(phase_voltage_rms_V)/3;

    when edge(f_sensor_freeze) then
      frozen_sensor_temperature=pre(T_winding_K);
    end when;
    T_sensor_C=
      (if f_sensor_freeze then frozen_sensor_temperature else T_winding_K)
        -273.15+f_sensor_bias_C;

    connect(supply.plug_p,currentSensor.plug_p);
    connect(currentSensor.plug_n,electricalPowerSensor.plug_p);
    connect(electricalPowerSensor.plug_ni,terminalBox.plugSupply);
    connect(electricalPowerSensor.plug_nv,neutral.plug_p);
    connect(supply.plug_n,neutral.plug_p);
    connect(neutral.pin_n,ground.p);
    connect(terminalBox.plug_sp,motor.plug_sp);
    connect(terminalBox.plug_sn,motor.plug_sn);
    connect(voltageSensor.plug_p,supply.plug_p);
    connect(voltageSensor.plug_n,supply.plug_n);
    connect(phaseVoltageSensor.plug_p,supply.plug_p);
    connect(phaseVoltageSensor.plug_n,neutral.plug_p);

    connect(motor.flange,shaftPowerSensor.flange_a);
    connect(shaftPowerSensor.flange_b,loadInertia.flange_a);
    connect(loadInertia.flange_b,loadTorque.flange);
    connect(loadInertia.flange_a,degradationFriction.flange);
    connect(loadTorqueCommand.y,loadTorque.tau);
    connect(degradationFrictionCommand.y,degradationFriction.tau);

    for phase in 1:3 loop
      connect(
        motor.thermalPort.heatPortStatorWinding[phase],
        windingThermalMass.port);
    end for;
    connect(motor.thermalPort.heatPortRotorWinding,windingThermalMass.port);
    connect(motor.thermalPort.heatPortStatorCore,frameThermalMass.port);
    connect(motor.thermalPort.heatPortRotorCore,frameThermalMass.port);
    connect(motor.thermalPort.heatPortStrayLoad,frameThermalMass.port);
    connect(motor.thermalPort.heatPortFriction,frameThermalMass.port);
    connect(windingThermalMass.port,windingToFrame.port_a);
    connect(windingToFrame.port_b,frameThermalMass.port);
    connect(frameThermalMass.port,frameToAmbient.port_a);
    connect(ambient.port,frameToAmbient.port_b);
    connect(ambientCommand.y,ambient.T);
    connect(frameConductanceCommand.y,frameToAmbient.G);

    annotation(
      experiment(StartTime=0, StopTime=8, Interval=0.001, Tolerance=1e-6));
  end InductionMotorDigitalTwin18kW;
end MotorDigitalTwin;
