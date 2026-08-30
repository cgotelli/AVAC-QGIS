#!/usr/bin/env python3
"""Reproduce the 2008 WRR dry-bottom sloping-bed case with AVAC or WAVE.

The original Chapter 8 calculation is one-dimensional.  This driver runs the
same frictionless shallow-water problem through the AVAC executable on a
five-cell-wide, transversely periodic strip, then evaluates its centerline. The
generated figures contain AVAC output and the analytical solution.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import dblquad, quad
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import root
from scipy.special import hyp2f1


HERE = Path(__file__).resolve().parent

from avac4qgis_validation.runtime import (
    GRAVITY,
    clean_case,
    configure_front_amr,
    fgout_centerline,
    fgout_times,
    maximum_written_amr_level,
    moving_front_corridors,
    prepare_avac_water_case,
    prepare_wave_hydraulic_case,
    run_solver,
    runtime,
    solver_executable,
)


H0 = 1.0
THETA = np.deg2rad(10.0)
BED_DATUM = 10.0
REAR_SPEED_TOLERANCE = 1.0e-2
# The original tutorial stopped at x=40 m, which the analytical front reaches
# before the final output.  The publication domain is extended downstream so
# both fronts remain interior for the complete comparison; the initial state,
# bed gradient, and boundary types are otherwise unchanged.
XLOWER, XUPPER = -10.0, 60.0
T_FINAL, NOUT = 5.0, 100
# The reference tutorial resolves the 50 m domain with 10,000 cells.  Keep
# the two-dimensional strip at that same 5 mm longitudinal resolution.
REFERENCE_DX = 0.005
T0 = np.sqrt(H0 / (np.cos(THETA) * GRAVITY))
U0 = np.sqrt(GRAVITY * H0 * np.cos(THETA))
# qinit.f90 from the supplied tutorial archive defines the initial dam-break
# wedge over [XB, 0].  Its free surface is horizontal at H0 and its depth is
# zero at the uphill edge.  It must not be replaced by a constant-depth slab.
XB = -H0 / np.tan(THETA)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def labelled_integer(path: Path, label: str) -> int:
    marker = f"=: {label}"
    for line in path.read_text(encoding="utf-8").splitlines():
        if marker in line:
            return int(line.split()[0])
    raise KeyError(f"Could not find {label!r} in {path}")


def theory_front(tau: np.ndarray) -> np.ndarray:
    """Analytical dry-front position from the 2008 WRR construction."""
    tau = np.asarray(tau, dtype=float)
    return H0 * (2.0 * tau + 0.5 * tau**2 * np.tan(THETA))


def theory_rear(tau: np.ndarray) -> np.ndarray:
    """Analytical rear boundary, including its turnaround branch."""
    tau = np.asarray(tau, dtype=float)
    transition = 2.0 / np.tan(THETA)
    moving = H0 * (-tau + 0.25 * tau**2 * np.tan(THETA))
    late = H0 * (-2.0 * tau + 0.5 * tau**2 * np.tan(THETA) + 1.0 / np.tan(THETA))
    return np.where(tau < transition, moving, late)


def initial_depth(x: np.ndarray) -> np.ndarray:
    """Exact triangular qinit depth, sampled at fixed-grid cell centers."""
    x = np.asarray(x, dtype=float)
    return np.where((x >= XB) & (x <= 0.0), H0 * (1.0 - x / XB), 0.0)


def track_boundaries(x: np.ndarray, depth: np.ndarray,
                     velocity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Measure the fronts with the supplied tutorial's definitions.

    In ``dry-bottom_Sloping-bed.ipynb``, ``x_b`` is the first upstream cell
    with resolvable motion, not the last cell that still matches the initial
    hydrostatic wedge.  The latter definition is particularly wrong after the
    analytical rear boundary turns downslope.  A 0.01 m/s resolution threshold
    is small relative to the O(1 m/s) benchmark flow but rejects sub-centimetre
    per second imbalance on the deliberately coarse hydrostatic far field.
    """
    rear = np.full(depth.shape[0], np.nan)
    front = np.full(depth.shape[0], np.nan)

    for index, (h, u) in enumerate(zip(depth, velocity)):
        rear_indices = np.flatnonzero(
            (u > REAR_SPEED_TOLERANCE) & (x < 0.0) & (h > 1.0e-4)
        )
        if rear_indices.size:
            # Coarse hydrostatic cells can occasionally exceed the velocity
            # tolerance in isolation.  The physical moving volume is the
            # downstream-most contiguous component, connected to the main
            # dam-break flow rather than to an isolated upstream cell.
            component_breaks = np.flatnonzero(np.diff(rear_indices) > 1)
            component_start = (
                rear_indices[component_breaks[-1] + 1]
                if component_breaks.size else rear_indices[0]
            )
            rear[index] = float(x[component_start])

        moving = x[u > 1.0e-4]
        if moving.size:
            front[index] = float(np.max(moving))
    return rear, front


