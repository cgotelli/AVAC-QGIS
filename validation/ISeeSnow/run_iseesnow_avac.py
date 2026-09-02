#!/usr/bin/env python3
"""Run the three supplied ISeeSnow cases with the AVAC4QGIS solver.

This is a validation driver, not a plugin feature. It deliberately keeps the
generated AVAC outputs under ``validation/ISeeSnow`` and records every
translation required by the two model conventions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

# The desktop conda installation has a stale editable-Clawpack import hook.
# AVAC must import its runtime-owned Clawpack tree instead.
sys.meta_path = [
    finder for finder in sys.meta_path
    if finder.__class__.__module__ != "_clawpack_editable_loader"
]
for _module_name in tuple(sys.modules):
    if _module_name == "clawpack" or _module_name.startswith("clawpack."):
        del sys.modules[_module_name]

import numpy as np
import shapefile as pyshp
import yaml

try:
    import resource
except ImportError:  # Windows does not provide the POSIX resource module.
    resource = None


VALIDATION_ROOT = Path(__file__).resolve().parent
RESULTS_ROOT = VALIDATION_ROOT
PROJECT_ROOT = VALIDATION_ROOT.parents[1]
from avac4qgis_validation.datasets import ensure_iseesnow  # noqa: E402
from avac4qgis_validation.runtime import (  # noqa: E402
    CLAWPACK_SOURCE,
    build_solver,
    prepare_source_execution,
    runtime as source_runtime,
)

BENCHMARK_ROOT = ensure_iseesnow()
PLUGIN_ROOT = PROJECT_ROOT / "avac_qgis"
sys.path.insert(0, str(PROJECT_ROOT))

from avac_qgis.core.configuration import controlled_values, load_complete_configuration  # noqa: E402
from avac_qgis.core.preprocessing import AvacRaster, write_init_binary  # noqa: E402
from avac_qgis.core.run_project import (  # noqa: E402
    prepare_isolated_runtime_run,
    read_run_metadata,
    update_run_status,
)


CASE_SPECIFICATIONS: dict[str, dict[str, Any]] = {
    "IdealizedTopo": {
        "dem": "DEM_IdealizedTopo.asc", "release": "release1HS.shp",
        "release_name": "release1HS", "simulation_id": "01IdealizedTopo",
        "model": "Voellmy", "mu": 0.4, "xi": 2000.0,
    },
    "RealTopo": {
        "dem": "DEM_RealTopo.asc", "release": "relWog.shp",
        "release_name": "relWog", "simulation_id": "02RealTopo",
        "model": "Voellmy", "mu": 0.2, "xi": 2000.0,
    },
    "CoulombOnly": {
        "dem": "DEM_CoulombOnly.asc", "release": "release1HS.shp",
        "release_name": "release1HS", "simulation_id": "03CoulombOnly",
        "model": "Coulomb", "mu": 0.4, "xi": 1.0e12,
    },
}
MODEL_TYPE = "AVAC4QGIS"
NORMAL_RELEASE_THICKNESS_M = 1.5
CELL_SIZE_M = 5.0
# ISeeSnow specifies the physical parameters but no common termination time.
# A 150 s truncation proved insufficient, so all cases now integrate through a
# 20-minute ceiling.  The native state output is subsequently checked for an
# actual rest condition; it is never selected to match another model.
SIMULATION_END_S = 1200.0
# Full GeoClaw state frames are diagnostics only. fgmax records its peak at
# each solver step; saving state every ten seconds does not subsample pft/pfv.
OUTPUT_INTERVAL_S = 10.0
VELOCITY_FLOW_THRESHOLD_MPS = 0.01
VELOCITY_DEPTH_THRESHOLD_M = 0.05
REST_CONSECUTIVE_OUTPUTS = 3
# A strict pointwise velocity criterion is not useful at a dry front: a tiny
# residual cell can retain an unrepresentative speed long after the avalanche
# deposit is effectively at rest.  "Stopped" therefore means less than 1% of
# the initial release volume is moving faster than the stated threshold for
# three consecutive output times.  Both values remain in the mass history.
REST_MOVING_VOLUME_FRACTION = 0.01
# GeoClaw's historical default was 50 m/s.  It rescales momentum in b4step2,
# changing the solution.  Use a finite value that is safely beyond any
# representable physical avalanche speed instead of relying on that limiter.
DISABLED_SPEED_LIMIT_MPS = 1.0e99
# IdealizedTopo and CoulombOnly are supplied in a Cartesian metric grid without
# an EPSG authority. This valid QGIS local CRS is deliberately non-geographic.
LOCAL_CARTESIAN_CRS_WKT = (
    'LOCAL_CS["ISeeSnow local Cartesian",UNIT["metre",1],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)


def fixed_grid_output_frame_count(simulation_end_s: float, output_interval_s: float) -> int:
    """Return an exact valid ISeeSnow fixed-grid frame count.

    GeoClaw accepts a final time and a number of frames, not an independent
    output interval.  Rounding a nonintegral ratio would silently change the
    requested cadence, so validation runs require an exact whole number of
    intervals and at least two frames for the fixed-grid machinery.
    """
    simulation_end_s = float(simulation_end_s)
    output_interval_s = float(output_interval_s)
    if not np.isfinite(simulation_end_s) or not np.isfinite(output_interval_s) or simulation_end_s <= 0.0 or output_interval_s <= 0.0:
        raise ValueError("Simulation end time and output interval must be positive finite values.")
    ratio = simulation_end_s / output_interval_s
    rounded = round(ratio)
    if not np.isclose(ratio, rounded, rtol=1.0e-10, atol=1.0e-10):
        raise ValueError(
            "ISeeSnow simulation end time must be an exact multiple of the fixed-grid output interval."
        )
    if rounded < 2:
        raise ValueError(
            "ISeeSnow validation needs at least two fixed-grid output frames; "
            "increase --simulation-end or decrease --output-interval."
        )
    return int(rounded)


def plugin_version() -> str:
    for line in (PLUGIN_ROOT / "metadata.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("AVAC4QGIS metadata has no version entry.")


@cache
def current_source_solver() -> Path:
    """Build the current AVAC source once, then return its executable.

    An existing ``xgeoclaw`` may pre-date an edit to the AVAC or GeoClaw
    sources.  ISeeSnow is a release-validation workflow, so it must not use
    that stale binary merely because it happens to exist.  ``build_solver``
    deliberately invokes the forced executable target, rebuilding the source
    tree once for this driver process.  The cache avoids rebuilding separately
    for each case in an ``--case all`` invocation.
    """
    source = build_solver("avac").resolve()
    executable = source / ("xgeoclaw.exe" if os.name == "nt" else "xgeoclaw")
    if not executable.is_file():
        raise RuntimeError(f"AVAC build completed without its solver executable: {executable}")
    return executable


@dataclass(frozen=True)
class EsriGrid:
    path: Path
    ncols: int
    nrows: int
    xllcenter: float
    yllcenter: float
    cellsize: float
    nodata: float
    values_north: np.ndarray

    @property
    def x_centres(self) -> np.ndarray:
        return self.xllcenter + np.arange(self.ncols, dtype=float) * self.cellsize

    @property
    def y_centres(self) -> np.ndarray:
        return self.yllcenter + np.arange(self.nrows, dtype=float) * self.cellsize


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_esri_ascii(path: Path) -> EsriGrid:
    header: dict[str, float] = {}
    with path.open(encoding="utf-8") as stream:
        for _ in range(6):
            key, value = stream.readline().split()[:2]
            header[key.lower()] = float(value)
    values = np.atleast_2d(np.loadtxt(path, skiprows=6, dtype=float))
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    if values.shape != (nrows, ncols):
        raise ValueError(f"{path} has {values.shape}, not its declared {(nrows, ncols)} grid.")
    cellsize = float(header["cellsize"])
    if not np.isclose(cellsize, CELL_SIZE_M):
        raise ValueError(f"ISeeSnow input {path.name} is not on the required 5 m grid.")
    if "xllcenter" in header:
        xllcenter = header["xllcenter"]
    else:
        xllcenter = header["xllcorner"] + cellsize / 2.0
    if "yllcenter" in header:
        yllcenter = header["yllcenter"]
    else:
        yllcenter = header["yllcorner"] + cellsize / 2.0
    return EsriGrid(path, ncols, nrows, xllcenter, yllcenter, cellsize, header["nodata_value"], values)


def copy_inputs(case_name: str, case_root: Path) -> dict[str, Path]:
    """Copy the exact benchmark inputs used by this run into the case record."""
    source = BENCHMARK_ROOT / "data" / case_name / "Inputs"
    destination = case_root / "Inputs"
    destination.mkdir(parents=True, exist_ok=True)
    for source_file in source.iterdir():
        if source_file.is_file():
            target = destination / source_file.name
            if not target.exists():
                shutil.copy2(source_file, target)
    specification = CASE_SPECIFICATIONS[case_name]
    return {
        "dem": destination / specification["dem"],
        "release": destination / specification["release"],
        "parameters": next(destination.glob("simulationParameterValues_*.csv")),
    }


def read_polygon_rings(shapefile: Path) -> list[tuple[np.ndarray, list[np.ndarray]]]:
    reader = pyshp.Reader(str(shapefile))
    rings: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for shape in reader.shapes():
        payload = shape.__geo_interface__
        polygons = [payload["coordinates"]] if payload["type"] == "Polygon" else payload.get("coordinates", [])
        for polygon in polygons:
            if not polygon or len(polygon[0]) < 3:
                continue
            rings.append((np.asarray(polygon[0], dtype=float), [np.asarray(hole, dtype=float) for hole in polygon[1:]]))
    if not rings:
        raise ValueError(f"Supplied ISeeSnow release has no usable polygon: {shapefile}")
    return rings


def benchmark_raster(dem: EsriGrid, *, crs_authid: str) -> AvacRaster:
    """Create an AVAC cell-centred terrain grid from an ISeeSnow raster.

    ISeeSnow ASCII headers locate values at cell centres.  AVAC keeps the
    same centre coordinates in :class:`AvacRaster`, while its topotype-3
    header records the outer cell edges; GeoClaw converts those edges back to
    centres on read.  This common registration makes the terrain, qinit and
    fixed-result grids coincide exactly with the benchmark cells.
    """
    xmin = dem.xllcenter - dem.cellsize / 2.0
    ymin = dem.yllcenter - dem.cellsize / 2.0
    x = dem.x_centres
    y = dem.y_centres
    metadata: dict[str, float | int] = {
        "xmin": float(xmin), "xmax": float(x[-1] + dem.cellsize / 2.0),
        "ymin": float(ymin), "ymax": float(y[-1] + dem.cellsize / 2.0),
        "ncols": dem.ncols, "nrows": dem.nrows, "cellsize": dem.cellsize, "nodata_value": dem.nodata,
    }
    values = np.asarray(dem.values_north, dtype=float)
    if np.isfinite(dem.nodata):
        values[np.isclose(values, dem.nodata)] = np.nan
    return AvacRaster(x, y, np.flipud(values), metadata, crs_authid, 1)


def set_benchmark_computational_extent(configuration_path: Path, dem: EsriGrid) -> None:
    """Align GeoClaw control volumes and result points to the benchmark grid.

    ISeeSnow supplies cell centres.  GeoClaw instead describes its
    computational rectangle by cell edges.  The validation domain therefore
    extends half a benchmark cell beyond the first and last centres, while
    the optional ``result_grid`` keeps fgmax points exactly on those centres.
    This changes neither the 5 m benchmark resolution nor the terrain values.
    """
    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    if not isinstance(configuration, dict) or not isinstance(configuration.get("dem_extent"), dict):
        raise ValueError("Prepared AVAC configuration has no dem_extent mapping.")
    extent = configuration["dem_extent"]
    half_cell = dem.cellsize / 2.0
    extent.update({
        "xmin": float(dem.x_centres[0] - half_cell),
        "xmax": float(dem.x_centres[-1] + half_cell),
        "ymin": float(dem.y_centres[0] - half_cell),
        "ymax": float(dem.y_centres[-1] + half_cell),
        "nbx": int(dem.ncols), "nby": int(dem.nrows), "cell_size": float(dem.cellsize),
    })
    configuration["result_grid"] = {
        "xllcenter": float(dem.x_centres[0]),
        "yllcenter": float(dem.y_centres[0]),
        "ncols": int(dem.ncols),
        "nrows": int(dem.nrows),
        "cell_size": float(dem.cellsize),
    }
    configuration_path.write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")


def enable_validation_gauge(
    configuration_path: Path,
    diagnostic_gauge: tuple[float, float] | None,
) -> None:
    """Restore an explicitly requested validation-only solver-step gauge.

    Normal AVAC preparation disables gauges because the plugin has no AVAC
    gauge editor.  An isolated validation run may nevertheless need a point
    history to diagnose a transient without changing output cadence.
    """
    if diagnostic_gauge is None:
        return
    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    configuration["gauges"] = {
        "gauge_recording": True,
        "gauges": [[1, *diagnostic_gauge]],
    }
    configuration_path.write_text(
        yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8",
    )


def normal_depth_to_vertical(dem: EsriGrid, coverage_south_to_north: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Translate ISeeSnow's normal release thickness to AVAC/GeoClaw h."""
    terrain = np.flipud(np.asarray(dem.values_north, dtype=float))
    if np.isfinite(dem.nodata):
        terrain[np.isclose(terrain, dem.nodata)] = np.nan
    filled = np.nan_to_num(terrain, nan=float(np.nanmean(terrain)))
    dz_dy, dz_dx = np.gradient(filled, dem.cellsize)
    cos_slope = 1.0 / np.sqrt(1.0 + dz_dx**2 + dz_dy**2)
    coverage = np.clip(np.asarray(coverage_south_to_north, dtype=float), 0.0, 1.0)
    normal_depth = NORMAL_RELEASE_THICKNESS_M * coverage
    vertical_depth = np.where(coverage > 0.0, normal_depth / cos_slope, 0.0)
    return vertical_depth, cos_slope


