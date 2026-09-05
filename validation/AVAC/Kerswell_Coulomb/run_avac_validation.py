#!/usr/bin/env python3
"""Run the Kerswell Coulomb dam-break using the AVAC source.

The Chapter 8 problem is expanded to a five-cell-wide strip with wall
boundaries across the strip.  The centerline is evaluated from the AVAC field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import brentq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AVAC_SOURCE = ROOT / "avac-main" / "src" / "AVAC"

from avac4qgis_validation.runtime import (
    GRAVITY,
    configure_analytical_coulomb_amr_compatibility,
    configure_front_amr,
    fgout_centerline,
    fgout_times,
    maximum_written_amr_level,
    moving_front_corridors,
    prepare_avac_coulomb_case,
    run_solver,
    solver_executable,
)
from avac4qgis_validation.kerswell import (
    UNDISTURBED_RELATIVE_DEPTH_TOLERANCE,
    position_riemann,
    time_riemann,
    undisturbed_rear_position,
)


H0 = 1.0
MU = 0.1
XLOWER, XUPPER = -10.0, 30.0
X0 = H0 / MU
T0 = np.sqrt(H0 / GRAVITY) / MU
U0 = np.sqrt(GRAVITY * H0)
TRANSVERSE_CELLS = 5
DEFAULT_T_FINAL_S = 10.0
DEFAULT_OUTPUT_COUNT = 200


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def theory_front(time_s: np.ndarray) -> np.ndarray:
    tau = np.asarray(time_s, dtype=float) / T0
    return X0 * np.where(tau < 2.0, 2.0 * tau - 0.5 * tau**2, 2.0)


def theory_rear(time_s: np.ndarray) -> np.ndarray:
    tau = np.asarray(time_s, dtype=float) / T0
    b = 0.5 * tau + 1.0
    moving = X0 * -(
        -3.64928 + 5.47993 * b - 2.06989 * b**2 + 0.319976 * b**3
        - 0.103745 * b**4 + 0.0230073 * b**5
    )
    return np.where(tau < 1.529654, moving, -0.721577 * X0)


def read_centerline(work: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return fgout time, x, depth, and x velocity on the strip centerline."""
    times: list[float] = []
    depth_rows: list[np.ndarray] = []
    velocity_rows: list[np.ndarray] = []
    x: np.ndarray | None = None
    for frame_no, _ in enumerate(fgout_times("avac", work), start=1):
        time_s, frame_x, h, hu, _hv, _bed = fgout_centerline("avac", work, frame_no)
        if x is None:
            x = frame_x
        u = np.divide(hu, h, out=np.zeros_like(h), where=h > 1.0e-12)
        times.append(time_s)
        depth_rows.append(h)
        velocity_rows.append(u)
    if x is None:
        raise RuntimeError("AVAC did not write fixed-grid output.")
    return np.asarray(times), x, np.asarray(depth_rows), np.asarray(velocity_rows)


def require_complete_output_schedule(
    times: np.ndarray, requested_final_time_s: float, output_count: int,
) -> None:
    """Reject partial or off-cadence fgout before computing verification metrics."""
    expected = np.linspace(0.0, requested_final_time_s, output_count)
    # GeoClaw serializes FGout times with eight digits after the decimal in
    # scientific notation.  Accept only that round-trip loss; larger cadence
    # changes are still rejected.
    tolerance = 1.0e-8 * max(1.0, requested_final_time_s)
    if len(times) != len(expected) or not np.allclose(
        times, expected, rtol=0.0, atol=tolerance,
    ):
        last = float(times[-1]) if len(times) else float("nan")
        raise RuntimeError(
            "Kerswell output is incomplete or off cadence: "
            f"expected {len(expected)} frames through {requested_final_time_s:g} s, "
            f"found {len(times)} through {last:g} s."
        )


