#!/usr/bin/env python3
"""Create manuscript AVAC verification figures from saved notebook results.

This script never launches AVAC.  It reads the numerical products generated
by the three case notebooks, so typography, colours, labels, and panel layout
can be revised without repeating the simulations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import brentq

from avac4qgis_validation.kerswell import position_riemann, time_riemann
from avac4qgis_validation.plot_style import (
    MODEL_COLORS,
    PAPER_COLORS,
    SERIES_COLORS,
    apply_paper_style,
    figure_size,
)


HERE = Path(__file__).resolve().parent
AVAC_ROOT = HERE.parent
REPOSITORY = AVAC_ROOT.parents[1]
DEFAULT_OUTPUT = REPOSITORY / "docs" / "article" / "figures"
G = 9.81
DRY_DEPTH_M = 1.0e-12
UNDISTURBED_RELATIVE_TOLERANCE = 1.0e-3


def load_case(folder: str) -> tuple[dict[str, object], dict[str, np.ndarray], np.ndarray]:
    results = AVAC_ROOT / folder / "publication_amr" / "results"
    if not results.is_dir():
        raise FileNotFoundError(
            f"Run the {folder} publication notebook before making figures: {results}"
        )
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    with np.load(results / "centerline_fields.npz") as archive:
        fields = {name: np.asarray(archive[name]) for name in archive.files}
    metric_name = (
        "front_back_metrics.csv" if folder == "Coulomb_sloping_bed"
        else "boundary_metrics.csv"
    )
    metrics = np.genfromtxt(results / metric_name, delimiter=",", names=True)
    return summary, fields, metrics


def kerswell_boundaries(tau: np.ndarray, *, rear_stop: float = -0.721577) -> tuple[np.ndarray, np.ndarray]:
    tau = np.asarray(tau, dtype=float)
    front = np.where(tau < 2.0, 2.0 * tau - 0.5 * tau**2, 2.0)
    b = 0.5 * tau + 1.0
    rear_moving = -(
        -3.64928 + 5.47993 * b - 2.06989 * b**2 + 0.319976 * b**3
        - 0.103745 * b**4 + 0.0230073 * b**5
    )
    rear = np.where(tau < 1.529654, rear_moving, rear_stop)
    return front, rear


def kerswell_profile(tau: float, step: float = 0.008) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the independent dimensionless Kerswell fan at one time."""
    s_values = np.arange(-1.0 + 1.0e-5, 1.0 - 1.0e-5 + step, step)
    valid_s: list[float] = []
    r_values: list[float] = []
    for s in s_values:
        lower, upper = 1.0 + 1.0e-9, 1.7657
        f_lower = time_riemann(float(s), lower) - tau
        f_upper = time_riemann(float(s), upper) - tau
        if not (np.isfinite(f_lower) and np.isfinite(f_upper)) or f_lower * f_upper >= 0.0:
            continue
        r = brentq(
            lambda value: time_riemann(float(s), value) - tau,
            lower, upper, xtol=1.0e-10,
        )
        valid_s.append(float(s))
        r_values.append(float(r))
    s = np.asarray(valid_s)
    r = np.asarray(r_values)
    x = np.asarray([position_riemann(float(ss), float(rr)) for ss, rr in zip(s, r)])
    return x, (r + s) ** 2 / 4.0, r - s - tau


def nearest_profile(fields: dict[str, np.ndarray], target_tau: float, time_scale: float):
    times = fields["time_s"]
    index = int(np.argmin(np.abs(times / time_scale - target_tau)))
    return index, float(times[index] / time_scale)


