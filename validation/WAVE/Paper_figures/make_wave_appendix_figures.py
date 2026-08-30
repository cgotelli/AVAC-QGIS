#!/usr/bin/env python3
"""Create appendix figures for the archived WAVE verification cases.

The script reads notebook products only; it never launches WAVE.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "validation"))

from avac4qgis_validation.plot_style import (  # noqa: E402
    MODEL_COLORS,
    PAPER_COLORS,
    SERIES_COLORS,
    apply_paper_style,
    figure_size,
)


def profile_panel(
    axis: plt.Axes,
    csv_path: Path,
    *,
    model_column: str,
    theory_column: str,
    title: str,
    label: str,
    ylabel: str = "Flow depth (m)",
) -> None:
    data = pd.read_csv(csv_path)
    x = data["x_m"].to_numpy(float)
    stride = max(1, len(x) // 42)
    axis.plot(x, data[theory_column], color=MODEL_COLORS["theory"], label="Analytical")
    axis.plot(
        x, data[model_column], color=MODEL_COLORS["wave"], linestyle="none",
        marker="o", markersize=3.0, markevery=stride, markerfacecolor="white",
        markeredgewidth=0.8, label="WAVE",
    )
    axis.set(xlabel="$x$ (m)", ylabel=ylabel, title=title)
    axis.text(0.015, 0.985, f"({label})", transform=axis.transAxes,
              ha="left", va="top", fontweight="bold")


def analytical_benchmarks(wave_root: Path, output: Path) -> dict[str, object]:
    cases = (
        ("01_transcritical_shock", "model_h_m", "swashes_h_m", "Transcritical bump with shock"),
        ("02_macdonald_smooth_shock", "model_h_m", "swashes_h_m", "MacDonald smooth shock"),
        ("03_ritter_dry_dam_break", "model_h_m", "swashes_h_m", "Ritter dry dam break"),
    )
    fig, axes = plt.subplots(2, 2, figsize=figure_size(2, aspect=0.90), constrained_layout=True)
    provenance: dict[str, object] = {}
    for label, axis, (folder, model_column, theory_column, title) in zip("abc", axes.flat, cases):
        results = wave_root / folder / "results"
        profile_panel(
            axis, results / "wave_vs_swashes.csv", model_column=model_column,
            theory_column=theory_column, title=title, label=label,
            ylabel="Section-mean depth (m)" if "pseudo2d" in folder else "Flow depth (m)",
        )
        provenance[folder] = json.loads((results / "summary.json").read_text())
        if label == "c":
            axis.set_ylim(top=0.006)

    axis = axes[1, 1]
    baines_root = wave_root / "07_baines_flow_over_bump" / "results"
    steady = pd.read_csv(baines_root / "wave_baines_steady_error.csv")
    rest = pd.read_csv(baines_root / "wave_lake_at_rest_error.csv")
    axis.semilogy(steady["time_s"], steady["Linf_depth_m"],
                  color=SERIES_COLORS[0], label=r"Steady bump, $L_\infty$")
    axis.semilogy(steady["time_s"], steady["L2_depth_m"],
                  color=SERIES_COLORS[1], linestyle="--", label=r"Steady bump, $L_2$")
    axis.semilogy(rest["time_s"], rest["Linf_eta_m"],
                  color=SERIES_COLORS[2], label=r"Lake at rest, $L_\infty$")
    axis.semilogy(rest["time_s"], rest["L2_eta_m"],
                  color=SERIES_COLORS[3], linestyle="--", label=r"Lake at rest, $L_2$")
    axis.set(xlabel="Time (s)", ylabel="Absolute error (m)", title="Baines bump and lake at rest")
    axis.set_ylim(top=1.0e-1)
    axis.text(0.015, 0.985, "(f)", transform=axis.transAxes,
              ha="left", va="top", fontweight="bold")
    provenance["07_baines_flow_over_bump"] = json.loads(
        (baines_root / "summary.json").read_text()
    )

    handles, labels = axes[0, 0].get_legend_handles_labels()
    extra_handles, extra_labels = axis.get_legend_handles_labels()
    fig.legend(handles + extra_handles, labels + extra_labels,
               loc="outside lower center", ncol=3)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"wave_additional_benchmarks.{suffix}")
    plt.close(fig)
    return provenance


def numerical_diagnostics(wave_root: Path, output: Path) -> dict[str, object]:
    wrr_root = wave_root / "2008_WRR_sloping_bed" / "results"
    wrr = pd.read_csv(wrr_root / "boundary_metrics.csv")
    wrr_summary = json.loads((wrr_root / "summary.json").read_text())
    theta = np.deg2rad(10.0)
    t0 = np.sqrt(1.0 / (9.81 * np.cos(theta)))
    t_theory = np.linspace(0.0, float(wrr_summary["open_boundary_reached_s"]), 500)
    tau = t_theory / t0
    transition = 2.0 / np.tan(theta)
    front = 2.0 * tau + 0.5 * tau**2 * np.tan(theta)
    rear = np.where(
        tau < transition,
        -tau + 0.25 * tau**2 * np.tan(theta),
        -2.0 * tau + 0.5 * tau**2 * np.tan(theta) + 1.0 / np.tan(theta),
    )

    fig, axes = plt.subplots(1, 2, figsize=figure_size(2, aspect=0.47), constrained_layout=True)
    axis = axes[0]
    axis.plot(t_theory, front, color=MODEL_COLORS["theory"], label="Analytical fronts", zorder=3)
    axis.plot(t_theory, rear, color=MODEL_COLORS["theory"], zorder=3)
    usable = wrr["time_s"] <= float(wrr_summary["open_boundary_reached_s"])
    axis.plot(wrr.loc[usable, "time_s"], wrr.loc[usable, "front_x_m"],
              linestyle="none", marker="o", color=MODEL_COLORS["wave"], label="WAVE", zorder=2)
    axis.plot(wrr.loc[usable, "time_s"], wrr.loc[usable, "rear_x_m"],
              linestyle="none", marker="s", color=MODEL_COLORS["wave"], zorder=2)
    axis.set(xlabel="Time (s)", ylabel="Boundary position (m)", title="Sloping-bed wet--dry flow")
    axis.text(0.015, 0.985, "(a)", transform=axis.transAxes,
              ha="left", va="top", fontweight="bold")

    amr_root = wave_root / "08_amr_parallel" / "results"
    profiles = pd.read_csv(amr_root / "final_profiles.csv")
    axis = axes[1]
    axis.plot(profiles["x_m"], profiles["uniform_fine_sampled_h_m"],
              color=MODEL_COLORS["theory"], label="Uniform 0.005 m reference")
    axis.plot(profiles["x_m"], profiles["uniform_coarse_h_m"],
              color=PAPER_COLORS["red"], linestyle="--", label="Uniform 0.05 m")
    axis.plot(profiles["x_m"], profiles["amr_level2_8core_h_m"],
              color=MODEL_COLORS["wave"], linestyle="none", marker="o", markersize=3.0,
              markevery=max(1, len(profiles) // 48), markerfacecolor="white", label="AMR, finest 0.005 m")
    axis.set(xlabel="$x$ (m)", ylabel="Flow depth (m)", title="AMR dry dam break")
    axis.set_ylim(top=0.12)
    axis.text(0.015, 0.985, "(b)", transform=axis.transAxes,
              ha="left", va="top", fontweight="bold")

    handles: list[object] = []
    labels: list[str] = []
    for legend_axis in axes:
        local_handles, local_labels = legend_axis.get_legend_handles_labels()
        handles.extend(local_handles); labels.extend(local_labels)
    fig.legend(handles, labels, loc="outside lower center", ncol=3)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"wave_numerical_diagnostics.{suffix}")
    plt.close(fig)
    return {
        "2008_WRR_sloping_bed": wrr_summary,
        "08_amr_parallel": json.loads((amr_root / "summary.json").read_text()),
    }


def main() -> None:
    apply_paper_style()
    wave_root = REPO / "validation" / "WAVE"
    output = REPO / "docs" / "article" / "figures"
    output.mkdir(parents=True, exist_ok=True)
    provenance = {
        "analytical_benchmarks": analytical_benchmarks(wave_root, output),
        "numerical_diagnostics": numerical_diagnostics(wave_root, output),
    }
    (output / "wave_appendix_figures.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "figures": 2}, indent=2))


if __name__ == "__main__":
    main()
