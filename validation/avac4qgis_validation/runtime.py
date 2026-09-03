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
AVAC_GHOST_CELLS = 2
VALIDATION_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = VALIDATION_ROOT.parent
CLAWPACK_SOURCE = WORKSPACE / "avac-main" / "clawpack-v5.14.0"
SOURCE_ROOTS = {
    "avac": WORKSPACE / "avac-main" / "src" / "AVAC",
    "wave": WORKSPACE / "avac-main" / "src" / "WAVE",
}
BUILD_STAMP_ROOT = VALIDATION_ROOT / ".solver-build-stamps"
_BUILD_INPUT_SUFFIXES = frozenset({".c", ".f", ".f90", ".f95", ".h", ".inc"})


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


def _is_build_input(path: Path) -> bool:
    """Whether a file can affect the native source build."""
    name = path.name.lower()
    return (
        path.suffix.lower() in _BUILD_INPUT_SUFFIXES
        or name.startswith("makefile")
        or name == "config.mk"
    )


def solver_fingerprint(kind: str) -> str:
    """Return a content hash of every source input used by a solver build.

    ``make -B .exe`` recompiles the local AVAC/WAVE sources and the vendored
    GeoClaw dependency tree.  Timestamp tests alone are insufficient here:
    a
    notebook can retain an executable built before an edit, and a restored
    checkout can preserve file timestamps.  Hashing the small set of native
    source and make inputs makes the executable provenance explicit.
    """
    if kind not in SOURCE_ROOTS:
        raise ValueError(f"Unknown runtime kind: {kind}")

    inputs: list[tuple[str, Path]] = []
    for label, root in (("solver", SOURCE_ROOTS[kind]), ("clawpack", CLAWPACK_SOURCE)):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and _is_build_input(path):
                relative = path.relative_to(root).as_posix()
                inputs.append((f"{label}/{relative}", path))

    digest = hashlib.sha256()
    for relative, path in sorted(inputs):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _build_stamp_path(kind: str) -> Path:
    return BUILD_STAMP_ROOT / f"{kind}.json"


def _write_build_stamp(kind: str, executable: Path, compiler: str) -> None:
    """Atomically record the source and executable identities after a build."""
    stamp = _build_stamp_path(kind)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "kind": kind,
        "solver_fingerprint": solver_fingerprint(kind),
        "executable_sha256": _sha256(executable),
        "compiler": compiler,
        "platform": sys.platform,
    }
    temporary = stamp.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(stamp)


def _has_current_build(kind: str) -> bool:
    """Return whether the executable exactly matches the current build inputs."""
    source = SOURCE_ROOTS[kind]
    executable = _solver_executable(source)
    stamp = _build_stamp_path(kind)
    if not executable.is_file() or not stamp.is_file():
        return False
    try:
        payload = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("format") != 1 or payload.get("kind") != kind:
        return False
    return (
        payload.get("solver_fingerprint") == solver_fingerprint(kind)
        and payload.get("executable_sha256") == _sha256(executable)
    )


