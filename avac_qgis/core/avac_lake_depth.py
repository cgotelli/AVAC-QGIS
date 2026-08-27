"""Derived AVAC depth product with the prepared WAVE lake area set to zero.

The source AVAC GeoTIFF is never changed.  This module creates a second,
multi-band GeoTIFF in the associated WAVE scenario so an AVAC overlay can be
shown or exported without avalanche depth appearing inside the lake where the
WAVE solution represents the water response.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from .results import RESULT_DIRECTORY, ResultDiscovery, discover_results, materialize_results
from .wave_project import WAVE_MARKER
from .wave_results import WAVE_RESULT_DIRECTORY


AVAC_LAKE_DEPTH_FORMAT = 1
AVAC_LAKE_DEPTH_MANIFEST = "avac_lake_depth.json"
AVAC_LAKE_DEPTH_FILENAME = "temporal_avac_depth_lake_zero.tif"


def _read_mapping(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{description} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} is not a mapping: {path}")
    return payload


def wave_source_avac_run(wave_root: str | Path) -> Path:
    """Return the AVAC run explicitly linked to a prepared WAVE scenario."""
    root = Path(wave_root).expanduser().resolve()
    marker = _read_mapping(root / WAVE_MARKER, "WAVE scenario marker")
    source = str(marker.get("source_avac_run") or "").strip()
    if not source:
        raise ValueError("The selected WAVE scenario does not identify its source AVAC run.")
    avac_root = Path(source).expanduser().resolve()
    if not avac_root.is_dir():
        raise ValueError(f"The WAVE scenario's source AVAC run is unavailable: {avac_root}")
    return avac_root


def _file_signature(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        try:
            stat = path.stat()
        except OSError as exc:
            raise ValueError(f"Required source file is unavailable: {path}") from exc
        digest.update(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _product_path(root: Path, path_value: object) -> Path:
    path = Path(str(path_value))
    return path if path.is_absolute() else root / path


def _prepared_lake_vector(wave_root: Path):
    """Polygonize the prepared WAVE wet mask with the solver grid geometry.

    The mask is the exact lake footprint used by the prepared WAVE model.  It
    deliberately supports old scenarios whose mask still includes a one-cell
    topography halo.
    """
    from osgeo import gdal, ogr

    try:
        config = yaml.safe_load((wave_root / "impulse_configuration.yaml").read_text(encoding="utf-8")) or {}
        lake, computation = config["lake"], config["computation"]
        cell = float(computation["cell_size"])
        xmin, xmax = float(lake["xmin"]), float(lake["xmax"])
        ymin, ymax = float(lake["ymin"]), float(lake["ymax"])
        mask_name = str(config["topo_files"]["mask_raster"])
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError("The prepared WAVE scenario has no usable lake-grid definition.") from exc
    if not np.isfinite(cell) or cell <= 0.0:
        raise ValueError("The prepared WAVE cell size is invalid.")
    nx, ny = int(round((xmax - xmin) / cell)), int(round((ymax - ymin) / cell))
    if nx < 1 or ny < 1:
        raise ValueError("The prepared WAVE lake-grid extent is invalid.")
    mask_path = wave_root / "Topo" / mask_name
    try:
        raw = np.atleast_2d(np.loadtxt(mask_path, skiprows=6))
    except (OSError, ValueError) as exc:
        raise ValueError(f"The prepared WAVE lake mask is unreadable: {mask_path}") from exc
    if raw.shape == (ny + 2, nx + 2):
        raw = raw[1:-1, 1:-1]
    if raw.shape != (ny, nx):
        raise ValueError(
            f"Prepared WAVE lake-mask dimensions {raw.shape} do not match its solver grid {(ny, nx)}."
        )
    wet = np.asarray(raw == 0.0, dtype=np.uint8)
    if not np.any(wet):
        raise ValueError("The prepared WAVE lake mask has no wet cells.")

    raster = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Byte)
    if raster is None:
        raise RuntimeError("GDAL could not create an in-memory WAVE lake mask.")
    raster.SetGeoTransform((xmin, cell, 0.0, ymax, 0.0, -cell))
    band = raster.GetRasterBand(1)
    band.WriteArray(wet)
    vector_source = ogr.GetDriverByName("MEM").CreateDataSource("avac_lake_depth_mask")
    vector_layer = vector_source.CreateLayer("lake", geom_type=ogr.wkbPolygon)
    vector_layer.CreateField(ogr.FieldDefn("inside", ogr.OFTInteger))
    # Use the same wet mask as source and validity mask: cells outside the
    # prepared WAVE lake are excluded rather than becoming a second polygon.
    gdal.Polygonize(band, band, vector_layer, 0, ["8CONNECTED=8"])
    if vector_layer.GetFeatureCount() < 1:
        raise ValueError("The prepared WAVE lake mask could not be polygonized.")
    return vector_source, vector_layer, mask_path


def _write_lake_zero_product(
    source_path: Path,
    wave_root: Path,
    destination: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[float], int]:
    """Copy an AVAC temporal product and set all lake-intersecting cells to 0."""
    from osgeo import gdal

    source = gdal.Open(str(source_path), gdal.GA_ReadOnly)
    if source is None or source.RasterCount < 1:
        raise ValueError(f"AVAC temporal depth product is unreadable: {source_path}")
    vector_source = vector_layer = mask = target = None
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        vector_source, vector_layer, _mask_path = _prepared_lake_vector(wave_root)
        mask = gdal.GetDriverByName("MEM").Create("", source.RasterXSize, source.RasterYSize, 1, gdal.GDT_Byte)
        if mask is None:
            raise RuntimeError("GDAL could not create an AVAC-grid lake mask.")
        mask.SetGeoTransform(source.GetGeoTransform())
        mask.SetProjection(source.GetProjection())
        gdal.RasterizeLayer(mask, [1], vector_layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
        inside = np.asarray(mask.GetRasterBand(1).ReadAsArray(), dtype=bool)
        if not np.any(inside):
            raise ValueError("The prepared WAVE lake footprint does not overlap the AVAC depth grid.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        target = gdal.GetDriverByName("GTiff").CreateCopy(
            str(temporary), source, strict=0,
            options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES", "INTERLEAVE=BAND"],
        )
        if target is None:
            raise RuntimeError(f"GDAL could not create derived WAVE Snow Depth Outside Lake product: {destination}")
        maximums: list[float] = []
        for index in range(1, target.RasterCount + 1):
            if cancelled and cancelled():
                raise InterruptedError("WAVE Snow Depth Outside Lake preparation cancelled.")
            band = target.GetRasterBand(index)
            values = np.asarray(band.ReadAsArray())
            values[inside] = 0.0
            band.WriteArray(values)
            nodata = band.GetNoDataValue()
            valid = values if nodata is None else values[~np.isclose(values, float(nodata))]
            maximums.append(float(np.nanmax(valid)) if valid.size else 0.0)
            band.FlushCache()
            if progress:
                progress(55 + int(45 * index / target.RasterCount))
        target.FlushCache()
        target = None
        source = None
        os.replace(temporary, destination)
        return maximums, int(np.count_nonzero(inside))
    finally:
        if target is not None:
            target = None
        source = None
        mask = None
        vector_layer = None
        vector_source = None
        temporary.unlink(missing_ok=True)


def _cached_product(root: Path, signature: str, expected_bands: int) -> dict[str, Any] | None:
    manifest_path = root / WAVE_RESULT_DIRECTORY / AVAC_LAKE_DEPTH_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    product = payload.get("temporal", {}).get("depth") if isinstance(payload, dict) else None
    if payload.get("format") != AVAC_LAKE_DEPTH_FORMAT or payload.get("source_signature") != signature or not isinstance(product, dict):
        return None
    path = root / WAVE_RESULT_DIRECTORY / str(product.get("path", ""))
    try:
        from osgeo import gdal
        dataset = gdal.Open(str(path))
        valid = bool(dataset and dataset.RasterCount == expected_bands)
        dataset = None
    except Exception:  # noqa: BLE001
        valid = False
    return payload if valid else None


def materialize_avac_lake_depth(
    avac_root: str | Path,
    wave_root: str | Path,
    *,
    fgout_grid: int = 1,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ResultDiscovery, dict[str, Any]]:
    """Create/reuse the lake-zero AVAC depth product for one linked completed scenario."""
    avac_root, wave_root = Path(avac_root).expanduser().resolve(), Path(wave_root).expanduser().resolve()
    linked_root = wave_source_avac_run(wave_root)
    if linked_root != avac_root:
        raise ValueError("Select the WAVE scenario prepared from the selected AVAC completed run.")
    if cancelled and cancelled():
        raise InterruptedError("WAVE Snow Depth Outside Lake preparation cancelled.")
    if progress:
        progress(2)
    discovery = discover_results(avac_root, fgout_grid)
    wave_marker = _read_mapping(wave_root / WAVE_MARKER, "WAVE scenario marker")
    wave_crs = str(wave_marker.get("crs_authid") or "").strip()
    if wave_crs and wave_crs != discovery.crs_authid:
        raise ValueError(
            "The selected WAVE scenario and AVAC results use different CRS definitions; reprepare the WAVE scenario."
        )
    source_manifest = materialize_results(
        discovery, ("depth",),
        progress=(lambda value: progress(int(0.55 * value))) if progress else None,
        cancelled=cancelled,
    )
    source_product = source_manifest["temporal"].get(f"fgout{discovery.fgout_grid:04d}_depth")
    if not isinstance(source_product, dict):
        raise ValueError("AVAC depth could not be materialized for the selected completed run.")
    source_path = _product_path(discovery.run_root / RESULT_DIRECTORY, source_product["path"])
    mask_path = wave_root / "Topo" / str(
        (yaml.safe_load((wave_root / "impulse_configuration.yaml").read_text(encoding="utf-8")) or {})
        .get("topo_files", {}).get("mask_raster", "mask.asc")
    )
    signature = _file_signature([source_path, mask_path, wave_root / "impulse_configuration.yaml", wave_root / WAVE_MARKER])
    cached = _cached_product(wave_root, signature, len(discovery.frames))
    if cached is not None:
        if progress:
            progress(100)
        return discovery, cached

    result_root = wave_root / WAVE_RESULT_DIRECTORY
    destination = result_root / AVAC_LAKE_DEPTH_FILENAME
    maximums, zeroed_cells = _write_lake_zero_product(
        source_path, wave_root, destination, progress=progress, cancelled=cancelled,
    )
    times = [float(frame.time_seconds) for frame in discovery.frames]
    product = {
        "path": AVAC_LAKE_DEPTH_FILENAME,
        "unit": "m",
        "range": [0.0, max(maximums, default=0.0)],
        "band_ranges": source_product.get("band_ranges", []),
        "fgout_grid": discovery.fgout_grid,
        "prepared_lake_mask": str(mask_path.relative_to(wave_root)),
        "zeroed_avac_cells": zeroed_cells,
    }
    payload = {
        "format": AVAC_LAKE_DEPTH_FORMAT,
        "source_avac_run": str(avac_root),
        "source_wave_run": str(wave_root),
        "source_signature": signature,
        "crs_authid": discovery.crs_authid,
        "temporal_origin_iso": source_manifest.get("temporal_origin_iso"),
        "simulation_time_seconds": times,
        "temporal": {"depth": product},
    }
    result_root.mkdir(parents=True, exist_ok=True)
    (result_root / AVAC_LAKE_DEPTH_MANIFEST).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if progress:
        progress(100)
    return discovery, payload
