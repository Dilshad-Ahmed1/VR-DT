within ;
package MotorDigitalTwin

  model MotorElectroThermalMechanicalFaultable
    "Reduced-order WEG W22 5.5 kW electro-thermal-mechanical digital twin"

    // ============================================================
    // MANUFACTURER / REFERENCE MOTOR DATA
    // WEG W22 IE3 - Product 13332532
    // 5.5 kW, 4-pole, 132S, 3-phase, 230/400 V, 50 Hz
    // ============================================================

    parameter Real P_rated_W = 5500.0;
    parameter Real V_rated_LL_V = 400.0;
    parameter Real I_rated_A = 10.9;
    parameter Real f_rated_Hz = 50.0;
    parameter Integer poles = 4;

    parameter Real n_rated_rpm = 1460.0;
    parameter Real eta_rated = 0.897;
    parameter Real pf_rated = 0.81;

    parameter Real J_rotor_kg_m2 = 0.0491;

    parameter Real omega_rated_rad_s =
      2.0*Modelica.Constants.pi*n_rated_rpm/60.0;

    parameter Real T_rated_Nm =
      P_rated_W/omega_rated_rad_s;

    parameter Real temperature_rise_rated_K = 80.0;


    // ============================================================
    // REDUCED-ORDER THERMAL MODEL
    // ============================================================

    parameter Real T_ambient_C = 25.0;

    parameter Real C_winding_J_K = 1500.0;
    parameter Real C_frame_J_K = 9000.0;

    // Engineering/model-calibration assumptions.
    parameter Real winding_loss_fraction = 0.60;
    parameter Real fixed_loss_fraction = 0.40;
    parameter Real fixed_loss_no_load_factor = 0.80;

    // Derived from manufacturer rated output and efficiency.
    parameter Real P_loss_rated_W =
      P_rated_W*(1.0/eta_rated - 1.0);

    parameter Real P_winding_loss_rated_W =
      winding_loss_fraction*P_loss_rated_W;

    // Engineering/model-calibration assumption.
    parameter Real Rth_winding_frame_K_W = 0.0400;

    // Calibrated so rated winding temperature rise is 80 K.
    parameter Real Rth_frame_ambient_K_W =
      (
        temperature_rise_rated_K
        - P_winding_loss_rated_W
          *Rth_winding_frame_K_W
      )
      /P_loss_rated_W;


    // ============================================================
    // REDUCED-ORDER MECHANICAL MODEL
    // ============================================================

    parameter Real B_friction_Nm_s = 0.002;

    // Engineering/model-calibration assumption:
    // characteristic mechanical response time.
    parameter Real mechanical_response_time_s = 2.0;

    parameter Real K_speed_Nm_s =
      J_rotor_kg_m2/mechanical_response_time_s;

    parameter Real max_torque_pu = 1.50;


    // ============================================================
    // RUNTIME CONTROL / FAULT INPUTS
    // ============================================================

    input Real u_load_torque_pu(
      min=0.0,
      max=1.5) = 1.0;

    input Real u_speed_pu(
      min=0.5,
      max=1.1) = 1.0;

    input Real u_cooling_flow_pu(
      min=0.0,
      max=1.0) = 1.0;

    input Real f_sensor_bias_C = 0.0;

    input Boolean f_sensor_freeze = false;

    input Real f_cooling_eff(
      min=0.05,
      max=1.0) = 1.0;

    input Real f_rth_degradation(
      min=1.0,
      max=5.0) = 1.0;

    input Real f_unbalance_severity(
      min=0.0,
      max=1.0) = 0.0;

    // Reduced-order electrical-fault approximation. This is not a
    // phase-resolved induction-machine model; it increases loss and exposes
    // an imbalance indicator while leaving the vibration channel unchanged.
    input Real f_voltage_imbalance_pu(
      min=0.0,
      max=0.2) = 0.0;


    // ============================================================
    // INTERNAL STATES
    // ============================================================

    Real T_winding(
      start=T_ambient_C + 5.0 + 273.15,
      fixed=true,
      stateSelect=StateSelect.always);

    Real T_frame(
      start=T_ambient_C + 2.0 + 273.15,
      fixed=true,
      stateSelect=StateSelect.always);

    Real omega_mech(
      start=omega_rated_rad_s,
      fixed=true,
      stateSelect=StateSelect.always);

    discrete Real T_frozen_val(
      start=T_ambient_C + 5.0 + 273.15);


    // ============================================================
    // INTERNAL SIGNALS
    // ============================================================

    Real load_pu;
    Real speed_cmd_pu;
    Real cooling_flow_pu;

    Real omega_ref;

    Real tau_load;
    Real tau_motor;

    Real P_winding_loss;
    Real P_fixed_loss;
    Real P_loss_total;

    Real P_shaft;
    Real P_electrical;
    Real I_rms;

    Real Rth_frame_ambient_actual;

    Real vibration_mm_s;


    // ============================================================
    // PUBLIC OUTPUTS / MEASUREMENT CHANNELS
    // ============================================================

    output Real T_winding_C =
      T_winding - 273.15;

    output Real T_frame_C =
      T_frame - 273.15;

    output Real T_sensor_C;

    output Real omega_rad_s =
      omega_mech;

    output Real speed_rpm =
      omega_mech
      *60.0
      /(2.0*Modelica.Constants.pi);

    output Real torque_load_Nm =
      tau_load;

    output Real torque_motor_Nm =
      tau_motor;

    output Real P_electrical_W =
      P_electrical;

    output Real P_shaft_W =
      P_shaft;

    output Real P_loss_total_W =
      P_loss_total;

    output Real I_rms_A =
      I_rms;

    output Real current_ripple_percent =
      100.0*f_voltage_imbalance_pu;

    output Real power_factor =
      pf_rated;

    output Real vibration_mm_s_out =
      vibration_mm_s;

    output Real thermal_margin_to_critical_K =
      120.0 - T_winding_C;

    output Integer thermal_state =
      if T_winding_C >= 120.0 then 2
      elseif T_winding_C >= 100.0 then 1
      else 0;


    // ============================================================
    // INITIAL CONDITIONS
    // ============================================================

  initial equation

    T_frozen_val = T_winding;


    // ============================================================
    // EQUATIONS
    // ============================================================

  equation

    // ------------------------------------------------------------
    // Clamp external commands at plant boundary
    // ------------------------------------------------------------

    load_pu =
      min(
        max(
          u_load_torque_pu,
          0.0),
        1.5);

    speed_cmd_pu =
      min(
        max(
          u_speed_pu,
          0.5),
        1.1);

    cooling_flow_pu =
      min(
        max(
          u_cooling_flow_pu,
          0.0),
        1.0);

    omega_ref =
      omega_rated_rad_s
      *speed_cmd_pu;


    // ------------------------------------------------------------
    // Reduced-order mechanical dynamics
    //
    // The speed-control term is selected from an explicit
    // mechanical response-time assumption rather than an arbitrary
    // large gain.
    //
    // At nominal conditions the equilibrium speed is exactly the
    // reference speed because the friction compensation uses
    // B_friction * omega_ref.
    // ------------------------------------------------------------

    tau_load =
      load_pu*T_rated_Nm;

    tau_motor =
      min(
        max(
          tau_load
          + B_friction_Nm_s*omega_ref
          + K_speed_Nm_s
            *(omega_ref - omega_mech),
          0.0),
        max_torque_pu*T_rated_Nm);

    J_rotor_kg_m2*der(omega_mech) =
      tau_motor
      - tau_load
      - B_friction_Nm_s*omega_mech;


    // ------------------------------------------------------------
    // Reduced-order loss model
    // ------------------------------------------------------------

    P_winding_loss =
      winding_loss_fraction
      *P_loss_rated_W
      *(load_pu^2);

    P_fixed_loss =
      fixed_loss_fraction
      *P_loss_rated_W
      *(
        fixed_loss_no_load_factor
        +(1.0 - fixed_loss_no_load_factor)
         *(load_pu^2)
      );

    P_loss_total =
      (P_winding_loss
       +P_fixed_loss)
      *(1.0 + 4.0*f_voltage_imbalance_pu);


    // ------------------------------------------------------------
    // Mechanical and electrical power
    // ------------------------------------------------------------

    P_shaft =
      max(
        0.0,
        tau_load*omega_mech);

    P_electrical =
      max(
        0.0,
        P_shaft + P_loss_total);

    I_rms =
      I_rated_A
      *sqrt(
        max(
          0.0,
          P_electrical
          /(P_rated_W/eta_rated)
        )
      );


    // ------------------------------------------------------------
    // Cooling degradation
    //
    // max() provides a numerical guard during FMU initialization
    // when external inputs may temporarily have zero/default values.
    // ------------------------------------------------------------

    Rth_frame_ambient_actual =
      Rth_frame_ambient_K_W
      *max(
        1.0,
        f_rth_degradation)
      /
      max(
        0.10,
        (
          0.10
          +0.90
           *cooling_flow_pu
           *max(
             0.05,
             f_cooling_eff)
        )
      );


    // ------------------------------------------------------------
    // Two-node lumped thermal network
    // ------------------------------------------------------------

    C_winding_J_K*der(T_winding) =
      P_winding_loss
      -(T_winding - T_frame)
       /Rth_winding_frame_K_W;

    C_frame_J_K*der(T_frame) =
      P_fixed_loss
      +(T_winding - T_frame)
       /Rth_winding_frame_K_W
      -(
        T_frame
        -(T_ambient_C + 273.15)
       )
       /Rth_frame_ambient_actual;


    // ------------------------------------------------------------
    // Sensor fault
    // ------------------------------------------------------------

    when edge(f_sensor_freeze) then
      T_frozen_val = T_winding;
    end when;

    T_sensor_C =
      if f_sensor_freeze then
        T_frozen_val
        -273.15
        +f_sensor_bias_C
      else
        T_winding
        -273.15
        +f_sensor_bias_C;


    // ------------------------------------------------------------
    // Research vibration channel
    //
    // These thresholds are experimental parameters and are NOT
    // claimed to be WEG manufacturer specifications.
    // ------------------------------------------------------------

    vibration_mm_s =
      1.0
      +4.0
       *f_unbalance_severity
       *load_pu
       *(
         max(
           omega_mech,
           1.0)
         /omega_rated_rad_s
        )^2;

  end MotorElectroThermalMechanicalFaultable;

end MotorDigitalTwin;