def build_solver(kind: str, cores: int | None = None) -> Path:
    """Build one source solver and record its exact native-source identity.

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
        # Clawpack's ``new`` recipe recursively expands every included
        # makefile name and is unreliable with some GNU Make versions.  A
        # forced executable target provides the intended clean-checkout
        # behavior while also rebuilding shared GeoClaw objects when AVAC and
        # WAVE are compiled successively with different preprocessor flags.
        subprocess.run([make, "-B", ".exe"], cwd=source, env=environment, check=True)
    executable = _solver_executable(source)
    if not executable.is_file():
        raise RuntimeError(f"The {kind.upper()} build completed without creating {executable}")
    _write_build_stamp(kind, executable, compiler)
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
    if not _has_current_build(kind):
        return build_solver(kind)
    return candidate


def solver_executable(kind: str) -> Path:
    """Return the current solver executable, building it on first use.

    Unlike a hard-coded ``xgeoclaw`` path, this accepts Windows' required
    ``xgeoclaw.exe`` suffix while preserving the Unix filename on macOS and
    Linux.
    """
    return _solver_executable(runtime(kind))


def prepare_source_execution(
    kind: str,
    work_directory: str | Path,
    *,
    setrun_override: str | Path | None = None,
) -> Path:
    """Generate Clawpack data files from the current repository sources.

    Validation notebooks exercise the solver being developed in this checkout,
    so they must not depend on an optional, previously packaged plugin runtime.
    This is the source-tree counterpart of the plugin's bundled-runtime setup:
    it activates the repository's vendored Clawpack, runs the current ``setrun``
    backend, and stages the generated ``*.data`` files in ``_output``.
    """
    if kind not in SOURCE_ROOTS:
        raise ValueError(f"Unknown runtime kind: {kind}")
    source = runtime(kind)
    work = Path(work_directory).expanduser().resolve()
    backend = (
        Path(setrun_override).expanduser().resolve()
        if setrun_override is not None
        else source / "setrun.py"
    )
    if not backend.is_file():
        raise RuntimeError(f"{kind.upper()} setrun backend is missing: {backend}")
    has_qinit = any((work / name).is_file() for name in ("init.avacbin", "init.xyz"))
    if kind == "avac" and (
        not (work / "AVAC_configuration.yaml").is_file()
        or not (work.parent / "Topo" / "topography.asc").is_file()
        or not has_qinit
    ):
        raise RuntimeError("Prepared AVAC inputs are incomplete; prepare the run again before execution.")

    output = work / "_output"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    _activate_packaged_clawpack(CLAWPACK_SOURCE)
    previous = Path.cwd()
    previous_argv = sys.argv
    try:
        os.chdir(work)
        namespace = {"__name__": "__main__", "__file__": str(work / "setrun.py")}
        sys.argv = [str(work / "setrun.py")]
        from avac_qgis.core.clawpack_logging import suppress_pyclaw_file_logging

        with suppress_pyclaw_file_logging():
            exec(compile(backend.read_bytes(), str(work / "setrun.py"), "exec"), namespace)  # noqa: S102
    finally:
        sys.argv = previous_argv
        os.chdir(previous)
    data_files = sorted(work.glob("*.data"))
    if not data_files:
        raise RuntimeError(f"Current {kind.upper()} setrun generated no .data files.")
    for data_file in data_files:
        shutil.copy2(data_file, output / data_file.name)
    return output


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


def write_topography(
    case: Path,
    xlower: float,
    xupper: float,
    ylower: float,
    yupper: float,
    dx: float,
    bed,
    *,
    ghost_cells: int = 2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Write the WAVE/GeoClaw topography and dry-mask grids.

    ``bed`` is evaluated at grid-cell centers.  ``ghost_cells`` halo cells
    are added on every side so boundary auxiliary cells remain inside a
    registered topography grid.  Both AVAC and WAVE use GeoClaw's standard
    two-cell halo.
    """
    nx = round((xupper - xlower) / dx)
    ny = round((yupper - ylower) / dx)
    if not (nx >= 2 and ny >= 2):
        raise ValueError("A quasi-1D validation needs at least two cells in each direction.")
    if ghost_cells < 1:
        raise ValueError("ghost_cells must be positive")
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
    """Expose this checkout and prioritize its vendored Clawpack package.

    Validation notebooks install only ``avac4qgis_validation``.  Their driver
    subprocesses run from case directories, so the repository root is not
    otherwise guaranteed to be importable when a current ``setrun.py`` imports
    the plugin's ``avac_qgis`` helpers.
    """
    for name in tuple(sys.modules):
        if name == "clawpack" or name.startswith("clawpack."):
            del sys.modules[name]
    sys.meta_path[:] = [
        finder for finder in sys.meta_path
        if finder.__class__.__module__ != "_clawpack_editable_loader"
    ]
    if str(WORKSPACE) not in sys.path:
        sys.path.insert(0, str(WORKSPACE))
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


def _replace_commented_value(path: Path, comment: str, value: str) -> None:
    """Replace one value on a generated Clawpack line identified by its comment."""
    lines = path.read_text().splitlines()
    marker = f"# {comment}"
    for index, line in enumerate(lines):
        if marker in line:
            lines[index] = f"{value:<28}{marker}"
            path.write_text("\n".join(lines) + "\n")
            return
    raise KeyError(f"Could not find comment {comment!r} in {path}")


