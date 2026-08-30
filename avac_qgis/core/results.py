"""Discovery and GIS materialization of immutable AVAC solver results.

The only AVAC binary reader used here is Clawpack's ``FGoutGrid`` reader --
the same reader used by the standalone GUI.  Derived GeoTIFFs are deliberately
kept outside ``AVAC/_output`` so solver artifacts remain reproducible.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from .run_project import read_run_metadata, write_run_metadata
from .runtime import validate_runtime
from .clawpack_logging import suppress_pyclaw_file_logging
from .simulation_time import format_simulation_seconds, temporal_band_records
from .time_utils import temporal_origin_iso


RESULT_FORMAT = 6
RESULT_DIRECTORY = "qgis_results"
RESULT_MANIFEST = "results.json"
EPOCH_ISO = "2000-01-01T00:00:00Z"  # Legacy fallback retained for old external manifests.


@dataclass(frozen=True)
class GridGeometry:
    width: int
    height: int
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    dx: float
    dy: float


@dataclass(frozen=True)
class TemporalFrame:
    frame_id: int
    time_seconds: float
    data_path: str
    metadata_path: str


@dataclass(frozen=True)
class ResultDiscovery:
    run_root: Path
    avac_dir: Path
    output_dir: Path
    crs_authid: str
    rho: float
    output_format: str
    fgout_grid: int
    fgmax_grid: int
    fgmax_path: Path | None
    fgmax_optional_quantities: tuple[str, ...]
    frames: tuple[TemporalFrame, ...]


def _frame_id(path: Path) -> int | None:
    suffix = path.name.rsplit(".t", 1)
    if len(suffix) != 2 or not suffix[1].isdigit():
        return None
    return int(suffix[1])


def _fgout_time(path: Path) -> float:
    try:
        return float(path.read_text(encoding="utf-8", errors="ignore").splitlines()[0].split()[0])
    except (OSError, IndexError, ValueError) as exc:
        raise ValueError(f"Invalid fgout time metadata: {path}") from exc


def _configuration(avac_dir: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load((avac_dir / "AVAC_configuration.yaml").read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"Completed run has no readable AVAC configuration: {avac_dir}") from exc
    if not isinstance(payload, dict):
        raise ValueError("AVAC configuration is not a mapping.")
    return payload


def discover_results(run_root: str | Path, fgout_grid: int = 1, fgmax_grid: int | None = None) -> ResultDiscovery:
    """Inspect a completed marked run without assuming duration or frame count."""
    run_root = Path(run_root).expanduser().resolve()
    metadata = read_run_metadata(run_root)
    if metadata.get("status") != "completed":
        raise ValueError("Results can only be loaded from a completed AVAC-QGIS run.")
    crs = str(metadata.get("dem_crs") or "").strip()
    # An experimental or idealized case can be expressed in a valid local
    # Cartesian coordinate plane without an externally defined CRS. Do not
    # invent a real-world projection for it: QGIS can display an unreferenced
    # raster and the user may later assign a CRS if an overlay is required.
    avac_dir = run_root / str(metadata.get("avac_directory", "AVAC"))
    configuration = _configuration(avac_dir)
    output_name = str(configuration.get("computation", {}).get("output_directory", "_output"))
    output_dir = Path(output_name) if Path(output_name).is_absolute() else avac_dir / output_name
    if not output_dir.is_dir():
        raise ValueError(f"Completed run has no AVAC output directory: {output_dir}")
    if fgout_grid < 1:
        raise ValueError("FGout grid number must be positive.")
    fgmax_grid = fgout_grid if fgmax_grid is None else fgmax_grid
    if fgmax_grid < 1:
        raise ValueError("FGmax grid number must be positive.")
    grid_name = f"fgout{fgout_grid:04d}"
    frames: list[TemporalFrame] = []
    for time_file in sorted(output_dir.glob(f"{grid_name}.t*")):
        frame_id = _frame_id(time_file)
        if frame_id is None:
            continue
        candidates = [output_dir / f"{grid_name}.b{frame_id:04d}", output_dir / f"{grid_name}.q{frame_id:04d}"]
        data = next((path for path in candidates if path.is_file()), None)
        if data is None:
            raise ValueError(f"fgout frame {frame_id} has time metadata but no paired binary/ASCII data file.")
        frames.append(TemporalFrame(frame_id, _fgout_time(time_file), data.name, time_file.name))
    if not frames:
        raise ValueError(f"No complete {grid_name} frames found in {output_dir}")
    if any(not np.isfinite(frame.time_seconds) for frame in frames):
        raise ValueError("fgout frame times must be finite.")
    config_rho = configuration.get("rheology", {}).get("rho", 300.0)
    fgmax_path = output_dir / f"fgmax{fgmax_grid:04d}.txt"
    if not fgmax_path.is_file():
        fgmax_path = None
    optional: tuple[str, ...] = ()
    if fgmax_path is not None:
        try:
            columns = int(np.loadtxt(fgmax_path, max_rows=1).size)
            if columns >= 9:
                optional = ("time_of_maximum_depth", "time_of_maximum_velocity", "arrival_time")
        except (OSError, ValueError):
            pass
    return ResultDiscovery(
        run_root, avac_dir, output_dir, crs, float(config_rho),
        str(configuration.get("output", {}).get("output_format", "binary32")), fgout_grid, fgmax_grid,
        fgmax_path, optional, tuple(frames),
    )


def _load_fgout(discovery: ResultDiscovery, frame_id: int) -> tuple[float, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Use Clawpack FGoutGrid, matching the standalone GUI wet/dry semantics."""
    metadata = read_run_metadata(discovery.run_root)
    claw_root = str(metadata.get("claw_root") or "").strip()
    if not claw_root:
        runtime = str(metadata.get("runtime") or "").strip()
        if runtime:
            manifest = validate_runtime(runtime)
            claw_root = str(Path(runtime) / str(manifest["clawpack"]["root"]))
    if not claw_root:
        raise ValueError("Run has no validated bundled Clawpack runtime; reopen/repair the AVAC runtime before loading results.")
    added = False
    if claw_root not in sys.path:
        sys.path.insert(0, claw_root)
        added = True
    try:
        # PyClaw 5.14 installs ``FileHandler('pyclaw.log')`` at import time.
        # Suppress just that configuration while reading immutable AVAC output;
        # this keeps QGIS restart/reopen independent of its process cwd.
        with suppress_pyclaw_file_logging():
            from clawpack.geoclaw import fgout_tools
            grid = fgout_tools.FGoutGrid(discovery.fgout_grid, str(discovery.output_dir), output_format=discovery.output_format)
            grid.read_fgout_grids_data()
            frame = grid.read_frame(int(frame_id))
    finally:
        if added:
            sys.path.remove(claw_root)
    x, y, fields = _avac_frame_fields(frame, discovery.rho, frame_id)
    return float(frame.t), x, y, fields


