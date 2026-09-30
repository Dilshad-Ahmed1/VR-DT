from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS800 = ROOT / "RESULTS" / "800s"
REALTIME_DIR = RESULTS / "realtime_matrix_v1"
FIGURES = RESULTS / "figures"
FIGURES.mkdir(exist_ok=True)

SCENARIOS = [
    "healthy", "cooling", "sensor_bias", "sensor_freeze",
    "rth_degradation", "unbalance", "combined",
]
CONTROLLERS = ["baseline", "adaptive", "constrained"]


def load_run(path: Path, run_kind: str) -> dict:
    df = pd.read_csv(path)
    stem = path.stem
    controller = next(name for name in CONTROLLERS if f"_{name}_" in f"_{stem}_")
    scenario = stem[: stem.rfind(f"_{controller}_")]

    solver_seconds = df["solver_step_time_s"].sum()
    row = {
        "scenario": scenario,
        "controller": controller,
        "run_kind": run_kind,
        "rows": len(df),
        "duration_s": float(df["time_s"].max()),
        "max_winding_temp_C": float(df["T_winding_C"].max()),
        "time_above_100C_s": float((df["T_winding_C"] >= 100.0).sum() * 0.5),
        "time_above_120C_s": float((df["T_winding_C"] >= 120.0).sum() * 0.5),
        "mean_fault_detection_latency_ms": float(df["fault_detection_latency_ms"].mean()),
        "p95_fault_detection_latency_ms": float(df["fault_detection_latency_ms"].quantile(0.95)),
        "max_fault_detection_latency_ms": float(df["fault_detection_latency_ms"].max()),
        "mean_state_estimator_latency_ms": float(df["state_estimator_latency_ms"].mean()),
        "mean_predictor_latency_ms": float(df["predictor_latency_ms"].mean()),
        "mean_controller_latency_ms": float(df["controller_latency_ms"].mean()),
        "mean_loop_compute_latency_ms": float(df["loop_compute_latency_ms"].mean()),
        "p95_loop_compute_latency_ms": float(df["loop_compute_latency_ms"].quantile(0.95)),
        "max_loop_compute_latency_ms": float(df["loop_compute_latency_ms"].max()),
        "solver_real_time_factor": float(
            (df["time_s"].iloc[-1] + 0.5) / max(solver_seconds, 1e-12)
        ),
    }

    if run_kind == "realtime" and "realtime_cycle_latency_ms" in df:
        deadline = df["realtime_deadline_ms"]
        misses = df["realtime_deadline_missed"]
        row.update({
            "realtime_deadline_ms": float(deadline.iloc[0]),
            "realtime_deadline_misses": int(misses.sum()),
            "realtime_deadline_miss_rate_percent": float(misses.mean() * 100.0),
            "realtime_cycle_latency_mean_ms": float(df["realtime_cycle_latency_ms"].mean()),
            "realtime_cycle_latency_p95_ms": float(df["realtime_cycle_latency_ms"].quantile(0.95)),
            "realtime_cycle_latency_max_ms": float(df["realtime_cycle_latency_ms"].max()),
            "realtime_deadline_headroom_mean_ms": float(
                (deadline - df["realtime_cycle_latency_ms"]).mean()
            ),
            "realtime_deadline_headroom_p05_ms": float(
                (deadline - df["realtime_cycle_latency_ms"]).quantile(0.95)
            ),
            "realtime_eligible": bool(misses.sum() == 0),
        })
    else:
        row.update({
            "realtime_deadline_ms": float("nan"),
            "realtime_deadline_misses": float("nan"),
            "realtime_deadline_miss_rate_percent": float("nan"),
            "realtime_cycle_latency_mean_ms": float("nan"),
            "realtime_cycle_latency_p95_ms": float("nan"),
            "realtime_cycle_latency_max_ms": float("nan"),
            "realtime_deadline_headroom_mean_ms": float("nan"),
            "realtime_deadline_headroom_p05_ms": float("nan"),
            "realtime_eligible": False,
        })
    return row