def configure_front_amr(
    work: Path,
    *,
    base_dx: float,
    xlower: float,
    xupper: float,
    ylower: float,
    yupper: float,
    levels: int,
    ratio: int = 2,
    transverse_ratio: int = 1,
    speed_tolerance: float = 0.02,
    output_ny: int = 1,
    max1d: int | None = None,
    forced_regions: list[tuple[int, int, float, float, float, float, float, float]] | None = None,
) -> dict[str, object]:
    """Configure dynamic quasi-1D AMR and finest-spacing centreline output.

    With ``forced_regions``, narrow benchmark-defined corridors allocate fine
    cells around the two analytical boundaries and the general speed flagger
    is disabled; otherwise the standard flagger follows resolvable motion.
    Fixed-grid output is sampled at the finest possible longitudinal spacing
    so front positions are not quantized by the base grid.  A single
    transverse output row is sufficient because these verification problems
    are exactly uniform in that direction; :func:`fgout_centerline` handles
    that valid GeoClaw form.
    """
    if (base_dx <= 0.0 or yupper <= ylower or levels < 2 or ratio < 2
            or transverse_ratio < 1 or speed_tolerance <= 0.0):
        raise ValueError(
            "Front AMR requires base_dx>0, yupper>ylower, levels>=2, "
            "ratio>=2, transverse_ratio>=1, and speed_tolerance>0"
        )
    ratios = [int(ratio)] * (int(levels) - 1)
    ratio_text = " ".join(str(value) for value in ratios)
    transverse_ratio_text = " ".join(str(int(transverse_ratio)) for _ in ratios)
    amr_data = work / "amr.data"
    _replace_data_value(amr_data, "amr_levels_max", str(int(levels)))
    _replace_data_value(amr_data, "refinement_ratios_x", ratio_text)
    _replace_data_value(amr_data, "refinement_ratios_y", transverse_ratio_text)
    _replace_data_value(amr_data, "refinement_ratios_t", ratio_text)
    _replace_data_value(amr_data, "flag_richardson", "F")
    _replace_data_value(amr_data, "flag2refine", "F" if forced_regions else "T")
    if max1d is not None:
        if max1d < 6:
            raise ValueError("max1d must leave room for interior and ghost cells")
        _replace_data_value(amr_data, "max1d", str(int(max1d)))
    _replace_data_value(
        work / "refinement.data",
        "speed_tolerance",
        " ".join(f"{float(speed_tolerance):.12g}" for _ in ratios),
    )
    if forced_regions:
        if any(
            region[0] < 1 or region[1] < region[0] or region[1] > levels
            for region in forced_regions
        ):
            raise ValueError("Forced-region levels must lie within the configured AMR levels")
        lines = [
            "########################################################",
            "### Validation-controlled moving front corridors      ###",
            "########################################################",
            "",
            f"{len(forced_regions)}                    =: num_regions",
        ]
        lines.extend(" ".join(f"{value:.16g}" for value in region) for region in forced_regions)
        (work / "regions.data").write_text("\n".join(lines) + "\n")

    refinement_factor = int(np.prod(ratios))
    finest_dx = float(base_dx) / refinement_factor
    nx_float = (float(xupper) - float(xlower)) / finest_dx
    if not np.isclose(nx_float, round(nx_float)):
        raise ValueError("The finest AMR spacing must divide the longitudinal domain exactly")
    if output_ny < 1:
        raise ValueError("output_ny must be positive")
    _replace_commented_value(
        work / "fgout_grids.data", "nx,ny", f"{round(nx_float)}  {int(output_ny)}"
    )
    if output_ny == 1:
        # A one-row fixed grid must have a single transverse coordinate.
        # Retaining distinct lower/upper y endpoints makes GeoClaw's binary
        # interpolation grid degenerate and fills the verification output
        # with NaNs.  Sample the physical strip centreline instead.
        ymid = 0.5 * (float(ylower) + float(yupper))
        _replace_commented_value(
            work / "fgout_grids.data", "x1, y1", f"{float(xlower):.16g}  {ymid:.16g}"
        )
        _replace_commented_value(
            work / "fgout_grids.data", "x2, y2", f"{float(xupper):.16g}  {ymid:.16g}"
        )
    # These verification drivers never consume fgmax.  Leaving the generated
    # full-domain grid enabled would update peak fields at every fine time
    # step and dominate the cost of a front-local AMR calculation.
    _replace_data_value(work / "fgmax_grids.data", "num_fgmax_grids", "0")
    return {
        "amr_levels": int(levels),
        "refinement_ratios": ratios,
        "transverse_refinement_ratios": [int(transverse_ratio)] * len(ratios),
        "base_dx_m": float(base_dx),
        "finest_dx_m": finest_dx,
        "speed_tolerance_m_s": float(speed_tolerance),
        "amr_flagging": "prescribed moving front corridors" if forced_regions else "resolved speed",
        "forced_region_count": len(forced_regions or []),
        "fgout_nx": round(nx_float),
        "fgout_ny": int(output_ny),
        "fgmax_enabled": False,
        "max1d": int(max1d) if max1d is not None else None,
    }


