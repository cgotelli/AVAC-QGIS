#!/usr/bin/env python3
"""Create the coupling-verification figure from the notebook run products."""

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
    results = REPO / "validation" / "COUPLING" / "publication" / "results"
    output = REPO / "docs" / "article" / "figures"
    output.mkdir(parents=True, exist_ok=True)
    history = pd.read_csv(results / "written_source_history.csv")
    closure = pd.read_csv(results / "wave_closure.csv")
    temporal = pd.read_csv(results / "time_sampling_convergence.csv")
    orientation = pd.read_csv(results / "shoreline_orientation.csv")
    summary = json.loads((results / "summary.json").read_text())

    fig, axes = plt.subplots(2, 2, figsize=figure_size(2, aspect=0.90))

    ax = axes[0, 0]
    ax.add_patch(plt.Rectangle((0.10, 0.06), 1.80, 0.44, color=MODEL_COLORS["wave"], alpha=0.22))
    ax.plot([0.10, 1.90], [0.52, 0.52], color=MODEL_COLORS["coupling"], linewidth=5.0,
            solid_capstyle="round")
    for x in np.linspace(0.32, 1.68, 5):
        ax.annotate("", xy=(x, 0.56), xytext=(x, 0.82),
                    arrowprops={"arrowstyle": "-|>", "color": MODEL_COLORS["avac"], "lw": 1.8})
    ax.text(1.00, 0.91, "Prescribed AVAC state", color=MODEL_COLORS["avac"], ha="center")
    ax.text(1.00, 0.28, "WAVE domain", color=MODEL_COLORS["wave"], ha="center")
    ax.set_xlim(0.0, 2.0); ax.set_ylim(0.0, 1.0)
    ax.set_aspect("auto"); ax.axis("off")
    ax.text(0.02, 0.96, "(a)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")

    ax = axes[0, 1]
    time = history["time_s"].to_numpy(float)
    expected = 0.10 * 0.020 * 0.80 * np.sin(np.pi * time) * (1.0 + 0.25 * time)
    ax.plot(time, expected, color=MODEL_COLORS["theory"], label="Prescribed", linestyle="-")
    ax.plot(time, history["volume_rate_m3_s"], color=MODEL_COLORS["coupling"],
            label="Written source", linestyle="--", marker="o", markerfacecolor="white")
    ax.set_xlabel("Time (s)"); ax.set_ylabel(r"Volume rate (m$^3$ s$^{-1}$)")
    ax.text(0.02, 0.96, "(b)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")

    ax = axes[1, 0]
    labels = ["Uniform\n0.10 m", "Uniform\n0.05 m", "AMR\nlevel 2"]
    quantities = (
        ("relative_volume_closure", "Volume", PAPER_COLORS["green"]),
        ("relative_momentum_x_closure", r"$x$ momentum", PAPER_COLORS["orange"]),
        ("relative_momentum_y_closure", r"$y$ momentum", PAPER_COLORS["purple"]),
    )
    x = np.arange(len(closure)); width = 0.24
    for index, (column, label, color) in enumerate(quantities):
        values = np.maximum(np.abs(closure[column].to_numpy(float)), 1.0e-15)
        ax.bar(x + (index - 1) * width, values, width=width, color=color, label=label)
    ax.set_yscale("log"); ax.set_xticks(x, labels)
    ax.set_ylabel("Absolute relative closure error")
    ax.set_ylim(top=3.2e-4)
    ax.text(0.02, 0.96, "(c)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")

    ax = axes[1, 1]
    ax.loglog(temporal["source_spacing_s"], temporal["volume_relative_error"],
              color=PAPER_COLORS["green"], marker="o", label="Volume: time sampling")
    ax.loglog(temporal["source_spacing_s"], temporal["momentum_x_relative_error"],
              color=PAPER_COLORS["orange"], marker="s", label="Momentum: time sampling")
    ax.loglog(orientation["spacing_m"], orientation["volume_relative_error"],
              color=PAPER_COLORS["red"], marker="^", linestyle="--", label="Volume: diagonal shoreline")
    ax.loglog(orientation["spacing_m"], orientation["momentum_x_relative_error"],
              color=PAPER_COLORS["purple"], marker="D", linestyle="--", label="Momentum: diagonal shoreline")
    ax.invert_xaxis()
    ax.set_xlabel("Source spacing in time (s) or space (m)")
    ax.set_ylabel("Absolute relative ledger error")
    ax.set_ylim(top=1.0)
    ax.text(0.02, 0.96, "(d)", transform=ax.transAxes, ha="left", va="top", fontweight="bold")
    handles: list[object] = []
    labels: list[str] = []
    for legend_axis in (axes[0, 1], axes[1, 0], axes[1, 1]):
        axis_handles, axis_labels = legend_axis.get_legend_handles_labels()
        for handle, label in zip(axis_handles, axis_labels):
            if label not in labels:
                handles.append(handle); labels.append(label)
    fig.legend(handles, labels, loc="outside lower center", ncol=3)
    fig.subplots_adjust(bottom=0.23, hspace=0.36, wspace=0.31)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"coupling_verification.{suffix}")
    plt.close(fig)

    provenance = {
        "figure": "coupling_verification",
        "source_summary": str(results / "summary.json"),
        "maximum_absolute_wave_relative_closure": summary["maximum_absolute_wave_relative_closure"],
        "finest_temporal_volume_relative_error": summary["finest_temporal_volume_relative_error"],
        "finest_temporal_momentum_relative_error": summary["finest_temporal_momentum_relative_error"],
        "maximum_diagonal_ledger_relative_error": summary["maximum_diagonal_ledger_relative_error"],
    }
    (output / "coupling_verification.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