def _avac_frame_fields(frame, rho: float, frame_id: int = 0) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Extract correctly oriented GIS fields from one AVAC FGout frame."""
    wet = frame.h >= 0.001
    velocity_wet = frame.h >= 0.05
    depth = np.asarray(np.ma.masked_where(~wet, frame.h).filled(0.0), dtype=float)
    has_velocity_components = hasattr(frame, "u") and hasattr(frame, "v")
    if has_velocity_components:
        u = np.asarray(np.ma.masked_where(~velocity_wet, frame.u).filled(0.0), dtype=float)
        v = np.asarray(np.ma.masked_where(~velocity_wet, frame.v).filled(0.0), dtype=float)
        scalar_speed = None
    else:
        # Older/synthetic FGout-like objects may expose only GeoClaw's
        # horizontal scalar speed.  Preserve that supported input shape; a
        # terrain-tangent reconstruction is impossible without direction.
        scalar_speed = np.asarray(np.ma.masked_where(~velocity_wet, frame.s).filled(0.0), dtype=float)
        u = v = None
    bed = np.asarray(frame.B if hasattr(frame, "B") else frame.eta - frame.h, dtype=float)
    # ``eta`` is the exact AVAC/GeoClaw free-surface state h + B.  In dry
    # cells it equals the fixed bed elevation.  Exposing it makes the initial
    # release prism and the bed left behind after release directly visible,
    # without inventing a stationary background snow cover.
    snow_surface_elevation = np.asarray(frame.eta, dtype=float)
    x, y = np.asarray(frame.x, dtype=float), np.asarray(frame.y, dtype=float)
    if depth.shape == (x.size, y.size):
        depth = depth.T
        velocity_wet = velocity_wet.T
        if has_velocity_components:
            u = u.T
            v = v.T
        else:
            scalar_speed = scalar_speed.T
        bed = bed.T
        snow_surface_elevation = snow_surface_elevation.T
    if depth.shape != (y.size, x.size):
        raise ValueError(f"Unexpected fgout array/coordinate orientation for frame {frame_id}: {depth.shape}")
    if snow_surface_elevation.shape != depth.shape:
        raise ValueError(
            f"Unexpected AVAC snow-surface orientation for frame {frame_id}: "
            f"{snow_surface_elevation.shape}"
        )
    if bed.shape != depth.shape:
        raise ValueError(f"Unexpected AVAC velocity/topography orientation for frame {frame_id}")

    # AVAC advances vertical depth and horizontal momentum on the map grid.
    # Users, rheological parameters, and avalanche benchmarks refer to speed
    # along the terrain surface.  For z=B(x,y), the missing vertical velocity
    # component of a bed-following velocity is w=u*Bx+v*By.
    if has_velocity_components:
        if u.shape != depth.shape or v.shape != depth.shape:
            raise ValueError(f"Unexpected AVAC velocity/topography orientation for frame {frame_id}")
        edge_order = 2 if min(bed.shape) >= 3 else 1
        dzdy, dzdx = np.gradient(bed, y, x, edge_order=edge_order)
        velocity = np.sqrt(u**2 + v**2 + (u*dzdx + v*dzdy)**2)
    else:
        if scalar_speed.shape != depth.shape:
            raise ValueError(f"Unexpected AVAC scalar-velocity orientation for frame {frame_id}")
        velocity = scalar_speed
    velocity[~np.asarray(velocity_wet, dtype=bool)] = 0.0
    return x, y, {
        "depth": depth,
        "velocity": velocity,
        "pressure": pressure_from_velocity(velocity, rho),
        "snow_surface_elevation": snow_surface_elevation,
    }


def _load_fgmax(discovery: ResultDiscovery) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    if discovery.fgmax_path is None:
        raise ValueError("No fgmax result is available for this run.")
    raw = np.loadtxt(discovery.fgmax_path)
    raw = np.atleast_2d(raw)
    if raw.shape[1] < 6:
        raise ValueError(f"Unexpected fgmax format: {discovery.fgmax_path}")
    raw = np.where(raw <= -1e90, np.nan, raw)
    x, y = np.unique(raw[:, 0]), np.unique(raw[:, 1])
    if raw.shape[0] != x.size * y.size:
        raise ValueError("fgmax samples do not form a rectangular grid.")
    xi, yi = np.searchsorted(x, raw[:, 0]), np.searchsorted(y, raw[:, 1])
    def field(column: int, *, positive_only: bool) -> np.ndarray:
        values = np.full((y.size, x.size), np.nan, dtype=float)
        values[yi, xi] = raw[:, column]
        if positive_only:
            return np.where(np.isfinite(values) & (values > 0.0), values, 0.0)
        # A zero time is scientifically valid (e.g. wet at t=0). Never-event
        # cells may use either AVAC's large negative sentinel or an older
        # negative convention.  Neither is a displayable simulation time.
        return np.where(np.isfinite(values) & (values >= 0.0), values, np.nan)
    depth, velocity = field(4, positive_only=True), field(5, positive_only=True)
    fields = {
        "max_depth": depth,
        "max_velocity": velocity,
        "max_pressure": pressure_from_velocity(velocity, discovery.rho),
    }
    if raw.shape[1] >= 9:
        fields.update({
            "time_max_depth": field(6, positive_only=False),
            "time_max_velocity": field(7, positive_only=False),
            "arrival_time": field(8, positive_only=False),
        })
    return x, y, fields


def pressure_from_velocity(velocity: np.ndarray, rho: float) -> np.ndarray:
    """Existing GUI kinetic-pressure definition, in kPa."""
    return 0.5 * float(rho) * np.asarray(velocity, dtype=float) ** 2 / 1000.0


def geometry_from_axes(x: np.ndarray, y: np.ndarray) -> GridGeometry:
    """Derive edge-based GDAL georeferencing from AVAC cell-centre axes."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size < 2 or y.size < 2:
        raise ValueError("Result axes must be one-dimensional with at least two cells.")
    dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
    if dx <= 0 or dy <= 0 or not np.allclose(np.diff(x), dx) or not np.allclose(np.diff(y), dy):
        raise ValueError("AVAC result grid is not regularly increasing; cannot write a GeoTIFF.")
    return GridGeometry(x.size, y.size, x[0] - dx / 2, x[-1] + dx / 2, y[0] - dy / 2, y[-1] + dy / 2, dx, dy)


