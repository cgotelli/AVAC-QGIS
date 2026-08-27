#!/usr/bin/env python3
"""Reproduce the Chapter 8 Coulomb sloping-bed notebook with AVAC.

The source tutorial calculation is one-dimensional.  This driver uses the
AVAC source and executable in a narrow, uniformly initialized strip with wall
boundaries in the transverse direction.  The centerline is used for the
comparison without invoking WAVE.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import brentq

from avac4qgis_validation.kerswell import position_riemann, time_riemann


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AVAC_SOURCE = ROOT / "avac-main" / "src" / "AVAC"
CLAW_SOURCE = ROOT / "avac-main" / "clawpack-v5.14.0"
SOLVER = AVAC_SOURCE / "xgeoclaw"

G = 9.81
H0 = 1.0
MU = 0.2
SLOPE = -np.deg2rad(5.0)
XLOWER, XUPPER = -10.0, 20.0
# Retain the last established AVAC validation setup.  This is deliberately a
# single transverse computational cell: AVAC remains a 2-D solver, while the
# uniform strip supplies the centerline benchmark.
T_FINAL, NOUT = 6.0, 60
NY = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_data_value(path: Path, label: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"=: {label}"
    for index, line in enumerate(lines):
        if marker in line:
            lines[index] = f"{value:<20} {line[line.index('=:') :]}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise KeyError(f"Could not find {label!r} in {path}")


def read_data_value(path: Path, label: str) -> float:
    """Read one numeric value from a Clawpack ``=: label`` data line."""
    marker = f"=: {label}"
    for line in path.read_text(encoding="utf-8").splitlines():
        if marker in line:
            return float(line.split("=:", 1)[0].strip())
    raise KeyError(f"Could not find {label!r} in {path}")


def write_arc_ascii(path: Path, xmin: float, ymin: float, dx: float, values: np.ndarray) -> None:
    """Write a north-up Arc ASCII grid."""
    values = np.asarray(values, dtype=float)
    nrows, ncols = values.shape
    header = [
        f"ncols {ncols}",
        f"nrows {nrows}",
        f"xllcorner {xmin:.15g}",
        f"yllcorner {ymin:.15g}",
        f"cellsize {dx:.15g}",
        "NODATA_value -9999",
    ]
    body = [" ".join(f"{value:.15g}" for value in row) for row in values]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def write_inputs(case: Path, dx: float) -> tuple[np.ndarray, np.ndarray]:
    topo = case / "Topo"
    work = case / "AVAC"
    topo.mkdir(parents=True)
    work.mkdir()

    ylower, yupper = 0.0, NY * dx
    nx = round((XUPPER - XLOWER) / dx)
    ny = round((yupper - ylower) / dx)
    # Include a one-cell halo in the input rasters, matching GeoClaw's
    # topography/qinit interpolation convention.
    x = XLOWER + (np.arange(nx + 2) - 0.5) * dx
    y = ylower + (np.arange(ny + 2) - 0.5) * dx
    X, _Y = np.meshgrid(x, y)
    bed = np.tan(SLOPE) * X
    write_arc_ascii(topo / "topography.asc", XLOWER - dx, ylower - dx, dx, bed[::-1])
    write_arc_ascii(topo / "mask.asc", XLOWER - dx, ylower - dx, dx, np.zeros_like(bed)[::-1])

    # AVAC/GeoClaw qinit values are depth, not free-surface elevation.
    with (work / "init.xyz").open("w", encoding="utf-8") as stream:
        for j in range(len(y) - 1, -1, -1):
            for i in range(len(x)):
                depth = H0 if XLOWER <= x[i] <= 0.0 else 0.0
                stream.write(f"{x[i]:.15g} {y[j]:.15g} {depth:.15g}\n")
    return x, y


def avac_configuration(dx: float, amr_levels: int) -> dict[str, object]:
    ylower, yupper = 0.0, NY * dx
    nx = round((XUPPER - XLOWER) / dx)
    return {
        "animation": {"animation_directory": "validation", "label_step": 1,
                      "making_html": False, "n_out": NOUT, "variable": "depth"},
        "computation": {
            "boundary": "extrap", "boundary_west": "wall", "boundary_east": "extrap",
            "boundary_south": "wall", "boundary_north": "wall", "cell_size": dx,
            # Match the explicit controls in Chapter 8's supplied setrun.py.
            "cfl_max": 0.5, "cfl_target": 0.25, "dry_limit": 1.0e-12,
            "force_stop": False, "initial_mass": False, "limiter": "superbee",
            "mass_frac_stop": 0.0, "mass_threshold_velocity": 0.0,
            "max_iter": 2_000_000, "nb_simul": NOUT, "output_directory": "_output",
            "refinement": amr_levels, "t_max": T_FINAL, "topo_dir": "", "track_mass": False,
            "xlower": XLOWER, "xupper": XUPPER, "ylower": ylower, "yupper": yupper,
            "dx": dx, "dy": dx,
        },
        "dem_extent": {
            "cell_size": dx, "nbx": nx, "nby": NY, "nodata_value": -9999.0,
            "xmin": XLOWER, "xmax": XUPPER, "ymin": ylower, "ymax": yupper,
        },
        "file_names": {
            "initiation_file": "init.xyz", "topo_source": "synthetic_validation",
            "topofile": "topography.asc", "type_dem": 3, "type_init": 1,
        },
        "gauges": {"gauge_recording": False, "gauges": []},
        "output": {"Language": "English", "delta_t": T_FINAL / NOUT,
                   "output_directory": "_output", "output_format": "binary", "verbosity": 0},
        "refinement": {"delta_t": None, "fine_dict": None, "finer_dem": None,
                       "topo_refinement": False},
        "release": {"correction_elevation": False, "correction_slope": False,
                    "d0": H0, "gradient_hypso": 0.0, "nu": 0.0,
                    "period_return": 0, "theta_cr": 0.0, "z_ref": 0.0,
                    "theta": 0.0, "free_surface": 0.0, "xb": 0.0},
        "rheology": {"C": 0.0, "beta": 0.0, "model": "Coulomb", "mu": MU,
                     "rho": 1000.0, "u_cr": 0.0, "xi": 1.0e12, "z_breaks": []},
    }


def activate_clawpack() -> None:
    for name in tuple(sys.modules):
        if name == "clawpack" or name.startswith("clawpack."):
            del sys.modules[name]
    sys.meta_path[:] = [
        finder for finder in sys.meta_path
        if finder.__class__.__module__ != "_clawpack_editable_loader"
    ]
    source = str(CLAW_SOURCE)
    if source not in sys.path:
        sys.path.insert(0, source)


def prepare(case: Path, dx: float, replace: bool, max1d: int | None,
            amr_levels: int) -> Path:
    if case.exists():
        if not replace:
            raise FileExistsError(f"{case} exists; use --replace to regenerate this exact case")
        shutil.rmtree(case)
    case.mkdir(parents=True)
    _x, _y = write_inputs(case, dx)
    work = case / "AVAC"
    (work / "AVAC_configuration.yaml").write_text(
        json.dumps(avac_configuration(dx, amr_levels), indent=2) + "\n", encoding="utf-8"
    )

    activate_clawpack()
    source = (AVAC_SOURCE / "setrun.py").read_text(encoding="utf-8")
    previous = Path.cwd()
    try:
        os.chdir(work)
        namespace = {"__name__": "validation_backend", "__file__": str(work / "setrun.py")}
        exec(compile(source, str(AVAC_SOURCE / "setrun.py"), "exec"), namespace)
        namespace["setrun"]().write()
    finally:
        os.chdir(previous)

    # The primary level-1 validation
    # suppresses regridding; explicit AMR sensitivity cases retain AVAC's
    # normal speed-based level flagging.
    replace_data_value(work / "geoclaw.data", "manning_coefficient", "0.0")
    # Chapter 8 overrides GeoClaw's default explicitly; this very small value
    # is part of the reference problem and must not be inferred from defaults.
    replace_data_value(work / "geoclaw.data", "dry_tolerance", "1.e-12")
    replace_data_value(work / "claw.data", "cfl_desired", "0.25")
    replace_data_value(work / "claw.data", "cfl_max", "0.5")
    replace_data_value(work / "claw.data", "limiter", "2 2 2")
    replace_data_value(work / "claw.data", "dt_initial", f"{0.2 * dx / np.sqrt(G):.15g}")
    replace_data_value(work / "claw.data", "verbosity", "0")
    # The primary validation is uniform.  Sensitivity controls may retain
    # AVAC's normal speed-based flagging to test dynamic AMR explicitly.
    replace_data_value(
        work / "amr.data", "flag2refine", "F" if amr_levels == 1 else "T"
    )
    longitudinal_cells = round((XUPPER - XLOWER) / dx)
    patch_maximum = longitudinal_cells if max1d is None else max1d
    if not 2 <= patch_maximum <= longitudinal_cells:
        raise ValueError(f"max1d must lie between 2 and {longitudinal_cells}")
    replace_data_value(work / "amr.data", "max1d", str(patch_maximum))

    controls = {
        "solver": str(SOLVER), "solver_sha256": sha256(SOLVER),
        "source_setrun": str(AVAC_SOURCE / "setrun.py"),
        "clawpack_source": str(CLAW_SOURCE), "dx_m": dx, "dy_m": dx, "ny": NY,
        "xlower_m": XLOWER, "xupper_m": XUPPER, "slope_degrees": float(np.rad2deg(SLOPE)),
        "mu": MU, "gravity_m_s2": G, "initial_depth_m": H0,
        "t_final_s": T_FINAL, "outputs": NOUT, "cfl_desired": 0.25, "cfl_max": 0.5,
        "dry_tolerance_m": 1.0e-12,
        "limiter": "Superbee", "amr_levels": amr_levels,
        "max1d": patch_maximum,
    }
    (case / "controls.json").write_text(json.dumps(controls, indent=2) + "\n", encoding="utf-8")
    return work


def run(work: Path, cores: int) -> None:
    if not SOLVER.is_file():
        raise FileNotFoundError(f"Build the current AVAC source first: {SOLVER}")
    environment = os.environ.copy()
    environment["OMP_NUM_THREADS"] = str(cores)
    result = subprocess.run([str(SOLVER)], cwd=work, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work / "solver.log").write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0 or "SOLUTION ERROR" in result.stdout or "Error ***" in result.stdout:
        tail = "\n".join(result.stdout.splitlines()[-40:])
        raise RuntimeError(f"AVAC failed:\n{tail}")


def read_frames(work: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    activate_clawpack()
    from clawpack.geoclaw import fgout_tools

    grid = fgout_tools.FGoutGrid(1, outdir=str(work), output_format="binary32")
    with contextlib.redirect_stdout(io.StringIO()):
        grid.read_fgout_grids_data()
    files = sorted(work.glob("fgout0001.t*"))
    times: list[float] = []
    h_rows: list[np.ndarray] = []
    u_rows: list[np.ndarray] = []
    x = None
    bed = None
    for frame_number, _file in enumerate(files, start=1):
        if grid.ny == 1:
            # Clawpack's generic 2-D binary reader rejects ny=1 because the
            # fgout header records dy=0 for the single transverse point.  The
            # binary payload itself is valid and is simply (meqn,mx,1) in
            # Fortran order, so read that one-cell-wide strip directly.
            suffix = str(frame_number).zfill(4)
            header_values = []
            for line in (work / f"fgout0001.q{suffix}").read_text().splitlines():
                if line.strip():
                    header_values.append(line.split()[0])
            if len(header_values) < 8:
                raise RuntimeError(f"Incomplete fgout header for frame {frame_number}")
            mx, my = int(header_values[2]), int(header_values[3])
            xlow, dx = float(header_values[4]), float(header_values[6])
            if my != 1 or mx != grid.nx:
                raise RuntimeError(
                    f"Unexpected single-row fgout shape ({mx}, {my}) in frame {frame_number}"
                )
            time_tokens = (work / f"fgout0001.t{suffix}").read_text().split()
            frame_time = float(time_tokens[0])
            meqn = int(time_tokens[2])
            file_format = time_tokens[-2].lower()
            dtype = np.float32 if file_format == "binary32" else np.float64
            values = np.fromfile(work / f"fgout0001.b{suffix}", dtype=dtype)
            expected = meqn * mx * my
            if values.size != expected:
                raise RuntimeError(
                    f"Frame {frame_number} has {values.size} values; expected {expected}"
                )
            q = values.reshape((meqn, mx, my), order="F")[:, :, 0]
            if meqn < 4:
                raise RuntimeError("The validation fgout must contain h, hu, hv, and bed")
            if x is None:
                x = xlow + (np.arange(mx, dtype=float) + 0.5) * dx
                bed = np.asarray(q[3], dtype=float)
            h = np.asarray(q[0], dtype=float)
            hu = np.asarray(q[1], dtype=float)
            times.append(frame_time)
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                frame = grid.read_frame(frame_number)
            middle = frame.h.shape[1] // 2
            if x is None:
                x = np.asarray(frame.X[:, middle], dtype=float)
                bed = np.asarray(frame.B[:, middle], dtype=float)
            h = np.asarray(frame.h[:, middle], dtype=float)
            hu = np.asarray(frame.hu[:, middle], dtype=float)
            times.append(float(frame.t))
        u = np.divide(hu, h, out=np.zeros_like(h), where=h > 1.0e-12)
        h_rows.append(h)
        u_rows.append(u)
    if x is None or bed is None:
        raise RuntimeError("No AVAC fixed-grid output frames were written")
    return np.asarray(times), x, bed, np.asarray(h_rows), np.asarray(u_rows)


def scales() -> tuple[float, float, float]:
    mu_effective = MU - np.tan(abs(SLOPE))
    gravity_effective = G * np.cos(SLOPE)
    x0 = H0 / mu_effective
    t0 = np.sqrt(H0 / gravity_effective) / mu_effective
    return mu_effective, x0, t0


def theory_front(tau: np.ndarray) -> np.ndarray:
    return np.where(tau < 2.0, 2.0 * tau - 0.5 * tau**2, 2.0)


def theory_rear(tau: np.ndarray) -> np.ndarray:
    b = 0.5 * tau + 1.0
    moving = -(-3.64928 + 5.47993*b - 2.06989*b**2 + 0.319976*b**3
               - 0.103745*b**4 + 0.0230073*b**5)
    return np.where(tau < 1.529654, moving, -0.721)


def kerswell_profile(tau: float, step: float = 0.01) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the Kerswell analytical depth/velocity profile at ``tau``.

    This is the calculation used in cells 37--41 of the original Chapter 8
    notebook.  It is kept in the validation driver rather than the solver:
    the analytical solution is a comparison target, never an AVAC input.
    """
    s_values = np.arange(-1.0 + 1.0e-5, 1.0 - 1.0e-5 + step, step)
    valid_s: list[float] = []
    r_values: list[float] = []
    for s in s_values:
        try:
            lower, upper = 1.0 + 1.0e-9, 1.7657
            f_lower = time_riemann(float(s), lower) - tau
            f_upper = time_riemann(float(s), upper) - tau
            if not (np.isfinite(f_lower) and np.isfinite(f_upper)) or f_lower * f_upper >= 0.0:
                continue
            r = brentq(lambda value: time_riemann(float(s), value) - tau,
                       lower, upper, xtol=1.0e-10)
        except (ArithmeticError, ValueError):
            continue
        valid_s.append(float(s))
        r_values.append(float(r))
    if not valid_s:
        return np.empty(0), np.empty(0), np.empty(0)
    s = np.asarray(valid_s)
    r = np.asarray(r_values)
    x = np.asarray([position_riemann(float(ss), float(rr)) for ss, rr in zip(s, r)])
    h = (r + s) ** 2 / 4.0
    u = r - s - tau
    return x, h, u


