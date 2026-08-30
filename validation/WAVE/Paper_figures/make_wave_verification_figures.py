#!/usr/bin/env python3
"""Create the main-paper WAVE verification figure from archived results."""

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
    apply_paper_style,
    figure_size,
)


def main() -> None:
    apply_paper_style()
    wave_root = REPO / "validation" / "WAVE"
    output = REPO / "docs" / "article" / "figures"
    output.mkdir(parents=True, exist_ok=True)

    rest = pd.read_csv(
        wave_root / "07_baines_flow_over_bump" / "results" / "wave_lake_at_rest_error.csv"
    )
    summary = json.loads(
        (wave_root / "04_thacker_planar_paraboloid" / "results" / "summary.json").read_text()
    )

    fig, axes = plt.subplots(1, 2, figsize=figure_size(2, aspect=0.43))

    ax = axes[0]
    ax.plot(
        rest["time_s"], rest["Linf_eta_m"], color=MODEL_COLORS["wave"],
        label=r"$L_\infty$", linestyle="-",
    )
    ax.plot(
        rest["time_s"], rest["L2_eta_m"], color=PAPER_COLORS["purple"],
        label=r"$L_2$", linestyle="--",
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Free-surface error (m)")
    ax.set_ylim(0.0, 0.8e-3)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, -3))
    ax.text(0.02, 0.96, "(a)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=2)

    ax = axes[1]
    thacker = pd.read_csv(
        wave_root / "04_thacker_planar_paraboloid" / "results" / "wave_vs_swashes.csv"
    )
    x = thacker["x_m"].to_numpy(float)
    bed = thacker["model_bed_m"].to_numpy(float)
    analytical_eta = bed + thacker["swashes_h_m"].to_numpy(float)
    stride = max(1, len(x) // 46)
    ax.plot(x, bed, color=PAPER_COLORS["orange"], linestyle=":", linewidth=1.5,
            label="Topography", zorder=1)
    ax.plot(x, thacker["model_eta_m"], color=MODEL_COLORS["wave"], linestyle="none",
            marker="o", markersize=3.0, markevery=stride, markerfacecolor="white",
            markeredgewidth=0.8, label="WAVE", zorder=2)
    ax.plot(x, analytical_eta, color=MODEL_COLORS["theory"], linewidth=1.6,
            label="Analytical", zorder=3)
    ax.set_xlabel("$x$ (m)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title("Thacker planar free surface")
    ax.set_ylim(top=0.35)
    ax.text(0.02, 0.96, "(b)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=3)

    fig.subplots_adjust(bottom=0.27, wspace=0.28)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"wave_analytical_verification.{suffix}")
    plt.close(fig)

    provenance = {
        "figure": "wave_analytical_verification",
        "lake_at_rest": {
            "source": str(rest.attrs.get("source", wave_root / "07_baines_flow_over_bump" / "results" / "wave_lake_at_rest_error.csv")),
            "maximum_Linf_eta_m": float(rest["Linf_eta_m"].max()),
            "maximum_L2_eta_m": float(rest["L2_eta_m"].max()),
        },
        "thacker": {
            "source": str(wave_root / "04_thacker_planar_paraboloid" / "results" / "summary.json"),
            "time_s": float(summary["final_time_s"]),
            "periods": int(summary["periods"]),
            "rmse_centerline_depth_m": float(summary["rmse_centerline_depth_m"]),
            "maximum_centerline_depth_error_m": float(summary["maximum_centerline_depth_error_m"]),
        },
    }
    (output / "wave_analytical_verification.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