def _create_geotiff(path: Path, band_count: int, geometry: GridGeometry, crs_authid: str):
    from osgeo import gdal, osr
    path.parent.mkdir(parents=True, exist_ok=True)
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), geometry.width, geometry.height, band_count, gdal.GDT_Float32,
                            options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES", "INTERLEAVE=BAND"])
    if dataset is None:
        raise RuntimeError(f"Could not create derived raster: {path}")
    if crs_authid:
        spatial_ref = osr.SpatialReference()
        spatial_ref.SetFromUserInput(crs_authid)
        dataset.SetProjection(spatial_ref.ExportToWkt())
    dataset.SetGeoTransform((geometry.xmin, geometry.dx, 0.0, geometry.ymax, 0.0, -geometry.dy))
    return dataset


def _write_band(
    dataset, band_no: int, array: np.ndarray, geometry: GridGeometry, *,
    description: str | None = None, metadata: dict[str, str] | None = None,
) -> None:
    if array.shape != (geometry.height, geometry.width):
        raise ValueError("Array shape does not match derived raster geometry.")
    writable = np.where(np.isfinite(array), array, -9999.0).astype(np.float32, copy=False)
    band = dataset.GetRasterBand(band_no)
    band.SetNoDataValue(-9999.0)
    if description:
        band.SetDescription(description)
    if metadata:
        band.SetMetadata({str(key): str(value) for key, value in metadata.items()})
    band.WriteArray(np.flipud(writable))  # AVAC arrays are south-to-north; GDAL rows are north-to-south.
    band.FlushCache()


