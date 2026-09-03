"""Scientific-input preparation for the AVAC4QGIS workflow.

The routines retain AVAC's coordinate arrays, north/south handling, and qinit
traversal. QGIS supplies raster values and polygon geometries; release depth is
initialized as a cell average using fractional polygon coverage so boundaries
that do not follow the DEM grid do not create a resolution-dependent volume.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import yaml
from matplotlib.path import Path as MplPath

from .configuration import (
    RELEASE_DEPTH_DEFAULTS,
    apply_controlled_values,
    load_complete_configuration,
    validate_grid_contract,
    validate_release_depth_parameters,
)


QINIT_BINARY_MAGIC = b"AVACQIN1"
QINIT_BINARY_HEADER = struct.Struct("<8sqqii4d")
QINIT_BINARY_NAME = "init.avacbin"
# A grid count is an integer quantity.  Keep this criterion aligned with
# ``setrun._whole_cell_count`` and ``validate_grid_contract`` so a prepared
# QGIS configuration cannot pass the frontend only to fail when the solver
# reads the same physical bounds.
GRID_COUNT_TOLERANCE = 1.0e-8


class PreparationCancelled(InterruptedError):
    """Raised when a QGIS preparation task is cancelled at a safe checkpoint."""


@dataclass(frozen=True)
class AvacRaster:
    """A regular raster whose axes locate cell centres.

    ``metadata[\"xmin\"]``/``xmax`` and ``ymin``/``ymax`` are the outer
    cell edges.  Keeping those two coordinate conventions explicit is
    important here: GeoClaw shifts topotype-3 ``xllcorner``/``yllcorner``
    values to centres, and AVAC's qinit readers likewise locate each supplied
    value at its listed centre.
    """

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray  # South-to-north, matching gui.services.read_ascii_raster.
    metadata: dict[str, float | int]
    crs_authid: str
    band: int


@dataclass(frozen=True)
class PreparedInputs:
    run_root: Path
    avac_dir: Path
    topo_path: Path
    init_path: Path
    configuration_path: Path
    mask: np.ndarray
    coverage: np.ndarray
    depth: np.ndarray


def _cell_centres(lower_edge: float, count: int, cell_size: float) -> np.ndarray:
    """Return the centres of ``count`` contiguous cells from an outer edge."""
    return float(lower_edge) + (np.arange(int(count), dtype=float) + 0.5) * float(cell_size)


def _qgis_crs_identifier(crs) -> str:
    """Return an authority id when available, otherwise a valid local CRS WKT.

    Some controlled laboratory/benchmark datasets use a Cartesian meter grid
    without a public EPSG authority.  QGIS still validates such a CRS, and
    GDAL accepts its WKT when writing derived products.  Retaining that WKT
    avoids assigning a false geographic reference just to satisfy preparation.
    """
    authid = str(crs.authid() or "").strip()
    if authid:
        return authid
    wkt = str(crs.toWkt() or "").strip()
    if wkt:
        return wkt
    raise ValueError("DEM CRS has no usable authority identifier or WKT.")


def raster_from_qgis_layer(layer, band: int = 1, extent=None, grid_cell_size: float | None = None) -> AvacRaster:
    """Read a QGIS raster provider into the standalone GUI's AVAC grid layout."""
    if layer is None or not layer.isValid():
        raise ValueError("Select a valid DEM raster layer.")
    if not layer.crs().isValid():
        raise ValueError("DEM must have a valid CRS.")
    from qgis.core import Qgis

    provider = layer.dataProvider()
    width, height = int(layer.width()), int(layer.height())
    if width <= 0 or height <= 0:
        raise ValueError("DEM has no raster cells.")
    if band < 1 or band > provider.bandCount():
        raise ValueError(f"DEM band {band} is unavailable.")

    source_extent = layer.extent()
    if extent is None:
        read_extent = source_extent
    else:
        read_extent = source_extent.intersect(extent)
        if read_extent.isNull() or read_extent.width() <= 0 or read_extent.height() <= 0:
            raise ValueError("Requested DEM preview extent does not overlap the selected raster layer.")
    pixel_x = source_extent.width() / width
    pixel_y = source_extent.height() / height
    if grid_cell_size is None:
        if extent is not None:
            width = max(1, int(round(read_extent.width() / pixel_x)))
            height = max(1, int(round(read_extent.height() / pixel_y)))
    else:
        requested_cell = float(grid_cell_size)
        if not np.isfinite(requested_cell) or requested_cell <= 0.0:
            raise ValueError("Requested raster grid cell size must be positive and finite.")
        if requested_cell + max(pixel_x, pixel_y, 1.0) * 1e-8 < max(pixel_x, pixel_y):
            raise ValueError("Requested raster grid cannot be finer than the source DEM resolution.")
        intervals_x = read_extent.width() / requested_cell
        intervals_y = read_extent.height() / requested_cell
        if not np.isclose(intervals_x, round(intervals_x), rtol=0.0, atol=1e-8) or not np.isclose(intervals_y, round(intervals_y), rtol=0.0, atol=1e-8):
            raise ValueError("Requested raster extent must span a whole number of output grid cells.")
        # A provider block contains one value per output *cell*, not nodes.
        # Its N values over an N-cell extent therefore lie at the N cell
        # centres. This also keeps a requested grid size valid when the full
        # source extent, rather than a cropped window, is read.
        width, height = int(round(intervals_x)), int(round(intervals_y))
        if width < 1 or height < 1:
            raise ValueError("Requested raster extent must contain at least one output grid cell.")
    block = provider.block(band, read_extent, width, height)
    # QgsRasterBlock rows are north-to-south.  Deliberately read through QGIS,
    # then flip to reproduce the legacy ASCII reader's south-to-north array.
    qgis_dtypes = {
        Qgis.DataType.Byte: np.uint8, Qgis.DataType.UInt16: np.uint16, Qgis.DataType.Int16: np.int16,
        Qgis.DataType.UInt32: np.uint32, Qgis.DataType.Int32: np.int32, Qgis.DataType.Float32: np.float32,
        Qgis.DataType.Float64: np.float64,
    }
    source_dtype = qgis_dtypes.get(block.dataType())
    raw = bytes(block.data())
    if source_dtype is not None and len(raw) == width * height * np.dtype(source_dtype).itemsize:
        north_to_south = np.frombuffer(raw, dtype=source_dtype).astype(float, copy=True).reshape((height, width))
    else:  # Defensive fallback for uncommon provider data types.
        north_to_south = np.fromiter(
            (block.value(row, column) for row in range(height) for column in range(width)),
            dtype=float, count=width * height,
        ).reshape((height, width))
    nodata = provider.sourceNoDataValue(band) if provider.sourceHasNoDataValue(band) else -9999.0
    if np.isfinite(nodata):
        north_to_south[np.isclose(north_to_south, nodata)] = np.nan
    north_to_south[~np.isfinite(north_to_south)] = np.nan

    xmin, xmax, ymin, ymax = read_extent.xMinimum(), read_extent.xMaximum(), read_extent.yMinimum(), read_extent.yMaximum()
    # QGIS reports outer raster edges, whereas AVAC qinit values are attached
    # to cell centres. GeoClaw likewise shifts a topotype-3 ``xllcorner`` to
    # its first terrain-sample centre, but later interpolates those samples as
    # nodes; ``prepare_inputs`` supplies its terrain-only edge halo separately.
    # Keep the original centre axes here for release rasterization and qinit
    # output. Endpoint axes would make qinit both half a cell shifted and
    # slightly stretched relative to the QGIS cells.
    cell_x, cell_y = (xmax - xmin) / width, (ymax - ymin) / height
    if not np.isclose(cell_x, cell_y, rtol=0.0, atol=max(abs(cell_x), abs(cell_y), 1.0) * 1e-8):
        layer_name = str(layer.name() or "selected DEM")
        raise ValueError(
            f"DEM '{layer_name}' cells must be square for AVAC terrain input "
            f"(X resolution {cell_x:.12g}, Y resolution {cell_y:.12g})."
        )
    output_cell = float(cell_x)
    x = _cell_centres(xmin, width, output_cell)
    y = _cell_centres(ymin, height, output_cell)
    metadata: dict[str, float | int] = {
        "xmin": float(xmin), "xmax": float(xmax), "ymin": float(ymin), "ymax": float(ymax),
        "ncols": width, "nrows": height,
        "cellsize": output_cell,
        "nodata_value": float(nodata),
    }
    return AvacRaster(x, y, north_to_south[::-1, :], metadata, _qgis_crs_identifier(layer.crs()), band)


def crop_raster_to_rings_extent(raster: AvacRaster, rings) -> AvacRaster:
    """Return the grid-aligned bounding rectangle of an optional domain mask.

    AVAC's terrain solver is rectangular, so a polygon reduces the numerical
    domain through its enclosing grid-aligned rectangle.  The polygon itself
    remains a deliberate user selection rather than a silently rasterized
    physical barrier.
    """
    vertices = [ring for exterior, holes in rings for ring in (exterior, *holes)]
    if not vertices:
        raise ValueError("Calculation-domain layer has no usable polygon geometry.")
    points = np.vstack(vertices)
    cell = float(raster.metadata["cellsize"])
    xmin0, ymin0 = float(raster.metadata["xmin"]), float(raster.metadata["ymin"])
    ix0 = max(0, int(np.floor((float(np.min(points[:, 0])) - xmin0) / cell)))
    ix1 = min(int(raster.metadata["ncols"]), int(np.ceil((float(np.max(points[:, 0])) - xmin0) / cell)) + 1)
    iy0 = max(0, int(np.floor((float(np.min(points[:, 1])) - ymin0) / cell)))
    iy1 = min(int(raster.metadata["nrows"]), int(np.ceil((float(np.max(points[:, 1])) - ymin0) / cell)) + 1)
    if ix1 - ix0 < 3 or iy1 - iy0 < 3:
        raise ValueError("Calculation domain is too small; it must cover at least a 3 by 3 DEM-cell rectangle.")
    values = raster.z[iy0:iy1, ix0:ix1]
    metadata = dict(raster.metadata)
    xmin, ymin = xmin0 + ix0 * cell, ymin0 + iy0 * cell
    metadata.update({"xmin": xmin, "xmax": xmin + (ix1 - ix0) * cell,
                     "ymin": ymin, "ymax": ymin + (iy1 - iy0) * cell,
                     "ncols": ix1 - ix0, "nrows": iy1 - iy0})
    return AvacRaster(raster.x[ix0:ix1], raster.y[iy0:iy1], values, metadata, raster.crs_authid, raster.band)


def configuration_for_raster(configuration: dict[str, Any], raster: AvacRaster) -> dict[str, Any]:
    """Return a configuration whose computational domain is covered by ``raster``.

    A QGIS raster represents a rectangular set of physical cells, so AVAC's
    computational domain must retain all of its outer edges.  GeoClaw reads
    topotype-3 values as nodal samples after shifting an ESRI ``xllcorner`` to
    its first sample centre.  :func:`prepare_inputs` therefore supplies an
    extra, topography-only edge halo; it never shortens the solver domain or
    the cell-centred qinit/release grid to compensate for that reader
    convention.

    The selected terrain extent must contain a whole number of computational
    cells.  Extending a non-divisible raster would create a solver strip with
    extrapolated terrain but no matching QGIS qinit cells, while silently
    cropping it loses release mass.  Reject that ambiguity explicitly.
    """
    result = deepcopy(configuration)
    metadata = raster.metadata
    try:
        source_cell = float(metadata["cellsize"])
        computational_cell = float(result["computation"]["cell_size"])
        ncols, nrows = int(metadata["ncols"]), int(metadata["nrows"])
        xmin, xmax = float(metadata["xmin"]), float(metadata["xmax"])
        ymin, ymax = float(metadata["ymin"]), float(metadata["ymax"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Cannot derive an AVAC domain from the selected DEM: {exc}") from exc
    if not np.isfinite(source_cell) or source_cell <= 0 or not np.isfinite(computational_cell) or computational_cell <= 0:
        raise ValueError("DEM and computational cell sizes must be positive finite values.")
    if ncols < 1 or nrows < 1:
        raise ValueError("Selected DEM must contain at least one row and one column.")
    if not all(np.isfinite(value) for value in (xmin, xmax, ymin, ymax)):
        raise ValueError("Selected DEM outer extent must contain finite coordinates.")
    if (
        not np.isclose((xmax - xmin) / source_cell, ncols, rtol=0.0, atol=GRID_COUNT_TOLERANCE)
        or not np.isclose((ymax - ymin) / source_cell, nrows, rtol=0.0, atol=GRID_COUNT_TOLERANCE)
    ):
        raise ValueError(
            "Selected DEM edges, dimensions, and cell size do not describe one regular cell-centred grid."
        )
    ratio = computational_cell / source_cell
    cells_per_computation = round(ratio)
    if cells_per_computation < 1 or not np.isclose(ratio, cells_per_computation, rtol=0.0, atol=1e-8):
        raise ValueError(
            "Source DEM cell size must equal or evenly subdivide the computational cell size; "
            "AVAC does not silently resample terrain during preparation."
        )
    if ncols % cells_per_computation or nrows % cells_per_computation:
        raise ValueError(
            f"Selected DEM dimensions ({ncols} x {nrows} cells) must each be divisible by "
            f"{cells_per_computation}, the number of DEM cells per {computational_cell:g} m "
            "computational cell. Crop or regrid the DEM, or choose a compatible computational cell size; "
            "AVAC will not silently crop release cells or extend the solver domain."
        )
    nx, ny = ncols // cells_per_computation, nrows // cells_per_computation
    # GeoClaw FGmax point_style=2 uses the first and last sample coordinates
    # to derive spacing with (n-1).  QGIS also needs two centre coordinates
    # per axis to reconstruct a raster envelope.  Reject a domain that could
    # run the finite-volume solver but cannot produce a valid AVAC result
    # raster through the configured fixed-grid output path.
    if nx < 2 or ny < 2:
        raise ValueError(
            f"Selected DEM ({ncols} x {nrows} cells) is too small for a {computational_cell:g} m AVAC grid. "
            "AVAC fixed-grid results need at least two computational cells on both axes."
        )
    dem_extent = result.get("dem_extent")
    if not isinstance(dem_extent, dict):
        raise ValueError("Configuration is missing its dem_extent mapping.")
    dem_extent.update({
        "xmin": xmin, "xmax": xmax,
        "ymin": ymin, "ymax": ymax,
        # ``setrun.py`` derives Clawpack's grid from the physical span.  Keep
        # these legacy informational fields consistent with that cell count.
        "nbx": nx, "nby": ny,
        "cell_size": computational_cell,
        "nodata_value": float(metadata["nodata_value"]),
    })
    gauges = result.get("gauges")
    if not isinstance(gauges, dict):
        raise ValueError("Configuration is missing its gauges mapping.")
    # Complete Lac_Lachat configurations can contain fixed-coordinate AVAC
    # gauges. AVAC4QGIS has no gauge editor, and each prepared case derives a
    # new domain from the selected DEM, so retaining such coordinates would
    # silently create invalid or misleading output. Preserve the YAML entries
    # for traceability but disable their recording in every plugin-prepared
    # case. Wave gauges are independent and remain part of the Wave workflow.
    gauges["gauge_recording"] = False
    return result


def rings_from_qgis_layer(layer, target_crs) -> list[tuple[np.ndarray, list[np.ndarray]]]:
    """Extract Polygon/MultiPolygon rings in the DEM CRS using an explicit transform."""
    from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject, QgsWkbTypes

    if layer is None or not layer.isValid():
        raise ValueError("Select a valid release polygon layer.")
    if not layer.crs().isValid():
        raise ValueError("Release polygon layer must have a valid CRS.")
    if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.GeometryType.PolygonGeometry:
        raise ValueError("Release layer must contain Polygon or MultiPolygon features.")
    transform = None
    if layer.crs() != target_crs:
        transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance().transformContext())

    result: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry.isNull() or geometry.isEmpty():
            continue
        geometry = QgsGeometry(geometry)
        if transform is not None and geometry.transform(transform) != 0:
            raise ValueError(f"Could not transform release feature {feature.id()} into DEM CRS.")
        polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
        for polygon in polygons:
            if not polygon or len(polygon[0]) < 3:
                continue
            exterior = np.asarray([(point.x(), point.y()) for point in polygon[0]], dtype=float)
            holes = [np.asarray([(point.x(), point.y()) for point in ring], dtype=float) for ring in polygon[1:] if len(ring) >= 3]
            result.append((exterior, holes))
    if not result:
        raise ValueError("Release layer has no valid Polygon or MultiPolygon geometries.")
    return result


def release_mask_from_rings(
    rings: Iterable[tuple[np.ndarray, Sequence[np.ndarray]]], x: np.ndarray, y: np.ndarray,
) -> np.ndarray:
    """Exact standalone-GUI inclusion convention: Matplotlib contains_points."""
    xx, yy = np.meshgrid(x, y)
    points = np.column_stack((xx.ravel(), yy.ravel()))
    inside_any = np.zeros(points.shape[0], dtype=bool)
    for exterior, holes in rings:
        exterior = np.asarray(exterior)
        # A bounding-box prefilter is mathematically exact for this inclusion
        # convention and avoids evaluating millions of known-outside points.
        candidate = (
            (points[:, 0] >= exterior[:, 0].min()) & (points[:, 0] <= exterior[:, 0].max()) &
            (points[:, 1] >= exterior[:, 1].min()) & (points[:, 1] <= exterior[:, 1].max())
        )
        inside = np.zeros(points.shape[0], dtype=bool)
        inside[candidate] = MplPath(exterior).contains_points(points[candidate])
        for hole in holes:
            hole = np.asarray(hole)
            hole_candidate = (
                inside & (points[:, 0] >= hole[:, 0].min()) & (points[:, 0] <= hole[:, 0].max()) &
                (points[:, 1] >= hole[:, 1].min()) & (points[:, 1] <= hole[:, 1].max())
            )
            inside[hole_candidate] &= ~MplPath(hole).contains_points(points[hole_candidate])
        inside_any |= inside
    return inside_any.reshape((y.size, x.size))


def release_coverage_from_rings(
    rings: Iterable[tuple[np.ndarray, Sequence[np.ndarray]]],
    x: np.ndarray,
    y: np.ndarray,
    cell_size: float,
    *,
    subsamples: int = 64,
) -> np.ndarray:
    """Return the area fraction of each DEM cell covered by release polygons.

    A centre-point mask changes the initialized volume whenever a polygon
    boundary is not aligned with the DEM.  This routine instead integrates
    polygon occupancy on a regular subcell grid.  Exterior rings, holes,
    multipart features, and overlaps are combined as a geometric union at
    the sampling points, so the result is bounded by zero and one.

    The calculation is restricted to polygon bounding boxes and processed in
    bounded chunks.  Sixty-four samples per direction make the boundary-area
    error negligible relative to the DEM resolution while keeping input
    preparation independent of optional geometry libraries.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    cell = float(cell_size)
    samples = int(subsamples)
    if x.ndim != 1 or y.ndim != 1 or x.size == 0 or y.size == 0:
        raise ValueError("Release coverage requires non-empty one-dimensional grid axes.")
    if not np.isfinite(cell) or cell <= 0.0:
        raise ValueError("Release coverage requires a positive finite cell size.")
    if samples < 2:
        raise ValueError("Release coverage requires at least two subcell samples per direction.")

    normalized: list[tuple[np.ndarray, list[np.ndarray]]] = []
    candidate = np.zeros((y.size, x.size), dtype=bool)
    half = 0.5 * cell
    for exterior, holes in rings:
        exterior = np.asarray(exterior, dtype=float)
        if exterior.ndim != 2 or exterior.shape[0] < 3 or exterior.shape[1] < 2:
            continue
        hole_arrays = [
            np.asarray(hole, dtype=float)
            for hole in holes
            if np.asarray(hole).ndim == 2 and np.asarray(hole).shape[0] >= 3
        ]
        normalized.append((exterior[:, :2], [hole[:, :2] for hole in hole_arrays]))
        columns = np.flatnonzero(
            (x >= float(np.min(exterior[:, 0])) - half)
            & (x <= float(np.max(exterior[:, 0])) + half)
        )
        rows = np.flatnonzero(
            (y >= float(np.min(exterior[:, 1])) - half)
            & (y <= float(np.max(exterior[:, 1])) + half)
        )
        if columns.size and rows.size:
            candidate[np.ix_(rows, columns)] = True
    if not normalized:
        return np.zeros((y.size, x.size), dtype=float)

    row_indices, column_indices = np.nonzero(candidate)
    coverage = np.zeros((y.size, x.size), dtype=float)
    offsets = ((np.arange(samples, dtype=float) + 0.5) / samples - 0.5) * cell
    offset_x, offset_y = np.meshgrid(offsets, offsets)
    offsets_xy = np.column_stack((offset_x.ravel(), offset_y.ravel()))
    # Keep each point array below roughly one million rows (about 16 MB).
    chunk_cells = max(1, 1_000_000 // offsets_xy.shape[0])

    for start in range(0, row_indices.size, chunk_cells):
        stop = min(start + chunk_cells, row_indices.size)
        rows = row_indices[start:stop]
        columns = column_indices[start:stop]
        centres = np.column_stack((x[columns], y[rows]))
        points = (centres[:, None, :] + offsets_xy[None, :, :]).reshape((-1, 2))
        inside_any = np.zeros(points.shape[0], dtype=bool)
        for exterior, holes in normalized:
            bbox = (
                (points[:, 0] >= float(np.min(exterior[:, 0])))
                & (points[:, 0] <= float(np.max(exterior[:, 0])))
                & (points[:, 1] >= float(np.min(exterior[:, 1])))
                & (points[:, 1] <= float(np.max(exterior[:, 1])))
            )
            if not np.any(bbox):
                continue
            inside = np.zeros(points.shape[0], dtype=bool)
            inside[bbox] = MplPath(exterior).contains_points(points[bbox])
            for hole in holes:
                hole_bbox = (
                    inside
                    & (points[:, 0] >= float(np.min(hole[:, 0])))
                    & (points[:, 0] <= float(np.max(hole[:, 0])))
                    & (points[:, 1] >= float(np.min(hole[:, 1])))
                    & (points[:, 1] <= float(np.max(hole[:, 1])))
                )
                if np.any(hole_bbox):
                    inside[hole_bbox] &= ~MplPath(hole).contains_points(points[hole_bbox])
            inside_any |= inside
        fractions = inside_any.reshape((stop - start, -1)).mean(axis=1)
        coverage[rows, columns] = fractions

    return coverage


def _initial_depth_parameter_values(release: dict[str, Any]) -> dict[str, float | bool]:
    """Validate and fill the parameters used by the initial-depth equation."""
    issues = validate_release_depth_parameters(release)
    if issues:
        raise ValueError("Invalid AVAC release parameters: " + " ".join(issues))
    return {key: release.get(key, default) for key, default in RELEASE_DEPTH_DEFAULTS.items()}


def _selected_cell_message(mask: np.ndarray) -> str:
    """Give a compact, reproducible location for an invalid release cell."""
    row, column = np.argwhere(mask)[0]
    return f"{int(np.count_nonzero(mask))} selected DEM cell(s); first at row {int(row)}, column {int(column)}"


def initial_depth_from_release(raster: AvacRaster, zone_mask: np.ndarray, release: dict[str, Any]) -> np.ndarray:
    """Return a finite, non-negative cell-average release-depth field.

    Corrections are part of the stated release model, not a numerical repair.
    Therefore a non-finite terrain/input value or a negative corrected depth
    in any covered cell is rejected instead of being silently converted to a
    dry cell or written to qinit as negative mass.
    """
    altitude = np.asarray(raster.z, dtype=float)
    if altitude.ndim != 2:
        raise ValueError("DEM elevation grid must be two-dimensional.")
    depth = np.zeros_like(altitude, dtype=float)
    coverage = np.asarray(zone_mask, dtype=float)
    if coverage.shape != altitude.shape:
        raise ValueError("Release coverage shape does not match DEM.")
    if np.any(~np.isfinite(coverage)) or np.any(coverage < 0.0) or np.any(coverage > 1.0):
        raise ValueError("Release coverage values must be finite fractions between zero and one.")

    parameters = _initial_depth_parameter_values(release)
    d0 = float(parameters["d0"])
    z_ref = float(parameters["z_ref"])
    gradient_hypso = float(parameters["gradient_hypso"])
    theta_cr = float(parameters["theta_cr"])
    nu = float(parameters["nu"])
    corr_elevation = bool(parameters["correction_elevation"])
    corr_slope = bool(parameters["correction_slope"])

    selected = coverage > 0.0
    if not np.any(selected):
        return depth
    invalid_terrain = selected & ~np.isfinite(altitude)
    if np.any(invalid_terrain):
        raise ValueError(
            "Release polygons cover non-finite DEM elevation values in "
            + _selected_cell_message(invalid_terrain)
            + "."
        )

    if corr_slope:
        try:
            cellsize = float(raster.metadata.get("cellsize", 1.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("DEM cell size must be a positive finite value for slope correction.") from exc
        if not np.isfinite(cellsize) or cellsize <= 0.0:
            raise ValueError("DEM cell size must be a positive finite value for slope correction.")
        if min(altitude.shape) < 2:
            raise ValueError("Slope correction requires at least two DEM rows and columns.")
        valid = np.isfinite(altitude)
        fill_value = float(np.mean(altitude[valid]))
        # Do not turn +/-inf neighbours into huge finite values.  Covered
        # non-finite cells were rejected above; this fill only keeps an
        # unrelated no-data hole from poisoning every surrounding gradient.
        z_fill = np.where(valid, altitude, fill_value)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            grad_y, grad_x = np.gradient(z_fill, cellsize)
            slope = np.sqrt(grad_x * grad_x + grad_y * grad_y)
            theta_rad = np.deg2rad(theta_cr)
            q_angle = np.arctan(slope)
            numerator = np.sin(theta_rad) - nu * np.cos(theta_rad)
            denominator = np.sin(q_angle) - nu * np.cos(q_angle)
            factor1 = np.zeros_like(slope, dtype=float)
            safe = (q_angle > np.deg2rad(25.0)) & (np.abs(denominator) > 1e-12)
            factor1[safe] = numerator / denominator[safe]
    else:
        factor1 = np.ones_like(altitude, dtype=float)

    with np.errstate(over="ignore", invalid="ignore"):
        factor2 = (altitude - z_ref) * gradient_hypso / 100.0 if corr_elevation else np.zeros_like(altitude)
        if corr_elevation and corr_slope:
            candidate = (d0 + factor2) * factor1
        elif corr_elevation:
            candidate = d0 + factor2
        elif corr_slope:
            candidate = d0 * factor1
        else:
            candidate = np.full_like(altitude, d0, dtype=float)

    invalid_candidate = selected & ~np.isfinite(candidate)
    if np.any(invalid_candidate):
        raise ValueError(
            "Initial-depth correction produced non-finite candidate depth in "
            + _selected_cell_message(invalid_candidate)
            + "."
        )
    negative_candidate = selected & (candidate < 0.0)
    if np.any(negative_candidate):
        minimum = float(np.min(candidate[negative_candidate]))
        raise ValueError(
            "Initial-depth correction produced negative candidate depth "
            f"(minimum {minimum:.12g} m) in {_selected_cell_message(negative_candidate)}. "
            "Adjust d0, reference elevation, hypsometric gradient, or slope-correction parameters."
        )
    with np.errstate(over="ignore", invalid="ignore"):
        depth[selected] = candidate[selected] * coverage[selected]
    invalid_depth = selected & (~np.isfinite(depth) | (depth < 0.0))
    if np.any(invalid_depth):
        raise ValueError(
            "Initial release depth must be finite and non-negative in "
            + _selected_cell_message(invalid_depth)
            + "."
        )
    return depth


def initial_snow_surface_elevation(raster: AvacRaster, depth: np.ndarray) -> np.ndarray:
    """Return the elevation of the snow surface actually initialized by AVAC.

    AVAC treats the selected DEM as its fixed basal topography and initializes
    only the mobile release depth.  This derived field is therefore ``DEM +
    initial depth``; it deliberately does not imply a stationary winter
    snowpack outside the release polygons.
    """
    altitude = np.asarray(raster.z, dtype=float)
    depth = np.asarray(depth, dtype=float)
    if depth.shape != altitude.shape:
        raise ValueError("Initial-depth array shape does not match DEM.")
    surface = altitude + depth
    surface[~np.isfinite(altitude)] = np.nan
    return surface


def _validated_topography_grid(
    raster: AvacRaster,
) -> tuple[np.ndarray, float, float, float, float, float, int, int]:
    """Validate a QGIS terrain raster before converting it to GeoClaw nodes."""
    values = np.asarray(raster.z, dtype=float)
    metadata = raster.metadata
    try:
        cell_size = float(metadata["cellsize"])
        xmin, xmax = float(metadata["xmin"]), float(metadata["xmax"])
        ymin, ymax = float(metadata["ymin"]), float(metadata["ymax"])
        ncols, nrows = int(metadata["ncols"]), int(metadata["nrows"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Cannot create GeoClaw terrain support from the selected DEM: {exc}") from exc
    if values.ndim != 2 or values.shape != (nrows, ncols):
        raise ValueError("DEM elevation array does not match its declared row and column dimensions.")
    if ncols < 1 or nrows < 1 or not np.isfinite(cell_size) or cell_size <= 0.0:
        raise ValueError("DEM must have positive finite cell size and at least one row and one column.")
    if not all(np.isfinite(value) for value in (xmin, xmax, ymin, ymax)):
        raise ValueError("DEM outer extent must contain finite coordinates.")
    if (
        not np.isclose((xmax - xmin) / cell_size, ncols, rtol=0.0, atol=GRID_COUNT_TOLERANCE)
        or not np.isclose((ymax - ymin) / cell_size, nrows, rtol=0.0, atol=GRID_COUNT_TOLERANCE)
    ):
        raise ValueError("DEM edges, dimensions, and cell size do not describe one regular grid.")
    return values, cell_size, xmin, xmax, ymin, ymax, ncols, nrows


def geoclaw_topography_halo(raster: AvacRaster) -> AvacRaster:
    """Return the topotype-3 terrain support needed around a base QGIS DEM.

    QGIS values and AVAC qinit values are cell-centred, piecewise-constant
    fields whose physical envelope is the metadata edge extent.  GeoClaw's
    topotype-3 reader, in contrast, shifts an ESRI ``xllcorner`` by half a
    cell and interpolates the values as *nodal* terrain samples.  Writing the
    original raster directly therefore leaves half a source cell unsupported
    at every solver edge.

    Replicate the outer terrain samples once on each side only for the
    GeoClaw topography file.  The resulting nodal support extends half a DEM
    cell beyond the original QGIS extent while the solver domain, release
    coverage and qinit raster retain their original physical bounds.  This
    intentionally avoids using a terrain halo as an extra release or qinit
    cell.  A supplemental fine DEM is an overlay on this base terrain and
    uses :func:`geoclaw_overlay_topography` instead, so it does not replace
    the base terrain beyond its declared footprint.
    """
    values, cell_size, xmin, xmax, ymin, ymax, ncols, nrows = _validated_topography_grid(raster)

    halo_metadata = dict(raster.metadata)
    halo_metadata.update({
        "xmin": xmin - cell_size,
        "xmax": xmax + cell_size,
        "ymin": ymin - cell_size,
        "ymax": ymax + cell_size,
        "ncols": ncols + 2,
        "nrows": nrows + 2,
        "cellsize": cell_size,
    })
    return AvacRaster(
        _cell_centres(float(halo_metadata["xmin"]), ncols + 2, cell_size),
        _cell_centres(float(halo_metadata["ymin"]), nrows + 2, cell_size),
        np.pad(values, ((1, 1), (1, 1)), mode="edge"),
        halo_metadata,
        raster.crs_authid,
        raster.band,
    )


def _midpoint_nodal_samples(values: np.ndarray, axis: int) -> np.ndarray:
    """Sample a linearly interpolated field at its cell edges and centres."""
    samples = np.moveaxis(np.asarray(values, dtype=float), axis, -1)
    count = samples.shape[-1]
    result = np.empty(samples.shape[:-1] + (2 * count + 1,), dtype=float)
    # Odd locations are the original QGIS sample centres.  Even interior
    # locations are their linear midpoints; the two outer nodes use the same
    # constant edge continuation as the base-DTM halo.
    result[..., 1::2] = samples
    result[..., 0] = samples[..., 0]
    result[..., -1] = samples[..., -1]
    if count > 1:
        result[..., 2:-1:2] = 0.5 * (samples[..., :-1] + samples[..., 1:])
    return np.moveaxis(result, -1, axis)


def geoclaw_overlay_topography(raster: AvacRaster) -> AvacRaster:
    """Convert a fine QGIS DEM to a closed-support GeoClaw terrain overlay.

    GeoClaw gives the finest overlapping topotype-3 file priority.  Padding a
    local fine DEM as though it were the base DEM therefore extrapolates its
    edge terrain by half a fine cell beyond the QGIS footprint and overwrites
    the base terrain there.  This reconstruction instead uses half the source
    spacing and node positions exactly on the QGIS outer edges.  It samples
    the same edge-padded bilinear terrain that :func:`geoclaw_topography_halo`
    represents *inside* the fine footprint, while its node envelope is closed
    at that footprint.  GeoClaw can consequently retain the base terrain at
    every exterior point.
    """
    values, cell_size, xmin, xmax, ymin, ymax, ncols, nrows = _validated_topography_grid(raster)
    node_values = _midpoint_nodal_samples(_midpoint_nodal_samples(values, 1), 0)
    node_cell_size = 0.5 * cell_size
    overlay_metadata = dict(raster.metadata)
    overlay_metadata.update({
        # ``write_topography`` records topotype-3's ESRI-style lower edge;
        # GeoClaw shifts it by half ``node_cell_size`` to the first node.
        "xmin": xmin - 0.25 * cell_size,
        "xmax": xmax + 0.25 * cell_size,
        "ymin": ymin - 0.25 * cell_size,
        "ymax": ymax + 0.25 * cell_size,
        "ncols": 2 * ncols + 1,
        "nrows": 2 * nrows + 1,
        "cellsize": node_cell_size,
    })
    return AvacRaster(
        _cell_centres(float(overlay_metadata["xmin"]), 2 * ncols + 1, node_cell_size),
        _cell_centres(float(overlay_metadata["ymin"]), 2 * nrows + 1, node_cell_size),
        node_values,
        overlay_metadata,
        raster.crs_authid,
        raster.band,
    )


def write_topography(path: Path, raster: AvacRaster, cancelled: Callable[[], bool] | None = None) -> None:
    """Use the legacy GUI's exact topotype-3 formatting and row order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    m, z = raster.metadata, np.asarray(raster.z, dtype=float)
    nodata = float(m["nodata_value"])
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"ncols {z.shape[1]}\n")
        handle.write(f"nrows {z.shape[0]}\n")
        handle.write(f"xllcorner {float(m['xmin'])}\n")
        handle.write(f"yllcorner {float(m['ymin'])}\n")
        handle.write(f"cellsize {float(m['cellsize'])}\n")
        handle.write(f"NODATA_value {nodata}\n")
        for row in np.flipud(np.where(np.isfinite(z), z, nodata)):
            if cancelled and cancelled():
                raise PreparationCancelled("AVAC input preparation cancelled.")
            handle.write(" ".join(f"{float(value):.10g}" for value in row) + "\n")


def read_avac_topography(path: str | Path, crs_authid: str = "") -> AvacRaster:
    """Read the AVAC topotype-3 ASCII terrain written by :func:`write_topography`.

    This is deliberately not delegated to GDAL: AVAC's solver-format header
    uses its own topotype convention and is not guaranteed to be recognized as
    an ESRI ASCII raster by a QGIS/GDAL build. The returned values follow this
    module's south-to-north array convention.
    """
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            header = [handle.readline().strip() for _ in range(6)]
    except OSError as exc:
        raise ValueError(f"AVAC topography is unavailable: {source}") from exc
    if any(not line for line in header):
        raise ValueError(f"AVAC topography header is incomplete: {source}")

    def value(index: int, label: str, cast):
        fields = header[index].split()
        if len(fields) < 2 or fields[0].lower() != label:
            raise ValueError(f"AVAC topography header has no valid {label} entry: {source}")
        try:
            return cast(fields[-1])
        except ValueError as exc:
            raise ValueError(f"AVAC topography header has an invalid {label} value: {source}") from exc

    ncols, nrows = value(0, "ncols", int), value(1, "nrows", int)
    xmin, ymin = value(2, "xllcorner", float), value(3, "yllcorner", float)
    cell_size, nodata = value(4, "cellsize", float), value(5, "nodata_value", float)
    if ncols < 1 or nrows < 1 or not np.isfinite(cell_size) or cell_size <= 0.0:
        raise ValueError(f"AVAC topography has invalid grid dimensions: {source}")
    try:
        north_to_south = np.atleast_2d(np.loadtxt(source, skiprows=6, dtype=float))
    except (OSError, ValueError) as exc:
        raise ValueError(f"AVAC topography values are unreadable: {source}") from exc
    if north_to_south.shape != (nrows, ncols):
        raise ValueError(
            f"AVAC topography dimensions {north_to_south.shape} do not match its header {(nrows, ncols)}: {source}"
        )
    if np.isfinite(nodata):
        north_to_south[np.isclose(north_to_south, nodata)] = np.nan
    values = np.flipud(north_to_south)
    # ``xllcorner``/``yllcorner`` describe outer cell edges. GeoClaw shifts
    # them by half a cell on read; expose the same centres to the GUI so a
    # prepared terrain, its release grid, and its qinit grid stay registered.
    x = _cell_centres(xmin, ncols, cell_size)
    y = _cell_centres(ymin, nrows, cell_size)
    metadata: dict[str, float | int] = {
        "xmin": float(xmin), "xmax": float(xmin + ncols * cell_size),
        "ymin": float(ymin), "ymax": float(ymin + nrows * cell_size),
        "ncols": ncols, "nrows": nrows, "cellsize": float(cell_size), "nodata_value": float(nodata),
    }
    return AvacRaster(x, y, values, metadata, crs_authid, 1)


def _validated_qinit_depth(raster: AvacRaster, depth: np.ndarray) -> np.ndarray:
    """Return qinit values only when every stored cell is physically valid."""
    values = np.asarray(depth, dtype=float)
    if values.shape != raster.z.shape:
        raise ValueError("Initial-depth array shape does not match DEM.")
    invalid = ~np.isfinite(values) | (values < 0.0)
    if np.any(invalid):
        raise ValueError(
            "Initial-depth qinit values must be finite and non-negative; invalid values occur in "
            + _selected_cell_message(invalid)
            + "."
        )
    return values


def write_init_xyz(path: Path, raster: AvacRaster, depth: np.ndarray, cancelled: Callable[[], bool] | None = None) -> None:
    """Write legacy NW-to-SE qinit ordering and precision."""
    values = _validated_qinit_depth(raster, depth)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in range(raster.y.size - 1, -1, -1):
            if cancelled and cancelled():
                raise PreparationCancelled("AVAC input preparation cancelled.")
            for column, x_value in enumerate(raster.x):
                handle.write(f"{x_value:.12g} {raster.y[row]:.12g} {float(values[row, column]):.12g}\n")


def write_init_binary(path: Path, raster: AvacRaster, depth: np.ndarray, cancelled: Callable[[], bool] | None = None) -> None:
    """Write AVAC's portable, bulk-readable qinit raster.

    The payload is explicitly little-endian and ordered north-to-south, with
    each row stored west-to-east.  This matches the indexing of the legacy
    ``init.xyz`` reader without serially formatting and parsing millions of
    redundant x/y coordinates.
    """
    values = _validated_qinit_depth(raster, depth)
    if raster.x.size < 2 or raster.y.size < 2:
        raise ValueError("Initial-condition raster must contain at least two rows and columns.")
    dx = float(raster.x[1] - raster.x[0])
    dy = float(raster.y[1] - raster.y[0])
    if dx <= 0.0 or dy <= 0.0 or not np.allclose(np.diff(raster.x), dx) or not np.allclose(np.diff(raster.y), dy):
        raise ValueError("Initial-condition raster coordinates must form a regular increasing grid.")
    header = QINIT_BINARY_HEADER.pack(
        QINIT_BINARY_MAGIC,
        int(raster.x.size),
        int(raster.y.size),
        1,  # scalar qinit component
        0,  # reserved for future format flags
        float(raster.x[0]),
        float(raster.y[-1]),
        dx,
        dy,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(header)
        for row in range(raster.y.size - 1, -1, -1):
            if cancelled and cancelled():
                raise PreparationCancelled("AVAC input preparation cancelled.")
            row_values = values[row]
            # Retain the legacy writer's ``.12g`` scientific-input precision
            # so switching transport formats does not alter solver results.
            # Extremely small finite values cannot be multiplied by a decimal
            # scale without overflowing that scale.  They are already far
            # below any practical dry tolerance, but retain their finite
            # binary value rather than turning them into NaN during rounding.
            nonzero = row_values != 0.0
            if np.any(nonzero):
                row_values = row_values.copy()
                indices = np.flatnonzero(nonzero)
                exponent = 11.0 - np.floor(np.log10(np.abs(row_values[indices])))
                roundable = exponent <= 308.0
                if np.any(roundable):
                    selected = indices[roundable]
                    scale = np.power(10.0, exponent[roundable])
                    row_values[selected] = np.rint(row_values[selected] * scale) / scale
            row_values.astype("<f8", copy=False).tofile(handle)


def materialize_configuration(template: Path, destination: Path, raster: AvacRaster, release: dict[str, Any], topo_dir: Path, controlled_values: dict[str, Any] | None = None, fine_raster: AvacRaster | None = None) -> dict[str, Any]:
    """Preserve a complete valid YAML template; alter only derived/run fields."""
    config = configuration_for_raster(
        apply_controlled_values(load_complete_configuration(template), controlled_values or {}), raster,
    )
    issues = validate_grid_contract(config, float(raster.metadata["cellsize"]))
    if issues:
        raise ValueError(" ".join(issues))
    if not isinstance(config.get("release"), dict):
        raise ValueError("Template requires a complete release mapping.")
    config["release"].update(release)
    release_issues = validate_release_depth_parameters(config["release"])
    if release_issues:
        raise ValueError("Invalid AVAC release parameters: " + " ".join(release_issues))
    config["file_names"].update({"topofile": "topography.asc", "initiation_file": QINIT_BINARY_NAME, "type_dem": 3, "type_init": 1})
    if not config["file_names"].get("topo_source"):
        raise ValueError("Template requires file_names.topo_source for the current setrun.py.")
    config["file_names"]["topo_directory"] = str(topo_dir)
    config["computation"]["topo_dir"] = str(topo_dir)
    if fine_raster is not None:
        if fine_raster.crs_authid != raster.crs_authid:
            raise ValueError("Refinement DEM CRS must match the main DEM CRS.")
        meta = fine_raster.metadata
        config["refinement"] = {
            "topo_refinement": True, "finer_dem": "fine_topography.asc", "delta_t": float(config["output"]["delta_t"]),
            "fine_dict": {"xmin": meta["xmin"], "xmax": meta["xmax"], "ymin": meta["ymin"], "ymax": meta["ymax"],
                          "nbx": meta["ncols"], "nby": meta["nrows"], "cell_size": meta["cellsize"], "nodata_value": meta["nodata_value"]},
        }
    else:
        # A bundled QGIS run can only enable refinement when it has a staged
        # fine DEM; never retain a template path that points outside the run.
        config["refinement"]["topo_refinement"] = False
        config["refinement"]["finer_dem"] = None
        config["refinement"]["fine_dict"] = "None"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    return config


def prepare_inputs(
    run_root: Path, raster: AvacRaster, rings, template: Path, release: dict[str, Any], controlled_values: dict[str, Any] | None = None, *, fine_raster: AvacRaster | None = None, allow_existing_run: bool = False,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PreparedInputs:
    """Materialize only AVAC scientific input files in a new per-run directory."""
    run_root = Path(run_root).expanduser().resolve()
    if run_root.exists() and any(run_root.iterdir()) and not allow_existing_run:
        raise ValueError(f"Run directory must be empty: {run_root}")
    avac_dir, topo_dir = run_root / "AVAC", run_root / "Topo"
    template_payload = configuration_for_raster(
        apply_controlled_values(load_complete_configuration(template), controlled_values or {}), raster,
    )
    grid_issues = validate_grid_contract(template_payload, float(raster.metadata["cellsize"]))
    if grid_issues:
        raise ValueError(" ".join(grid_issues))
    if not isinstance(template_payload.get("release"), dict):
        raise ValueError("Template is missing its complete release section.")
    # The dock exposes only deliberate overrides.  Depth calculation must still
    # receive every scientific release parameter from the complete template.
    effective_release = dict(template_payload["release"])
    effective_release.update(release)
    if progress:
        progress(25)
    if cancelled and cancelled():
        raise PreparationCancelled("AVAC input preparation cancelled.")
    coverage = release_coverage_from_rings(
        rings, raster.x, raster.y, float(raster.metadata["cellsize"]),
    )
    mask = coverage > 0.0
    if not np.any(mask):
        raise ValueError("Release polygons do not cover any part of the selected DEM grid.")
    if progress:
        progress(40)
    depth = initial_depth_from_release(raster, coverage, effective_release)
    topo_path, init_path, configuration_path = topo_dir / "topography.asc", avac_dir / QINIT_BINARY_NAME, avac_dir / "AVAC_configuration.yaml"
    if progress:
        progress(50)
    # GeoClaw interpolates topotype-3 terrain as nodal samples.  Give that
    # reader edge support without changing the physical QGIS/qinit grid.
    write_topography(topo_path, geoclaw_topography_halo(raster), cancelled)
    if fine_raster is not None:
        # A local fine DEM overlays the base terrain.  Unlike the base file,
        # it must not be edge-padded beyond its QGIS footprint because GeoClaw
        # would give that extrapolated fringe precedence over the base DEM.
        write_topography(
            topo_dir / "fine_topography.asc", geoclaw_overlay_topography(fine_raster), cancelled,
        )
    if progress:
        progress(72)
    write_init_binary(init_path, raster, depth, cancelled)
    if progress:
        progress(90)
    if cancelled and cancelled():
        raise PreparationCancelled("AVAC input preparation cancelled.")
    materialize_configuration(template, configuration_path, raster, effective_release, topo_dir, controlled_values, fine_raster)
    if progress:
        progress(98)
    return PreparedInputs(run_root, avac_dir, topo_path, init_path, configuration_path, mask, coverage, depth)
