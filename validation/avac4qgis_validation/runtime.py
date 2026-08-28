"""Shared AVAC4QGIS validation runtime and case-preparation utilities.

The validation cases deliberately execute the current AVAC and WAVE source
executables compiled in this workspace. They do not invoke PyClaw's Python
solver or any tutorial executable. This makes every recorded validation
result directly traceable to the rebuilt source binary being evaluated for
the next plugin runtime; a historical packaged archive is never substituted
silently.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import contextmanager

import numpy as np


GRAVITY = 9.81
VALIDATION_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = VALIDATION_ROOT.parent
CLAWPACK_SOURCE = WORKSPACE / "avac-main" / "clawpack-v5.14.0"
SOURCE_ROOTS = {
    "avac": WORKSPACE / "avac-main" / "src" / "AVAC",
    "wave": WORKSPACE / "avac-main" / "src" / "WAVE",
}


def _solver_executable(source: Path) -> Path:
    """Return the platform-native solver executable below ``source``."""
    return source / ("xgeoclaw.exe" if os.name == "nt" else "xgeoclaw")


def _make_command() -> str | None:
    """Return a GNU Make-compatible command, including Windows' ``gmake``."""
    return next(
        (command for command in ("make", "gmake", "mingw32-make")
         if shutil.which(command) is not None),
        None,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_solver(kind: str, cores: int | None = None) -> Path:
    """Build one source solver when a clean checkout has no executable.

    The repository deliberately excludes compiled binaries.  Validation
    notebooks therefore call this routine through :func:`runtime` on first
    use.  A Fortran compiler and ``make`` are system prerequisites because
    they cannot be installed reliably into a running notebook kernel.
    """
    if kind not in SOURCE_ROOTS:
        raise ValueError(f"Unknown runtime kind: {kind}")
    source = SOURCE_ROOTS[kind]
    make = _make_command()
    compiler = os.environ.get("FC") or shutil.which("gfortran")
    if make is None or compiler is None:
        raise RuntimeError(
            f"Cannot build {kind.upper()}: install GNU Make (or gmake) and gfortran, "
            "then rerun this notebook."
        )
    environment = os.environ.copy()
    environment["CLAW"] = str(CLAWPACK_SOURCE)
    environment["FC"] = compiler
    environment.setdefault("OMP_NUM_THREADS", str(cores or max(1, os.cpu_count() or 1)))
    if os.name == "nt":
        builder = WORKSPACE / "tools" / "build_windows_solvers.py"
        if not builder.is_file():
            raise RuntimeError(
                f"Cannot build {kind.upper()} on Windows: expected helper {builder} is missing."
            )
        subprocess.run(
            [
                sys.executable, str(builder), "--target", kind.upper(),
                "--make", make, "--fc", compiler, "--no-strip",
            ],
            cwd=WORKSPACE,
            env=environment,
            check=True,
        )
    else:
        subprocess.run([make, "new"], cwd=source, env=environment, check=True)
    executable = _solver_executable(source)
    if not executable.is_file():
        raise RuntimeError(f"The {kind.upper()} build completed without creating {executable}")
    return source


def runtime(kind: str) -> Path:
    """Return a current, locally compiled solver source directory.

    The solver SHA-256 is stored with each validation run.  It is intentionally
    not compared to a historical hard-coded hash: a source correction requires
    a new validation, rather than silently reusing an obsolete package.
    """
    if kind not in SOURCE_ROOTS:
        raise ValueError(f"Unknown runtime kind: {kind}")
    candidate = SOURCE_ROOTS[kind]
    executable = _solver_executable(candidate)
    if not executable.is_file():
        return build_solver(kind)
    return candidate


def solver_executable(kind: str) -> Path:
    """Return the current solver executable, building it on first use.

    Unlike a hard-coded ``xgeoclaw`` path, this accepts Windows' required
    ``xgeoclaw.exe`` suffix while preserving the Unix filename on macOS and
    Linux.
    """
    return _solver_executable(runtime(kind))


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def clean_case(case: Path) -> None:
    """Recreate only the generated working folders of a validation case."""
    for name in ("AVAC", "Wave", "Topo", "CL", "results"):
        target = case / name
        if target.exists():
            shutil.rmtree(target)
    for name in ("AVAC", "Wave", "Topo", "CL", "results"):
        (case / name).mkdir(parents=True, exist_ok=True)


def _arc_ascii(path: Path, xmin: float, ymin: float, dx: float, values: np.ndarray) -> None:
    """Write a north-up Arc ASCII grid, including one ghost cell on every edge."""
    values = np.asarray(values, dtype=float)
    nrows, ncols = values.shape
    lines = [
        f"ncols {ncols}",
        f"nrows {nrows}",
        f"xllcorner {xmin:.12g}",
        f"yllcorner {ymin:.12g}",
        f"cellsize {dx:.12g}",
        "NODATA_value -9999",
    ]
    lines.extend(" ".join(f"{value:.12g}" for value in row) for row in values)
    path.write_text("\n".join(lines) + "\n")


def write_topography(case: Path, xlower: float, xupper: float, ylower: float, yupper: float,
                     dx: float, bed) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Write the WAVE/GeoClaw topography and dry-mask grids.

    ``bed`` is evaluated at grid-cell centers.  Two halo cells are added on
    every side to cover GeoClaw's two ghost-cell layers.  A one-cell halo is
    insufficient for periodic boundaries and can leave boundary auxiliary
    cells outside every registered topography grid.
    """
    nx = round((xupper - xlower) / dx)
    ny = round((yupper - ylower) / dx)
    if not (nx >= 2 and ny >= 2):
        raise ValueError("A quasi-1D validation needs at least two cells in each direction.")
    ghost_cells = 2
    x = xlower + (np.arange(nx + 2 * ghost_cells) - ghost_cells + 0.5) * dx
    y = ylower + (np.arange(ny + 2 * ghost_cells) - ghost_cells + 0.5) * dx
    X, Y = np.meshgrid(x, y)
    elevations = np.asarray(bed(X, Y), dtype=float)
    if elevations.shape != X.shape:
        elevations = np.broadcast_to(elevations, X.shape).copy()
    # Arc ASCII is written north-to-south; internal arrays are south-to-north.
    _arc_ascii(
        case / "Topo" / "topography.asc",
        xlower - ghost_cells * dx,
        ylower - ghost_cells * dx,
        dx,
        elevations[::-1],
    )
    _arc_ascii(
        case / "Topo" / "mask.asc",
        xlower - ghost_cells * dx,
        ylower - ghost_cells * dx,
        dx,
        np.zeros_like(elevations),
    )
    return x, y, elevations


def write_depth_xyz(path: Path, x: np.ndarray, y: np.ndarray, depth) -> None:
    """Write a GeoClaw qinit xyz depth grid in NW-to-SE order."""
    X, Y = np.meshgrid(x, y)
    values = np.asarray(depth(X, Y), dtype=float)
    if values.shape != X.shape:
        values = np.broadcast_to(values, X.shape).copy()
    with path.open("w") as stream:
        for j in range(len(y) - 1, -1, -1):
            for i in range(len(x)):
                stream.write(f"{x[i]:.12g} {y[j]:.12g} {values[j, i]:.12g}\n")


def _activate_packaged_clawpack(source_root: Path) -> None:
    """Prioritize the plugin's vendored Clawpack over a broken local editable install."""
    for name in tuple(sys.modules):
        if name == "clawpack" or name.startswith("clawpack."):
            del sys.modules[name]
    sys.meta_path[:] = [
        finder for finder in sys.meta_path
        if finder.__class__.__module__ != "_clawpack_editable_loader"
    ]
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def _minimal_yaml_module(directory: Path) -> None:
    """Use JSON (valid YAML) without adding a PyYAML dependency to the notebooks."""
    (directory / "yaml.py").write_text(
        "import json\n\ndef safe_load(stream):\n    return json.load(stream)\n"
    )


def _replace_data_value(path: Path, label: str, value: str) -> None:
    """Replace a labelled Clawpack data-file value without changing its schema."""
    lines = path.read_text().splitlines()
    marker = f"=: {label}"
    for index, line in enumerate(lines):
        if marker in line:
            suffix = line[line.index("=:"):]
            lines[index] = f"{value:<20} {suffix}"
            path.write_text("\n".join(lines) + "\n")
            return
    raise KeyError(f"Could not find {label!r} in {path}")


def _write_qinit_data(path: Path, depth_file: Path, qinit_type: int = 1) -> None:
    path.write_text(
        "########################################################\n"
        "### DO NOT EDIT THIS FILE: validation-specific qinit ###\n"
        "### Generated from the packaged WAVE data-file schema ####\n"
        "### qinit is the prescribed initial depth field          ###\n"
        "########################################################\n\n"
        f"{qinit_type}                    =: qinit_type\n\n"
        f"'{depth_file}'\n"
        "F                    =: variable_eta_init\n"
        "0                    =: num_force_dry\n"
    )


def _write_internal_inflow(path: Path, entries: list[tuple[float, float, list[tuple[float, float, float]]]],
                           times: list[float]) -> None:
    """Write the plugin's internal-inflow format; entries may be empty (zero source)."""
    with path.open("w") as stream:
        stream.write("1\n")
        stream.write(f"{len(times)} {len(entries)}\n")
        stream.write(" ".join(f"{time:.16g}" for time in times) + "\n")
        for x, y, series in entries:
            if len(series) != len(times):
                raise ValueError("Each internal-inflow time series must match the time vector.")
            stream.write(f"{x:.16g} {y:.16g}\n")
            for h_rate, hu_rate, hv_rate in series:
                stream.write(f"{h_rate:.16g} {hu_rate:.16g} {hv_rate:.16g}\n")


def _run_setrun(kind: str, case: Path, qinit: bool) -> None:
    package = runtime(kind)
    work = case / ("Wave" if kind == "wave" else "AVAC")
    _minimal_yaml_module(work)
    backend = package / "setrun.py"
    source = backend.read_text()
    if kind == "wave" and qinit:
        old = "rundata.qinit_data.qinit_type = 0\n    rundata.qinit_data.qinitfiles = []"
        new = (
            "rundata.qinit_data.qinit_type = 1\n"
            "    rundata.qinit_data.qinitfiles = []\n"
            "    rundata.qinit_data.qinitfiles.append([1, 2, 'initial_depth.xyz'])"
        )
        if old not in source:
            raise RuntimeError("The packaged WAVE setrun qinit block changed unexpectedly.")
        source = source.replace(old, new, 1)
    source_root = CLAWPACK_SOURCE
    with working_directory(work):
        _activate_packaged_clawpack(source_root)
        # ``sys.path[0]`` remains the directory of the calling validation
        # script after chdir.  Add the generated work directory explicitly so
        # the dependency-free local ``yaml.py`` shim is importable.
        work_string = str(work)
        if work_string not in sys.path:
            sys.path.insert(0, work_string)
        # Do not execute the backend as __main__: Jupyter adds kernel arguments
        # to sys.argv, which the legacy setrun footer would mistake for inputs.
        namespace = {"__name__": "validation_backend", "__file__": str(work / "setrun.py")}
        exec(compile(source, str(backend), "exec"), namespace)
        namespace["setrun"]().write()


def prepare_wave_case(case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
                      dx: float, t_final: float, nout: int, bed, depth, momentum: float | None = None,
                      boundary_lower: tuple[int, int] = (3, 3),
                      boundary_upper: tuple[int, int] = (1, 3)) -> Path:
    """Prepare a frictionless, quasi-1D WAVE runtime case.

    If ``momentum`` is set, the plugin's *own* internal-inflow module applies
    a uniform, one-timestep momentum impulse.  It is an initialization device
    for the Baines steady-flow state, then the source is zero for the run.
    """
    case = case.resolve()
    clean_case(case)
    x, y, _ = write_topography(case, xlower, xupper, ylower, yupper, dx, bed)
    write_depth_xyz(case / "Wave" / "initial_depth.xyz", x, y, depth)
    config = {
        "lake": {"topography": "topography.asc", "water_level": -10000.0,
                 "xmin": xlower, "xmax": xupper, "ymin": ylower, "ymax": yupper},
        "topo_files": {"topography": "topography.asc", "mask_raster": "mask.asc", "missing_value": -9999.0},
        "computation": {"boundary": "extrap", "cell_size": dx, "cfl_max": 1.0, "cfl_target": 0.8,
                        "damping": 1.0, "dry_limit": 1.0e-8, "initial_mass": False,
                        "limiter": "mc", "max_iter": 2000000, "mode": "internal_shoreline",
                        "nb_grid": round((xupper - xlower) / dx), "nb_simul": nout,
                        "refinement": 1, "t_0": 0.0, "t_max": t_final},
        "gauges": {"gauge_recording": False},
        "output": {"delta_t": t_final / nout, "output_directory": "_output", "output_format": "binary", "verbosity": 0},
        "rheology": {"Strickler": [1.0e12, 1.0e12], "friction": False,
                     "friction_break_elevation": 0.0, "friction_depth_limit": 1.0e12,
                     "gravity": GRAVITY, "rho": 1000.0, "wave_tolerance_flag": 1.0e12},
    }
    (case / "impulse_configuration.yaml").write_text(json.dumps(config, indent=2) + "\n")
    _write_internal_inflow(case / "CL" / "internal_inflow.data", [], [0.0, t_final])
    _run_setrun("wave", case, qinit=True)
    work = case / "Wave"
    _write_qinit_data(work / "qinit.data", work / "initial_depth.xyz")
    # The legacy WAVE setrun currently serializes a scientific-notation value
    # loaded from its YAML/JSON configuration as a quoted token on some Python/
    # Clawpack combinations (for example ``'1e-08'``).  GeoClaw reads this
    # field as a Fortran real and consequently aborts before the first step.
    # Write the same configured value as an unquoted real; this changes no
    # numerical parameter and makes the validation exercise the intended
    # current WAVE runtime.
    _replace_data_value(work / "geoclaw.data", "dry_tolerance", "1.e-8")
    _replace_data_value(work / "claw.data", "dt_initial", "0.002")
    _replace_data_value(work / "claw.data", "verbosity", "0")
    _replace_data_value(work / "claw.data", "bc_lower", f"{boundary_lower[0]} {boundary_lower[1]}")
    _replace_data_value(work / "claw.data", "bc_upper", f"{boundary_upper[0]} {boundary_upper[1]}")
    if momentum is not None:
        # The solver evaluates this source on its first (0.002 s) step only.
        # Every cell gets du/dt = q / dt, with no mass source.
        dt = 0.002
        xc = xlower + (np.arange(round((xupper - xlower) / dx)) + 0.5) * dx
        yc = ylower + (np.arange(round((yupper - ylower) / dx)) + 0.5) * dx
        entries = [(float(xx), float(yy), [(0.0, momentum / dt, 0.0), (0.0, 0.0, 0.0)])
                   for yy in yc for xx in xc]
        _write_internal_inflow(case / "CL" / "internal_inflow.data", entries, [0.0, dt])
    return work


def prepare_wave_hydraulic_case(
    case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
    dx: float, t_final: float, nout: int, bed, depth=None, state=None,
    manning: float = 0.0,
    boundary_west: str = "extrap", boundary_east: str = "extrap",
    boundary_south: str = "wall", boundary_north: str = "wall",
    hydraulic_boundaries: dict[int, tuple[int, float, float]] | None = None,
    limiter: str = "mc", max1d: int | None = None,
    refinement: int = 1,
    forced_regions: list[tuple[int, int, float, float, float, float, float, float]] | None = None,
) -> Path:
    """Prepare a published water benchmark with the WAVE source package.

    This mirrors :func:`prepare_avac_hydraulic_case`: geometry, initial
    conservative state, boundary data, CFL controls, output schedule, and
    grid decomposition are identical.  WAVE retains standard GeoClaw water
    AMR interpolation; AVAC's granular ``conserve_depth_amr`` mode is not
    enabled.
    """
    if depth is None and state is None:
        raise ValueError("Either depth or a full conservative state is required.")
    if depth is not None and state is not None:
        raise ValueError("Specify depth or state, not both.")
    if refinement < 1:
        raise ValueError("refinement must be at least 1")
    if forced_regions and any(
        region[0] < 1 or region[1] < region[0] or region[1] > refinement
        for region in forced_regions
    ):
        raise ValueError("Forced-region levels must fall within 1..refinement")

    case = case.resolve()
    clean_case(case)
    x, y, _bed_values = write_topography(
        case, xlower, xupper, ylower, yupper, dx, bed
    )
    init_path = case / "Wave" / "initial_state.xyz"
    qinit_type = 1
    if state is None:
        write_depth_xyz(init_path, x, y, depth)
    else:
        write_state_xyz(init_path, x, y, state)
        qinit_type = 5

    boundary_codes = {
        "user": 0, "extrap": 1, "periodic": 2, "wall": 3,
    }
    config = {
        "lake": {
            "topography": "topography.asc", "water_level": -10000.0,
            "xmin": xlower, "xmax": xupper, "ymin": ylower, "ymax": yupper,
        },
        "topo_files": {
            "topography": "topography.asc", "mask_raster": "mask.asc",
            "missing_value": -9999.0,
        },
        "computation": {
            "boundary": "extrap", "cell_size": dx, "cfl_max": 0.5,
            "cfl_target": 0.25, "damping": 1.0, "dry_limit": 1.0e-12,
            "initial_mass": False, "limiter": limiter, "max_iter": 5000000,
            "mode": "internal_shoreline", "nb_grid": round((xupper-xlower)/dx),
            "nb_simul": nout, "refinement": int(refinement),
            "t_0": 0.0, "t_max": t_final,
        },
        "gauges": {"gauge_recording": False},
        "output": {
            "delta_t": t_final/nout, "output_directory": "_output",
            "output_format": "binary", "verbosity": 0,
        },
        "rheology": {
            "Strickler": [1.0/manning if manning>0.0 else 1.0e12]*2,
            "friction": bool(manning>0.0), "friction_break_elevation": 0.0,
            "friction_depth_limit": 1.0e12, "gravity": GRAVITY, "rho": 1000.0,
            "wave_tolerance_flag": 1.0e12,
        },
    }
    (case/"impulse_configuration.yaml").write_text(json.dumps(config,indent=2)+"\n")
    _write_internal_inflow(case/"CL"/"internal_inflow.data",[],[0.0,t_final])
    _run_setrun("wave",case,qinit=True)
    work = case/"Wave"
    _write_qinit_data(work/"qinit.data",init_path,qinit_type=qinit_type)

    definitions = hydraulic_boundaries or {}
    lines = ["# side mode stage discharge"]
    for side in range(1,5):
        mode, stage_value, discharge = definitions.get(side,(0,0.0,0.0))
        lines.append(f"{side} {mode} {stage_value:.16g} {discharge:.16g}")
    (work/"hydraulic_bc.data").write_text("\n".join(lines)+"\n")

    _replace_data_value(
        work/"claw.data", "bc_lower",
        f"{boundary_codes[boundary_west]} {boundary_codes[boundary_south]}",
    )
    _replace_data_value(
        work/"claw.data", "bc_upper",
        f"{boundary_codes[boundary_east]} {boundary_codes[boundary_north]}",
    )
    _replace_data_value(work/"geoclaw.data","friction_forcing","T" if manning>0 else "F")
    if manning>0.0:
        # setrun writes one coefficient per Strickler zone; keep that complete
        # generated vector instead of replacing it with a scalar.
        _replace_data_value(work/"geoclaw.data","friction_depth","1.e12")
    _replace_data_value(work/"geoclaw.data","dry_tolerance","1.e-12")
    _replace_data_value(work/"claw.data","cfl_desired","0.25")
    _replace_data_value(work/"claw.data","cfl_max","0.5")
    _replace_data_value(work/"amr.data","flag2refine","F")
    if forced_regions:
        region_lines = [
            "########################################################",
            "### Validation-controlled forced AMR regions          ###",
            "########################################################",
            "",
            f"{len(forced_regions)}                    =: num_regions",
        ]
        region_lines.extend(
            " ".join(str(value) for value in region)
            for region in forced_regions
        )
        (work/"regions.data").write_text("\n".join(region_lines)+"\n")
    _replace_data_value(work/"claw.data","dt_initial",f"{min(0.01,0.05*dx):.12g}")
    nghost=2
    minimum_max1d=round((yupper-ylower)/dx)+2*nghost
    patch_limit=(round((xupper-xlower)/dx)+2*nghost if max1d is None
                 else max(int(max1d),minimum_max1d))
    _replace_data_value(work/"amr.data","max1d",str(max(60,patch_limit)))
    _replace_data_value(work/"claw.data","verbosity","0")
    return work


def prepare_avac_coulomb_case(case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
                              dx: float, t_final: float, nout: int, mu: float, depth) -> Path:
    """Prepare a quasi-1D Coulomb case with the packaged AVAC runtime."""
    case = case.resolve()
    clean_case(case)
    x, y, _ = write_topography(case, xlower, xupper, ylower, yupper, dx, lambda X, Y: np.zeros_like(X))
    write_depth_xyz(case / "AVAC" / "init.xyz", x, y, depth)
    config = {
        "animation": {"animation_directory": "validation", "label_step": 1, "making_html": False, "n_out": nout, "variable": "depth"},
        "computation": {"boundary": "extrap", "boundary_west": "wall", "boundary_east": "extrap",
                        "boundary_south": "wall", "boundary_north": "wall", "cell_size": dx,
                        "cfl_max": 1.0, "cfl_target": 0.8, "dry_limit": 1.0e-8, "force_stop": False,
                        "initial_mass": False, "limiter": "mc", "mass_frac_stop": 0.0,
                        "mass_threshold_velocity": 0.0, "max_iter": 2000000, "nb_simul": nout,
                        "output_directory": "_output", "refinement": 1, "t_max": t_final,
                        "topo_dir": "", "track_mass": False, "xlower": xlower, "xupper": xupper,
                        "ylower": ylower, "yupper": yupper, "dx": dx, "dy": dx},
        "dem_extent": {"cell_size": dx, "nbx": round((xupper-xlower)/dx), "nby": round((yupper-ylower)/dx),
                       "nodata_value": -9999, "xmax": xupper, "xmin": xlower, "ymax": yupper, "ymin": ylower},
        "file_names": {"initiation_file": "init.xyz", "topo_source": "synthetic_validation",
                       "topofile": "topography.asc", "type_dem": 3, "type_init": 1},
        "gauges": {"gauge_recording": False, "gauges": []},
        "output": {"Language": "English", "delta_t": t_final/nout, "output_directory": "_output",
                   "output_format": "binary", "verbosity": 0},
        "refinement": {"delta_t": None, "fine_dict": None, "finer_dem": None, "topo_refinement": False},
        "release": {"correction_elevation": False, "correction_slope": False, "d0": 1.0,
                    "gradient_hypso": 0.0, "nu": 0.0, "period_return": 0, "theta_cr": 0,
                    "z_ref": 0, "theta": 0.0, "free_surface": 0.0, "xb": 0.0},
        "rheology": {"C": 0.0, "beta": 0.0, "model": "Coulomb", "mu": mu, "rho": 1000.0,
                     "u_cr": 0.0, "xi": 1.0e12, "z_breaks": []},
    }
    (case / "AVAC" / "AVAC_configuration.yaml").write_text(json.dumps(config, indent=2) + "\n")
    _run_setrun("avac", case, qinit=False)
    work = case / "AVAC"
    # Keep AVAC's custom friction source but eliminate the unrelated GeoClaw
    # Manning contribution, yielding the pure Coulomb model of Kerswell.
    _replace_data_value(work / "geoclaw.data", "manning_coefficient", "0.0")
    # Match the Chapter 8 reference calculation's numerical controls so the
    # comparison isolates the equations/source update rather than CFL,
    # limiter, or wet/dry differences.
    _replace_data_value(work / "geoclaw.data", "dry_tolerance", "1.e-12")
    _replace_data_value(work / "claw.data", "cfl_desired", "0.25")
    _replace_data_value(work / "claw.data", "cfl_max", "0.5")
    _replace_data_value(work / "claw.data", "limiter", "2 2 2")
    initial_dt = 0.2 * dx / np.sqrt(GRAVITY)
    _replace_data_value(work / "claw.data", "dt_initial", f"{initial_dt:.12g}")
    _replace_data_value(work / "claw.data", "verbosity", "0")
    return work


def prepare_avac_water_case(case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
                            dx: float, t_final: float, nout: int, bed, depth,
                            boundary_west: str = "wall", boundary_east: str = "extrap",
                            boundary_south: str = "wall", boundary_north: str = "wall",
                            limiter: str = "mc", max1d: int | None = None) -> Path:
    """Prepare a frictionless quasi-1D water case with the packaged AVAC solver.

    The AVAC executable includes GeoClaw's shallow-water solver.  Disabling
    its granular/Manning friction paths yields the same water equations used
    by the GeoClaw tutorial, while still exercising the installed AVAC binary,
    its ``setrun`` configuration path, topography reader, qinit reader, and
    fgout writer.
    """
    case = case.resolve()
    clean_case(case)
    x, y, _ = write_topography(case, xlower, xupper, ylower, yupper, dx, bed)
    write_depth_xyz(case / "AVAC" / "init.xyz", x, y, depth)
    config = {
        "animation": {"animation_directory": "validation", "label_step": 1,
                      "making_html": False, "n_out": nout, "variable": "depth"},
        "computation": {
            "boundary": "extrap", "boundary_west": boundary_west,
            "boundary_east": boundary_east, "boundary_south": boundary_south,
            "boundary_north": boundary_north, "cell_size": dx, "cfl_max": 0.5,
            "cfl_target": 0.25, "dry_limit": 1.0e-12, "force_stop": False,
            "initial_mass": False, "limiter": limiter, "mass_frac_stop": 0.0,
            "mass_threshold_velocity": 0.0, "max_iter": 2000000,
            "nb_simul": nout, "output_directory": "_output", "refinement": 1,
            "t_max": t_final, "topo_dir": "", "track_mass": False,
            "xlower": xlower, "xupper": xupper, "ylower": ylower,
            "yupper": yupper, "dx": dx, "dy": dx,
        },
        "dem_extent": {
            "cell_size": dx, "nbx": round((xupper - xlower) / dx),
            "nby": round((yupper - ylower) / dx), "nodata_value": -9999,
            "xmax": xupper, "xmin": xlower, "ymax": yupper, "ymin": ylower,
        },
        "file_names": {
            "initiation_file": "init.xyz", "topo_source": "synthetic_validation",
            "topofile": "topography.asc", "type_dem": 3, "type_init": 1,
        },
        "gauges": {"gauge_recording": False, "gauges": []},
        "output": {
            "Language": "English", "delta_t": t_final / nout,
            "output_directory": "_output", "output_format": "binary", "verbosity": 0,
        },
        "refinement": {"delta_t": None, "fine_dict": None, "finer_dem": None,
                       "topo_refinement": False},
        "release": {
            "correction_elevation": False, "correction_slope": False, "d0": 1.0,
            "gradient_hypso": 0.0, "nu": 0.0, "period_return": 0, "theta_cr": 0,
            "z_ref": 0, "theta": 0.0, "free_surface": 0.0, "xb": 0.0,
        },
        # Zero-stress water mode: the source hook is used only to clear
        # momentum from cells that have become dry.  Coulomb, Voellmy, and
        # Manning stresses are identically zero.
        "rheology": {
            "C": 0.0, "beta": 0.0, "model": "Coulomb", "mu": 0.0,
            "rho": 1000.0, "u_cr": 0.0, "xi": 1.0e12, "z_breaks": [],
        },
    }
    (case / "AVAC" / "AVAC_configuration.yaml").write_text(json.dumps(config, indent=2) + "\n")
    _run_setrun("avac", case, qinit=False)
    work = case / "AVAC"
    # Match dry-bottom_Sloping-bed's numerical controls: Superbee limiting,
    # a 1e-12 dry tolerance, CFL target/max of 0.25/0.5, and one non-regridded base
    # patch.  The AVAC source hook remains enabled only for dry-cell cleanup;
    # with mu=0, Manning=0, and xi=infinity it applies no physical stress.
    _replace_data_value(work / "geoclaw.data", "friction_forcing", "T")
    _replace_data_value(work / "geoclaw.data", "manning_coefficient", "0.0")
    _replace_data_value(work / "geoclaw.data", "dry_tolerance", "1.e-12")
    _replace_data_value(work / "claw.data", "cfl_desired", "0.25")
    _replace_data_value(work / "claw.data", "cfl_max", "0.5")
    _replace_data_value(work / "amr.data", "flag2refine", "F")
    # AVAC's standard setup starts at 0.01 s, which is appropriate for the
    # plugin's metre-scale grids but violates CFL on the tutorial's 0.005 m
    # grid before adaptive stepping can react.  Start below CFL 0.2; the
    # normal variable-step controller subsequently selects its own stable dt.
    initial_dt = 0.2 * dx / np.sqrt(GRAVITY)
    _replace_data_value(work / "claw.data", "dt_initial", f"{initial_dt:.12g}")
    # AMRClaw tests ``interior_cells + 2 * nghost > max1d`` when constructing
    # base patches.  ``None`` requests one long patch; an explicit value may
    # be used to create several same-level patches for OpenMP execution.
    nghost = 2
    minimum_max1d = round((yupper - ylower) / dx) + 2 * nghost
    if max1d is None:
        patch_limit = round((xupper - xlower) / dx) + 2 * nghost
    else:
        patch_limit = int(max1d)
        if patch_limit < minimum_max1d:
            raise ValueError(
                f"max1d={patch_limit} cannot contain the transverse strip; "
                f"it must be at least {minimum_max1d}."
            )
    _replace_data_value(work / "amr.data", "max1d", str(max(60, patch_limit)))
    _replace_data_value(work / "claw.data", "verbosity", "0")
    return work


def write_state_xyz(path: Path, x: np.ndarray, y: np.ndarray, state) -> None:
    """Write a complete conservative state ``x y h hu hv`` for qinit type 5."""
    X, Y = np.meshgrid(x, y)
    h, hu, hv = (np.asarray(value, dtype=float) for value in state(X, Y))
    target_shape = X.shape
    h = np.broadcast_to(h, target_shape)
    hu = np.broadcast_to(hu, target_shape)
    hv = np.broadcast_to(hv, target_shape)
    with path.open("w") as stream:
        for j in range(len(y) - 1, -1, -1):
            for i in range(len(x)):
                stream.write(
                    f"{x[i]:.12g} {y[j]:.12g} {h[j, i]:.12g} "
                    f"{hu[j, i]:.12g} {hv[j, i]:.12g}\n"
                )


def prepare_avac_hydraulic_case(
    case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
    dx: float, t_final: float, nout: int, bed, depth=None, state=None,
    manning: float = 0.0,
    boundary_west: str = "extrap", boundary_east: str = "extrap",
    boundary_south: str = "wall", boundary_north: str = "wall",
    hydraulic_boundaries: dict[int, tuple[int, float, float]] | None = None,
    limiter: str = "mc", max1d: int | None = None,
) -> Path:
    """Prepare a published hydraulic benchmark with AVAC's water model.

    ``hydraulic_boundaries`` maps side 1=west, 2=east, 3=south,
    4=north to ``(mode, stage, discharge)``.  The modes are documented in
    ``hydraulic_bc_module.f90``.  This executes the same AVAC Riemann solver,
    topography, AMR transfer, and output path used by the plugin.
    """
    if depth is None and state is None:
        raise ValueError("Either depth or a full conservative state is required.")
    if depth is not None and state is not None:
        raise ValueError("Specify depth or state, not both.")

    case = case.resolve()
    clean_case(case)
    x, y, _bed_values = write_topography(
        case, xlower, xupper, ylower, yupper, dx, bed
    )
    init_path = case / "AVAC" / "init.xyz"
    qinit_type = 1
    if state is None:
        write_depth_xyz(init_path, x, y, depth)
    else:
        write_state_xyz(init_path, x, y, state)
        qinit_type = 5

    config = {
        "animation": {"animation_directory": "validation", "label_step": 1,
                      "making_html": False, "n_out": nout, "variable": "depth"},
        "computation": {
            "boundary": "extrap", "boundary_west": boundary_west,
            "boundary_east": boundary_east, "boundary_south": boundary_south,
            "boundary_north": boundary_north, "cell_size": dx, "cfl_max": 0.5,
            "cfl_target": 0.25, "dry_limit": 1.0e-12, "force_stop": False,
            "initial_mass": False, "limiter": limiter, "mass_frac_stop": 0.0,
            "mass_threshold_velocity": 0.0, "max_iter": 5000000,
            "nb_simul": nout, "output_directory": "_output", "refinement": 1,
            "t_max": t_final, "topo_dir": "", "track_mass": False,
            "xlower": xlower, "xupper": xupper, "ylower": ylower,
            "yupper": yupper, "dx": dx, "dy": dx,
        },
        "dem_extent": {
            "cell_size": dx, "nbx": round((xupper-xlower)/dx),
            "nby": round((yupper-ylower)/dx), "nodata_value": -9999,
            "xmax": xupper, "xmin": xlower, "ymax": yupper, "ymin": ylower,
        },
        "file_names": {
            "initiation_file": "init.xyz", "topo_source": "synthetic_validation",
            "topofile": "topography.asc", "type_dem": 3, "type_init": qinit_type,
        },
        "gauges": {"gauge_recording": False, "gauges": []},
        "output": {"Language": "English", "delta_t": t_final/nout,
                   "output_directory": "_output", "output_format": "binary",
                   "verbosity": 0},
        "refinement": {"delta_t": None, "fine_dict": None, "finer_dem": None,
                       "topo_refinement": False},
        "release": {"correction_elevation": False, "correction_slope": False,
                    "d0": 1.0, "gradient_hypso": 0.0, "nu": 0.0,
                    "period_return": 0, "theta_cr": 0, "z_ref": 0,
                    "theta": 0.0, "free_surface": 0.0, "xb": 0.0},
        "rheology": {"C": 0.0, "beta": 0.0, "model": "Water", "mu": 0.0,
                     "rho": 1000.0, "u_cr": 0.0, "xi": 1.0e12,
                     "z_breaks": []},
    }
    (case/"AVAC"/"AVAC_configuration.yaml").write_text(
        json.dumps(config, indent=2)+"\n"
    )
    _run_setrun("avac", case, qinit=False)
    work = case/"AVAC"
    _write_qinit_data(work/"qinit.data", init_path, qinit_type=qinit_type)

    definitions = hydraulic_boundaries or {}
    lines = ["# side mode stage discharge"]
    for side in range(1, 5):
        mode, stage_value, discharge = definitions.get(side, (0, 0.0, 0.0))
        lines.append(f"{side} {mode} {stage_value:.16g} {discharge:.16g}")
    (work/"hydraulic_bc.data").write_text("\n".join(lines)+"\n")

    # Keep the water source hook active even for n=0.  Besides applying the
    # standard semi-implicit Manning term, src2 performs GeoClaw's required
    # dry-cell momentum cleanup.  Disabling the hook for a frictionless
    # dry-bed case lets roundoff momentum survive at the moving shoreline and
    # can eventually produce an undefined dry-cell velocity.
    _replace_data_value(work/"geoclaw.data", "friction_forcing", "T")
    _replace_data_value(work/"geoclaw.data", "manning_coefficient", f"{manning:.16g}")
    _replace_data_value(work/"geoclaw.data", "friction_depth", "1.e12")
    _replace_data_value(work/"geoclaw.data", "dry_tolerance", "1.e-12")
    _replace_data_value(work/"claw.data", "cfl_desired", "0.25")
    _replace_data_value(work/"claw.data", "cfl_max", "0.5")
    _replace_data_value(work/"amr.data", "flag2refine", "F")
    _replace_data_value(work/"claw.data", "dt_initial", f"{min(0.01,0.05*dx):.12g}")
    nghost = 2
    minimum_max1d = round((yupper-ylower)/dx)+2*nghost
    if max1d is None:
        patch_limit = round((xupper-xlower)/dx)+2*nghost
    else:
        patch_limit = max(int(max1d), minimum_max1d)
    _replace_data_value(work/"amr.data", "max1d", str(max(60,patch_limit)))
    _replace_data_value(work/"claw.data", "verbosity", "0")
    return work


def _external_time_command(executable: Path) -> tuple[list[str], str]:
    """Return a non-mutating resource-measurement wrapper for this host."""
    if sys.platform == "darwin":
        return ["/usr/bin/time", "-l", str(executable)], "macos_time_l"
    if Path("/usr/bin/time").is_file():
        return ["/usr/bin/time", "-v", str(executable)], "gnu_time_v"
    return [str(executable)], "wall_clock_only"


def _parse_external_time(stderr: str, flavor: str) -> dict[str, float | None]:
    """Parse `/usr/bin/time` without mixing timing text into solver.log."""
    metrics: dict[str, float | None] = {
        "user_cpu_s": None,
        "system_cpu_s": None,
        "peak_resident_memory_bytes": None,
    }
    if flavor == "macos_time_l":
        match = re.search(
            r"([0-9.]+) real\s+([0-9.]+) user\s+([0-9.]+) sys", stderr
        )
        if match:
            metrics["user_cpu_s"] = float(match.group(2))
            metrics["system_cpu_s"] = float(match.group(3))
        match = re.search(r"^\s*(\d+)\s+maximum resident set size\s*$", stderr, re.M)
        if match:
            metrics["peak_resident_memory_bytes"] = float(match.group(1))
    elif flavor == "gnu_time_v":
        match = re.search(r"User time \(seconds\):\s*([0-9.]+)", stderr)
        if match:
            metrics["user_cpu_s"] = float(match.group(1))
        match = re.search(r"System time \(seconds\):\s*([0-9.]+)", stderr)
        if match:
            metrics["system_cpu_s"] = float(match.group(1))
        match = re.search(
            r"Maximum resident set size \(kbytes\):\s*(\d+)", stderr
        )
        if match:
            metrics["peak_resident_memory_bytes"] = 1024.0 * float(match.group(1))
    return metrics


def run_solver(kind: str, working_directory: Path, cores: int = 1) -> dict[str, object]:
    """Run the exact checked solver binary and save its complete log.

    ``cores`` controls only OpenMP parallelism; it does not change the grid,
    equations, time integrator, or output schedule.  A single core remains the
    default so earlier validation notebooks retain deterministic behavior.
    """
    if cores < 1:
        raise ValueError("cores must be at least 1")
    executable = solver_executable(kind)
    environment = os.environ.copy()
    environment["OMP_NUM_THREADS"] = str(int(cores))
    command, timing_flavor = _external_time_command(executable)
    started_local = datetime.now(ZoneInfo("Europe/Zurich")).isoformat()
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=working_directory,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wall_s = time.perf_counter() - started
    (working_directory / "solver.log").write_text(result.stdout)
    (working_directory / "solver_time.log").write_text(result.stderr)
    resource_metrics = _parse_external_time(result.stderr, timing_flavor)
    metrics: dict[str, object] = {
        "format": 1,
        "solver_kind": kind,
        "executable": str(executable),
        "executable_sha256": _sha256(executable),
        "command": command,
        "timing_flavor": timing_flavor,
        "started_local": started_local,
        "timezone": "Europe/Zurich",
        "openmp_threads": int(cores),
        "wall_s": wall_s,
        **resource_metrics,
        "returncode": result.returncode,
    }
    (working_directory / "solver_execution_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n"
    )
    combined_output = result.stdout + "\n" + result.stderr
    solver_error = (
        "SOLUTION ERROR" in combined_output
        or "Error ***" in combined_output
        or "set_fgout: ERROR" in combined_output
        or "ERROR reading hydraulic" in combined_output
        or "ERROR: hydraulic boundary" in combined_output
        or "ERROR: total-discharge boundary" in combined_output
    )
    if result.returncode != 0 or solver_error:
        tail = "\n".join(combined_output.splitlines()[-30:])
        raise RuntimeError(
            f"{kind} solver failed with exit code {result.returncode}:\n{tail}"
        )
    return metrics


def fgout_frame(kind: str, work: Path, frame: int):
    """Read a uniform fgout frame through the packaged Clawpack reader."""
    # visclaw compares the supplied frame number to a tuple cache key; a NumPy
    # integer makes that comparison vectorized and fails ambiguously.
    frame = int(frame)
    source_root = CLAWPACK_SOURCE
    with working_directory(work):
        _activate_packaged_clawpack(source_root)
        from clawpack.geoclaw import fgout_tools
        grid = fgout_tools.FGoutGrid(1, outdir=str(work), output_format="binary32")
        grid.read_fgout_grids_data()
        return grid.read_frame(frame)


def fgout_times(kind: str, work: Path) -> list[float]:
    """Return fgout frame times without assuming the requested output cadence."""
    frames = sorted(work.glob("fgout0001.t*"))
    return [float(path.read_text().splitlines()[0].split()[0]) for path in frames]


def centerline(frame, field: str = "h") -> tuple[np.ndarray, np.ndarray]:
    """Return the x centerline of a uniform fgout field."""
    values = np.asarray(getattr(frame, field))
    middle = values.shape[1] // 2
    return np.asarray(frame.X[:, middle]), values[:, middle]


def write_csv(path: Path, header: str, columns: list[np.ndarray]) -> None:
    np.savetxt(path, np.column_stack(columns), delimiter=",", header=header, comments="")