def write_iseesnow_initial_condition(
    path: Path,
    raster: AvacRaster,
    dem: EsriGrid,
    coverage_south_to_north: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Write the ISeeSnow depth conversion in AVAC's active qinit format.

    The normal-depth conversion is validation-specific, but the transport
    format must remain the plugin's binary ``init.avacbin`` contract.  Keeping
    the two actions together prevents a caller from accidentally overwriting
    the prepared binary file with a legacy text grid.
    """
    vertical_depth, cosine_slope = normal_depth_to_vertical(dem, coverage_south_to_north)
    write_init_binary(path, raster, vertical_depth)
    return vertical_depth, cosine_slope


def normal_peak_thickness(
    peak_depth_south_to_north: np.ndarray,
    initial_vertical_depth_south_to_north: np.ndarray,
    cosine_slope_south_to_north: np.ndarray,
) -> np.ndarray:
    """Return ISeeSnow normal PFT without changing internal row orientation."""
    peak_depth = np.asarray(peak_depth_south_to_north, dtype=float)
    initial_depth = np.asarray(initial_vertical_depth_south_to_north, dtype=float)
    cosine_slope = np.asarray(cosine_slope_south_to_north, dtype=float)
    if not (peak_depth.shape == initial_depth.shape == cosine_slope.shape):
        raise ValueError("PFT fields must share one south-to-north benchmark grid.")
    return np.maximum(peak_depth, initial_depth) * cosine_slope


def write_esri_ascii(path: Path, grid: EsriGrid, values_north: np.ndarray) -> None:
    values = np.asarray(values_north, dtype=float)
    if values.shape != (grid.nrows, grid.ncols):
        raise ValueError(f"Cannot write {path.name}: shape {values.shape} does not match benchmark grid.")
    output = np.where(np.isfinite(values), values, 0.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write(f"ncols {grid.ncols}\n")
        stream.write(f"nrows {grid.nrows}\n")
        stream.write(f"xllcenter {grid.xllcenter:.12g}\n")
        stream.write(f"yllcenter {grid.yllcenter:.12g}\n")
        stream.write(f"cellsize {grid.cellsize:.12g}\n")
        stream.write("nodata_value -9999\n")
        np.savetxt(stream, output, fmt="%.9g")


def configure_template(
    case_name: str,
    case_root: Path,
    simulation_end_s: float = SIMULATION_END_S,
    output_interval_s: float = OUTPUT_INTERVAL_S,
    limiter: str = "vanleer",
    cfl_target: float = 0.5,
    diagnostic_gauge: tuple[float, float] | None = None,
    refinement_levels: int = 1,
) -> Path:
    specification = CASE_SPECIFICATIONS[case_name]
    output_frames = fixed_grid_output_frame_count(simulation_end_s, output_interval_s)
    template = yaml.safe_load((PLUGIN_ROOT / "resources" / "AVAC_configuration100.yaml").read_text(encoding="utf-8"))
    template["computation"].update({
        "cell_size": CELL_SIZE_M, "refinement": int(refinement_levels), "t_max": simulation_end_s,
        "nb_simul": output_frames, "boundary": "extrap",
        "limiter": limiter, "cfl_target": cfl_target,
    })
    template["animation"]["n_out"] = output_frames
    template["output"].update({"delta_t": output_interval_s, "output_format": "binary32", "verbosity": 0})
    template["release"].update({
        "d0": NORMAL_RELEASE_THICKNESS_M, "correction_slope": False,
        "correction_elevation": False, "period_return": 1,
    })
    template["rheology"].update({
        "model": specification["model"], "mu": specification["mu"], "xi": specification["xi"],
        "C": 0.0, "rho": 300.0, "u_cr": 0.0, "beta": 0.0,
    })
    template["gauges"] = {
        "gauge_recording": diagnostic_gauge is not None,
        "gauges": ([] if diagnostic_gauge is None else [[1, *diagnostic_gauge]]),
    }
    destination = case_root / "avac_iseesnow_template.yaml"
    destination.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
    return destination


def write_plugin_case_configuration(case_name: str, case_root: Path, inputs: dict[str, Path], template: Path) -> Path:
    """Write a complete, reopenable AVAC4QGIS Case for one validation input.

    The Case restores the exact copied benchmark layers, AVAC template and
    user-facing parameters. It deliberately does not encode derived solver
    output or alter a completed ``Run``; pressing Prepare in the plugin creates
    a fresh normal run below ``<case>/runs``.
    """
    specification = CASE_SPECIFICATIONS[case_name]
    local = case_name != "RealTopo"
    crs_reference = ({"crs_wkt": LOCAL_CARTESIAN_CRS_WKT} if local else {"crs_authid": "EPSG:31287"})
    payload = {
        "format": "AVAC4QGIS plugin configuration",
        "version": 1,
        "working_directory": str(case_root.resolve()),
        "avac": {
            "configuration_template": str(template.resolve()),
            "parameters": controlled_values(load_complete_configuration(template)),
            "inputs": {
                "dem": {
                    "layer_id": "", "name": f"ISeeSnow {case_name} DEM",
                    "source": str(inputs["dem"].resolve()), "provider": "gdal", "kind": "raster",
                    **crs_reference,
                },
                "release": {
                    "layer_id": "", "name": f"ISeeSnow {case_name} release",
                    "source": str(inputs["release"].resolve()), "provider": "ogr", "kind": "vector",
                    **crs_reference,
                },
            },
        },
        "wave": {"enabled": False, "setup": None},
    }
    destination = case_root / f"AVAC4QGIS_ISeeSnow_{specification['simulation_id']}_Case.yaml"
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return destination


def ensure_plugin_case_configurations(case_names) -> list[Path]:
    """Create/update Case files without running or modifying a solver result."""
    destinations: list[Path] = []
    for case_name in case_names:
        case_root = RESULTS_ROOT / case_name
        inputs = copy_inputs(case_name, case_root)
        template = case_root / "avac_iseesnow_template.yaml"
        if not template.is_file():
            template = configure_template(case_name, case_root)
        destinations.append(write_plugin_case_configuration(case_name, case_root, inputs, template))
    return destinations


def solver_environment(workers: int) -> dict[str, str]:
    environment = dict(os.environ)
    for key in ("CLAW", "CLAW_PYTHON", "FC", "PYTHONPATH"):
        environment.pop(key, None)
    environment["OMP_NUM_THREADS"] = str(workers)
    return environment


def launch_solver(solver: Path, output_dir: Path, log_path: Path, workers: int) -> tuple[float, float]:
    """Run the validated executable and return wall and child CPU seconds."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None
    start = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run([str(solver)], cwd=output_dir, env=solver_environment(workers), stdout=log, stderr=subprocess.STDOUT)
    wall_seconds = time.perf_counter() - start
    if resource and before:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_seconds = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    else:
        # Windows has no POSIX child-resource counter.  Keep the report schema
        # stable with a wall-clock estimate instead of failing before a run.
        cpu_seconds = wall_seconds
    if result.returncode != 0:
        raise RuntimeError(f"xgeoclaw exited with {result.returncode}; inspect {log_path}")
    return wall_seconds, cpu_seconds


def disable_speed_limit(geoclaw_data: Path) -> float:
    """Disable GeoClaw's solver-level momentum cap for this validation run.

    ``speed_limit`` is a finite input read by the compiled solver.  Supplying
    a value far beyond floating-point physical speeds is preferable to an
    infinity token, whose parsing is compiler dependent.  This intentionally
    happens *before* the solver starts and is recorded with every submission.
    """
    if not geoclaw_data.is_file():
        raise FileNotFoundError(f"GeoClaw data file is missing: {geoclaw_data}")
    lines = geoclaw_data.read_text(encoding="utf-8").splitlines()
    changed = False
    rewritten: list[str] = []
    for line in lines:
        if "=: speed_limit" in line:
            rewritten.append(f"{DISABLED_SPEED_LIMIT_MPS:.1e}             =: speed_limit         # disabled for ISeeSnow validation")
            changed = True
        else:
            rewritten.append(line)
    if not changed:
        raise RuntimeError(f"GeoClaw data file has no speed_limit entry: {geoclaw_data}")
    geoclaw_data.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return DISABLED_SPEED_LIMIT_MPS


def set_spatial_order(claw_data: Path, spatial_order: int) -> int:
    """Set GeoClaw's requested spatial order and record it in ``claw.data``.

    Order 1 is the conservative Godunov dry-front setting. Order 2 enables
    GeoClaw's second-order update; its native mass history is deliberately
    retained because its wet/dry positivity repair can change volume. No
    output field is normalized or otherwise post-processed in either mode.
    """
    if spatial_order not in (1, 2):
        raise ValueError("ISeeSnow spatial order must be 1 or 2.")
    if not claw_data.is_file():
        raise FileNotFoundError(f"Claw data file is missing: {claw_data}")
    comment = (
        "conservative dry-front validation setting"
        if spatial_order == 1
        else "second-order ISeeSnow sensitivity setting; retain native mass diagnostic"
    )
    lines = claw_data.read_text(encoding="utf-8").splitlines()
    changed = False
    rewritten: list[str] = []
    for line in lines:
        if "=: order" in line:
            rewritten.append(f"{spatial_order}                    =: order               # {comment}")
            changed = True
        else:
            rewritten.append(line)
    if not changed:
        raise RuntimeError(f"Claw data file has no order entry: {claw_data}")
    claw_data.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return spatial_order


def _replace_generated_value(path: Path, label: str, value: str) -> None:
    """Replace one ``=: label`` value in a generated Clawpack data file."""
    marker = f"=: {label}"
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if marker in line:
            lines[index] = f"{value:<20} {line[line.index('=:') :]}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise KeyError(f"Could not find {label!r} in {path}")


def set_amr_resolution(output_dir: Path, levels: int, ratio: int) -> float:
    """Configure square dynamic AMR for an isolated resolution diagnostic."""
    levels, ratio = int(levels), int(ratio)
    if levels < 1 or levels > 3:
        raise ValueError("ISeeSnow diagnostics support one to three AMR levels.")
    if ratio < 2:
        raise ValueError("AMR refinement ratios must be at least two.")
    amr_data = output_dir / "amr.data"
    _replace_generated_value(amr_data, "amr_levels_max", str(levels))
    ratios = " ".join([str(ratio)] * max(1, levels - 1))
    for label in ("refinement_ratios_x", "refinement_ratios_y", "refinement_ratios_t"):
        _replace_generated_value(amr_data, label, ratios)
    _replace_generated_value(amr_data, "flag2refine", "T" if levels > 1 else "F")
    _replace_generated_value(
        output_dir / "refinement.data",
        "speed_tolerance",
        " ".join(["0.05"] * max(1, levels - 1)),
    )
    return CELL_SIZE_M / ratio ** (levels - 1)


def fgmax_fields(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = np.atleast_2d(np.loadtxt(path, dtype=float))
    if raw.shape[1] < 6:
        raise ValueError(f"Unexpected AVAC fgmax layout in {path}")
    x, y = np.unique(raw[:, 0]), np.unique(raw[:, 1])
    if raw.shape[0] != x.size * y.size:
        raise ValueError("AVAC fgmax samples do not form a regular rectangle.")
    xi, yi = np.searchsorted(x, raw[:, 0]), np.searchsorted(y, raw[:, 1])
    depth = np.zeros((y.size, x.size), dtype=float)
    velocity = np.zeros_like(depth)
    depth[yi, xi] = np.maximum(raw[:, 4], 0.0)
    velocity[yi, xi] = np.maximum(raw[:, 5], 0.0)
    return x, y, depth, velocity


def require_benchmark_alignment(x: np.ndarray, y: np.ndarray, grid: EsriGrid) -> None:
    if x.shape != grid.x_centres.shape or y.shape != grid.y_centres.shape:
        raise RuntimeError(
            f"AVAC fixed-grid shape {(x.size, y.size)} differs from the required ISeeSnow "
            f"shape {(grid.ncols, grid.nrows)}; no resampling was performed."
        )
    if not np.allclose(x, grid.x_centres, rtol=0.0, atol=1e-8) or not np.allclose(y, grid.y_centres, rtol=0.0, atol=1e-8):
        raise RuntimeError(
            "AVAC fixed-grid coordinates do not exactly match the required ISeeSnow raster centres; "
            "no shifted or interpolated submission raster was written."
        )


def _active_amr_mask(state, states) -> np.ndarray:
    """Return native cells not covered by any finer AMR patch."""
    patch = state.patch
    nx, ny = state.q.shape[1:3]
    x = patch.lower_global[0] + (np.arange(nx) + 0.5) * patch.delta[0]
    y = patch.lower_global[1] + (np.arange(ny) + 0.5) * patch.delta[1]
    mask = np.ones((nx, ny), dtype=bool)
    for finer in states:
        if finer.patch.level <= patch.level:
            continue
        covered_x = (
            (x >= finer.patch.lower_global[0] - 1.0e-12)
            & (x <= finer.patch.upper_global[0] + 1.0e-12)
        )
        covered_y = (
            (y >= finer.patch.lower_global[1] - 1.0e-12)
            & (y <= finer.patch.upper_global[1] + 1.0e-12)
        )
        if np.any(covered_x) and np.any(covered_y):
            mask[np.ix_(covered_x, covered_y)] = False
    return mask


def native_state_statistics(clawpack_source: Path, output_dir: Path) -> list[dict[str, float]]:
    """Read mass and motion directly from native GeoClaw state frames.

    Fixed-grid (fgout) fields are interpolated visualization products.  They
    are useful for maps but are not a conservation diagnostic.  These values
    instead sum a non-overlapping native AMR hierarchy: coarse cells covered
    by a finer patch are excluded. This is identical to the level-one sum for
    the publication configuration and also supports isolated resolution tests.
    """
    claw_root = Path(clawpack_source).expanduser().resolve()
    if str(claw_root) not in sys.path:
        sys.path.insert(0, str(claw_root))
    from clawpack import pyclaw

    frame_ids = sorted(
        int(path.name.rsplit(".t", 1)[1])
        for path in output_dir.glob("fort.t????")
        if path.name.rsplit(".t", 1)[1].isdigit()
    )
    if not frame_ids:
        raise RuntimeError("AVAC produced no native state frames for mass/motion reporting.")
    rows: list[dict[str, float]] = []
    for frame_id in frame_ids:
        solution = pyclaw.Solution()
        solution.read(frame_id, path=str(output_dir), file_format="binary", read_aux=False)
        signed_volume = positive_volume = moving_volume = 0.0
        max_speed = 0.0
        for state in solution.states:
            dx, dy = (float(value) for value in state.grid.delta)
            area = dx * dy
            h = np.asarray(state.q[0], dtype=float)
            hu = np.asarray(state.q[1], dtype=float)
            hv = np.asarray(state.q[2], dtype=float)
            active = _active_amr_mask(state, solution.states)
            finite_h = np.where(np.isfinite(h), h, 0.0)
            signed_volume += float(np.sum(finite_h[active]) * area)
            positive = np.maximum(finite_h, 0.0)
            positive_volume += float(np.sum(positive[active]) * area)
            wet = active & (positive >= VELOCITY_DEPTH_THRESHOLD_M)
            speed = np.zeros_like(positive)
            speed[wet] = np.hypot(hu[wet], hv[wet]) / positive[wet]
            speed = np.where(np.isfinite(speed), speed, 0.0)
            moving = active & (speed > VELOCITY_FLOW_THRESHOLD_MPS)
            moving_volume += float(np.sum(positive[moving]) * area)
            if np.any(active):
                max_speed = max(max_speed, float(np.max(speed[active])))
        rows.append({
            "frame": float(frame_id), "time_seconds": float(solution.t),
            "signed_volume_m3": signed_volume,
            "positive_volume_m3": positive_volume,
            "negative_volume_m3": signed_volume - positive_volume,
            "moving_volume_m3": moving_volume,
            "moving_volume_fraction": 0.0,  # completed relative to t=0 below
            "max_speed_mps": max_speed,
            "maximum_level": float(max(state.patch.level for state in solution.states)),
        })
    initial = rows[0]["positive_volume_m3"]
    if initial <= 0.0:
        raise RuntimeError("The initial native AVAC state contains no positive volume.")
    for row in rows:
        row["moving_volume_fraction"] = row["moving_volume_m3"] / initial
    return rows


def rest_time(rows: list[dict[str, float]]) -> float | None:
    """Return the first time with three practically motion-free outputs."""
    consecutive = 0
    for row in rows:
        if row["moving_volume_fraction"] <= REST_MOVING_VOLUME_FRACTION:
            consecutive += 1
            if consecutive >= REST_CONSECUTIVE_OUTPUTS:
                return float(row["time_seconds"])
        else:
            consecutive = 0
    return None


def write_mass_history(path: Path, rows: list[dict[str, float]]) -> None:
    fields = [
        "frame", "time_seconds", "signed_volume_m3", "positive_volume_m3",
        "negative_volume_m3", "moving_volume_m3", "moving_volume_fraction",
        "max_speed_mps", "maximum_level",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def submission_paths(case_name: str, case_root: Path) -> tuple[Path, Path, Path]:
    specification = CASE_SPECIFICATIONS[case_name]
    stem = f"{specification['release_name']}_{specification['simulation_id']}_null_{MODEL_TYPE}"
    output = case_root / "Submission"
    return output / f"{stem}_pft.asc", output / f"{stem}_pfv.asc", output / f"{stem}.txt"


def write_configuration_record(
    case_name: str,
    path: Path,
    runtime: Path,
    run_root: Path,
    inputs: dict[str, Path],
    cpu_s: float,
    wall_s: float,
    state_rows: list[dict[str, float]],
    stopped_time_s: float | None,
    spatial_order: int,
    solver: Path,
    simulation_end_s: float,
    output_interval_s: float,
    limiter: str,
    cfl_target: float,
    refinement_levels: int,
    refinement_ratio: int,
) -> None:
    specification = CASE_SPECIFICATIONS[case_name]
    lines = [
        "AVAC4QGIS ISeeSnow benchmark configuration",
        f"case = {case_name}",
        f"plugin_version = {plugin_version()}",
        f"solver_source = {runtime}",
        "runtime_manifest_sha256 = not applicable (validation uses the current source tree)",
        f"clawpack_source = {CLAWPACK_SOURCE}",
        f"clawpack_source_init_sha256 = {sha256(CLAWPACK_SOURCE / 'clawpack' / '__init__.py')}",
        "solver_origin = current repository source, compiled locally and explicitly recorded",
        f"solver = {solver}",
        f"solver_sha256 = {sha256(solver)}",
        "numerical_model = depth-integrated GeoClaw/AVAC with AVAC source terms",
        f"rheology = {specification['model']}",
        f"mu = {specification['mu']}",
        f"xi = {specification['xi']}",
        f"cell_size_m = {CELL_SIZE_M}",
        f"refinement_levels = {refinement_levels}",
        f"refinement_ratio = {refinement_ratio}",
        f"finest_effective_cell_size_m = {CELL_SIZE_M / refinement_ratio**(refinement_levels - 1):.12g}",
        f"simulation_end_ceiling_s = {simulation_end_s}",
        f"fixed_grid_output_interval_s = {output_interval_s}",
        f"limiter = {limiter}",
        f"cfl_target = {cfl_target}",
        f"rest_speed_threshold_mps = {VELOCITY_FLOW_THRESHOLD_MPS}",
        f"reported_velocity_depth_threshold_m = {VELOCITY_DEPTH_THRESHOLD_M}",
        f"rest_moving_volume_fraction = {REST_MOVING_VOLUME_FRACTION}",
        f"rest_consecutive_output_frames = {REST_CONSECUTIVE_OUTPUTS}",
        f"practical_rest_condition_first_met_s = {stopped_time_s if stopped_time_s is not None else 'not reached by ceiling'}",
        f"native_initial_volume_m3 = {state_rows[0]['positive_volume_m3']:.12g}",
        f"native_final_signed_volume_m3 = {state_rows[-1]['signed_volume_m3']:.12g}",
        f"native_final_positive_volume_m3 = {state_rows[-1]['positive_volume_m3']:.12g}",
        f"native_final_max_speed_mps = {state_rows[-1]['max_speed_mps']:.12g}",
        f"speed_limit_mps = {DISABLED_SPEED_LIMIT_MPS:.1e} (disabled; no practical solver velocity cap)",
        "spatial_method = " + (
            "first-order Godunov (conservative dry-front validation setting)"
            if spatial_order == 1 else
            "second-order GeoClaw update (native mass history retained; no volume correction)"
        ),
        f"release_polygon_sha256 = {sha256(inputs['release'])}",
        f"dem_sha256 = {sha256(inputs['dem'])}",
        f"release_thickness_normal_m = {NORMAL_RELEASE_THICKNESS_M}",
        "initialization = h_vertical = h_normal / cos(local DEM slope) inside supplied release polygon",
        "submitted_pft = maximum AVAC vertical h multiplied by cos(local DEM slope)",
        "submitted_pfv = AVAC native peak terrain-tangent speed sqrt(u^2 + v^2 + (u*Bx + v*By)^2) where h > 0.05 m",
        "velocity_diagnostic = zero for h <= 0.05 m; Kurganov-Petrova momentum/depth desingularization for 0.05 m < h < 0.20 m; exact momentum/depth for h >= 0.20 m; fgmax output only, with no state modification, velocity cap, or field clipping",
        "release_elevation_correction = false",
        "release_slope_correction = false",
        "benchmark_grid_contract = GeoClaw cell centres and fixed-grid points equal supplied ISeeSnow cell centres",
        f"solver_wall_seconds = {wall_s:.6f}",
        f"solver_cpu_seconds = {cpu_s:.6f}",
        f"run_root = {run_root}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prune_transient_frames(output_dir: Path) -> dict[str, int]:
    """Remove native state frames only after all statistics are saved.

    ISeeSnow requests peak rasters and a simulation summary, but the
    AVAC4QGIS Results tab reads the paired ``fgout`` files to prepare static
    and temporal GIS products. Keep those immutable visualization frames;
    only the native ``fort`` state frames used for the already-recorded mass
    history are transient.
    """
    retained = {"fgmax0001.txt", "timing.csv", "fort.amr"}
    removable = [
        path for path in output_dir.iterdir()
        if path.is_file() and path.name not in retained
        and (path.name.startswith("fort.a") or path.name.startswith("fort.b")
             or path.name.startswith("fort.q") or path.name.startswith("fort.t"))
    ]
    size_bytes = sum(path.stat().st_size for path in removable)
    for path in removable:
        path.unlink()
    return {"removed_frame_files": len(removable), "removed_frame_bytes": size_bytes}


def run_case(
    case_name: str,
    workers: int,
    overwrite: bool,
    retain_raw_frames: bool,
    spatial_order: int,
    simulation_end_s: float = SIMULATION_END_S,
    output_interval_s: float = OUTPUT_INTERVAL_S,
    limiter: str = "vanleer",
    cfl_target: float = 0.5,
    diagnostic_gauge: tuple[float, float] | None = None,
    refinement_levels: int = 1,
    refinement_ratio: int = 2,
    solver_override: Path | None = None,
) -> dict[str, Any]:
    case_root = RESULTS_ROOT / case_name
    inputs = copy_inputs(case_name, case_root)
    dem = parse_esri_ascii(inputs["dem"])
    crs = "EPSG:31287" if case_name == "RealTopo" else ""
    raster = benchmark_raster(dem, crs_authid=crs)
    rings = read_polygon_rings(inputs["release"])
    template = configure_template(
        case_name, case_root, simulation_end_s, output_interval_s, limiter,
        cfl_target, diagnostic_gauge, refinement_levels,
    )
    plugin_case = write_plugin_case_configuration(case_name, case_root, inputs, template)
    run_root = case_root / "Run"
    if run_root.exists():
        if not overwrite:
            raise FileExistsError(f"{run_root} already exists; use --overwrite only to discard this case run.")
        shutil.rmtree(run_root)
    runtime = source_runtime("avac").resolve()
    solver = (
        Path(solver_override).expanduser().resolve()
        if solver_override is not None else current_source_solver()
    )
    if not solver.is_file():
        raise FileNotFoundError(f"AVAC solver executable is unavailable: {solver}")
    prepared = prepare_isolated_runtime_run(
        run_root, runtime, raster, rings, template, {},
        {"benchmark": "ISeeSnow", "case": case_name, "dem_crs": crs,
         "solver_source": str(runtime), "execution_mode": "current_source"},
    )
    set_benchmark_computational_extent(prepared.configuration_path, dem)
    enable_validation_gauge(prepared.configuration_path, diagnostic_gauge)
    vertical_depth, cosine_slope = write_iseesnow_initial_condition(
        prepared.init_path, raster, dem, prepared.coverage,
    )
    write_esri_ascii(
        case_root / "initial_depth_normal.asc",
        dem,
        np.flipud(NORMAL_RELEASE_THICKNESS_M * prepared.coverage),
    )
    write_esri_ascii(case_root / "initial_depth_vertical.asc", dem, np.flipud(vertical_depth))
    output_dir = prepare_source_execution(
        "avac",
        prepared.avac_dir,
        setrun_override=PROJECT_ROOT / "avac-main" / "src" / "AVAC" / "setrun.py",
    )
    configured_speed_limit = disable_speed_limit(output_dir / "geoclaw.data")
    spatial_order = set_spatial_order(output_dir / "claw.data", spatial_order)
    finest_cell_size = set_amr_resolution(
        output_dir, refinement_levels, refinement_ratio,
    )
    wall_s, cpu_s = launch_solver(solver, output_dir, case_root / "solver.log", workers)
    update_run_status(prepared.avac_dir, "completed", solver_wall_seconds=wall_s, solver_cpu_seconds=cpu_s)

    x, y, peak_depth, peak_velocity = fgmax_fields(output_dir / "fgmax0001.txt")
    require_benchmark_alignment(x, y, dem)
    # Include the specified release at t=0 explicitly.  All three arrays are
    # south-to-north here; only the ESRI writer conversion below flips rows.
    normal_peak_depth = normal_peak_thickness(peak_depth, vertical_depth, cosine_slope)
    pft_path, pfv_path, configuration_path = submission_paths(case_name, case_root)
    write_esri_ascii(pft_path, dem, np.flipud(normal_peak_depth))
    write_esri_ascii(pfv_path, dem, np.flipud(peak_velocity))
    state_rows = native_state_statistics(CLAWPACK_SOURCE, output_dir)
    write_mass_history(case_root / "native_mass_history.csv", state_rows)
    stopped_time = rest_time(state_rows)
    # Use mass from native state arrays, not interpolated fixed-grid results.
    # Those are the control volumes updated by the solver.
    initial_volume = state_rows[0]["positive_volume_m3"]
    final_volume = state_rows[-1]["positive_volume_m3"]
    write_configuration_record(
        case_name, configuration_path, runtime, run_root, inputs, cpu_s, wall_s,
        state_rows, stopped_time, spatial_order, solver, simulation_end_s,
        output_interval_s, limiter, cfl_target, refinement_levels,
        refinement_ratio,
    )
    record = {
        "case": case_name, "cpu_seconds": cpu_s, "wall_seconds": wall_s,
        "simulation_end_ceiling_seconds": simulation_end_s,
        "flow_stopped_at_seconds": stopped_time,
        "flow_stopped_before_ceiling": stopped_time is not None,
        "final_max_speed_mps": state_rows[-1]["max_speed_mps"],
        "speed_limit_mps": configured_speed_limit,
        "spatial_order": spatial_order,
        "limiter": limiter,
        "cfl_target": cfl_target,
        "diagnostic_gauge": diagnostic_gauge,
        "refinement_levels": refinement_levels,
        "refinement_ratio": refinement_ratio,
        "finest_effective_cell_size_m": finest_cell_size,
        "maximum_amr_level": int(max(row["maximum_level"] for row in state_rows)),
        "plugin_version": plugin_version(),
        "solver": str(solver),
        "solver_sha256": sha256(solver),
        "initial_volume_m3": initial_volume, "final_volume_m3": final_volume,
        "signed_final_volume_m3": state_rows[-1]["signed_volume_m3"],
        "relative_volume_change": (final_volume - initial_volume) / initial_volume,
        "native_mass_history": str(case_root / "native_mass_history.csv"),
        "pft": str(pft_path), "pfv": str(pfv_path), "configuration": str(configuration_path),
        "plugin_case": str(plugin_case),
    }
    if not retain_raw_frames:
        record["transient_frame_cleanup"] = prune_transient_frames(output_dir)
    (case_root / "run_summary.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def write_result_table(records: list[dict[str, Any]]) -> None:
    destination = RESULTS_ROOT / "simulationResultTable.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["", "testCase", "computation duration (CPU) [s]", "avalanche flow time [s]", "volume at t0 [m3]", "volume at tFinal [m3]", "spatial resolution x [m]", "spatial resolution y [m]"])
        for index, record in enumerate(records, 1):
            stop_time = record.get("flow_stopped_at_seconds")
            writer.writerow([
                index, record["case"], f"{record['cpu_seconds']:.6f}",
                f"{float(stop_time):.6f}" if stop_time is not None else "not reached",
                f"{record['initial_volume_m3']:.6f}", f"{record['final_volume_m3']:.6f}",
                CELL_SIZE_M, CELL_SIZE_M,
            ])


def completed_case_records() -> list[dict[str, Any]]:
    """Read completed individual-case summaries without re-running a solver."""
    records = []
    for case_name in CASE_SPECIFICATIONS:
        path = RESULTS_ROOT / case_name / "run_summary.json"
        if not path.is_file():
            raise FileNotFoundError(f"No completed validation summary for {case_name}: {path}")
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def main() -> None:
    global RESULTS_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", *CASE_SPECIFICATIONS), default="all")
    parser.add_argument("--workers", type=int, default=1, help="OpenMP worker count; one is the reproducible default.")
    parser.add_argument("--overwrite", action="store_true", help="Discard an existing case Run directory before running it again.")
    parser.add_argument("--retain-raw-frames", action="store_true", help="Keep all transient GeoClaw time frames (several GB per case).")
    parser.add_argument("--spatial-order", type=int, choices=(1, 2), default=2,
                        help="GeoClaw spatial order: 2 is the current ISeeSnow baseline and retains native mass drift for audit; 1 is conservative dry-front.")
    parser.add_argument("--simulation-end", type=float, default=SIMULATION_END_S,
                        help="Integration ceiling in seconds (default: 1200; shorter values are intended only for diagnostics).")
    parser.add_argument("--output-interval", type=float, default=OUTPUT_INTERVAL_S,
                        help="Native/fixed-grid output interval in seconds (default: 10).")
    parser.add_argument("--limiter", choices=("minmod", "superbee", "vanleer", "mc"), default="vanleer",
                        help="Second-order wave limiter (default: van Leer).")
    parser.add_argument("--cfl-target", type=float, default=0.5,
                        help="Desired variable-step Courant number (default: 0.5).")
    parser.add_argument("--write-table-only", action="store_true", help="Write the three-case ISeeSnow result table from completed summaries without running AVAC.")
    parser.add_argument(
        "--results-root", type=Path, default=VALIDATION_ROOT,
        help="Write complete case products below this directory instead of replacing the publication results.",
    )
    parser.add_argument(
        "--diagnostic-gauge", type=float, nargs=2, metavar=("X", "Y"),
        help="Record one solver-step point history at X Y; intended for isolated diagnostic results.",
    )
    parser.add_argument(
        "--refinement-levels", type=int, choices=(1, 2, 3), default=1,
        help="Dynamic AMR levels for an isolated resolution diagnostic (default: 1).",
    )
    parser.add_argument(
        "--refinement-ratio", type=int, default=2,
        help="Square refinement ratio between diagnostic AMR levels (default: 2).",
    )
    parser.add_argument(
        "--solver", type=Path,
        help="Explicit AVAC executable for an isolated mechanism diagnostic.",
    )
    args = parser.parse_args()
    RESULTS_ROOT = args.results_root.expanduser().resolve()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if args.write_table_only:
        if args.case != "all" or args.overwrite or args.retain_raw_frames:
            raise SystemExit("--write-table-only requires the default --case all and no run flags.")
        ensure_plugin_case_configurations(CASE_SPECIFICATIONS)
        records = completed_case_records()
        write_result_table(records)
        print(json.dumps(records, indent=2))
        return
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    try:
        fixed_grid_output_frame_count(args.simulation_end, args.output_interval)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not 0 < args.cfl_target <= 1:
        raise SystemExit("--cfl-target must lie in (0, 1]")
    if args.refinement_ratio < 2:
        raise SystemExit("--refinement-ratio must be at least two")
    cases = list(CASE_SPECIFICATIONS) if args.case == "all" else [args.case]
    diagnostic_gauge = tuple(args.diagnostic_gauge) if args.diagnostic_gauge else None
    ensure_plugin_case_configurations(cases)
    records = [
        run_case(
            case_name, args.workers, args.overwrite, args.retain_raw_frames,
            args.spatial_order, args.simulation_end, args.output_interval,
            args.limiter, args.cfl_target, diagnostic_gauge,
            args.refinement_levels, args.refinement_ratio, args.solver,
        )
        for case_name in cases
    ]
    if args.case == "all":
        write_result_table(records)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