def collect() -> pd.DataFrame:
    simulation = [
        load_run(path, "simulation")
        for path in sorted(RESULTS800.glob("*_800s.csv"))
        if "basyx" not in path.name
    ]
    realtime = [
        load_run(path, "realtime")
        for path in sorted(REALTIME_DIR.glob("*_800s.csv"))
    ]
    frame = pd.DataFrame(simulation + realtime)
    frame["scenario"] = pd.Categorical(frame["scenario"], SCENARIOS, ordered=True)
    frame["controller"] = pd.Categorical(frame["controller"], CONTROLLERS, ordered=True)
    return frame.sort_values(["run_kind", "scenario", "controller"])


def save_plots(frame: pd.DataFrame) -> None:
    plt.rcParams.update({"axes.grid": True, "grid.alpha": 0.3})
    sim = frame[frame["run_kind"] == "simulation"]
    rt = frame[frame["run_kind"] == "realtime"]

    latency = frame.pivot_table(
        index="scenario", columns=["run_kind", "controller"],
        values="mean_fault_detection_latency_ms", aggfunc="first",
    ).reindex(SCENARIOS)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    latency.plot(kind="bar", ax=ax, width=0.82)
    ax.set_title("Fault-detection latency: 7700-s simulation versus 800-s wall-clock runs")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Mean detection latency (ms)")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(FIGURES / "realtime_vs_simulation_detection_latency.png", dpi=220)
    plt.close(fig)

    rt_heat = rt.pivot(index="scenario", columns="controller", values="realtime_cycle_latency_p95_ms").reindex(SCENARIOS)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    image = ax.imshow(rt_heat.to_numpy(), cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(rt_heat.columns)), rt_heat.columns)
    ax.set_yticks(range(len(rt_heat.index)), rt_heat.index)
    for row_index in range(rt_heat.shape[0]):
        for column_index in range(rt_heat.shape[1]):
            ax.text(column_index, row_index, f"{rt_heat.iloc[row_index, column_index]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, label="P95 cycle latency (ms)")
    ax.set_title("Wall-clock cycle latency in the real-time matrix")
    ax.set_xlabel("Controller")
    ax.set_ylabel("Scenario")
    fig.tight_layout()
    fig.savefig(FIGURES / "realtime_cycle_latency_heatmap.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    plot = rt.pivot(index="scenario", columns="controller", values="realtime_deadline_headroom_mean_ms").reindex(SCENARIOS)
    plot.plot(kind="bar", ax=ax, width=0.82)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Mean control-cycle headroom against the 500-ms deadline")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Deadline headroom (ms)")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(title="Controller")
    fig.tight_layout()
    fig.savefig(FIGURES / "realtime_deadline_headroom.png", dpi=220)
    plt.close(fig)

    thermal = sim.pivot_table(index="scenario", columns="controller", values="max_winding_temp_C", aggfunc="first").reindex(SCENARIOS)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    image = ax.imshow(thermal.to_numpy(), cmap="RdYlBu_r", aspect="auto", vmin=80, vmax=130)
    ax.set_xticks(range(len(thermal.columns)), thermal.columns)
    ax.set_yticks(range(len(thermal.index)), thermal.index)
    for row_index in range(thermal.shape[0]):
        for column_index in range(thermal.shape[1]):
            ax.text(column_index, row_index, f"{thermal.iloc[row_index, column_index]:.1f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, label="Maximum winding temperature (C)")
    ax.set_title("7700-s simulation thermal outcome by scenario and controller")
    ax.set_xlabel("Controller")
    ax.set_ylabel("Scenario")
    fig.tight_layout()
    fig.savefig(FIGURES / "simulation_7700s_thermal_heatmap.png", dpi=220)
    plt.close(fig)

    compare = frame[frame["controller"] == "constrained"].copy()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for run_kind, group in compare.groupby("run_kind"):
        ax.plot(group["scenario"].astype(str), group["max_winding_temp_C"], marker="o", label=run_kind)
    ax.axhline(120, color="black", linestyle="--", linewidth=1, label="Model critical threshold")
    ax.set_title("Constrained-controller thermal outcome: simulation versus wall-clock run")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Maximum winding temperature (C)")
    ax.tick_params(axis="x", rotation=30)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "realtime_vs_simulation_thermal_outcomes.png", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    result = collect()
    output = RESULTS / "realtime_vs_simulation_summary.csv"
    result.to_csv(output, index=False)
    save_plots(result)
    print(f"Wrote {output}")
    print(result.to_string(index=False))