def read_centerline(work: Path, solver_kind: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    times: list[float] = []
    depth_rows: list[np.ndarray] = []
    velocity_rows: list[np.ndarray] = []
    x: np.ndarray | None = None
    bed: np.ndarray | None = None
    for frame_no, _ in enumerate(fgout_times(solver_kind, work), start=1):
        time_s, frame_x, h, hu, _hv, frame_bed = fgout_centerline(
            solver_kind, work, frame_no
        )
        if x is None:
            x = frame_x
            bed = frame_bed
        times.append(time_s)
        depth_rows.append(h)
        # Exact velocity diagnostic used in the supplied notebook:
        #     u = q[1] / (q[0] + 1e-10)  where q[0] > 0.
        # The regularizer has no measurable effect above the front thresholds,
        # but retaining it avoids silently changing the published detector.
        velocity_rows.append(np.divide(hu, h + 1.0e-10,
                                       out=np.zeros_like(h), where=h > 0.0))
    if x is None or bed is None:
        raise RuntimeError(f"{solver_kind.upper()} did not write fixed-grid output.")
    return np.asarray(times), x, bed, np.asarray(depth_rows), np.asarray(velocity_rows)


def trace(rhs, start: float, times: np.ndarray) -> np.ndarray:
    curve = np.empty_like(times)
    curve[0] = start
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        t = times[index - 1]
        position = curve[index - 1]
        k1 = rhs(position, t)
        k2 = rhs(position + 0.5 * dt * k1, t + 0.5 * dt)
        k3 = rhs(position + 0.5 * dt * k2, t + 0.5 * dt)
        k4 = rhs(position + dt * k3, t + dt)
        curve[index] = position + dt * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
    return curve


# The following Riemann construction is transcribed from the original
# dry-bottom_Sloping-bed notebook.  It is post-processing only: AVAC never
# receives this solution as an initial or boundary condition.
@lru_cache(maxsize=None)
def riemann(r: float, s: float, x: float, y: float) -> float:
    denominator = (r - y) ** 1.5 * (x - s) ** 1.5
    if denominator == 0.0:
        return 0.0
    z = ((r - x) * (y - s)) / ((x - s) * (r - y))
    if not np.isfinite(z) or abs(z) >= 1.0:
        return 0.0
    return (r - s) ** 3 * hyp2f1(1.5, 1.5, 1, z) / denominator


@lru_cache(maxsize=None)
def triemann(r: float, s: float) -> float:
    def integrand(value: float) -> float:
        return riemann(value, -2.0, r, s) * (2.0 - 5.0 * value) / (4.0 * (value + 2.0))
    integral, _ = quad(integrand, 2.0 + 1.0e-4, r, limit=1000, epsabs=1.0e-5, epsrel=1.0e-5)
    return float(np.real(integral) / np.tan(THETA))


@lru_cache(maxsize=None)
def xsriemann(r: float, s: float) -> float:
    def first_integrand(value: float) -> float:
        return riemann(value, -2.0, r, s) * (2.0 - 5.0 * value) / (4.0 * (value + 2.0))
    first, _ = quad(first_integrand, 2.0 + 1.0e-4, r, limit=1000, epsabs=1.0e-5, epsrel=1.0e-5)
    c1 = (3.0 * s + r) * first / (4.0 * np.tan(THETA))

    def second_integrand(value: float, rr: float) -> float:
        return riemann(value, -2.0, rr, s) * (2.0 - 5.0 * value) / (4.0 * (value + 2.0)) * (value > rr)

    c2, _ = dblquad(
        second_integrand, r, 2.0 - 1.0e-4,
        lambda rr: max(2.0 + 1.0e-4, rr), lambda rr: r,
        epsabs=1.0e-5, epsrel=1.0e-5,
    )
    return float(c1 + c2 / (4.0 * np.tan(THETA)))


def analytical_profile(tau: float, samples: int = 55) -> tuple[np.ndarray, np.ndarray]:
    """Depth profile of the original sloping-bed analytical solution."""
    s_values = np.linspace(-2.0 + 1.0e-2, 2.0 - 1.0e-2, samples)
    r_values: list[float] = []
    valid_s: list[float] = []
    for s in s_values:
        solution = root(lambda value: triemann(float(value[0]), float(s)) - tau,
                        x0=np.asarray([(s + 2.0) / 2.0]), method="lm")
        if not solution.success or not np.isfinite(solution.x[0]):
            continue
        r = float(solution.x[0])
        if not (-2.0 < s < r < 2.0):
            continue
        valid_s.append(float(s))
        r_values.append(r)
    if not valid_s:
        return np.empty(0), np.empty(0)
    s = np.asarray(valid_s)
    r = np.asarray(r_values)
    positions = np.asarray([xsriemann(float(rr), float(ss)) for rr, ss in zip(r, s)])
    positions += 0.5 * tau**2 * np.tan(THETA)
    depth = (r - s) ** 2 / 16.0
    keep = np.isfinite(positions) & np.isfinite(depth) & (depth <= H0 + 1.0e-10)
    return positions[keep] * H0, depth[keep] * H0


def make_figures(times: np.ndarray, x: np.ndarray, bed: np.ndarray, depth: np.ndarray,
                 velocity: np.ndarray, rear: np.ndarray, front: np.ndarray,
                 figures: Path, model_label: str, file_tag: str) -> None:
    figures.mkdir(exist_ok=True)
    h_interp = RegularGridInterpolator((times, x), depth, bounds_error=False, fill_value=0.0)
    u_interp = RegularGridInterpolator((times, x), velocity, bounds_error=False, fill_value=0.0)
    characteristic_time = np.arange(0.0, times[-1] + 1.0e-12, 0.01)

    def h_at(position: float, time: float) -> float:
        return max(float(h_interp([[time, position]])[0]), 0.0)

    def u_at(position: float, time: float) -> float:
        return float(u_interp([[time, position]])[0])

    fig, axis = plt.subplots(figsize=(10.5, 5.2))
    for index, start in enumerate(np.linspace(-5.0, 0.0, 5)):
        curve = trace(lambda xx, tt: u_at(xx, tt) + np.sqrt(GRAVITY * h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve / H0, characteristic_time / T0, color="0.5", lw=1.1,
                  label=r"$r$-characteristics" if index == 0 else None)
    for index, value in enumerate(np.linspace(-2.0, 2.0, 8)):
        start = 1.0e-4 * value * U0
        curve = trace(
            lambda xx, tt, s=value: np.sqrt(GRAVITY * h_at(xx, tt) * np.cos(THETA))
            + tt * np.sin(THETA) * GRAVITY + s * U0,
            start, characteristic_time,
        )
        axis.plot(curve / H0, characteristic_time / T0, color="#1249d8", lw=1.0,
                  label=r"$s$-characteristics in fan" if index == 0 else None)
    for index, start in enumerate(np.linspace(-5.0, -0.5, 6)):
        curve = trace(lambda xx, tt: u_at(xx, tt) - np.sqrt(GRAVITY * h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve / H0, characteristic_time / T0, color="#00a9b8", lw=1.0,
                  label=r"$s$-characteristics at rest" if index == 0 else None)
    tau_curve = characteristic_time / T0
    interior_front = front < x[-1] - 1.5 * np.median(np.diff(x))
    # The tutorial measures x_b for every output time.  The downstream dry
    # front reaching the open eastern boundary does not invalidate the
    # upstream rear-front measurement, so never truncate x_b on that event.
    rear_visible = np.isfinite(rear)
    axis.scatter(rear[rear_visible] / H0, times[rear_visible] / T0,
                 marker="+", color="black", s=18, label=rf"$x_b$ ({model_label})")
    # The supplied tutorial domain ends at x=40 m.  A dry-front position is
    # not measurable after it reaches the open boundary, so do not draw the
    # boundary-clamped values as if they were an interior solution.
    axis.scatter(front[interior_front] / H0, times[interior_front] / T0,
                 marker="o", color="black", s=8, label=rf"$x_f$ ({model_label})")
    axis.plot(theory_front(tau_curve) / H0, tau_curve, color="#d62728", lw=1.8, label=r"$x_f$ (theory)")
    axis.plot(theory_rear(tau_curve) / H0, tau_curve, color="#e69500", lw=1.8, label=r"$x_b$ (theory)")
    axis.set(xlabel=r"$x/H_0$", ylabel=r"$t/T_0$", xlim=(-6.0, 25.0), ylim=(0.0, 5.0 / T0))
    axis.grid(alpha=0.35)
    axis.legend(ncol=3, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(figures / f"wrr_characteristics_{file_tag}_vs_theory.png", dpi=240)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 5))
    for time_s in (2.0, 3.0, 4.0):
        index = int(np.argmin(np.abs(times - time_s)))
        axis.plot(x / H0, depth[index] / H0, lw=1.2,
                  label=rf"{model_label}, $t={times[index]:.1f}$ s")
        tau_value = times[index] / T0
        axis.axvline(theory_rear(np.asarray([tau_value]))[0] / H0, color="#e69500", ls="--", lw=0.85)
        axis.axvline(theory_front(np.asarray([tau_value]))[0] / H0, color="#d62728", ls="--", lw=0.85)
    axis.plot([], [], "--", color="#e69500", lw=0.9, label=r"theory $x_b$")
    axis.plot([], [], "--", color="#d62728", lw=0.9, label=r"theory $x_f$")
    axis.set(xlabel=r"$x/H_0$", ylabel=r"$h/H_0$", xlim=(-10.0, 60.0), ylim=(-0.03, 1.08))
    axis.grid(alpha=0.35)
    axis.legend(ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(figures / f"wrr_depth_profiles_{file_tag}_vs_theory.png", dpi=240)
    plt.close(fig)

    frame_index = int(np.argmin(np.abs(times - 1.5)))
    fig, axis = plt.subplots(figsize=(10, 4.2))
    axis.plot(x, bed, color="saddlebrown", lw=1.2, label="bed")
    axis.plot(x, bed + depth[frame_index], color="#0072B2", lw=1.4,
              label=rf"{model_label} free surface, $t={times[frame_index]:.2f}$ s")
    axis.set(xlabel=r"$x$ (m)", ylabel="elevation (m)")
    axis.grid(alpha=0.35)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(figures / f"wrr_surface_profile_{file_tag}.png", dpi=240)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dx", type=float, default=REFERENCE_DX,
        help="uniform AVAC x/y cell size in m (default: 0.005 m, matching the tutorial)",
    )
    parser.add_argument("--t-final", type=float, default=T_FINAL)
    parser.add_argument("--nout", type=int, default=NOUT)
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument("--amr-levels", type=int, default=1)
    parser.add_argument("--amr-ratio", type=int, default=2)
    parser.add_argument("--speed-tolerance", type=float, default=0.02)
    parser.add_argument("--ny", type=int, default=5)
    parser.add_argument(
        "--max1d", type=int, default=1254,
        help=(
            "maximum same-level patch extent including ghost cells "
            "(default: 1254, eight longitudinal patches at dx=0.005 m)"
        ),
    )
    parser.add_argument(
        "--postprocess-only", action="store_true",
        help="regenerate diagnostics from an already completed solver run",
    )
    parser.add_argument("--solver", choices=("avac", "wave"), default="avac")
    parser.add_argument("--output-root", type=Path, default=HERE)
    args = parser.parse_args()
    if (args.dx <= 0 or args.t_final <= 0 or args.nout < 3 or args.cores < 1
            or args.max1d < 6 or args.amr_levels < 1 or args.amr_ratio < 2
            or args.speed_tolerance <= 0 or args.ny < 1):
        raise ValueError("Invalid positive grid/run controls; nout must be >=3 and AMR ratio >=2")
    if not np.isclose((XUPPER - XLOWER) / args.dx, round((XUPPER - XLOWER) / args.dx)):
        raise ValueError("dx must divide the 70 m publication domain exactly")

    case_root = args.output_root.resolve()
    case_root.mkdir(parents=True, exist_ok=True)
    work = case_root / ("AVAC" if args.solver == "avac" else "Wave")
    if not args.postprocess_only:
        clean_case(case_root)
        prepare = (prepare_avac_water_case if args.solver == "avac"
                   else prepare_wave_hydraulic_case)
        prepare_kwargs = {
            "case": case_root, "xlower": XLOWER, "xupper": XUPPER,
            "ylower": 0.0, "yupper": args.ny * args.dx,
            "dx": args.dx, "t_final": args.t_final, "nout": args.nout,
            # A constant datum leaves the equations and exact solution
            # unchanged, while keeping dry downstream cells above GeoClaw's
            # default sea level during AMR interpolation.
            "bed": lambda X, Y: BED_DATUM + np.tan(-THETA) * X,
            # Exact transcription of qinit.f90 in
            # Chapter_8/1_Sloping-bed/dry-bottom_Sloping-bed.tar.gz:
            # q(1,i) = H0 * (1 - x / xb), xb = -H0 / tan(theta).
            "depth": lambda X, Y: np.where(
                (X >= XB) & (X <= 0.0), H0 * (1.0 - X / XB), 0.0
            ),
            # Periodic transverse boundaries are the faithful two-dimensional
            # extrusion of the tutorial's one-dimensional problem.  Reflective
            # side walls can seed small transverse modes in a narrow strip.
            "boundary_west": "wall", "boundary_east": "extrap",
            "boundary_south": "periodic", "boundary_north": "periodic",
            "limiter": "superbee", "max1d": args.max1d,
        }
        if args.solver == "avac":
            prepare_kwargs["refinement"] = args.amr_levels
            prepare_kwargs["qinit_dx"] = (
                args.dx / args.amr_ratio ** (args.amr_levels - 1)
            )
        work = prepare(**prepare_kwargs)
        controls: dict[str, object] = {
            "base_dx_m": float(args.dx), "finest_dx_m": float(args.dx),
            "amr_levels": 1, "refinement_ratios": [],
            "speed_tolerance_m_s": None, "fgout_ny": args.ny,
            "max1d": args.max1d,
        }
        if args.solver == "avac" and args.amr_levels > 1:
            corridor_interval = 0.05
            corridor_margin = 0.15
            corridors = moving_front_corridors(
                lambda values: theory_front(np.asarray(values) / T0),
                lambda values: theory_rear(np.asarray(values) / T0),
                t_final=args.t_final, interval=corridor_interval,
                margin=corridor_margin, xlower=XLOWER, xupper=XUPPER,
                ylower=0.0, yupper=args.ny * args.dx,
                level=args.amr_levels,
            )
            controls = configure_front_amr(
                work, base_dx=args.dx, xlower=XLOWER, xupper=XUPPER,
                ylower=0.0, yupper=args.ny * args.dx,
                levels=args.amr_levels, ratio=args.amr_ratio,
                speed_tolerance=args.speed_tolerance, output_ny=1,
                max1d=args.max1d,
                forced_regions=corridors,
            ) | {
                "corridor_interval_s": corridor_interval,
                "corridor_margin_m": corridor_margin,
                "qinit_dx_m": prepare_kwargs["qinit_dx"],
                "rear_speed_tolerance_m_s": REAR_SPEED_TOLERANCE,
            }
        controls |= {
            "domain_xlower_m": XLOWER,
            "domain_xupper_m": XUPPER,
        }
        (case_root / "controls.json").write_text(json.dumps(controls, indent=2) + "\n")
        run_solver(args.solver, work, cores=args.cores)
    elif not work.is_dir():
        raise FileNotFoundError("No completed solver directory is available for post-processing")
    times, x, bed, depth, velocity = read_centerline(work, args.solver)
    controls = json.loads((case_root / "controls.json").read_text())
    rear, front = track_boundaries(x, depth, velocity)
    dx_actual = float(np.median(np.diff(x)))
    max1d_actual = labelled_integer(work / "amr.data", "max1d")
    mass = np.sum(depth, axis=1) * dx_actual
    expected_initial_mass = H0**2 / (2.0 * np.tan(THETA))
    initial_depth_error = float(np.max(np.abs(depth[0] - initial_depth(x))))
    tau = times / T0
    interior_front = np.isfinite(front) & (front < x[-1] - 1.5 * dx_actual)
    if not np.any(interior_front):
        raise RuntimeError("The front reaches the open boundary before any interior diagnostic frame")
    # Frame zero has no moving dry front by definition; it is not an outflow
    # event.  Only a resolved front that reaches the downstream boundary
    # terminates the interior comparison window.
    outflow_start = np.flatnonzero(np.isfinite(front) & ~interior_front)
    closed_mass = mass[interior_front]
    summary = {
        "solver": str(solver_executable(args.solver)),
        "solver_sha256": sha256(solver_executable(args.solver)),
        "water_model": f"{args.solver.upper()} Water",
        "bed_datum_m": BED_DATUM,
        "diagnostic_dx_m": dx_actual,
        "width_base_cells": args.ny,
        **controls,
        "maximum_amr_level_seen": maximum_written_amr_level(work),
        "final_amr_level": maximum_written_amr_level(work, final_only=True),
        "max1d": max1d_actual,
        "cores": args.cores,
        "t_final_s": float(times[-1]),
        "front_rmse_m_before_open_boundary_m": float(np.sqrt(np.nanmean(
            (front[interior_front] - theory_front(tau[interior_front])) ** 2
        ))),
        "rear_rmse_m_before_open_boundary_m": float(np.sqrt(np.nanmean(
            (rear[interior_front] - theory_rear(tau[interior_front])) ** 2
        ))),
        "front_rmse_m_full_domain": float(np.sqrt(np.nanmean(
            (front[interior_front] - theory_front(tau[interior_front])) ** 2
        ))),
        "rear_rmse_m_full_domain": float(np.sqrt(np.nanmean(
            (rear[interior_front] - theory_rear(tau[interior_front])) ** 2
        ))),
        "rear_rmse_m_full_run": float(np.sqrt(np.nanmean(
            (rear - theory_rear(tau)) ** 2
        ))),
        "rear_final_error_m": float(rear[-1] - theory_rear(tau[-1])),
        "initial_depth_max_abs_error_m": initial_depth_error,
        "mass_initial_m2_per_m": float(mass[0]),
        "mass_initial_theory_m2_per_m": float(expected_initial_mass),
        "mass_range_before_open_boundary_m2_per_m": float(np.ptp(closed_mass)),
        "mass_range_full_domain_m2_per_m": float(np.ptp(closed_mass)),
        "open_boundary_reached_s": float(times[outflow_start[0]]) if outflow_start.size else None,
        "mass_final_m2_per_m": float(mass[-1]),
    }
    results = case_root / "results"
    results.mkdir(exist_ok=True)
    np.savez_compressed(results / "centerline_fields.npz", time_s=times, x_m=x, bed_m=bed,
                        depth_m=depth, velocity_m_s=velocity)
    np.savetxt(results / "boundary_metrics.csv", np.column_stack((times, front, rear, np.max(np.abs(velocity), axis=1), mass)),
               delimiter=",", header="time_s,front_x_m,rear_x_m,max_speed_m_s,mass_m2_per_m", comments="")
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    make_figures(times, x, bed, depth, velocity, rear, front,
                 case_root / "figures", args.solver.upper(), args.solver)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
