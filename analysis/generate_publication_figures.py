from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


# ============================================================
# GLOBAL SETTINGS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = RESULTS / "figures"
OUT.mkdir(exist_ok=True)

compare = pd.read_csv(RESULTS / "analysis_results.csv")

scenario_order = [
    "healthy",
    "cooling",
    "sensor_bias",
    "sensor_freeze",
    "rth_degradation",
    "unbalance",
    "combined",
]

controller_order = [
    "baseline",
    "adaptive",
    "constrained",
]

# Publication-oriented typography
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 15,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.dpi": 150,
    "savefig.dpi": 400,
})


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def save_fig(fig, filename):
    """Save a publication-quality figure."""
    fig.savefig(
        OUT / filename,
        dpi=400,
        bbox_inches="tight",
        pad_inches=0.15,
    )
    plt.close(fig)


def box(
    ax,
    xy,
    w,
    h,
    text,
    fc="#EAF2FF",
    ec="#2F4B7C",
    fontsize=11,
    lw=1.8,
):
    """Draw a clean rounded box with centered text."""
    patch = FancyBboxPatch(
        xy,
        w,
        h,
        boxstyle="round,pad=0.035,rounding_size=0.10",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
    )

    ax.add_patch(patch)

    ax.text(
        xy[0] + w / 2,
        xy[1] + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        linespacing=1.25,
        wrap=True,
    )

    return patch


def arrow(
    ax,
    start,
    end,
    text=None,
    text_offset=(0, 0),
    color="#333333",
    linewidth=1.7,
):
    """Draw an arrow with optional label positioned away from arrow."""
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=18,
        linewidth=linewidth,
        color=color,
    )

    ax.add_patch(arr)

    if text:
        mid_x = (start[0] + end[0]) / 2 + text_offset[0]
        mid_y = (start[1] + end[1]) / 2 + text_offset[1]

        ax.text(
            mid_x,
            mid_y,
            text,
            fontsize=9,
            ha="center",
            va="center",
            bbox=dict(
                boxstyle="round,pad=0.18",
                facecolor="white",
                edgecolor="none",
                alpha=0.90,
            ),
        )