def standardized_coulomb_metrics(
    metrics: np.ndarray,
    fields: dict[str, np.ndarray],
    *,
    time_scale: float,
    length_scale: float,
    front_name: str,
    rear_name: str,
    rear_stop: float,
    recompute_front: bool = True,
) -> tuple[np.ndarray, dict[str, float]]:
    """Measure both Coulomb cases with one AMR-robust boundary definition.

    The horizontal advancing front is the envelope of the wet support at
    GeoClaw's dry tolerance.  The inclined-bed notebook already archives both
    that raw support and an energy-resolved front; for that case the latter is
    retained so a vanishingly thin wet film is not mistaken for creep.  The
    rear is the downstream edge of material still within 0.1 % of the
    released depth.
    """
    output = metrics.copy()
    x = fields["x_m"]
    depth = fields["depth_m"]
    front_values: list[float] = []
    rear_values: list[float] = []
    front_envelope = -np.inf
    for index, row in enumerate(depth):
        if recompute_front:
            wet = x[row > DRY_DEPTH_M]
            if wet.size:
                front_envelope = max(front_envelope, float(np.max(wet)))
            front_values.append(front_envelope)
        else:
            front_values.append(float(metrics[front_name][index]))
        undisturbed = x[np.abs(row - 1.0) <= UNDISTURBED_RELATIVE_TOLERANCE]
        rear_values.append(float(np.max(undisturbed)) if undisturbed.size else np.nan)
    front = np.asarray(front_values)
    rear = np.asarray(rear_values)
    output[front_name] = front
    output[rear_name] = rear
    tau = fields["time_s"] / time_scale
    theory_front, theory_rear = kerswell_boundaries(tau, rear_stop=rear_stop)
    front_moving = tau <= 2.0
    rear_moving = tau <= 1.529654
    report = {
        "dry_depth_m": DRY_DEPTH_M,
        "undisturbed_relative_depth_tolerance": UNDISTURBED_RELATIVE_TOLERANCE,
        "front_rmse_moving_m": float(np.sqrt(np.nanmean(
            (front[front_moving] - length_scale * theory_front[front_moving]) ** 2
        ))),
        "rear_rmse_moving_m": float(np.sqrt(np.nanmean(
            (rear[rear_moving] - length_scale * theory_rear[rear_moving]) ** 2
        ))),
        "front_final_m": float(front[-1]),
        "front_theory_final_m": float(length_scale * theory_front[-1]),
        "rear_final_m": float(rear[-1]),
        "rear_theory_final_m": float(length_scale * theory_rear[-1]),
    }
    return output, report


