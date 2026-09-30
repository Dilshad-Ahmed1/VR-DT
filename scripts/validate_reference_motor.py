from __future__ import annotations

import math
from pathlib import Path

import yaml


def main() -> int:
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "twin_config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    motor = cfg["reference_motor"]
    published = motor["published"]
    derived = motor["derived"]

    rated_speed_rpm = published["rated_speed_rpm"]
    rated_output_W = published["rated_output_W"]
    rated_efficiency = published["efficiency_percent_at_100pct_load"] / 100.0

    omega = 2.0 * math.pi * rated_speed_rpm / 60.0

    # Derived from P = T * omega.
    torque_from_power = rated_output_W / omega

    # Manufacturer catalog torque is published in kgf·m.
    torque_from_catalog = (
        published["rated_torque_kgfm"] * 9.80665
    )

    # Electrical input derived from rated output / efficiency.
    p_in = rated_output_W / rated_efficiency
    p_loss = p_in - rated_output_W

    # Derived equivalent total thermal resistance from manufacturer
    # temperature-rise specification and total rated loss.
    rth_total = published["temperature_rise_K"] / p_loss

    # Independent cross-check from V-I-PF.
    p_from_vipf = (
        math.sqrt(3.0)
        * published["rated_voltage_line_line_V"]
        * published["rated_current_A_at_400V"]
        * published["power_factor_at_100pct_load"]
    )

    checks = {
        "speed_rad_s": (
            omega,
            derived["rated_speed_rad_s"],
            1e-3,
        ),
        "rated_torque_from_power_Nm": (
            torque_from_power,
            derived["rated_torque_Nm_from_power"],
            1e-3,
        ),
        "rated_torque_catalog_Nm": (
            torque_from_catalog,
            derived["rated_torque_Nm_from_catalog"],
            1e-3,
        ),
        "rated_input_W": (
            p_in,
            derived["rated_electrical_input_W_from_efficiency"],
            0.5,
        ),
        "rated_loss_W": (
            p_loss,
            derived["rated_total_loss_W"],
            0.5,
        ),
        "total_Rth_K_per_W": (
            rth_total,
            derived["rated_total_thermal_resistance_K_per_W"],
            1e-5,
        ),
    }

    torque_rounding_difference_pct = (
        abs(torque_from_power - torque_from_catalog)
        / torque_from_catalog
        * 100.0
    )

    input_power_difference_pct = (
        abs(p_in - p_from_vipf)
        / p_in
        * 100.0
    )

    print("=== WEG reference motor consistency check ===")
    print(f"Product: {motor['provenance']['designation']}")
    print(f"Product code: {motor['provenance']['product_code']}")

    print(f"Rated speed: {omega:.6f} rad/s")
    print(f"Rated torque from P/ω: {torque_from_power:.6f} N·m")
    print(f"Rated torque from WEG catalog: {torque_from_catalog:.6f} N·m")

    print(f"Rated electrical input (from efficiency): {p_in:.3f} W")
    print(f"Rated total loss: {p_loss:.3f} W")
    print(f"Derived total thermal resistance: {rth_total:.6f} K/W")

    print(f"Cross-check V-I-PF active power: {p_from_vipf:.3f} W")
    print(
        "Difference between efficiency and V-I-PF input power: "
        f"{input_power_difference_pct:.3f}%"
    )
    print(
        "Difference between P/ω torque and catalog torque: "
        f"{torque_rounding_difference_pct:.3f}%"
    )

    # The tiny torque difference is due to independently rounded
    # manufacturer/catalog quantities and is reported, not treated
    # as a model inconsistency.
    print()

    ok = True

    for name, (actual, expected, tolerance) in checks.items():
        passed = abs(actual - expected) <= tolerance
        ok &= passed

        print(
            f"[{'PASS' if passed else 'FAIL'}] "
            f"{name}: actual={actual:.6f}, config={expected:.6f}"
        )

    print()

    if not ok:
        raise SystemExit("Reference motor consistency check failed.")

    print("Reference motor consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())