def extract(
    work: Path,
    controls: dict[str, object],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    times, x, depth, velocity = read_centerline(work)
    require_complete_output_schedule(
        times,
        float(controls.get("requested_t_final_s", DEFAULT_T_FINAL_S)),
        int(controls.get("outputs", DEFAULT_OUTPUT_COUNT)),
    )
    dx = float(np.median(np.diff(x)))
    front = np.full(times.shape, np.nan)
    rear = np.full(times.shape, np.nan)
    rear_exact = np.full(times.shape, np.nan)
    max_speed = np.max(np.abs(velocity), axis=1)
    for index, (h, u) in enumerate(zip(depth, velocity)):
        wet = x[h > 1.0e-12]
        if wet.size:
            front[index] = float(np.max(wet))
        rear[index] = undisturbed_rear_position(x, h, H0)
        undisturbed_exact = x[np.abs(h - H0) <= 1.0e-8]
        if undisturbed_exact.size:
            rear_exact[index] = float(np.max(undisturbed_exact))
    mass = np.sum(depth, axis=1) * dx
    moving_front = times <= 2.0 * T0
    moving_rear = times <= 1.529654 * T0
    summary = {
        **controls,
        "diagnostic_dx_m": dx,
        "width_base_cells": int(
            controls.get("width_base_cells", TRANSVERSE_CELLS)
        ),
        "maximum_amr_level_seen": maximum_written_amr_level(work),
        "final_amr_level": maximum_written_amr_level(work, final_only=True),
        "t_final_s": float(times[-1]),
        "front_rmse_moving_m": float(np.sqrt(np.nanmean(
            (front[moving_front] - theory_front(times[moving_front])) ** 2
        ))),
        "rear_rmse_moving_m": float(np.sqrt(np.nanmean(
            (rear[moving_rear] - theory_rear(times[moving_rear])) ** 2
        ))),
        "rear_exact_state_rmse_moving_m": float(np.sqrt(np.nanmean(
            (rear_exact[moving_rear] - theory_rear(times[moving_rear])) ** 2
        ))),
        "rear_relative_depth_tolerance": UNDISTURBED_RELATIVE_DEPTH_TOLERANCE,
        "front_final_m": float(front[-1]),
        "front_theory_final_m": float(theory_front(times[-1])),
        "rear_final_m": float(rear[-1]),
        "rear_theory_final_m": float(theory_rear(times[-1])),
        "maximum_speed_final_m_s": float(max_speed[-1]),
        "mass_initial_m2_per_m": float(mass[0]),
        "mass_range_m2_per_m": float(np.ptp(mass)),
    }
    return times, x, depth, velocity, summary | {
        "_front": front, "_rear": rear, "_rear_exact": rear_exact, "_mass": mass,
    }


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


def analytical_profile(tau: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Kerswell's analytical profile, evaluated only for plotting."""
    s_values = np.arange(-1.0 + 1.0e-5, 1.0, 0.01)
    valid_s: list[float] = []
    r_values: list[float] = []
    for s in s_values:
        lower, upper = 1.0 + 1.0e-9, 1.7657
        try:
            f_lower = time_riemann(float(s), lower) - tau
            f_upper = time_riemann(float(s), upper) - tau
        except (ArithmeticError, ValueError):
            continue
        if not (np.isfinite(f_lower) and np.isfinite(f_upper)) or f_lower * f_upper >= 0.0:
            continue
        r = brentq(lambda value: time_riemann(float(s), value) - tau, lower, upper, xtol=1.0e-10)
        valid_s.append(float(s))
        r_values.append(float(r))
    if not valid_s:
        return np.empty(0), np.empty(0), np.empty(0)
    s = np.asarray(valid_s)
    r = np.asarray(r_values)
    x = np.asarray([position_riemann(float(ss), float(rr)) for ss, rr in zip(s, r)]) * X0
    h = (r + s) ** 2 / 4.0
    u = (r - s - tau) * U0
    return x, h, u


def plot(times: np.ndarray, x: np.ndarray, depth: np.ndarray, velocity: np.ndarray,
         summary: dict[str, float], figures: Path) -> None:
    figures.mkdir(exist_ok=True)
    front = np.asarray(summary.pop("_front"))
    rear = np.asarray(summary.pop("_rear"))
    mass = np.asarray(summary.pop("_mass"))
    h_interp = RegularGridInterpolator((times, x), depth, bounds_error=False, fill_value=0.0)
    u_interp = RegularGridInterpolator((times, x), velocity, bounds_error=False, fill_value=0.0)
    characteristic_time = np.arange(0.0, min(8.0, times[-1]) + 1.0e-12, 0.01)

    def h_at(position: float, time: float) -> float:
        return max(float(h_interp([[time, position]])[0]), 0.0)

    def u_at(position: float, time: float) -> float:
        return float(u_interp([[time, position]])[0])

    fig, axis = plt.subplots(figsize=(10, 5.2))
    for index, start in enumerate(np.linspace(-5.0, 0.0, 5)):
        curve = trace(lambda xx, tt: u_at(xx, tt) + np.sqrt(GRAVITY * h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve / X0, characteristic_time / T0, color="0.5", lw=1.15,
                  label=r"$r$-characteristics" if index == 0 else None)
    for index, value in enumerate(np.linspace(-1.0, 1.0, 8)):
        curve = trace(
            lambda xx, tt, s=value: np.sqrt(GRAVITY * h_at(xx, tt)) - 2.0 * s * U0 - MU * GRAVITY * tt,
            0.0, characteristic_time,
        )
        axis.plot(curve / X0, characteristic_time / T0, color="#1249d8", lw=1.05,
                  label=r"$s$-characteristics" if index == 0 else None)
    for index, start in enumerate(np.linspace(-5.0, -0.5, 6)):
        curve = trace(lambda xx, tt: u_at(xx, tt) - np.sqrt(GRAVITY * h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve / X0, characteristic_time / T0, color="#00a9b8", lw=1.05,
                  label=r"$s$-characteristics at rest" if index == 0 else None)
    axis.scatter(rear / X0, times / T0, marker="+", s=18, color="black", label=r"$x_b$ (AVAC)")
    axis.scatter(front / X0, times / T0, marker="o", s=9, color="black", label=r"$x_f$ (AVAC)")
    axis.plot(theory_front(characteristic_time) / X0, characteristic_time / T0,
              color="#d62728", lw=1.8, label=r"$x_f$ (Kerswell theory)")
    axis.plot(theory_rear(characteristic_time) / X0, characteristic_time / T0,
              color="#e69500", lw=1.8, label=r"$x_b$ (Kerswell theory)")
    axis.set(xlabel=r"$x/X_0$", ylabel=r"$t/T_0$", xlim=(-1.0, 2.5), ylim=(0.0, 2.5))
    axis.grid(alpha=0.35)
    axis.legend(ncol=3, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(figures / "figure_8_7_avac_vs_theory.png", dpi=240)
    plt.close(fig)

    theory_time = np.linspace(0.0, times[-1], 800)
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.4))
    axes[0].plot(theory_time / T0, theory_rear(theory_time) / X0, "k-", lw=1.8, label="Kerswell theory")
    axes[0].plot(times / T0, rear / X0, "+", color="#0072B2", ms=5, label="AVAC")
    axes[0].set(xlabel=r"$t/T_0$", ylabel=r"$x_b/X_0$", title="Rear boundary")
    axes[1].plot(theory_time / T0, theory_front(theory_time) / X0, "k-", lw=1.8, label="Kerswell theory")
    axes[1].plot(times / T0, front / X0, "+", color="#0072B2", ms=5, label="AVAC")
    axes[1].set(xlabel=r"$t/T_0$", ylabel=r"$x_f/X_0$", title="Front boundary")
    for axis in axes:
        axis.grid(alpha=0.35)
        axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(figures / "figure_8_10_avac_vs_theory.png", dpi=240)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7.6), sharex=True)
    for time_s in (1.0, 2.0, 4.0, 6.0):
        index = int(np.argmin(np.abs(times - time_s)))
        x_theory, h_theory, u_theory = analytical_profile(float(times[index] / T0))
        axes[0].plot(x / X0, depth[index] / H0, lw=1.05, label=rf"AVAC, $t={times[index]:.1f}$ s")
        axes[1].plot(x / X0, velocity[index] / U0, lw=1.05, label=rf"AVAC, $t={times[index]:.1f}$ s")
        if x_theory.size:
            axes[0].plot(x_theory / X0, h_theory / H0, "k--", lw=0.85)
            axes[1].plot(x_theory / X0, u_theory / U0, "k--", lw=0.85)
    axes[0].plot([], [], "k--", label="Kerswell theory")
    axes[0].set(ylabel=r"$h/H_0$", ylim=(-0.03, 1.08), title="Depth profiles")
    axes[1].set(xlabel=r"$x/X_0$", ylabel=r"$u/U_0$", title="Velocity profiles")
    for axis in axes:
        axis.set(xlim=(-1.2, 2.3))
        axis.grid(alpha=0.35)
        axis.legend(ncol=2, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(figures / "profiles_avac_vs_theory.png", dpi=240)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.1))
    axes[0].semilogy(times, np.maximum(np.max(np.abs(velocity), axis=1), 1.0e-15), color="#0072B2")
    axes[0].axvline(2.0 * T0, color="black", ls="--", lw=1, label="theoretical front arrest")
    axes[0].set(xlabel="time (s)", ylabel="maximum speed (m/s)")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(times, mass - mass[0], color="#0072B2")
    axes[1].set(xlabel="time (s)", ylabel=r"mass change (m$^2$/m)")
    for axis in axes:
        axis.grid(alpha=0.35)
    fig.tight_layout()
    fig.savefig(figures / "avac_arrest_and_mass.png", dpi=240)
    plt.close(fig)


