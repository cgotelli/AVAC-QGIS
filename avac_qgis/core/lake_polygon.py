"""Derive a persistent lake polygon from a DEM, water level, and seed point."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .preprocessing import AvacRaster


def seed_cell(raster: AvacRaster, x: float, y: float) -> tuple[int, int]:
    """Return the south-to-north DEM cell containing ``(x, y)``."""
    try:
        xmin, xmax = float(raster.metadata["xmin"]), float(raster.metadata["xmax"])
        ymin, ymax = float(raster.metadata["ymin"]), float(raster.metadata["ymax"])
        cell = float(raster.metadata["cellsize"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("DEM grid metadata is incomplete.") from exc
    if not np.isfinite(cell) or cell <= 0.0:
        raise ValueError("DEM cell size must be positive and finite.")
    if not (xmin <= float(x) < xmax and ymin <= float(y) < ymax):
        raise ValueError("The selected point is outside the terrain DEM.")
    column = int(np.floor((float(x) - xmin) / cell))
    row = int(np.floor((float(y) - ymin) / cell))
    row = min(max(row, 0), raster.z.shape[0] - 1)
    column = min(max(column, 0), raster.z.shape[1] - 1)
    return row, column


def connected_lake_mask(
    elevation: np.ndarray,
    seed: tuple[int, int],
    water_level: float,
    *,
    require_closed: bool = True,
) -> np.ndarray:
    """Return the four-connected cells at or below ``water_level``.

    Four-neighbour connectivity matches the north/south/east/west faces of
    the finite-volume grid.  A run-length flood fill keeps this operation
    linear and responsive for large high-resolution reservoir DEMs without
    introducing a SciPy dependency.
    """
    values = np.asarray(elevation, dtype=float)
    if values.ndim != 2 or not values.size:
        raise ValueError("Terrain DEM must be a non-empty two-dimensional grid.")
    level = float(water_level)
    if not np.isfinite(level):
        raise ValueError("Water-surface elevation must be finite.")
    row, column = int(seed[0]), int(seed[1])
    if row < 0 or row >= values.shape[0] or column < 0 or column >= values.shape[1]:
        raise ValueError("Lake seed cell is outside the terrain grid.")
    eligible = np.isfinite(values) & (values <= level)
    if not eligible[row, column]:
        selected = values[row, column]
        detail = "NoData" if not np.isfinite(selected) else f"{selected:g} m"
        raise ValueError(
            f"The selected DEM cell is {detail}, above the {level:g} m water level. "
            "Click inside the inundated lake basin."
        )

    connected = np.zeros(values.shape, dtype=bool)
    stack: list[tuple[int, int]] = [(row, column)]
    rows, columns = values.shape
    while stack:
        current_row, current_column = stack.pop()
        if connected[current_row, current_column] or not eligible[current_row, current_column]:
            continue
        left = current_column
        while left > 0 and eligible[current_row, left - 1] and not connected[current_row, left - 1]:
            left -= 1
        right = current_column
        while right + 1 < columns and eligible[current_row, right + 1] and not connected[current_row, right + 1]:
            right += 1
        connected[current_row, left:right + 1] = True
        for neighbour_row in (current_row - 1, current_row + 1):
            if neighbour_row < 0 or neighbour_row >= rows:
                continue
            candidates = eligible[neighbour_row, left:right + 1] & ~connected[neighbour_row, left:right + 1]
            starts = np.flatnonzero(candidates & np.r_[True, ~candidates[:-1]])
            stack.extend((neighbour_row, left + int(offset)) for offset in starts)

    if not np.any(connected):
        raise ValueError("The selected point produced no connected lake cells.")
    if require_closed and (
        connected[0].any() or connected[-1].any()
        or connected[:, 0].any() or connected[:, -1].any()
    ):
        raise ValueError(
            "The connected water body reaches the terrain DEM edge, so its contour is not closed. "
            "Use a terrain DEM that fully encloses the water body, or lower the water level."
        )
    return connected


def write_lake_polygon(
    destination: str | Path,
    raster: AvacRaster,
    mask: np.ndarray,
    *,
    water_level: float,
    seed_x: float,
    seed_y: float,
) -> Path:
    """Polygonize a connected DEM mask into a persistent GeoPackage."""
    from osgeo import gdal, ogr, osr

    destination = Path(destination).expanduser().resolve()
    values = np.asarray(mask, dtype=np.uint8)
    if values.shape != np.asarray(raster.z).shape or not np.any(values):
        raise ValueError("Lake mask must match the DEM and contain at least one cell.")
    if destination.exists():
        raise ValueError(f"Refusing to overwrite an existing derived lake polygon: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cell = float(raster.metadata["cellsize"])
    xmin = float(raster.metadata["xmin"])
    ymax = float(raster.metadata["ymax"])

    source = gdal.GetDriverByName("MEM").Create("", values.shape[1], values.shape[0], 1, gdal.GDT_Byte)
    if source is None:
        raise RuntimeError("GDAL could not create the lake-mask raster.")
    source.SetGeoTransform((xmin, cell, 0.0, ymax, 0.0, -cell))
    spatial_reference = osr.SpatialReference()
    if spatial_reference.SetFromUserInput(str(raster.crs_authid)) != 0:
        raise ValueError("Terrain DEM CRS cannot be written to the lake polygon.")
    source.SetProjection(spatial_reference.ExportToWkt())
    band = source.GetRasterBand(1)
    band.WriteArray(np.flipud(values))

    driver = ogr.GetDriverByName("GPKG")
    if driver is None:
        raise RuntimeError("GDAL has no GeoPackage vector driver.")
    dataset = driver.CreateDataSource(str(destination))
    if dataset is None:
        raise ValueError(f"Could not create the derived lake polygon: {destination}")
    layer = dataset.CreateLayer("lake", srs=spatial_reference, geom_type=ogr.wkbPolygon)
    for name, field_type in (
        ("inside", ogr.OFTInteger), ("water_m", ogr.OFTReal),
        ("seed_x", ogr.OFTReal), ("seed_y", ogr.OFTReal), ("cells", ogr.OFTInteger64),
    ):
        layer.CreateField(ogr.FieldDefn(name, field_type))
    if gdal.Polygonize(band, band, layer, 0, []) != 0 or layer.GetFeatureCount() != 1:
        dataset = None
        source = None
        raise ValueError("GDAL could not create one connected polygon from the selected lake basin.")
    feature = layer.GetNextFeature()
    feature.SetField("water_m", float(water_level))
    feature.SetField("seed_x", float(seed_x))
    feature.SetField("seed_y", float(seed_y))
    feature.SetField("cells", int(np.count_nonzero(values)))
    if layer.SetFeature(feature) != 0:
        dataset = None
        source = None
        raise ValueError("Could not store the derived lake-polygon attributes.")
    feature = None
    dataset = None
    source = None
    return destination