def style_axis(ax):
    """Consistent style for quantitative plots."""
    ax.grid(
        True,
        linestyle="--",
        linewidth=0.7,
        alpha=0.3,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# ============================================================
# FIGURE 1 — ARCHITECTURE OVERVIEW
# ============================================================

fig, ax = plt.subplots(figsize=(15, 8))

ax.set_xlim(0, 15)
ax.set_ylim(0, 8)
ax.axis("off")

# Main pipeline
box(
    ax,
    (0.5, 5.5),
    1.8,
    1.0,
    "Motor / FMU",
    fc="#D9EDF7",
)

box(
    ax,
    (3.0, 5.5),
    2.0,
    1.0,
    "State\nEstimator",
    fc="#DFF0D8",
)

box(
    ax,
    (5.7, 5.5),
    2.1,
    1.0,
    "Fault Detector\n& Severity",
    fc="#FFF2CC",
)

box(
    ax,
    (8.5, 5.5),
    2.0,
    1.0,
    "Thermal\nPredictor",
    fc="#FBE5D6",
)

box(
    ax,
    (11.3, 5.5),
    2.0,
    1.0,
    "Adaptive\nController",
    fc="#FDE9D9",
)

# Horizontal arrows
arrow(
    ax,
    (2.3, 6.0),
    (3.0, 6.0),
    "measurements",
    text_offset=(0, 0.28),
)

arrow(
    ax,
    (5.0, 6.0),
    (5.7, 6.0),
    "thermal state",
    text_offset=(0, 0.28),
)

arrow(
    ax,
    (7.8, 6.0),
    (8.5, 6.0),
    "fault information",
    text_offset=(0, 0.28),
)

arrow(
    ax,
    (10.5, 6.0),
    (11.3, 6.0),
    "thermal risk",
    text_offset=(0, 0.28),
)

# Closed-loop return path
arrow(
    ax,
    (12.3, 5.5),
    (12.3, 3.8),
)

arrow(
    ax,
    (12.3, 3.8),
    (1.4, 3.8),
    "control command",
    text_offset=(0, -0.28),
)

arrow(
    ax,
    (1.4, 3.8),
    (1.4, 5.5),
)

# AAS branch
arrow(
    ax,
    (6.8, 5.5),
    (6.8, 2.8),
    "AAS synchronization",
    text_offset=(0.65, 0),
)

box(
    ax,
    (5.0, 1.5),
    3.6,
    1.1,
    "AAS / BaSyx\nDigital Twin Asset State",
    fc="#F3E8FF",
)

ax.text(
    7.5,
    7.35,
    "Closed-Loop Digital Twin Architecture",
    ha="center",
    va="center",
    fontsize=17,
    fontweight="bold",
)

save_fig(fig, "architecture_overview.png")


# ============================================================
# FIGURE 2 — CLOSED-LOOP TIMING
# ============================================================

fig, ax = plt.subplots(figsize=(14, 6))

ax.set_xlim(0, 14)
ax.set_ylim(0, 5)
ax.axis("off")

blocks = [
    ("Measure /\nEstimate", 0.5, 2.5, 1.8, 0.9),
    ("Detect /\nSeverity", 2.8, 2.5, 1.8, 0.9),
    ("Thermal\nPrediction", 5.1, 2.5, 1.8, 0.9),
    ("Control\nLaw", 7.4, 2.5, 1.8, 0.9),
    ("AAS\nSnapshot", 9.7, 2.5, 1.8, 0.9),
    ("FMU\nAdvance", 12.0, 2.5, 1.5, 0.9),
]

for label, x, y, w, h in blocks:
    box(
        ax,
        (x, y),
        w,
        h,
        label,
        fc="#EEF7FF",
        fontsize=10.5,
    )

for i in range(len(blocks) - 1):
    x1 = blocks[i][1] + blocks[i][3]
    x2 = blocks[i + 1][1]

    arrow(
        ax,
        (x1, 2.95),
        (x2, 2.95),
    )

ax.text(
    7.0,
    4.25,
    "Single Closed-Loop Cycle",
    ha="center",
    fontsize=17,
    fontweight="bold",
)

ax.text(
    7.0,
    1.25,
    "Estimate → detect → predict → control → synchronize → advance",
    ha="center",
    fontsize=12,
)

ax.text(
    7.0,
    0.75,
    "The controller uses the current digital-twin state before the next FMU advance.",
    ha="center",
    fontsize=10,
    color="#555555",
)

save_fig(fig, "closed_loop_timing.png")


# ============================================================
# FIGURE 3 — THERMAL MODEL
# ============================================================

fig, ax = plt.subplots(figsize=(14, 7))

ax.set_xlim(0, 14)
ax.set_ylim(0, 7)
ax.axis("off")

box(
    ax,
    (0.8, 4.5),
    2.5,
    1.2,
    "Winding + Fixed\nLosses",
    fc="#D9F2D9",
)

box(
    ax,
    (4.2, 4.5),
    2.0,
    1.2,
    "Winding\nThermal State\n$T_w$",
    fc="#D9EDF7",
)

box(
    ax,
    (7.2, 4.5),
    2.0,
    1.2,
    "Frame\nThermal State\n$T_f$",
    fc="#D9EDF7",
)

box(
    ax,
    (10.2, 4.5),
    2.2,
    1.2,
    "Ambient\nTemperature\n$T_a$",
    fc="#E5E7EB",
)

arrow(
    ax,
    (3.3, 5.1),
    (4.2, 5.1),
    "heat input",
    text_offset=(0, 0.30),
)

arrow(
    ax,
    (6.2, 5.1),
    (7.2, 5.1),
    "$R_{wf}$",
    text_offset=(0, 0.30),
)

arrow(
    ax,
    (9.2, 5.1),
    (10.2, 5.1),
    "$R_{fa}$",
    text_offset=(0, 0.30),
)

# Cooling branch
box(
    ax,
    (9.8, 1.8),
    3.0,
    1.0,
    "Cooling / Thermal\nResistance Degradation",
    fc="#FFF2CC",
)

arrow(
    ax,
    (11.2, 4.5),
    (11.2, 2.8),
    "cooling effect",
    text_offset=(0.8, 0),
)

ax.text(
    7.0,
    6.45,
    "Reduced-Order Two-Node Thermal Model",
    ha="center",
    fontsize=17,
    fontweight="bold",
)

ax.text(
    7.0,
    0.75,
    r"$C_w \frac{dT_w}{dt}=P_w-\frac{T_w-T_f}{R_{wf}}$",
    ha="center",
    fontsize=12,
)

ax.text(
    7.0,
    0.30,
    r"$C_f \frac{dT_f}{dt}=P_f+\frac{T_w-T_f}{R_{wf}}-\frac{T_f-T_a}{R_{fa}}$",
    ha="center",
    fontsize=12,
)

save_fig(fig, "thermal_model_diagram.png")


# ============================================================
# FIGURE 4 — FAULT ARCHITECTURE
# ============================================================

fig, ax = plt.subplots(figsize=(14, 8))

ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis("off")

fault_labels = [
    "Sensor Bias",
    "Sensor Freeze",
    "Cooling Degradation",
    "Thermal Resistance\nDegradation",
    "Mechanical Unbalance",
]

fault_y = [6.6, 5.35, 4.10, 2.85, 1.60]

for label, y in zip(fault_labels, fault_y):

    box(
        ax,
        (0.7, y),
        2.6,
        0.8,
        label,
        fc="#FBE5D6",
        fontsize=10,
    )

    arrow(
        ax,
        (3.3, y + 0.4),
        (5.0, y + 0.4),
    )

# Central processing block
box(
    ax,
    (5.0, 2.4),
    3.2,
    3.6,
    "Residuals\n\nState Observers\n\nFault Indicators\n\nSeverity Estimation",
    fc="#EAF2FF",
    fontsize=11,
)

arrow(
    ax,
    (8.2, 4.2),
    (10.0, 4.2),
    "normalized severity",
    text_offset=(0, 0.32),
)

box(
    ax,
    (10.0, 3.3),
    2.7,
    1.8,
    "Adaptive /\nConstrained\nController",
    fc="#FFF2CC",
    fontsize=12,
)

ax.text(
    7.0,
    7.55,
    "Fault-to-Control Information Flow",
    ha="center",
    fontsize=17,
    fontweight="bold",
)

save_fig(fig, "fault_architecture.png")


# ============================================================
# FIGURE 5 — TEMPERATURE TRAJECTORIES
# ============================================================

combined_files = {
    controller: RESULTS / f"combined_{controller}_7700s.csv"
    for controller in controller_order
}

fig, ax = plt.subplots(figsize=(12, 7))

for controller, path in combined_files.items():

    df = pd.read_csv(path)

    ax.plot(
        df["time_s"],
        df["T_winding_C"],
        label=controller.capitalize(),
        linewidth=2.5,
    )

ax.axhline(
    120,
    color="black",
    linestyle="--",
    linewidth=1.5,
    label="Critical temperature",
)

ax.axhline(
    100,
    color="gray",
    linestyle=":",
    linewidth=1.3,
    label="Warning threshold",
)

ax.set_title(
    "Combined-Scenario Winding Temperature",
    fontweight="bold",
)

ax.set_xlabel("Time (s)")
ax.set_ylabel("Winding Temperature (°C)")

ax.legend(
    loc="best",
    frameon=True,
)

style_axis(ax)

fig.tight_layout()
save_fig(fig, "temperature_trajectories.png")


# ============================================================
# FIGURE 6 — LOAD COMMAND
# ============================================================

fig, ax = plt.subplots(figsize=(12, 7))

for controller in controller_order:

    df = pd.read_csv(
        RESULTS / f"combined_{controller}_7700s.csv"
    )

    ax.plot(
        df["time_s"],
        df["controller_load_command_pu"],
        label=controller.capitalize(),
        linewidth=2.5,
    )

ax.set_title(
    "Combined-Scenario Load Command",
    fontweight="bold",
)

ax.set_xlabel("Time (s)")
ax.set_ylabel("Load Command (p.u.)")

ax.legend(
    loc="best",
    frameon=True,
)

style_axis(ax)

fig.tight_layout()
save_fig(fig, "load_command_trajectories.png")


# ============================================================
# FIGURE 7 — PREDICTIVE TEMPERATURE
# ============================================================

controller = "constrained"

df = pd.read_csv(
    RESULTS / f"combined_{controller}_7700s.csv"
)

fig, ax = plt.subplots(figsize=(12, 7))

ax.plot(
    df["time_s"],
    df["T_winding_C"],
    label="Measured winding temperature",
    linewidth=2.5,
)

ax.plot(
    df["time_s"],
    df["predicted_30s_C"],
    linestyle="--",
    label="30 s prediction",
    linewidth=2.0,
)

ax.plot(
    df["time_s"],
    df["predicted_60s_C"],
    linestyle=":",
    label="60 s prediction",
    linewidth=2.5,
)

ax.set_title(
    "Thermal Prediction vs. Winding Temperature",
    fontweight="bold",
)

ax.set_xlabel("Time (s)")
ax.set_ylabel("Temperature (°C)")

ax.legend(
    loc="best",
    frameon=True,
)

style_axis(ax)

fig.tight_layout()
save_fig(fig, "predictive_temperature_plots.png")


# ============================================================
# FIGURE 8 — BASYX / AAS ARCHITECTURE
# ============================================================

fig, ax = plt.subplots(figsize=(15, 7))

ax.set_xlim(0, 15)
ax.set_ylim(0, 7)
ax.axis("off")

box(
    ax,
    (0.7, 4.3),
    2.3,
    1.1,
    "Motor / FMU",
    fc="#D9EDF7",
)

box(
    ax,
    (4.0, 4.3),
    2.3,
    1.1,
    "Python\nDigital Twin",
    fc="#DFF0D8",
)

box(
    ax,
    (7.3, 4.3),
    2.4,
    1.1,
    "AAS\nSubmodels",
    fc="#FFF2CC",
)

box(
    ax,
    (10.7, 4.3),
    3.0,
    1.1,
    "BaSyx Registry\n+ Repository",
    fc="#F3E8FF",
)

arrow(
    ax,
    (3.0, 4.85),
    (4.0, 4.85),
    "state",
    text_offset=(0, 0.30),
)

arrow(
    ax,
    (6.3, 4.85),
    (7.3, 4.85),
    "serialize",
    text_offset=(0, 0.30),
)

arrow(
    ax,
    (9.7, 4.85),
    (10.7, 4.85),
    "publish",
    text_offset=(0, 0.30),
)

box(
    ax,
    (4.2, 1.7),
    6.6,
    1.1,
    "Read / Update Operations\nand Communication-Latency Metrics",
    fc="#EAF2FF",
    fontsize=11,
)

arrow(
    ax,
    (5.15, 4.3),
    (5.15, 2.8),
    "monitoring",
    text_offset=(0.75, 0),
)

ax.text(
    7.5,
    6.35,
    "Asset Administration Shell / BaSyx Integration",
    ha="center",
    fontsize=17,
    fontweight="bold",
)

save_fig(fig, "basyx_aas_architecture.png")


# ============================================================
# FIGURE 9 — TEMPERATURE HEATMAP
# ============================================================

summary = (
    compare
    .pivot_table(
        index="scenario",
        columns="controller",
        values="max_winding_temp_C",
        aggfunc="first",
    )
    .reindex(scenario_order)
)

fig, ax = plt.subplots(figsize=(10, 7))

heat = ax.imshow(
    summary[controller_order].to_numpy(),
    cmap="RdYlBu_r",
    aspect="auto",
    vmin=80,
    vmax=120,
)

ax.set_xticks(range(len(controller_order)))
ax.set_xticklabels(
    [x.capitalize() for x in controller_order]
)

ax.set_yticks(range(len(scenario_order)))
ax.set_yticklabels(
    [
        x.replace("_", " ").title()
        for x in scenario_order
    ]
)

ax.set_title(
    "Maximum Winding Temperature Across Scenarios",
    fontweight="bold",
    pad=15,
)

for i in range(summary.shape[0]):
    for j in range(len(controller_order)):

        value = summary.loc[
            summary.index[i],
            controller_order[j],
        ]

        ax.text(
            j,
            i,
            f"{value:.1f}",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
        )

cbar = fig.colorbar(
    heat,
    ax=ax,
    pad=0.03,
)

cbar.set_label(
    "Maximum Winding Temperature (°C)",
    fontsize=11,
)

fig.tight_layout()

save_fig(fig, "temperature_heatmap.png")


print(f"Publication-quality figures written to: {OUT}")