def boundary_panel(axis, metrics: np.ndarray, time_scale: float, length_scale: float,
                   *, front_name: str, rear_name: str, rear_stop: float) -> None:
    tau = np.asarray(metrics["time_s"], dtype=float) / time_scale
    theory_tau = np.linspace(0.0, float(np.max(tau)), 500)
    front_theory, rear_theory = kerswell_boundaries(theory_tau, rear_stop=rear_stop)
    axis.plot(theory_tau, front_theory, color=MODEL_COLORS["theory"], label="Analytical",
              zorder=3)
    axis.plot(theory_tau, rear_theory, color=MODEL_COLORS["theory"], zorder=3)
    axis.plot(tau, metrics[front_name] / length_scale, linestyle="none", marker="o",
              markevery=max(1, len(tau) // 30), color=MODEL_COLORS["avac"],
              markeredgecolor="white", markeredgewidth=0.45, label="AVAC", zorder=2)
    axis.plot(tau, metrics[rear_name] / length_scale, linestyle="none", marker="s",
              markevery=max(1, len(tau) // 30), color=MODEL_COLORS["avac"],
              markeredgecolor="white", markeredgewidth=0.45, zorder=2)
    axis.axhline(0.0, color=PAPER_COLORS["grid"], linewidth=0.8)
    axis.set(xlabel=r"$t/T_0$", ylabel=r"boundary position $x/X_0$")


def profile_panels(depth_axis, velocity_axis, fields: dict[str, np.ndarray],
                   time_scale: float, length_scale: float, velocity_scale: float) -> None:
    index, tau = nearest_profile(fields, 1.0, time_scale)
    theory_x, theory_h, theory_u = kerswell_profile(tau)
    theory_front, theory_rear = kerswell_boundaries(np.asarray([tau]))
    rear = float(theory_rear[0])
    front = float(theory_front[0])
    fan = (
        (theory_x >= rear - 1.0e-6)
        & (theory_x <= front + 1.0e-6)
        & (theory_h >= 0.0)
        & (theory_h <= 1.0 + 1.0e-6)
    )
    fan_x = theory_x[fan]
    fan_h = np.minimum(theory_h[fan], 1.0)
    fan_u = theory_u[fan]
    ordering = np.argsort(fan_x)
    fan_x, fan_h, fan_u = fan_x[ordering], fan_h[ordering], fan_u[ordering]
    xmin = float(np.min(fields["x_m"] / length_scale))
    xmax = float(np.max(fields["x_m"] / length_scale))
    x = fields["x_m"] / length_scale
    depth_axis.plot([xmin, rear], [1.0, 1.0], color=MODEL_COLORS["theory"], label="Analytical",
                    zorder=3)
    depth_axis.plot(fan_x, fan_h, color=MODEL_COLORS["theory"], zorder=3)
    depth_axis.plot([front, xmax], [0.0, 0.0], color=MODEL_COLORS["theory"], zorder=3)
    depth_axis.plot(x, fields["depth_m"][index], color=MODEL_COLORS["avac"],
                    linestyle="none", marker="o", markersize=2.5,
                    markevery=max(1, len(x) // 260), label="AVAC", zorder=2)
    velocity_axis.plot([xmin, rear], [0.0, 0.0], color=MODEL_COLORS["theory"], label="Analytical",
                       zorder=3)
    velocity_axis.plot(fan_x, fan_u, color=MODEL_COLORS["theory"], zorder=3)
    velocity_axis.plot(x, fields["velocity_m_s"][index] / velocity_scale,
                       color=MODEL_COLORS["avac"], linestyle="none", marker="o",
                       markersize=2.5, markevery=max(1, len(x) // 260), label="AVAC", zorder=2)
    depth_axis.set(xlabel=r"$x/X_0$", ylabel=r"$h/H_0$")
    velocity_axis.set(xlabel=r"$x/X_0$", ylabel=r"$u/U_0$")
    depth_axis.text(0.97, 0.94, rf"$t/T_0={tau:.2f}$", transform=depth_axis.transAxes,
                    ha="right", va="top")
    velocity_axis.text(0.97, 0.94, rf"$t/T_0={tau:.2f}$", transform=velocity_axis.transAxes,
                       ha="right", va="top")


def main_figure(output: Path) -> dict[str, dict[str, float]]:
    k_summary, k_fields, k_metrics = load_case("Kerswell_Coulomb")
    s_summary, s_fields, s_metrics = load_case("Coulomb_sloping_bed")
    fig, axes = plt.subplots(2, 3, figsize=figure_size(2, aspect=0.79), constrained_layout=True)

    k_x0 = 1.0 / 0.1
    k_t0 = np.sqrt(1.0 / G) / 0.1
    k_u0 = np.sqrt(G)
    k_metrics, k_report = standardized_coulomb_metrics(
        k_metrics, k_fields, time_scale=k_t0, length_scale=k_x0,
        front_name="front_x_m", rear_name="rear_x_m", rear_stop=-0.721577,
    )
    boundary_panel(axes[0, 0], k_metrics, k_t0, k_x0,
                   front_name="front_x_m", rear_name="rear_x_m", rear_stop=-0.721577)
    profile_panels(axes[0, 1], axes[0, 2], k_fields, k_t0, k_x0, k_u0)

    s_x0 = float(s_summary["length_scale_m"])
    s_t0 = float(s_summary["time_scale_s"])
    s_u0 = np.sqrt(G * np.cos(np.deg2rad(5.0)))
    s_metrics, s_report = standardized_coulomb_metrics(
        s_metrics, s_fields, time_scale=s_t0, length_scale=s_x0,
        front_name="front_envelope_x_m", rear_name="rear_h1_x_m", rear_stop=-0.721,
        recompute_front=False,
    )
    boundary_panel(axes[1, 0], s_metrics, s_t0, s_x0,
                   front_name="front_envelope_x_m", rear_name="rear_h1_x_m", rear_stop=-0.721)
    profile_panels(axes[1, 1], axes[1, 2], s_fields, s_t0, s_x0, s_u0)

    for col, title in enumerate(("Moving boundaries", "Flow depth", "Velocity")):
        axes[0, col].set_title(title)
    axes[0, 0].text(-0.23, 1.12, "Horizontal bed", transform=axes[0, 0].transAxes,
                    color=PAPER_COLORS["ink"], fontweight="bold")
    axes[1, 0].text(-0.23, 1.12, r"$5^\circ$ inclined bed", transform=axes[1, 0].transAxes,
                    color=PAPER_COLORS["ink"], fontweight="bold")
    for label, axis in zip("abcdef", axes.flat):
        axis.text(0.015, 0.985, f"({label})", transform=axis.transAxes,
                  ha="left", va="top", fontweight="bold")
    for axis in axes[:, 1:].flat:
        axis.set_xlim(-1.05, 2.08)
        axis.set_ylim(0.0, 1.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2)
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"avac_coulomb_verification.{suffix}")
    plt.close(fig)
    return {"Kerswell_Coulomb": k_report, "Coulomb_sloping_bed": s_report}


def wrr_figure(output: Path, manuscript_diagnostics: dict[str, dict[str, float]]) -> None:
    summary, fields, metrics = load_case("2008_WRR_sloping_bed")
    theta = np.deg2rad(10.0)
    t0 = np.sqrt(1.0 / (G * np.cos(theta)))
    times = np.asarray(metrics["time_s"], dtype=float)
    tau = times / t0
    open_boundary_value = summary.get("open_boundary_reached_s")
    open_boundary_time = (
        float(open_boundary_value) if open_boundary_value is not None
        else float(np.max(times))
    )
    theory_time = np.linspace(0.0, open_boundary_time, 600)
    theory_tau = theory_time / t0
    front_theory = 2.0 * theory_tau + 0.5 * theory_tau**2 * np.tan(theta)
    transition = 2.0 / np.tan(theta)
    rear_theory = np.where(
        theory_tau < transition,
        -theory_tau + 0.25 * theory_tau**2 * np.tan(theta),
        -2.0 * theory_tau + 0.5 * theory_tau**2 * np.tan(theta) + 1.0 / np.tan(theta),
    )

    fig, axes = plt.subplots(1, 2, figsize=figure_size(2, aspect=0.45), constrained_layout=True)
    axes[0].plot(theory_time, front_theory, color=MODEL_COLORS["theory"], label="Analytical fronts")
    axes[0].plot(theory_time, rear_theory, color=MODEL_COLORS["theory"])
    comparison = times <= open_boundary_time
    axes[0].plot(times[comparison], metrics["front_x_m"][comparison],
                 linestyle="none", marker="o", color=MODEL_COLORS["avac"],
                 label="AVAC")
    axes[0].plot(times[comparison], metrics["rear_x_m"][comparison],
                 linestyle="none", marker="s", color=MODEL_COLORS["avac"])
    axes[0].set(xlabel=r"time $t$ (s)", ylabel=r"boundary position $x$ (m)")
    axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)

    x = fields["x_m"]
    for color, target in zip(SERIES_COLORS[:3], (2.0, 3.5, 5.0)):
        index = int(np.argmin(np.abs(fields["time_s"] - target)))
        actual = float(fields["time_s"][index])
        axes[1].plot(x, fields["depth_m"][index], color=color,
                     label=rf"AVAC, $t={actual:.1f}$ s")
        local_tau = actual / t0
        front = 2.0 * local_tau + 0.5 * local_tau**2 * np.tan(theta)
        rear = (
            -local_tau + 0.25 * local_tau**2 * np.tan(theta)
            if local_tau < transition else
            -2.0 * local_tau + 0.5 * local_tau**2 * np.tan(theta) + 1.0 / np.tan(theta)
        )
        axes[1].axvline(front, color=color, linestyle="--", linewidth=1.1)
        axes[1].axvline(rear, color=color, linestyle=":", linewidth=1.1)
    axes[1].plot([], [], color=MODEL_COLORS["theory"], linestyle="--", label="Analytical front")
    axes[1].plot([], [], color=MODEL_COLORS["theory"], linestyle=":", label="Analytical rear")
    axes[1].set(xlabel=r"$x$ (m)", ylabel=r"flow depth $h$ (m)", xlim=(-15.0, 60.0))
    axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)
    for label, axis in zip("ab", axes):
        axis.text(0.015, 0.985, f"({label})", transform=axis.transAxes,
                  ha="left", va="top", fontweight="bold")
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"avac_wrr_water_limit.{suffix}")
    plt.close(fig)

    provenance = {
        "Kerswell_Coulomb": {
            "run_summary": load_case("Kerswell_Coulomb")[0],
            "manuscript_diagnostics": manuscript_diagnostics["Kerswell_Coulomb"],
        },
        "Coulomb_sloping_bed": {
            "run_summary": load_case("Coulomb_sloping_bed")[0],
            "manuscript_diagnostics": manuscript_diagnostics["Coulomb_sloping_bed"],
        },
        "2008_WRR_sloping_bed": {"run_summary": summary},
    }
    (output / "avac_verification_run_summaries.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    apply_paper_style()
    manuscript_diagnostics = main_figure(args.output_root.resolve())
    wrr_figure(args.output_root.resolve(), manuscript_diagnostics)
    print(args.output_root.resolve())


if __name__ == "__main__":
    main()
