"""QGIS products for completed bundled Wave simulations (no video export)."""

from __future__ import annotations

import json
import os
import sys
import csv
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from .clawpack_logging import suppress_pyclaw_file_logging
from .results import GridGeometry, _create_geotiff, _write_band, geometry_from_axes
from .runtime import validate_runtime
from .simulation_time import format_simulation_seconds, temporal_band_records
from .time_utils import TEMPORAL_ORIGIN_FIELD, localize_iso_datetime, temporal_origin_iso
from .wave_project import WAVE_MARKER

WAVE_RESULT_DIRECTORY = "qgis_wave_results"
WAVE_RESULT_MANIFEST = "results.json"
WAVE_RESULT_ERROR_LOG = "result_loading_error.log"
WAVE_RESULT_FORMAT = 3


@dataclass(frozen=True)
class WaveFrame:
    frame_id: int
    time_seconds: float


@dataclass(frozen=True)
class WaveDiscovery:
    root: Path
    output: Path
    runtime: Path
    crs_authid: str
    output_format: str
    water_level: float
    temporal_origin_iso: str
    frames: tuple[WaveFrame, ...]


def _wave_temporal_origin_iso(root: Path, marker: dict) -> str:
    """Resolve the AVAC-owned temporal origin for a Wave scenario.

    New scenarios persist the inherited origin in their marker.  The source
    fallback keeps results from scenarios prepared by earlier plugin versions
    synchronized too, without rewriting the user's prepared scenario merely
    because its results are viewed.
    """
    explicit = str(marker.get(TEMPORAL_ORIGIN_FIELD) or "").strip()
    if explicit:
        try:
            return localize_iso_datetime(explicit)
        except ValueError:
            pass
    source_root = str(marker.get("source_avac_run") or "").strip()
    if source_root:
        source_marker = Path(source_root).expanduser() / ".avac_qgis_run.json"
        try:
            source = json.loads(source_marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            return temporal_origin_iso(source, source_marker)
    return temporal_origin_iso(marker, root / WAVE_MARKER)


def discover_wave_results(root: str | Path, runtime: str | Path) -> WaveDiscovery:
    root, runtime = Path(root).resolve(), Path(runtime).resolve()
    config = yaml.safe_load((root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    marker = json.loads((root / WAVE_MARKER).read_text(encoding="utf-8"))
    output = root / "Wave" / str(config["output"]["output_directory"])
    if not output.is_dir():
        raise ValueError("Wave output directory is unavailable.")
    frames: list[WaveFrame] = []
    for time_file in sorted(output.glob("fgout0001.t*")):
        suffix = time_file.name.rsplit(".t", 1)[-1]
        if not suffix.isdigit() or not any((output / f"fgout0001.{kind}{int(suffix):04d}").is_file() for kind in ("b", "q")):
            continue
        try:
            time = float(time_file.read_text(encoding="utf-8", errors="ignore").splitlines()[0].split()[0])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Invalid Wave frame time: {time_file}") from exc
        frames.append(WaveFrame(int(suffix), time))
    if not frames:
        raise ValueError("No complete Wave fgout0001 frames were found.")
    crs = str(marker.get("crs_authid") or "")
    if not crs:
        raise ValueError("This Wave scenario lacks CRS metadata. Reprepare it with the current plugin before loading results.")
    origin_iso = _wave_temporal_origin_iso(root, marker)
    return WaveDiscovery(
        root, output, runtime, crs, str(config["output"]["output_format"]),
        float(config["lake"]["water_level"]), origin_iso, tuple(frames),
    )


def load_wave_frame(discovery: WaveDiscovery, frame_id: int):
    manifest = validate_runtime(discovery.runtime)
    claw = str(discovery.runtime / str(manifest["clawpack"]["root"]))
    added = claw not in sys.path
    if added:
        sys.path.insert(0, claw)
    try:
        with suppress_pyclaw_file_logging():
            from clawpack.geoclaw import fgout_tools
            grid = fgout_tools.FGoutGrid(1, str(discovery.output), output_format=discovery.output_format)
            grid.read_fgout_grids_data(); frame = grid.read_frame(frame_id)
    finally:
        if added:
            sys.path.remove(claw)
    x, y = np.asarray(frame.x, float), np.asarray(frame.y, float)
    h, b, hu, hv = np.asarray(frame.h, float), np.asarray(frame.B, float), np.asarray(frame.hu, float), np.asarray(frame.hv, float)
    if h.shape == (x.size, y.size):
        h, b, hu, hv = h.T, b.T, hu.T, hv.T
    if h.shape != (y.size, x.size):
        raise ValueError("Unexpected Wave fgout grid orientation.")
    return float(frame.t), x, y, np.where(h >= .0001, h, 0.0), b, hu, hv


def _mask(root: Path, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Read/crop the numeric-header force-dry mask to the fgout grid.

    The terrain source may be wider than the explicitly selected Wave domain,
    so the mask cannot be assumed to have the fgout dimensions.
    """
    path = root / "Topo" / "mask.asc"
    header = path.read_text(encoding="utf-8").splitlines()[:6]
    try:
        ncols, nrows = int(header[0].split()[0]), int(header[1].split()[0])
        xmin, ymin, cell = (float(header[index].split()[0]) for index in (2, 3, 4))
    except (IndexError, ValueError) as exc:
        raise ValueError("Wave force-dry mask header is invalid.") from exc
    raw = np.loadtxt(path, skiprows=6)
    raw = np.atleast_2d(raw)
    if raw.shape != (nrows, ncols):
        raise ValueError("Wave force-dry mask dimensions do not match its header.")
    # Current scenarios store exactly one force-dry value per fgout/solver
    # cell.  Its header uses the nonstandard lookup anchors required by
    # GeoClaw's Fortran qinit routine, so shape is the authoritative mapping.
    # Retain the coordinate-crop path below for scenarios prepared by older
    # plugin versions, whose masks included the topography halo.
    if raw.shape == (np.asarray(y).size, np.asarray(x).size):
        return np.flipud(raw) == 0.0
    # GeoClaw may expose fgout coordinates as either the source-grid values or
    # cell centers, depending on its ASCII-topography convention. Resolve the
    # convention from the actual frame rather than assuming a full-domain mask.
    offset = next((candidate for candidate in (0.0, 0.5)
                   if np.allclose((np.asarray(x) - xmin) / cell - candidate, np.rint((np.asarray(x) - xmin) / cell - candidate))
                   and np.allclose((np.asarray(y) - ymin) / cell - candidate, np.rint((np.asarray(y) - ymin) / cell - candidate))), None)
    if offset is None:
        raise ValueError("Wave fgout grid is not aligned with the force-dry mask.")
    columns = np.rint((np.asarray(x) - xmin) / cell - offset).astype(int)
    rows = np.rint((np.asarray(y) - ymin) / cell - offset).astype(int)
    if (np.any(columns < 0) or np.any(columns >= ncols) or np.any(rows < 0) or np.any(rows >= nrows)):
        raise ValueError("Wave fgout grid is not aligned with the force-dry mask.")
    return np.flipud(raw)[np.ix_(rows, columns)] == 0.0


def materialize_wave_diagnostics(discovery: WaveDiscovery) -> dict:
    """Create the lake-water-volume history CSV product."""
    _, x, y, initial_depth, _bed, _hu, _hv = load_wave_frame(discovery, discovery.frames[0].frame_id)
    wet_mask = _mask(discovery.root, x, y)
    geometry = geometry_from_axes(x, y); area = geometry.dx * geometry.dy
    times, volumes = [], []
    for descriptor in discovery.frames:
        time, fx, fy, depth, _bed, _hu, _hv = load_wave_frame(discovery, descriptor.frame_id)
        if geometry_from_axes(fx, fy) != geometry:
            raise ValueError("Wave fgout frames are inconsistent.")
        times.append(time); volumes.append(float(np.sum(depth[wet_mask]) * area))
    result = discovery.root / WAVE_RESULT_DIRECTORY; result.mkdir(exist_ok=True)
    volume_path = result / "lake_volume_history.csv"
    with volume_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(["simulation_time_s", "lake_water_volume_m3"])
        writer.writerows((f"{time:.12g}", f"{value:.12g}") for time, value in zip(times, volumes))
    return {"volume_csv": str(volume_path)}


def read_wave_gauges(discovery: WaveDiscovery) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Return configured GeoClaw gauge depth histories from raw gauge files."""
    config = yaml.safe_load((discovery.root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    gauges = config.get("gauges", {})
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for key, details in gauges.items():
        if key == "gauge_recording":
            continue
        path = discovery.output / f"gauge{int(key) + 1:05d}.txt"
        if not path.is_file():
            continue
        raw = np.atleast_2d(np.loadtxt(path, comments="#"))
        if raw.shape[1] < 3:
            continue
        result[str(details.get("name") or f"Gauge {int(key) + 1}")] = (raw[:, 1], raw[:, 2])
    return result


def wave_temporal_values(variable: str, bed: np.ndarray, depth: np.ndarray, initial_surface: np.ndarray) -> np.ndarray:
    """Return the physical WAVE quantity represented by one temporal band."""
    if variable == "depth":
        return np.asarray(depth, dtype=float)
    if variable == "water_elevation":
        return np.where(np.asarray(depth, dtype=float) >= .0001, np.asarray(bed, dtype=float) + depth, np.nan)
    if variable == "surface_displacement":
        return (np.asarray(bed, dtype=float) + depth) - np.asarray(initial_surface, dtype=float)
    raise ValueError("Unsupported Wave temporal variable.")


def materialize_wave_results(discovery: WaveDiscovery, variable: str = "surface_displacement") -> dict:
    if variable not in {"depth", "water_elevation", "surface_displacement"}:
        raise ValueError("Unsupported Wave temporal variable.")
    result = discovery.root / WAVE_RESULT_DIRECTORY; result.mkdir(exist_ok=True)
    _, x, y, initial_depth, initial_bed, _hu, _hv = load_wave_frame(discovery, discovery.frames[0].frame_id)
    geometry = geometry_from_axes(x, y)
    band_records = temporal_band_records(
        discovery.temporal_origin_iso, [frame.time_seconds for frame in discovery.frames],
    )
    initial_surface = initial_bed + initial_depth
    temporal_path = result / f"temporal_{variable}.tif"
    partial = result / f".temporal_{variable}.partial.tif"
    dataset = _create_geotiff(partial, len(discovery.frames), geometry, discovery.crs_authid)
    dataset.SetMetadataItem("AVAC_FIRST_FRAME_START_ISO8601", str(band_records[0]["start_iso"]))
    dataset.SetMetadataItem("AVAC_TEMPORAL_AXIS", "elapsed simulation seconds")
    crest = np.full_like(initial_depth, -np.inf); drawdown = np.full_like(initial_depth, np.inf)
    minimum, maximum = np.inf, -np.inf
    try:
        for band, descriptor in enumerate(discovery.frames, 1):
            time, fx, fy, depth, bed, _hu, _hv = load_wave_frame(discovery, descriptor.frame_id)
            if not np.isclose(time, descriptor.time_seconds) or geometry_from_axes(fx, fy) != geometry:
                raise ValueError("Wave fgout frames are inconsistent.")
            displacement = wave_temporal_values("surface_displacement", bed, depth, initial_surface)
            # Water elevation is eta = B + h on wet cells only. Dry cells are
            # NoData, so neither the map nor its legend can show dry terrain
            # as a water surface.
            values = wave_temporal_values(variable, bed, depth, initial_surface)
            record = band_records[band - 1]
            _write_band(
                dataset, band, values, geometry,
                description=f"Wave {variable.replace('_', ' ').title()} at simulation {format_simulation_seconds(time)}",
                metadata={
                    "AVAC_SIMULATION_TIME_SECONDS": f"{time:.17g}",
                    "AVAC_TEMPORAL_START_ISO8601": str(record["start_iso"]),
                    "AVAC_TEMPORAL_END_ISO8601": str(record["end_iso"]),
                },
            )
            crest = np.maximum(crest, displacement); drawdown = np.minimum(drawdown, displacement)
            finite_values = values[np.isfinite(values)]
            if finite_values.size:
                minimum = min(minimum, float(np.min(finite_values)))
                maximum = max(maximum, float(np.max(finite_values)))
    except Exception:
        # A partial raster cannot be selected by QGIS and should never be
        # mistaken for a completed product on the next attempt.
        raise
    finally:
        if dataset is not None:
            dataset.FlushCache(); dataset = None
    try:
        os.replace(partial, temporal_path)
    except OSError as exc:
        raise RuntimeError(f"Could not finalize Wave temporal raster {temporal_path.name}: {exc}") from exc
    for name, values in (("maximum_surface_rise", np.maximum(crest, 0.0)), ("maximum_surface_drawdown", np.maximum(-drawdown, 0.0))):
        dataset = _create_geotiff(result / f"{name}.tif", 1, geometry, discovery.crs_authid); _write_band(dataset, 1, values, geometry); dataset.FlushCache(); dataset = None
    if variable == "surface_displacement":
        absolute = max(abs(minimum), abs(maximum)) if np.isfinite(minimum) and np.isfinite(maximum) else 0.0
        limits = [-absolute, absolute]
    elif variable == "depth":
        limits = [0.0, max(0.0, maximum if np.isfinite(maximum) else 0.0)]
    else:
        limits = [minimum, maximum] if np.isfinite(minimum) and np.isfinite(maximum) else [0.0, 1.0]
    payload = {"format": WAVE_RESULT_FORMAT, "source": str(discovery.root), "simulation_time_seconds": [f.time_seconds for f in discovery.frames],
               "temporal_origin_iso": discovery.temporal_origin_iso, "temporal_axis_epoch": discovery.temporal_origin_iso,
               "temporal_band_ranges": band_records,
               "static": {"maximum_surface_rise": {"path": "maximum_surface_rise.tif", "unit": "m", "range": [0., float(np.nanmax(np.maximum(crest, 0.0)))]}, "maximum_surface_drawdown": {"path": "maximum_surface_drawdown.tif", "unit": "m", "range": [0., float(np.nanmax(np.maximum(-drawdown, 0.0)))]}},
               "temporal": {variable: {"path": temporal_path.name, "unit": "m", "range": limits, "band_ranges": band_records}}}
    manifest_path = result / WAVE_RESULT_MANIFEST
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    if (
        isinstance(previous, dict)
        and previous.get("format") == WAVE_RESULT_FORMAT
        and previous.get("source") == payload["source"]
        and previous.get("simulation_time_seconds") == payload["simulation_time_seconds"]
        and isinstance(previous.get("temporal"), dict)
    ):
        payload["temporal"] = {**previous["temporal"], **payload["temporal"]}
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