def _write_geotiff(path: Path, arrays: list[np.ndarray], geometry: GridGeometry, crs_authid: str) -> None:
    dataset = _create_geotiff(path, len(arrays), geometry, crs_authid)
    for band_no, array in enumerate(arrays, 1):
        _write_band(dataset, band_no, array, geometry)
    dataset.FlushCache()
    dataset = None


def _raw_fingerprint(discovery: ResultDiscovery) -> str:
    # One manifest caches full and refined grids, so its validity cannot
    # depend on whichever grid happened to be selected most recently.
    paths = sorted(path for path in discovery.output_dir.glob("fgmax*.txt") if path.is_file())
    paths += sorted(path for path in discovery.output_dir.glob("fgout*.*") if path.is_file())
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _manifest_path(discovery: ResultDiscovery) -> Path:
    return discovery.run_root / RESULT_DIRECTORY / RESULT_MANIFEST


def cached_results(discovery: ResultDiscovery) -> dict[str, Any] | None:
    try:
        payload = json.loads(_manifest_path(discovery).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("format") != RESULT_FORMAT or payload.get("raw_fingerprint") != _raw_fingerprint(discovery):
        return None
    if not isinstance(payload.get("static"), dict) or not isinstance(payload.get("temporal"), dict):
        return None
    return payload


STATIC_UNITS = {
    "max_depth": "m", "max_velocity": "m/s", "max_pressure": "kPa",
    "time_max_depth": "Simulation time [s]", "time_max_velocity": "Simulation time [s]",
    "arrival_time": "Simulation time [s]",
}
TEMPORAL_UNITS = {
    "depth": "m", "velocity": "m/s", "pressure": "kPa",
    "snow_surface_elevation": "m",
}


def _valid_product(result_dir: Path, product: dict[str, Any] | None, expected_bands: int = 1) -> bool:
    if not isinstance(product, dict) or not (result_dir / str(product.get("path", ""))).is_file():
        return False
    try:
        from osgeo import gdal
        dataset = gdal.Open(str(result_dir / str(product["path"])))
        valid = bool(dataset and dataset.RasterCount == expected_bands)
        dataset = None
        return valid
    except Exception:  # noqa: BLE001
        return False


def _write_temporal_variable(
    discovery: ResultDiscovery, variable: str, progress: Callable[[int], None] | None,
    cancelled: Callable[[], bool] | None = None, band_records: list[dict[str, Any]] | None = None,
) -> tuple[GridGeometry, tuple[float, float]]:
    """Stream one requested fgout variable to a band-interleaved GeoTIFF."""
    result_dir = discovery.run_root / RESULT_DIRECTORY
    geometry: GridGeometry | None = None
    minimum = math.inf
    maximum = -math.inf
    dataset = None
    stem = f"temporal_fgout{discovery.fgout_grid:04d}_{variable}"
    path = result_dir / f"{stem}.tif"
    temporary_path = result_dir / f".{stem}.partial.tif"
    temporary_path.unlink(missing_ok=True)
    records = band_records or temporal_band_records(EPOCH_ISO, [frame.time_seconds for frame in discovery.frames])
    if len(records) != len(discovery.frames):
        raise ValueError("Temporal band metadata does not match the result frame count.")
    try:
        for index, descriptor in enumerate(discovery.frames, 1):
            if cancelled and cancelled():
                raise InterruptedError("AVAC result preparation cancelled.")
            actual_time, x, y, fields = _load_fgout(discovery, descriptor.frame_id)
            if not np.isclose(actual_time, descriptor.time_seconds):
                raise ValueError(f"fgout frame {descriptor.frame_id} time does not match its .t metadata file.")
            current_geometry = geometry_from_axes(x, y)
            if geometry is None:
                geometry = current_geometry
                dataset = _create_geotiff(temporary_path, len(discovery.frames), geometry, discovery.crs_authid)
                dataset.SetMetadataItem("AVAC_FIRST_FRAME_START_ISO8601", str(records[0]["start_iso"]))
                dataset.SetMetadataItem("AVAC_TEMPORAL_AXIS", "elapsed simulation seconds")
            elif geometry != current_geometry:
                raise ValueError("fgout frames use inconsistent grids; a single temporal raster is not valid.")
            values = fields[variable]
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise ValueError(f"Temporal AVAC variable {variable} has no finite values in frame {descriptor.frame_id}.")
            minimum = min(minimum, float(np.min(finite)))
            maximum = max(maximum, float(np.nanmax(values)))
            record = records[index - 1]
            _write_band(
                dataset, index, values, geometry,
                description=f"{variable.replace('_', ' ').title()} at simulation {format_simulation_seconds(actual_time)}",
                metadata={
                    "AVAC_SIMULATION_TIME_SECONDS": f"{actual_time:.17g}",
                    "AVAC_TEMPORAL_START_ISO8601": str(record["start_iso"]),
                    "AVAC_TEMPORAL_END_ISO8601": str(record["end_iso"]),
                },
            )
            if progress:
                progress(int(20 + 80 * index / len(discovery.frames)))
    finally:
        if dataset is not None:
            dataset.FlushCache()
            dataset = None
    if geometry is None:
        raise ValueError("No temporal frames were materialized.")
    os.replace(temporary_path, path)
    limits = (minimum, maximum) if variable == "snow_surface_elevation" else (0.0, maximum)
    return geometry, limits


def materialize_results(
    discovery: ResultDiscovery,
    temporal_variables: tuple[str, ...] = ("depth", "velocity", "pressure"),
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Create/reuse selected GIS products without changing raw AVAC output."""
    requested = tuple(dict.fromkeys(temporal_variables))
    unknown = set(requested) - set(TEMPORAL_UNITS)
    if unknown:
        raise ValueError("Unsupported temporal AVAC variable: " + ", ".join(sorted(unknown)))
    cached = cached_results(discovery)
    result_dir = discovery.run_root / RESULT_DIRECTORY
    run_metadata = read_run_metadata(discovery.run_root)
    origin_iso = temporal_origin_iso(run_metadata, discovery.run_root / ".avac_qgis_run.json")
    band_records = temporal_band_records(origin_iso, [frame.time_seconds for frame in discovery.frames])
    payload = cached or {
        "format": RESULT_FORMAT, "source_run": str(discovery.run_root), "raw_output": str(discovery.output_dir),
        "raw_fingerprint": _raw_fingerprint(discovery), "crs_authid": discovery.crs_authid,
        "temporal_frames": [asdict(frame) for frame in discovery.frames],
        "simulation_time_seconds": [frame.time_seconds for frame in discovery.frames],
        "temporal_origin_iso": origin_iso, "temporal_axis_epoch": origin_iso,
        "temporal_band_ranges": band_records, "density_kg_m3": discovery.rho, "static": {}, "temporal": {},
    }
    x, y, static_fields = _load_fgmax(discovery)
    static_geometry = geometry_from_axes(x, y)
    for index, (name, array) in enumerate(static_fields.items(), 1):
        product_key = name if discovery.fgmax_grid == 1 else f"fgmax{discovery.fgmax_grid:04d}_{name}"
        filename = f"{name}.tif" if discovery.fgmax_grid == 1 else f"fgmax{discovery.fgmax_grid:04d}_{name}.tif"
        product = payload["static"].get(product_key)
        if not _valid_product(result_dir, product):
            _write_geotiff(result_dir / filename, [array], static_geometry, discovery.crs_authid)
        payload["static"][product_key] = {
            "path": filename, "unit": STATIC_UNITS[name],
            "range": [float(np.nanmin(array)), float(np.nanmax(array))],
            "event_time": name.startswith("time_") or name == "arrival_time",
            "fgmax_grid": discovery.fgmax_grid,
        }
        if progress:
            progress(int(20 * index / len(static_fields)))
    payload.setdefault("static_geometries", {})[f"fgmax{discovery.fgmax_grid:04d}"] = asdict(static_geometry)
    payload["available_fgmax_optional_quantities"] = list(discovery.fgmax_optional_quantities)
    for variable in requested:
        if cancelled and cancelled():
            raise InterruptedError("AVAC result preparation cancelled.")
        product_key = f"fgout{discovery.fgout_grid:04d}_{variable}"
        product = payload["temporal"].get(product_key)
        if not _valid_product(result_dir, product, len(discovery.frames)):
            try:
                geometry, limits = _write_temporal_variable(discovery, variable, progress, cancelled, band_records)
            except Exception:
                (result_dir / f".temporal_fgout{discovery.fgout_grid:04d}_{variable}.partial.tif").unlink(missing_ok=True)
                raise
            payload["temporal"][product_key] = {
                "path": f"temporal_fgout{discovery.fgout_grid:04d}_{variable}.tif", "unit": TEMPORAL_UNITS[variable],
                "range": list(limits), "geometry": asdict(geometry), "density_kg_m3": discovery.rho,
                "fgout_grid": discovery.fgout_grid, "band_ranges": band_records,
            }
    # Existing temporal products remain valid if another variable is added.
    for variable, product in list(payload["temporal"].items()):
        if not _valid_product(result_dir, product, len(discovery.frames)):
            payload["temporal"].pop(variable)
    result_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(discovery).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata = read_run_metadata(discovery.run_root)
    metadata["qgis_results"] = {"format": RESULT_FORMAT, "directory": RESULT_DIRECTORY, "manifest": str(_manifest_path(discovery).relative_to(discovery.run_root))}
    write_run_metadata(discovery.run_root, metadata)
    if progress:
        progress(100)
    return payload