def extract(case: Path) -> tuple[dict[str, float], Path]:
    work = case / "AVAC"
    times, x, bed, depth, velocity = read_frames(work)
    dx = float(np.median(np.diff(x)))
    dry_tolerance = read_data_value(work / "geoclaw.data", "dry_tolerance")
    speed_limit = read_data_value(work / "geoclaw.data", "speed_limit")
    numerical_energy_speed = np.sqrt(dry_tolerance) * speed_limit
    front = np.full(times.shape, np.nan)
    front_raw = np.full(times.shape, np.nan)
    rear = np.full(times.shape, np.nan)
    envelope = -np.inf
    raw_envelope = -np.inf
    resolved_speed = np.zeros(times.shape)
    for index, (h, u) in enumerate(zip(depth, velocity)):
        energy_speed = np.sqrt(np.maximum(h, 0.0)) * np.abs(u)
        resolved = energy_speed > numerical_energy_speed
        moving = x[(u > 1.0e-5) & resolved]
        moving_raw = x[u > 1.0e-5]
        if moving.size:
            envelope = max(envelope, float(np.max(moving)))
        if moving_raw.size:
            raw_envelope = max(raw_envelope, float(np.max(moving_raw)))
        front[index] = envelope if np.isfinite(envelope) else np.nan
        front_raw[index] = raw_envelope if np.isfinite(raw_envelope) else np.nan
        if np.any(resolved):
            resolved_speed[index] = float(np.max(np.abs(u[resolved])))
        undisturbed = x[np.abs(h - H0) <= 1.0e-8]
        rear[index] = float(np.max(undisturbed)) if undisturbed.size else np.nan
    mu_effective, x0, t0 = scales()
    tau = times / t0
    mass = np.sum(depth, axis=1) * dx
    final_speed_raw = float(np.max(np.abs(velocity[-1])))
    summary = {
        "effective_coulomb_coefficient": mu_effective,
        "length_scale_m": x0,
        "time_scale_s": t0,
        "front_rmse_m": float(np.sqrt(np.nanmean((front - x0 * theory_front(tau))**2))),
        "rear_rmse_m": float(np.sqrt(np.nanmean((rear - x0 * theory_rear(tau))**2))),
        "front_final_m": float(front[-1]), "front_theory_final_m": float(2.0 * x0),
        "front_raw_final_m": float(front_raw[-1]),
        "rear_final_m": float(rear[-1]), "rear_theory_final_m": float(-0.721 * x0),
        "maximum_speed_final_m_s": float(resolved_speed[-1]),
        "maximum_speed_final_raw_m_s": final_speed_raw,
        "front_resolution_dry_tolerance_m": dry_tolerance,
        "front_resolution_speed_limit_m_s": speed_limit,
        "front_resolution_energy_density_proxy_m3_s2": (
            0.5 * dry_tolerance * speed_limit**2
        ),
        "mass_initial_m2_per_m": float(mass[0]), "mass_range_m2_per_m": float(np.ptp(mass)),
    }
    results = case / "results"
    results.mkdir(exist_ok=True)
    np.savez_compressed(results / "centerline_fields.npz", time_s=times, x_m=x, bed_m=bed,
                        depth_m=depth, velocity_m_s=velocity)
    np.savetxt(results / "front_back_metrics.csv",
               np.column_stack((times, front, front_raw, rear,
                                resolved_speed, np.max(np.abs(velocity), axis=1), mass)),
               delimiter=",",
               header=("time_s,front_envelope_x_m,front_raw_envelope_x_m,"
                       "rear_h1_x_m,max_resolved_speed_m_s,max_raw_speed_m_s,"
                       "mass_m2_per_m"),
               comments="")
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary, results