def moving_front_corridors(
    front,
    rear,
    *,
    t_final: float,
    interval: float,
    margin: float,
    xlower: float,
    xupper: float,
    ylower: float,
    yupper: float,
    level: int,
) -> list[tuple[int, int, float, float, float, float, float, float]]:
    """Return narrow, overlapping AMR regions around two known benchmark fronts.

    The analytical locations are used only to allocate resolution; they are
    never passed to the AVAC state or numerical flux.  Each interval samples
    both endpoints and its midpoint, then adds a fixed spatial margin.  A
    half-interval overlap prevents a front from crossing a corridor boundary
    between regridding events.
    """
    if (t_final <= 0.0 or interval <= 0.0 or margin <= 0.0 or level < 2
            or xupper <= xlower or yupper <= ylower):
        raise ValueError("Invalid moving-front corridor controls")
    edges = np.linspace(0.0, t_final, int(np.ceil(t_final / interval)) + 1)
    regions: list[tuple[int, int, float, float, float, float, float, float]] = []
    for left, right in zip(edges[:-1], edges[1:]):
        sample_times = np.asarray([left, 0.5 * (left + right), right])
        time_low = max(0.0, left - 0.5 * interval)
        time_high = min(t_final, right + 0.5 * interval)
        for location in (front, rear):
            positions = np.asarray(location(sample_times), dtype=float)
            region_left = max(xlower, float(np.nanmin(positions)) - margin)
            region_right = min(xupper, float(np.nanmax(positions)) + margin)
            if region_right > region_left:
                regions.append(
                    (level, level, time_low, time_high, region_left, region_right, ylower, yupper)
                )
    return regions


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
    dry_tolerance: float = 1.0e-12,
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
            "cfl_target": 0.25, "damping": 1.0, "dry_limit": float(dry_tolerance),
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
    _replace_data_value(work/"geoclaw.data","dry_tolerance",f"{float(dry_tolerance):.12g}")
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