def main() -> None:
    global TRANSVERSE_CELLS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dx", type=float, default=0.01, help="base-grid spacing in m")
    parser.add_argument("--t-final", type=float, default=DEFAULT_T_FINAL_S)
    parser.add_argument("--nout", type=int, default=DEFAULT_OUTPUT_COUNT)
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument(
        "--ny", type=int, default=TRANSVERSE_CELLS,
        help="number of uniform transverse cells in the quasi-1D strip",
    )
    parser.add_argument("--case-name", default="publication_amr")
    parser.add_argument("--amr-levels", type=int, default=3)
    parser.add_argument("--amr-ratio", type=int, default=2)
    parser.add_argument("--speed-tolerance", type=float, default=0.02)
    parser.add_argument("--max1d", type=int, default=1000)
    parser.add_argument(
        "--solver", type=Path,
        help="exact AVAC executable to run; requires --solver-source",
    )
    parser.add_argument(
        "--solver-source", type=Path,
        help="source directory containing the setrun.py paired with --solver",
    )
    parser.add_argument(
        "--postprocess-only",
        action="store_true",
        help="recompute diagnostics and figures from the completed fixed-grid output",
    )
    args = parser.parse_args()
    if (args.solver is None) != (args.solver_source is None):
        raise SystemExit("--solver and --solver-source must be supplied together")
    if (args.dx <= 0 or args.t_final <= 0 or args.nout < 3 or args.cores < 1
            or args.ny < 1
            or args.amr_levels < 2 or args.amr_ratio < 2 or args.speed_tolerance <= 0):
        raise ValueError("dx, t-final, cores, ny, speed-tolerance, and nout>=3 must be positive; AMR needs levels>=2 and ratio>=2")
    if not np.isclose((XUPPER - XLOWER) / args.dx, round((XUPPER - XLOWER) / args.dx)):
        raise ValueError("dx must divide the 40 m domain exactly")

    TRANSVERSE_CELLS = int(args.ny)

    case_root = HERE / args.case_name
    figures = case_root / "figures"
    if args.postprocess_only:
        work = case_root / "AVAC"
        controls_path = case_root / "controls.json"
        if not work.is_dir() or not controls_path.is_file():
            raise FileNotFoundError(
                f"Completed case not found for post-processing: {case_root}"
            )
        controls = json.loads(controls_path.read_text(encoding="utf-8"))
        TRANSVERSE_CELLS = int(
            controls.get("width_base_cells", TRANSVERSE_CELLS)
        )
        # Legacy controls predate these explicit schedule fields.  In that
        # case, the post-processing CLI values remain the disclosed contract.
        controls.setdefault("requested_t_final_s", float(args.t_final))
        controls.setdefault("outputs", int(args.nout))
        controls.setdefault("width_base_cells", TRANSVERSE_CELLS)
    else:
        solver = (
            args.solver.expanduser().resolve()
            if args.solver is not None else solver_executable("avac")
        )
        solver_source = (
            args.solver_source.expanduser().resolve()
            if args.solver_source is not None else AVAC_SOURCE.resolve()
        )
        if not solver.is_file():
            raise FileNotFoundError(f"AVAC solver executable is missing: {solver}")
        setrun_backend = solver_source / "setrun.py"
        if not setrun_backend.is_file():
            raise FileNotFoundError(f"AVAC setrun backend is missing: {setrun_backend}")
        setrun_backend_sha256 = sha256(setrun_backend)
        solver_sha256 = sha256(solver)
        work = prepare_avac_coulomb_case(
            case_root, xlower=XLOWER, xupper=XUPPER, ylower=0.0,
            yupper=TRANSVERSE_CELLS * args.dx,
            dx=args.dx, t_final=args.t_final, nout=args.nout, mu=MU,
            depth=lambda X, Y: np.where((X >= XLOWER) & (X <= 0.0), H0, 0.0),
            refinement=args.amr_levels,
            source_override=solver_source,
            analytical_validation_ghost_cells=2,
        )
        compatibility = configure_analytical_coulomb_amr_compatibility(work)
        corridor_interval = 0.05
        corridor_margin = 0.15
        corridors = moving_front_corridors(
            theory_front, theory_rear, t_final=args.t_final,
            interval=corridor_interval, margin=corridor_margin,
            xlower=XLOWER, xupper=XUPPER, ylower=0.0,
            yupper=TRANSVERSE_CELLS * args.dx,
            level=args.amr_levels,
        )
        controls = configure_front_amr(
            work, base_dx=args.dx, xlower=XLOWER, xupper=XUPPER,
            ylower=0.0, yupper=TRANSVERSE_CELLS * args.dx,
            levels=args.amr_levels, ratio=args.amr_ratio,
            speed_tolerance=args.speed_tolerance, output_ny=1, max1d=args.max1d,
            forced_regions=corridors,
        ) | compatibility | {
            "corridor_interval_s": corridor_interval,
            "corridor_margin_m": corridor_margin,
            "solver": str(solver),
            "solver_sha256": solver_sha256,
            "source_setrun": str(setrun_backend),
            "source_setrun_sha256": setrun_backend_sha256,
            "requested_t_final_s": float(args.t_final),
            "outputs": int(args.nout),
            "width_base_cells": TRANSVERSE_CELLS,
        }
        (case_root / "controls.json").write_text(json.dumps(controls, indent=2) + "\n")
        if sha256(setrun_backend) != setrun_backend_sha256:
            raise RuntimeError("AVAC setrun backend changed during setup")
        if sha256(solver) != controls["solver_sha256"]:
            raise RuntimeError("AVAC solver executable changed between setup and launch")
        run_solver(
            "avac", work, cores=args.cores, executable_override=solver,
        )
        if sha256(solver) != controls["solver_sha256"]:
            raise RuntimeError("AVAC solver executable changed during validation")
        if sha256(setrun_backend) != controls["source_setrun_sha256"]:
            raise RuntimeError("AVAC setrun backend changed during validation")

    times, x, depth, velocity, summary = extract(work, controls)
    front = np.asarray(summary.pop("_front"))
    rear = np.asarray(summary.pop("_rear"))
    rear_exact = np.asarray(summary.pop("_rear_exact"))
    mass = np.asarray(summary.pop("_mass"))
    results = case_root / "results"
    results.mkdir(exist_ok=True)
    np.savez_compressed(results / "centerline_fields.npz", time_s=times, x_m=x, depth_m=depth, velocity_m_s=velocity)
    np.savetxt(
        results / "boundary_metrics.csv",
        np.column_stack((times, front, rear, rear_exact, np.max(np.abs(velocity), axis=1), mass)),
        delimiter=",",
        header=("time_s,front_x_m,rear_x_m,rear_exact_state_x_m,"
                "max_speed_m_s,mass_m2_per_m"),
        comments="",
    )
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    plot(times, x, depth, velocity, summary | {"_front": front, "_rear": rear, "_mass": mass}, figures)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