def trace_characteristic(rhs, x0: float, times: np.ndarray) -> np.ndarray:
    """Fixed-step RK4 trace through the saved finite-volume field."""
    output = np.empty_like(times)
    output[0] = x0
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        t = times[index - 1]
        value = output[index - 1]
        k1 = rhs(value, t)
        k2 = rhs(value + 0.5 * dt * k1, t + 0.5 * dt)
        k3 = rhs(value + 0.5 * dt * k2, t + 0.5 * dt)
        k4 = rhs(value + dt * k3, t + dt)
        output[index] = value + dt * (k1 + 2*k2 + 2*k3 + k4) / 6.0
    return output


def plot(case: Path) -> None:
    results = case / "results"
    with np.load(results / "centerline_fields.npz") as data:
        times, x, bed = data["time_s"], data["x_m"], data["bed_m"]
        depth, velocity = data["depth_m"], data["velocity_m_s"]
    metrics = np.genfromtxt(results / "front_back_metrics.csv", delimiter=",", names=True)
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    figures = case / "figures"
    figures.mkdir(exist_ok=True)
    _mu_effective, x0, t0 = scales()
    g_effective = G * np.cos(SLOPE)
    u0 = np.sqrt(g_effective * H0)

    fig, axis = plt.subplots(figsize=(10, 4.5))
    axis.plot(x, bed, color="saddlebrown", lw=2)
    axis.set(xlabel=r"$x$ (m)", ylabel=r"$z$ (m)", title="Uniform 5° sloping bed")
    axis.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(figures / "topography.png", dpi=220); plt.close(fig)

    frame_index = min(20, len(times) - 1)
    fig, axis = plt.subplots(figsize=(10, 5))
    axis.plot(x, depth[frame_index], color="#0072B2", lw=1.4,
              label=rf"AVAC, $t={times[frame_index]:.2f}$ s")
    axis.set(xlabel=r"$x$ (m)", ylabel=r"$h(x,t)$ (m)")
    axis.legend(frameon=False); axis.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(figures / "depth_frame_20.png", dpi=220); plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 5))
    axis.plot(x, velocity[frame_index], color="#D55E00", lw=1.4,
              label=rf"AVAC, $t={times[frame_index]:.2f}$ s")
    axis.set(xlabel=r"$x$ (m)", ylabel=r"$u(x,t)$ (m s$^{-1}$)")
    axis.legend(frameon=False); axis.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(figures / "velocity_frame_20.png", dpi=220); plt.close(fig)

    tau = times / t0
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))
    axes[0].plot(times, metrics["rear_h1_x_m"], "+", color="#0072B2", label="AVAC")
    axes[0].plot(times, x0 * theory_rear(tau), color="black", label="theory")
    axes[0].set(xlabel=r"$t$ (s)", ylabel=r"$x_b$ (m)", title="Rear boundary")
    axes[1].plot(times, metrics["front_envelope_x_m"], "+", color="#0072B2", label="AVAC")
    axes[1].plot(times, x0 * theory_front(tau), color="black", label="theory")
    axes[1].set(xlabel=r"$t$ (s)", ylabel=r"$x_f$ (m)", title="Front boundary")
    for axis in axes:
        axis.grid(alpha=0.3); axis.legend(frameon=False)
    fig.tight_layout(); fig.savefig(figures / "boundary_positions_avac_vs_theory.png", dpi=240); plt.close(fig)

    if "front_raw_envelope_x_m" in metrics.dtype.names:
        fig, axis = plt.subplots(figsize=(8.5, 4.8))
        axis.plot(times, x0 * theory_front(tau), "k-", lw=1.7,
                  label="Kerswell theory")
        axis.plot(times, metrics["front_envelope_x_m"], "+", color="#0072B2",
                  ms=5.0, label="AVAC resolved front")
        axis.plot(times, metrics["front_raw_envelope_x_m"], "x", color="#D55E00",
                  ms=4.0, label=r"AVAC raw $u>10^{-5}$ support")
        axis.set(xlabel=r"$t$ (s)", ylabel=r"$x_f$ (m)", title="Resolved and raw front diagnostics")
        axis.grid(alpha=0.3); axis.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(figures / "front_support_diagnostic_avac.png", dpi=240)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))
    axes[0].plot(tau, metrics["rear_h1_x_m"] / x0, "+", color="#0072B2", label="AVAC")
    axes[0].plot(tau, theory_rear(tau), color="black", label="theory")
    axes[0].set(xlabel=r"$t/T_0$", ylabel=r"$x_b/X_0$", title="Rear boundary")
    axes[1].plot(tau, metrics["front_envelope_x_m"] / x0, "+", color="#0072B2", label="AVAC")
    axes[1].plot(tau, theory_front(tau), color="black", label="theory")
    axes[1].set(xlabel=r"$t/T_0$", ylabel=r"$x_f/X_0$", title="Front boundary")
    for axis in axes:
        axis.grid(alpha=0.3); axis.legend(frameon=False)
    fig.tight_layout(); fig.savefig(figures / "boundary_positions_dimensionless_avac_vs_theory.png", dpi=240); plt.close(fig)

    # Characteristics are diagnostic curves traced through the AVAC field,
    # following the construction in the original notebook.
    h_interpolator = RegularGridInterpolator((times, x), depth, bounds_error=False, fill_value=0.0)
    u_interpolator = RegularGridInterpolator((times, x), velocity, bounds_error=False, fill_value=0.0)
    def h_at(position: float, time: float) -> float:
        return max(float(h_interpolator([[time, position]])[0]), 0.0)
    def u_at(position: float, time: float) -> float:
        return float(u_interpolator([[time, position]])[0])
    characteristic_time = np.linspace(0.0, min(10.0, times[-1]), 1001)
    fig, axis = plt.subplots(figsize=(12, 5))
    for i, start in enumerate(np.linspace(-5.0, 0.0, 5)):
        curve = trace_characteristic(lambda xx, tt: u_at(xx, tt) + np.sqrt(g_effective*h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve, characteristic_time, color="0.5", lw=1.1,
                  label=r"$r$-characteristics" if i == 0 else None)
    for i, svalue in enumerate(np.linspace(-1.0, 1.0, 8)):
        curve = trace_characteristic(lambda xx, tt, s=svalue: np.sqrt(g_effective*h_at(xx, tt)) - 2*s*u0 - _mu_effective*g_effective*tt, 0.0, characteristic_time)
        axis.plot(curve, characteristic_time, color="#0072B2", lw=1.0,
                  label=r"$s$-characteristics in fan" if i == 0 else None)
    for i, start in enumerate(np.linspace(-5.0, -0.5, 3)):
        curve = trace_characteristic(lambda xx, tt: u_at(xx, tt) - np.sqrt(g_effective*h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve, characteristic_time, color="#00A6A6", lw=1.0,
                  label=r"$s$-characteristics" if i == 0 else None)
    axis.plot(x0*theory_front(characteristic_time/t0), characteristic_time, color="#D55E00", lw=1.8, label=r"$x_f$ theory")
    axis.plot(x0*theory_rear(characteristic_time/t0), characteristic_time, color="#E69F00", lw=1.8, label=r"$x_b$ theory")
    axis.scatter(metrics["rear_h1_x_m"], times, marker="+", s=16, color="black", label=r"$x_b$ AVAC")
    axis.scatter(metrics["front_envelope_x_m"], times, marker="o", s=8, color="black", label=r"$x_f$ AVAC")
    axis.set(xlabel=r"$x$ (m)", ylabel=r"$t$ (s)", xlim=(-6.0, 25.0), ylim=(0.0, 10.0))
    axis.grid(alpha=0.3); axis.legend(ncol=3, fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(figures / "characteristics_physical_units.png", dpi=240); plt.close(fig)

    fig, axis = plt.subplots(figsize=(10.5, 5.2))
    for i, start in enumerate(np.linspace(-5.0, 0.0, 5)):
        curve = trace_characteristic(lambda xx, tt: u_at(xx, tt) + np.sqrt(g_effective*h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve/x0, characteristic_time/t0, color="0.5", lw=1.1,
                  label=r"$r$-characteristics" if i == 0 else None)
    for i, svalue in enumerate(np.linspace(-1.0, 1.0, 8)):
        curve = trace_characteristic(lambda xx, tt, s=svalue: np.sqrt(g_effective*h_at(xx, tt)) - 2*s*u0 - _mu_effective*g_effective*tt, 0.0, characteristic_time)
        axis.plot(curve/x0, characteristic_time/t0, color="#0072B2", lw=1.0,
                  label=r"$s$-characteristics in fan" if i == 0 else None)
    for i, start in enumerate(np.linspace(-5.0, -0.5, 3)):
        curve = trace_characteristic(lambda xx, tt: u_at(xx, tt) - np.sqrt(g_effective*h_at(xx, tt)), start, characteristic_time)
        axis.plot(curve/x0, characteristic_time/t0, color="#00A6A6", lw=1.0,
                  label=r"$s$-characteristics" if i == 0 else None)
    axis.plot(theory_front(characteristic_time/t0), characteristic_time/t0, color="#D55E00", lw=1.8, label=r"$x_f$ theory")
    axis.plot(theory_rear(characteristic_time/t0), characteristic_time/t0, color="#E69F00", lw=1.8, label=r"$x_b$ theory")
    axis.scatter(metrics["rear_h1_x_m"]/x0, times/t0, marker="+", s=16, color="black", label=r"$x_b$ AVAC")
    axis.scatter(metrics["front_envelope_x_m"]/x0, times/t0, marker="o", s=8, color="black", label=r"$x_f$ AVAC")
    axis.set(xlabel=r"$x/X_0$", ylabel=r"$t/T_0$", xlim=(-1.0, 2.5), ylim=(0.0, 3.6))
    axis.grid(alpha=0.3); axis.legend(ncol=3, fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(figures / "characteristics_dimensionless.png", dpi=240); plt.close(fig)

    # The final pair of panels reproduces the Kerswell analytical comparison
    # in the tutorial.  Profiles at physical times 1--6 s are retained even
    # after the theoretical front reaches its arrested position.
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for physical_time in range(1, 7):
        output_index = int(np.argmin(np.abs(times - physical_time)))
        profile_tau = float(physical_time / t0)
        x_theory, h_theory, u_theory = kerswell_profile(profile_tau)
        label = rf"AVAC $t={physical_time}$ s"
        axes[0].plot(x / x0, depth[output_index] / H0, lw=0.85, label=label)
        axes[1].plot(x / x0, velocity[output_index] / u0, lw=0.85, label=label)
        if x_theory.size:
            keep_h = (h_theory <= 1.0) & (x_theory <= theory_front(np.asarray([profile_tau]))[0])
            keep_u = (u_theory > 0.0) & (x_theory <= theory_front(np.asarray([profile_tau]))[0])
            axes[0].plot(x_theory[keep_h], h_theory[keep_h], "k--", alpha=0.65, lw=0.8)
            axes[1].plot(x_theory[keep_u], u_theory[keep_u], "k--", alpha=0.65, lw=0.8)
    x_front = np.linspace(0.0, 2.0, 200)
    axes[1].plot(x_front, np.sqrt(4.0 - 2.0*x_front), "k:", lw=1.2,
                 label=r"Kerswell front $u_f$")
    axes[0].set(ylabel=r"$h/H_0$", ylim=(-0.03, 1.08), title="Depth: AVAC (solid) and Kerswell theory (dashed)")
    axes[1].set(xlabel=r"$x/X_0$", ylabel=r"$u/U_0$", title="Velocity: AVAC (solid) and Kerswell theory (dashed)")
    for axis in axes:
        axis.set(xlim=(-1.2, 2.3)); axis.grid(alpha=0.3)
    axes[0].legend(ncol=2, fontsize=8, frameon=False)
    axes[1].legend(fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(figures / "flow-depth_dimensionless.png", dpi=240); plt.close(fig)

    (figures / "caption.txt").write_text(
        "Coulomb sloping-bed AVAC validation. "
        f"Front RMSE={summary['front_rmse_m']:.6g} m; rear RMSE={summary['rear_rmse_m']:.6g} m.\n",
        encoding="utf-8",
    )


def main() -> None:
    global T_FINAL, NOUT, NY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dx", type=float, default=0.005, help="uniform AVAC x/y cell size in m")
    parser.add_argument("--case-name", default="AVAC_current", help="subdirectory below this validation case")
    parser.add_argument("--cores", type=int, default=8)
    parser.add_argument(
        "--ny", type=int, default=NY,
        help="number of uniform transverse cells in the quasi-1D strip",
    )
    parser.add_argument("--t-final", type=float, default=T_FINAL)
    parser.add_argument("--nout", type=int, default=NOUT)
    parser.add_argument(
        "--amr-levels", type=int, default=2,
        help="maximum AMR levels in the established AVAC validation setup",
    )
    parser.add_argument(
        "--max1d", type=int, default=250,
        help="maximum base-patch dimension of the established AVAC setup",
    )
    parser.add_argument("--replace", action="store_true", help="replace only the named generated case")
    args = parser.parse_args()
    if (args.dx <= 0.0 or args.cores < 1 or args.ny < 1
            or args.amr_levels < 1
            or args.t_final <= 0.0 or args.nout < 1):
        raise ValueError(
            "dx, cores, ny, amr-levels, t-final, and nout must be positive"
        )
    longitudinal_cells = (XUPPER - XLOWER) / args.dx
    if not np.isclose(longitudinal_cells, round(longitudinal_cells)):
        raise ValueError("dx must divide the 30 m longitudinal domain exactly")
    T_FINAL, NOUT, NY = float(args.t_final), int(args.nout), int(args.ny)
    case = HERE / args.case_name
    work = prepare(
        case, args.dx, args.replace, args.max1d, args.amr_levels
    )
    run(work, args.cores)
    summary, _results = extract(case)
    plot(case)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