def prepare_avac_coulomb_case(
    case: Path, *, xlower: float, xupper: float, ylower: float, yupper: float,
    dx: float, t_final: float, nout: int, mu: float, depth,
    refinement: int = 1, bed=None,
    boundary_west: str = "wall", boundary_east: str = "extrap",
    boundary_south: str = "wall", boundary_north: str = "wall",
    model: str = "Coulomb", cohesion: float = 0.0,
    rho: float = 1000.0, xi: float = 1.0e12,
) -> Path:
    """Prepare a Coulomb-family case with the packaged AVAC runtime.

    The historical analytical cases use the defaults: a flat, quasi-1D strip
    with a wall upstream and extrapolation downstream.  Supplying ``bed`` and
    boundary names permits compact two-dimensional property tests without
    introducing a second solver configuration or a validation-only equation.
    """
    if refinement < 1:
        raise ValueError("refinement must be at least 1")
    if model not in {"Coulomb", "Voellmy", "cohesive_Voellmy"}:
        raise ValueError(f"Unsupported AVAC granular model: {model!r}")
    if cohesion < 0.0 or rho <= 0.0 or xi <= 0.0:
        raise ValueError("cohesion must be nonnegative and rho/xi must be positive")
    boundary_codes = {
        "user": 0, "extrap": 1, "periodic": 2, "wall": 3,
    }
    boundaries = (
        boundary_west, boundary_east, boundary_south, boundary_north,
    )
    if any(name not in boundary_codes for name in boundaries):
        raise ValueError(f"Unsupported AVAC boundary in {boundaries!r}")
    case = case.resolve()
    clean_case(case)
    bed = (lambda X, Y: np.zeros_like(X)) if bed is None else bed
    x, y, _ = write_topography(
        case, xlower, xupper, ylower, yupper, dx, bed,
        ghost_cells=AVAC_GHOST_CELLS,
    )
    write_depth_xyz(case / "AVAC" / "init.xyz", x, y, depth)
    config = {
        "animation": {"animation_directory": "validation", "label_step": 1, "making_html": False, "n_out": nout, "variable": "depth"},
        "computation": {"boundary": "extrap", "boundary_west": boundary_west,
                        "boundary_east": boundary_east,
                        "boundary_south": boundary_south,
                        "boundary_north": boundary_north, "cell_size": dx,
                        "cfl_max": 1.0, "cfl_target": 0.8, "dry_limit": 1.0e-8, "force_stop": False,
                        "initial_mass": False, "limiter": "mc", "mass_frac_stop": 0.0,
                        "mass_threshold_velocity": 0.0, "max_iter": 2000000, "nb_simul": nout,
                        "output_directory": "_output", "refinement": int(refinement), "t_max": t_final,
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
        "rheology": {"C": cohesion, "beta": 0.0, "model": model, "mu": mu, "rho": rho,
                     "u_cr": 0.0, "xi": xi, "z_breaks": []},
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
                            limiter: str = "mc", max1d: int | None = None,
                            refinement: int = 1,
                            qinit_dx: float | None = None) -> Path:
    """Prepare a frictionless quasi-1D water case with the packaged AVAC solver.

    The AVAC executable includes GeoClaw's shallow-water solver.  Disabling
    its granular/Manning friction paths yields the same water equations used
    by the GeoClaw tutorial, while still exercising the installed AVAC binary,
    its ``setrun`` configuration path, topography reader, qinit reader, and
    fgout writer.
    """
    if refinement < 1:
        raise ValueError("refinement must be at least 1")
    qinit_dx = dx if qinit_dx is None else float(qinit_dx)
    if qinit_dx <= 0.0:
        raise ValueError("qinit_dx must be positive")
    qinit_cells = (xupper - xlower) / qinit_dx
    if not np.isclose(qinit_cells, round(qinit_cells)):
        raise ValueError("qinit_dx must divide the longitudinal domain exactly")
    case = case.resolve()
    clean_case(case)
    x, y, _ = write_topography(
        case, xlower, xupper, ylower, yupper, dx, bed,
        ghost_cells=AVAC_GHOST_CELLS,
    )
    # Sample qinit independently at the finest longitudinal AMR spacing.  A
    # deliberately coarse far field must not degrade an analytical initial
    # profile before refinement is created.  The quasi-1D state is uniform in
    # y, so retaining the base-grid transverse sampling avoids a large file.
    qinit_ghost_cells = AVAC_GHOST_CELLS
    qinit_x = xlower + (
        np.arange(round(qinit_cells) + 2 * qinit_ghost_cells)
        - qinit_ghost_cells + 0.5
    ) * qinit_dx
    write_depth_xyz(case / "AVAC" / "init.xyz", qinit_x, y, depth)
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
            "nb_simul": nout, "output_directory": "_output", "refinement": int(refinement),
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
        # Select AVAC's explicit water branch, not a zero-friction Coulomb
        # surrogate.  Besides disabling granular stress, this retains
        # GeoClaw's free-surface-preserving AMR interpolation on sloping beds.
        "rheology": {
            "C": 0.0, "beta": 0.0, "model": "Water", "mu": 0.0,
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
    _replace_data_value(work / "amr.data", "flag2refine", "T" if refinement > 1 else "F")
    # AVAC's standard setup starts at 0.01 s, which is appropriate for the
    # plugin's metre-scale grids but violates CFL on the tutorial's 0.005 m
    # grid before adaptive stepping can react.  Start below CFL 0.2; the
    # normal variable-step controller subsequently selects its own stable dt.
    initial_dt = 0.2 * dx / np.sqrt(GRAVITY)
    _replace_data_value(work / "claw.data", "dt_initial", f"{initial_dt:.12g}")
    # AMRClaw tests ``interior_cells + 2 * nghost > max1d`` when constructing
    # base patches.  ``None`` requests one long patch; an explicit value may
    # be used to create several same-level patches for OpenMP execution.
    nghost = AVAC_GHOST_CELLS
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
        case, xlower, xupper, ylower, yupper, dx, bed,
        ghost_cells=AVAC_GHOST_CELLS,
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
    nghost = AVAC_GHOST_CELLS
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
        or "Too many dt reductions" in combined_output
        or "Stopping calculation" in combined_output
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


def fgout_centerline(
    kind: str, work: Path, frame: int
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``t, x, h, hu, hv, B`` for one fixed-grid centreline frame.

    Clawpack's general two-dimensional reader rejects a one-row fixed grid
    because its legacy header stores a zero transverse increment.  The binary
    payload is nevertheless well defined, so that special case is read
    directly.  Multi-row outputs continue through the packaged reader.
    """
    frame = int(frame)
    source_root = CLAWPACK_SOURCE
    with working_directory(work):
        _activate_packaged_clawpack(source_root)
        from clawpack.geoclaw import fgout_tools

        grid = fgout_tools.FGoutGrid(1, outdir=str(work), output_format="binary32")
        grid.read_fgout_grids_data()
        if grid.ny != 1:
            fg = grid.read_frame(frame)
            middle = fg.h.shape[1] // 2
            return (
                float(fg.t),
                np.asarray(fg.X[:, middle], dtype=float),
                np.asarray(fg.h[:, middle], dtype=float),
                np.asarray(fg.hu[:, middle], dtype=float),
                np.asarray(fg.hv[:, middle], dtype=float),
                np.asarray(fg.B[:, middle], dtype=float),
            )

        suffix = str(frame).zfill(4)
        header_values = [
            line.split()[0]
            for line in (work / f"fgout0001.q{suffix}").read_text().splitlines()
            if line.strip()
        ]
        if len(header_values) < 8:
            raise RuntimeError(f"Incomplete fgout header for frame {frame}")
        mx, my = int(header_values[2]), int(header_values[3])
        xlow, dx = float(header_values[4]), float(header_values[6])
        if my != 1 or mx != grid.nx:
            raise RuntimeError(f"Unexpected one-row fgout shape ({mx}, {my}) in frame {frame}")
        time_tokens = (work / f"fgout0001.t{suffix}").read_text().split()
        time_s = float(time_tokens[0])
        meqn = int(time_tokens[2])
        file_format = time_tokens[-2].lower()
        dtype = np.float32 if file_format == "binary32" else np.float64
        values = np.fromfile(work / f"fgout0001.b{suffix}", dtype=dtype)
        expected = meqn * mx * my
        if values.size != expected:
            raise RuntimeError(
                f"Frame {frame} has {values.size} values; expected {expected}"
            )
        q = values.reshape((meqn, mx, my), order="F")[:, :, 0]
        if meqn < 4:
            raise RuntimeError("The validation fgout must contain h, hu, hv, and bed")
        x = xlow + (np.arange(mx, dtype=float) + 0.5) * dx
        return time_s, x, q[0].astype(float), q[1].astype(float), q[2].astype(float), q[3].astype(float)


def maximum_written_amr_level(work: Path, *, final_only: bool = False) -> int:
    """Return the maximum AMR level recorded in native frame headers."""
    frames = sorted(
        path for path in work.glob("fort.q*")
        if path.name.replace("fort.q", "").isdigit()
    )
    if not frames:
        raise RuntimeError(f"No native solver frames in {work}")
    if final_only:
        frames = frames[-1:]
    levels = [
        int(match.group(1))
        for path in frames
        for match in re.finditer(
            r"^\s*(\d+)\s+AMR_level\s*$", path.read_text(), flags=re.MULTILINE
        )
    ]
    if not levels:
        raise RuntimeError(f"No AMR patch levels recorded in {work}")
    return max(levels)


def centerline(frame, field: str = "h") -> tuple[np.ndarray, np.ndarray]:
    """Return the x centerline of a uniform fgout field."""
    values = np.asarray(getattr(frame, field))
    middle = values.shape[1] // 2
    return np.asarray(frame.X[:, middle]), values[:, middle]


def write_csv(path: Path, header: str, columns: list[np.ndarray]) -> None:
    np.savetxt(path, np.column_stack(columns), delimiter=",", header=header, comments="")
