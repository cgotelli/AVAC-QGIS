"""Preparation of isolated lake-wave scenarios.

The lake-wave extension consumes a completed AVAC run, but never writes to it.
Its input and output tree is deliberately separate from ``runs`` so enabling
the extension cannot alter the normal AVAC workflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .preprocessing import AvacRaster, release_mask_from_rings, write_topography
from .run_project import read_run_metadata
from .time_utils import local_now_iso, local_run_stamp, temporal_origin_iso
from .workspace import validate_workspace

WAVE_MARKER = ".avac_qgis_wave_run.json"
WAVE_FORMAT = 1


@dataclass(frozen=True)
class PreparedWaveLake:
    """Solver-grid lake state shared by preview and scenario preparation."""

    raster: AvacRaster
    inside: np.ndarray
    solver_wet: np.ndarray
    shoreline_faces: np.ndarray
    domain: dict[str, float]
    cell_size: float
    water_level: float
    dry_tolerance: float
    stabilized_cells: int
    stabilization_radius_cells: int

    @property
    def initial_depth(self) -> np.ndarray:
        """Water depth shown by the preview on the exact prepared terrain."""
        values = np.asarray(self.raster.z, dtype=float)
        wet = self.inside & np.isfinite(values) & (values < self.water_level)
        return np.where(wet, self.water_level - values, np.nan)


def _now() -> str:
    return local_now_iso()


def _new_wave_root(workspace: str | Path) -> Path:
    root = validate_workspace(workspace) / "wave_runs"
    root.mkdir(exist_ok=True)
    stem = "wave_" + local_run_stamp()
    candidate, number = root / stem, 1
    while candidate.exists():
        number += 1
        candidate = root / f"{stem}_{number:02d}"
    return candidate


def _write_marker(root: Path, payload: dict[str, Any]) -> None:
    (root / WAVE_MARKER).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_source(avac_root: Path) -> dict[str, Any]:
    metadata = read_run_metadata(avac_root)
    if metadata.get("status") != "completed":
        raise ValueError("Select a completed AVAC run.")
    output = avac_root / "AVAC" / "_output"
    if not any(output.glob("fort.q*")):
        raise ValueError("The selected AVAC run has no fort.q output required for the Wave shoreline inflow.")
    return metadata


def validate_wave_source_compatibility(
    avac_root: str | Path,
    wave_crs_authid: str,
    domain: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Require AVAC and WAVE to share coordinates and spatial coverage."""
    avac_root = Path(avac_root).expanduser().resolve()
    metadata = _validate_source(avac_root)
    source_crs = str(metadata.get("dem_crs") or "").strip().upper()
    wave_crs = str(wave_crs_authid or "").strip().upper()
    if source_crs and wave_crs and source_crs != wave_crs:
        raise ValueError(
            f"Selected AVAC run uses {source_crs}, but the Wave terrain uses {wave_crs}. "
            "Select an AVAC run from the same case and coordinate reference system."
        )
    if domain is not None:
        try:
            configuration = yaml.safe_load(
                (avac_root / "AVAC" / "AVAC_configuration.yaml").read_text(encoding="utf-8")
            )
            source_extent = configuration.get("dem_extent") if isinstance(configuration, dict) else None
            if not isinstance(source_extent, dict):
                return metadata
            separated = (
                float(domain["xmax"]) <= float(source_extent["xmin"])
                or float(domain["xmin"]) >= float(source_extent["xmax"])
                or float(domain["ymax"]) <= float(source_extent["ymin"])
                or float(domain["ymin"]) >= float(source_extent["ymax"])
            )
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise ValueError("Completed AVAC run has no valid spatial extent for Wave coupling.") from exc
        if separated:
            raise ValueError(
                "Selected AVAC run does not overlap the Wave calculation domain. "
                "Select the completed AVAC run for this lake/reservoir case."
            )
    return metadata


def avac_computation_domain(avac_root: str | Path) -> dict[str, float]:
    """Return the exact rectangular domain of a completed AVAC run.

    WAVE no longer owns a second user-defined calculation rectangle.  Both
    solvers use these AVAC bounds, while their cell sizes may still differ.
    """
    avac_root = Path(avac_root).expanduser().resolve()
    _validate_source(avac_root)
    path = avac_root / "AVAC" / "AVAC_configuration.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        extent = payload["dem_extent"]
        result = {key: float(extent[key]) for key in ("xmin", "xmax", "ymin", "ymax")}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Completed AVAC run has no valid computation domain: {path}") from exc
    if not all(np.isfinite(value) for value in result.values()):
        raise ValueError("Completed AVAC computation-domain coordinates must be finite.")
    if result["xmax"] <= result["xmin"] or result["ymax"] <= result["ymin"]:
        raise ValueError("Completed AVAC computation domain has invalid bounds.")
    return result


def _source_timing(avac_root: Path) -> tuple[float, int]:
    """Read the completed AVAC duration and output count for the Wave run."""
    path = avac_root / "AVAC" / "AVAC_configuration.yaml"
    try:
        computation = yaml.safe_load(path.read_text(encoding="utf-8"))["computation"]
        duration, outputs = float(computation["t_max"]), int(computation["nb_simul"])
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"Completed AVAC timing configuration is missing or invalid: {path}") from exc
    if duration <= 0 or outputs < 1:
        raise ValueError("Completed AVAC duration and output count must both be positive.")
    return duration, outputs


def _validated_domain(raster: AvacRaster, domain: dict[str, float], cell_size: float) -> dict[str, float]:
    """Validate the explicit rectangular GeoClaw domain against the terrain."""
    try:
        result = {key: float(domain[key]) for key in ("xmin", "xmax", "ymin", "ymax")}
        terrain = {key: float(raster.metadata[key]) for key in ("xmin", "xmax", "ymin", "ymax")}
        terrain_cell = float(raster.metadata["cellsize"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Wave domain or terrain metadata is invalid: {exc}") from exc
    if result["xmax"] <= result["xmin"] or result["ymax"] <= result["ymin"]:
        raise ValueError("Wave domain maximum coordinates must be greater than their minimum coordinates.")
    if result["xmin"] < terrain["xmin"] or result["xmax"] > terrain["xmax"] or result["ymin"] < terrain["ymin"] or result["ymax"] > terrain["ymax"]:
        raise ValueError("Wave domain must be fully covered by the selected terrain/bathymetry DEM.")
    ratio = cell_size / terrain_cell
    factor = round(ratio)
    if factor < 1 or not np.isclose(ratio, factor, rtol=0.0, atol=1e-8):
        raise ValueError(
            f"Wave grid cell size ({cell_size:g} m) must equal the DEM resolution ({terrain_cell:g} m) "
            "or be a whole-number multiple of it."
        )
    for axis in ("x", "y"):
        offset = (result[f"{axis}min"] - terrain[f"{axis}min"]) / terrain_cell
        if not np.isclose(offset, round(offset), rtol=0.0, atol=1e-8):
            raise ValueError(f"Wave {axis}-minimum must align with the terrain/bathymetry DEM grid.")
        cells = (result[f"{axis}max"] - result[f"{axis}min"]) / cell_size
        if cells < 2 or not np.isclose(cells, round(cells), rtol=0.0, atol=1e-8):
            raise ValueError(f"Wave {axis}-extent must span an integer number of at least two {cell_size:g} m cells.")
    return result


def terrain_for_wave_domain(raster: AvacRaster, domain: dict[str, float], cell_size: float) -> AvacRaster:
    """Create a cell-centered terrain grid with a one-cell GeoClaw halo.

    GeoClaw integrates topotype-3 terrain over each finite-volume cell.  A
    topography file that starts exactly at the computational lower bounds only
    covers half of the first row/column, so the uncovered fraction is treated
    as zero elevation.  The resulting quarter/half bed elevations can create
    enormous, nonphysical initial depths at the south and west edges.  Supply
    one complete Wave cell of terrain on every side instead.  Where the
    unchanged calculation rectangle touches the source DEM edge, extend the
    nearest DEM row or column into this topography-only halo.

    If the Wave grid is coarser than the DEM, each output terrain value is the
    mean of the finite source cells in that block.  No sub-DEM detail is
    invented and the computational rectangle itself is unchanged.
    """
    source_cell = float(raster.metadata["cellsize"])
    factor = int(round(cell_size / source_cell))
    nx = int(round((domain["xmax"] - domain["xmin"]) / cell_size))
    ny = int(round((domain["ymax"] - domain["ymin"]) / cell_size))
    halo_xmin, halo_ymin = domain["xmin"] - cell_size, domain["ymin"] - cell_size
    x0 = int(round((halo_xmin - float(raster.metadata["xmin"])) / source_cell))
    y0 = int(round((halo_ymin - float(raster.metadata["ymin"])) / source_cell))
    source_width, source_height = (nx + 2) * factor, (ny + 2) * factor
    source = np.asarray(raster.z, dtype=float)
    source_y0, source_x0 = max(y0, 0), max(x0, 0)
    source_y1 = min(y0 + source_height, source.shape[0])
    source_x1 = min(x0 + source_width, source.shape[1])
    values = source[source_y0:source_y1, source_x0:source_x1]
    if values.size == 0:
        raise ValueError("Wave calculation domain does not overlap usable terrain cells.")
    pad_bottom, pad_left = max(0, -y0), max(0, -x0)
    pad_top = max(0, y0 + source_height - source.shape[0])
    pad_right = max(0, x0 + source_width - source.shape[1])
    values = np.pad(values, ((pad_bottom, pad_top), (pad_left, pad_right)), mode="edge")
    if values.shape != (source_height, source_width):
        raise ValueError("Wave terrain grid could not be aligned with the calculation domain.")
    if factor > 1:
        blocks = values.reshape(ny + 2, factor, nx + 2, factor)
        finite = np.isfinite(blocks)
        counts = finite.sum(axis=(1, 3))
        sums = np.where(finite, blocks, 0.0).sum(axis=(1, 3))
        values = np.divide(sums, counts, out=np.full(counts.shape, np.nan, dtype=float), where=counts > 0)
    if not np.isfinite(values).all():
        raise ValueError("Wave terrain contains missing elevations in or immediately beside the calculation domain.")
    metadata = dict(raster.metadata)
    metadata.update({"xmin": halo_xmin, "xmax": domain["xmax"] + cell_size,
                     "ymin": halo_ymin, "ymax": domain["ymax"] + cell_size,
                     "ncols": nx + 2, "nrows": ny + 2, "cellsize": float(cell_size)})
    x = halo_xmin + (np.arange(nx + 2, dtype=float) + .5) * cell_size
    y = halo_ymin + (np.arange(ny + 2, dtype=float) + .5) * cell_size
    return AvacRaster(x, y, values, metadata, raster.crs_authid, raster.band)


def _wave_config(domain: dict[str, float], cell_size: float, water_level: float, *, duration: float, output_count: int,
                 parameters: dict[str, Any]) -> dict[str, Any]:
    width = domain["xmax"] - domain["xmin"]
    height = domain["ymax"] - domain["ymin"]
    nx, ny = int(round(width / cell_size)), int(round(height / cell_size))
    if nx < 2 or ny < 2:
        raise ValueError("Wave grid must contain at least two cells in both directions.")
    # Match the upstream Lac_Lachat WAVE schema.  These conservative defaults
    # are explicit in the file and can later be exposed without schema drift.
    return {
        "lake": {"topography": "topography_lake.asc", "water_level": float(water_level), **domain},
        "topo_files": {"topography": "topography_lake.asc", "mask_raster": "mask.asc", "missing_value": -9999.0},
        "computation": {"boundary": "extrap", "cell_size": float(cell_size), "cfl_max": parameters["cfl_max"], "cfl_target": parameters["cfl_target"],
                        "damping": parameters["damping"], "dry_limit": parameters["dry_limit"], "initial_mass": False, "limiter": parameters["limiter"], "max_iter": 100000,
                        "mode": "internal_shoreline", "nb_grid": max(nx, ny), "nb_simul": int(output_count), "refinement": 1,
                        "t_0": 0.0, "t_max": float(duration)},
        "gauges": {"gauge_recording": False},
        "output": {"delta_t": float(duration) / int(output_count), "output_directory": "_output", "output_format": "binary", "verbosity": 0},
        # GeoClaw applies coefficient 1 below the first elevation break and
        # coefficient 2 above it.  The lake bed is below the water level, so
        # write the water value first and the dry-land value second.
        "rheology": {"Strickler": [parameters["water_strickler"], parameters["land_strickler"]], "friction": True,
                      "friction_break_elevation": float(water_level), "friction_depth_limit": parameters["friction_depth_limit"],
                      "gravity": 9.81, "rho": 1000.0, "wave_tolerance_flag": parameters["wave_tolerance_flag"]},
    }


def wave_lake_mask_from_rings(
    lake_rings,
    x: np.ndarray,
    y: np.ndarray,
    *,
    source_cell_size: float | None = None,
    coverage_threshold: float = .5,
) -> np.ndarray:
    """Return a mesh-consistent initial-lake mask from a polygon layer.

    A Wave cell represents one finite-volume state, not a fraction of a
    state.  Applying GDAL's ``ALL_TOUCHED`` rule directly to a coarser Wave
    mesh therefore turns even a narrow sliver of a detailed shoreline polygon
    into a *full* water cell.  The resulting jagged, partly submerged fringe
    is an artificial source of waves when the global initial water level is
    applied by GeoClaw.

    When the source DEM is finer than the Wave mesh, first rasterize the
    polygon on the source-cell grid (still with the requested all-touched
    convention), then retain a Wave cell only when at least half of its area
    is lake.  This gives one unambiguous, grid-aligned stair-step shoreline;
    its positional error is bounded by one Wave cell rather than by arbitrary
    sub-cell slivers.  With no ``source_cell_size`` this retains the direct
    all-touched behavior used by callers that already work at solver
    resolution.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size < 1 or y.size < 1:
        raise ValueError("Wave lake-mask coordinates must be non-empty one-dimensional arrays.")
    if x.size > 1:
        dx = float(np.median(np.diff(x)))
        if dx <= 0.0 or not np.allclose(np.diff(x), dx, rtol=0.0, atol=max(abs(dx), 1.0) * 1e-8):
            raise ValueError("Wave lake-mask X coordinates must form a regular increasing grid.")
    else:
        dx = 1.0
    if y.size > 1:
        dy = float(np.median(np.diff(y)))
        if dy <= 0.0 or not np.allclose(np.diff(y), dy, rtol=0.0, atol=max(abs(dy), 1.0) * 1e-8):
            raise ValueError("Wave lake-mask Y coordinates must form a regular increasing grid.")
    else:
        dy = dx
    if not 0.0 < float(coverage_threshold) <= 1.0:
        raise ValueError("Wave lake-mask coverage threshold must be in the interval (0, 1].")

    def rasterize(mask_x: np.ndarray, mask_y: np.ndarray, mask_dx: float, mask_dy: float) -> np.ndarray:
        """Rasterize the rings using a direct GDAL path, with a pure fallback."""
        try:
            from osgeo import gdal, ogr
        except ImportError:
            return release_mask_from_rings(lake_rings, mask_x, mask_y)

        vector_driver = ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")
        raster_driver = gdal.GetDriverByName("MEM")
        if vector_driver is None or raster_driver is None:
            return release_mask_from_rings(lake_rings, mask_x, mask_y)
        vector = vector_driver.CreateDataSource("")
        layer = vector.CreateLayer("lake", geom_type=ogr.wkbPolygon)
        feature_count = 0
        for exterior, holes in lake_rings:
            polygon = ogr.Geometry(ogr.wkbPolygon)
            for coordinates in (exterior, *holes):
                coordinates = np.asarray(coordinates, dtype=float)
                if coordinates.ndim != 2 or coordinates.shape[0] < 3 or coordinates.shape[1] != 2:
                    continue
                ring = ogr.Geometry(ogr.wkbLinearRing)
                for coordinate_x, coordinate_y in coordinates:
                    ring.AddPoint_2D(float(coordinate_x), float(coordinate_y))
                if not np.allclose(coordinates[0], coordinates[-1], rtol=0.0, atol=0.0):
                    ring.AddPoint_2D(float(coordinates[0, 0]), float(coordinates[0, 1]))
                polygon.AddGeometry(ring)
            if polygon.GetGeometryCount() < 1:
                continue
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(polygon)
            if layer.CreateFeature(feature) != 0:
                raise ValueError("GDAL could not rasterize the lake water-body polygon.")
            feature_count += 1
            feature = None
        if feature_count == 0:
            raise ValueError("Lake water-body layer has no valid polygon rings.")
        raster = raster_driver.Create("", int(mask_x.size), int(mask_y.size), 1, gdal.GDT_Byte)
        raster.SetGeoTransform((float(mask_x[0] - mask_dx / 2.0), mask_dx, 0.0,
                                float(mask_y[-1] + mask_dy / 2.0), 0.0, -mask_dy))
        band = raster.GetRasterBand(1)
        band.Fill(0)
        if gdal.RasterizeLayer(raster, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"]) != 0:
            raise ValueError("GDAL could not create the Wave lake mask.")
        result = np.flipud(np.asarray(band.ReadAsArray(), dtype=np.uint8)).astype(bool, copy=False)
        raster = None
        vector = None
        return result

    if source_cell_size is None:
        return rasterize(x, y, dx, dy)
    source_cell = float(source_cell_size)
    if not np.isfinite(source_cell) or source_cell <= 0.0:
        raise ValueError("Wave source DEM cell size must be positive and finite.")
    ratio_x, ratio_y = dx / source_cell, dy / source_cell
    factor_x, factor_y = round(ratio_x), round(ratio_y)
    if (factor_x < 1 or factor_y < 1
            or not np.isclose(ratio_x, factor_x, rtol=0.0, atol=1e-8)
            or not np.isclose(ratio_y, factor_y, rtol=0.0, atol=1e-8)):
        raise ValueError("Wave lake-mask grid must be an integer multiple of the source DEM resolution.")
    if factor_x == 1 and factor_y == 1:
        return rasterize(x, y, dx, dy)

    # Both the Wave domain and its halo are validated against the source grid,
    # so this fine grid has an exact whole-number block per solver cell.
    fine_x = x[0] - dx / 2.0 + (np.arange(x.size * factor_x, dtype=float) + .5) * source_cell
    fine_y = y[0] - dy / 2.0 + (np.arange(y.size * factor_y, dtype=float) + .5) * source_cell
    fine_mask = rasterize(fine_x, fine_y, source_cell, source_cell)
    coverage = fine_mask.reshape(y.size, factor_y, x.size, factor_x).mean(axis=(1, 3))
    return coverage >= float(coverage_threshold)


def shoreline_faces_from_wet_mask(wet: np.ndarray, domain: dict[str, float], cell_size: float) -> np.ndarray:
    """Return grid-aligned land-to-water faces around the initial wet lake.

    Each row contains target-cell centre ``x, y``, face-centre ``x, y``, the
    unit normal pointing from land into the lake, and face length.  A diagonal
    shoreline therefore becomes a conservative north/south/east/west
    staircase on the exact GeoClaw grid instead of an outer-domain boundary.
    """
    wet = np.asarray(wet, dtype=bool)
    ny = int(round((float(domain["ymax"]) - float(domain["ymin"])) / cell_size))
    nx = int(round((float(domain["xmax"]) - float(domain["xmin"])) / cell_size))
    if wet.shape != (ny, nx):
        raise ValueError(f"Wet-lake mask shape {wet.shape} does not match the Wave grid {(ny, nx)}.")
    west = np.zeros_like(wet); west[:, 1:] = wet[:, :-1]
    east = np.zeros_like(wet); east[:, :-1] = wet[:, 1:]
    south = np.zeros_like(wet); south[1:, :] = wet[:-1, :]
    north = np.zeros_like(wet); north[:-1, :] = wet[1:, :]
    parts: list[np.ndarray] = []
    for exposed, face_dx, face_dy, normal_x, normal_y in (
        (wet & ~west, -0.5, 0.0, 1.0, 0.0),
        (wet & ~east, 0.5, 0.0, -1.0, 0.0),
        (wet & ~south, 0.0, -0.5, 0.0, 1.0),
        (wet & ~north, 0.0, 0.5, 0.0, -1.0),
    ):
        rows, columns = np.nonzero(exposed)
        if rows.size == 0:
            continue
        target_x = float(domain["xmin"]) + (columns.astype(float) + 0.5) * cell_size
        target_y = float(domain["ymin"]) + (rows.astype(float) + 0.5) * cell_size
        parts.append(np.column_stack((
            target_x, target_y, target_x + face_dx * cell_size,
            target_y + face_dy * cell_size,
            np.full(rows.size, normal_x), np.full(rows.size, normal_y),
            np.full(rows.size, float(cell_size)),
        )))
    if not parts:
        raise ValueError("The initial lake has no shoreline faces on the Wave grid.")
    return np.vstack(parts)


def _write_force_dry_mask(
    path: Path,
    solver_wet: np.ndarray,
    domain: dict[str, float],
    cell_size: float,
    *,
    nodata_value: int = -9999,
) -> None:
    """Write a force-dry grid that maps exactly to GeoClaw solver cells.

    GeoClaw's ``read_force_dry`` format looks like an ASCII raster, but its
    ``qinit`` lookup does not use normal corner-registered raster indexing.
    The x index is used directly as a one-based Fortran index and the y index
    is subsequently reversed because the file rows run north to south.  The
    two half-cell anchors below compensate for that convention so solver cell
    ``(i, j)`` reads exactly ``solver_wet[j - 1, i - 1]``.

    This file must contain only the finite-volume solver grid.  The separate
    topography raster includes a one-cell interpolation halo; including that
    halo here shifts the force-dry mask and incorrectly initializes submerged
    lake cells as dry, launching a wave before any avalanche inflow exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    wet = np.asarray(solver_wet, dtype=bool)
    if wet.ndim != 2 or not wet.size:
        raise ValueError("Wave force-dry mask must be a nonempty two-dimensional solver grid.")
    cell = float(cell_size)
    if not np.isfinite(cell) or cell <= 0.0:
        raise ValueError("Wave force-dry mask cell size must be positive and finite.")
    ny = int(round((float(domain["ymax"]) - float(domain["ymin"])) / cell))
    nx = int(round((float(domain["xmax"]) - float(domain["xmin"])) / cell))
    if wet.shape != (ny, nx):
        raise ValueError(f"Wave force-dry mask shape {wet.shape} does not match the solver grid {(ny, nx)}.")
    values = np.where(wet, 0, 1)
    # These are GeoClaw lookup anchors, not conventional raster lower-left
    # corners.  Preserve full precision because projected coordinates can be
    # large compared with the cell size.
    x_lookup_anchor = float(domain["xmin"]) - 0.5 * cell
    y_lookup_anchor = float(domain["ymin"]) + 0.5 * cell
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{values.shape[1]} ncols\n")
        handle.write(f"{values.shape[0]} nrows\n")
        handle.write(f"{x_lookup_anchor:.17g} xlower\n")
        handle.write(f"{y_lookup_anchor:.17g} ylower\n")
        handle.write(f"{cell:.17g} cellsize\n")
        handle.write(f"{int(nodata_value)} nodata_value\n")
        for row in np.flipud(values):
            handle.write(" ".join(str(int(value)) for value in row) + "\n")


def prepare_wave_lake(
    lake_raster: AvacRaster,
    lake_rings,
    *,
    water_level: float,
    cell_size: float,
    domain: dict[str, float],
    dry_tolerance: float = 1.e-4,
) -> PreparedWaveLake:
    """Compute the costly solver-grid lake state once for preview and writing."""
    if not np.isfinite(lake_raster.z).any():
        raise ValueError("Lake/bathymetry DEM has no finite elevation cells.")
    wave_domain = _validated_domain(lake_raster, domain, float(cell_size))
    wave_raster = terrain_for_wave_domain(lake_raster, wave_domain, float(cell_size))
    inside = wave_lake_mask_from_rings(
        lake_rings, wave_raster.x, wave_raster.y,
        source_cell_size=float(lake_raster.metadata["cellsize"]),
    )
    # GeoClaw represents the topography by a continuous bilinear surface and
    # integrates it over each finite-volume cell.  Consequently, a dry cell
    # beside a deep lake can still have a *mean* bed below the prescribed
    # water level when just one of the four topography samples belongs to the
    # lake.  The global sea-level initialization then creates a narrow ring of
    # water at t=0.  When force-dry expires it falls into the lake and launches
    # numerical, rather than physical, waves.
    #
    # Create a mesh-consistent zero-depth shoreline.  Every dry exterior
    # topography sample below the water level is lifted to a barely higher
    # waterline, and the one-cell interior rim is treated the same way.  The
    # rim removes deep samples from the bilinear support of dry cells.  This
    # does not make the exterior permanently dry: after initialization a real
    # wave can still wet it as soon as its water surface exceeds the rim.  The
    # small offset is the solver dry tolerance and prevents a numerical wet
    # state caused by equality at the waterline.
    dry_tolerance = float(dry_tolerance)
    if not np.isfinite(dry_tolerance) or dry_tolerance <= 0.0:
        raise ValueError("Wave dry-depth limit must be positive and finite.")
    guard_level = float(water_level) + dry_tolerance
    finite = np.isfinite(wave_raster.z)
    outside = ~inside
    padded_outside = np.pad(outside, 1, mode="constant", constant_values=True)
    adjacent_to_exterior = np.zeros_like(inside)
    for row_offset in range(3):
        for column_offset in range(3):
            adjacent_to_exterior |= padded_outside[
                row_offset:row_offset + inside.shape[0],
                column_offset:column_offset + inside.shape[1],
            ]
    exterior_guard = outside & finite & (wave_raster.z < guard_level)
    interior_rim = inside & adjacent_to_exterior & finite & (wave_raster.z < guard_level)
    # A lake only one or two Wave cells wide has no interior cell left after a
    # one-cell numerical rim.  Do not reject such a valid (if very coarse)
    # setup solely for stabilization; the exterior guard still prevents the
    # initial global-water-level leakage in that case.
    candidate_values = np.where(exterior_guard | interior_rim, guard_level, wave_raster.z)
    candidate_wet = inside & finite & (candidate_values < float(water_level))
    if not np.any(candidate_wet[1:-1, 1:-1]):
        interior_rim = np.zeros_like(inside)
    guarded = exterior_guard | interior_rim
    stabilized_values = np.where(guarded, guard_level, wave_raster.z)
    wet = inside & finite & (stabilized_values < float(water_level))
    if not np.any(wet[1:-1, 1:-1]):
        raise ValueError(
            "The selected water level creates no wet lake cells inside the lake boundary. "
            "Use the same vertical datum as the lake/bathymetry DEM."
        )
    stabilized_cells = int(np.count_nonzero(guarded[1:-1, 1:-1]))
    selected_radius = 1 if np.any(interior_rim[1:-1, 1:-1]) else 0
    wave_raster = AvacRaster(
        wave_raster.x, wave_raster.y, stabilized_values,
        dict(wave_raster.metadata), wave_raster.crs_authid, wave_raster.band,
    )
    # Source faces follow the mesh-conforming polygon, including its shallow
    # zero-depth rim.  The rim is part of the lake and can be physically wetted
    # by inflow or run-up; it is not an artificial exterior boundary.
    solver_wet = inside[1:-1, 1:-1]
    shoreline_faces = shoreline_faces_from_wet_mask(solver_wet, wave_domain, float(cell_size))
    return PreparedWaveLake(
        wave_raster, inside, solver_wet, shoreline_faces, dict(wave_domain),
        float(cell_size), float(water_level), dry_tolerance, stabilized_cells, selected_radius,
    )


def _validated_prepared_lake(
    prepared: PreparedWaveLake,
    domain: dict[str, float],
    cell_size: float,
    water_level: float,
    dry_tolerance: float,
) -> PreparedWaveLake:
    """Reject stale preview data rather than preparing a different scenario."""
    if not isinstance(prepared, PreparedWaveLake):
        raise ValueError("Prepared Wave water-level preview is invalid; create it again.")
    if not np.isclose(prepared.cell_size, float(cell_size), rtol=0.0, atol=1e-9):
        raise ValueError("Wave grid cell size changed after water-level preview; create the preview again.")
    if not np.isclose(prepared.water_level, float(water_level), rtol=0.0, atol=1e-9):
        raise ValueError("Wave water level changed after preview; create the preview again.")
    if not np.isclose(prepared.dry_tolerance, float(dry_tolerance), rtol=0.0, atol=1e-12):
        raise ValueError("Wave dry-depth limit changed after preview; create the preview again.")
    if any(not np.isclose(prepared.domain[key], float(domain[key]), rtol=0.0, atol=1e-8)
           for key in ("xmin", "xmax", "ymin", "ymax")):
        raise ValueError("Wave calculation domain changed after water-level preview; create the preview again.")
    expected_shape = (prepared.solver_wet.shape[0] + 2, prepared.solver_wet.shape[1] + 2)
    if prepared.raster.z.shape != expected_shape or prepared.inside.shape != expected_shape:
        raise ValueError("Prepared Wave water-level preview has inconsistent raster dimensions.")
    return prepared


def prepare_wave_scenario(workspace: str | Path, avac_root: str | Path, lake_raster: AvacRaster, lake_rings,
                          *, water_level: float, cell_size: float, domain: dict[str, float], parameters: dict[str, Any] | None = None,
                          gauges: list[dict[str, float | str]] | None = None,
                          prepared_lake: PreparedWaveLake | None = None) -> Path:
    """Write topography, dry mask and upstream-compatible WAVE configuration.

    ``lake_rings`` must already be transformed to the lake raster CRS.  The
    AVAC source is validated only; none of its configuration or output files
    are copied, modified, or deleted.
    """
    avac_root = Path(avac_root).expanduser().resolve()
    source = validate_wave_source_compatibility(avac_root, lake_raster.crs_authid, domain)
    # The Wave run is a continuation of this AVAC simulation.  It must use
    # the identical civil-time origin so QGIS can display AVAC and Wave bands
    # at the same elapsed simulation time in one Temporal Controller frame.
    source_temporal_origin = temporal_origin_iso(source, avac_root / ".avac_qgis_run.json")
    duration, output_count = _source_timing(avac_root)
    if not np.isfinite(lake_raster.z).any():
        raise ValueError("Lake/bathymetry DEM has no finite elevation cells.")
    wave_domain = _validated_domain(lake_raster, domain, float(cell_size))
    defaults = {"damping": .3, "cfl_target": .5, "cfl_max": 1.0, "limiter": "vanleer", "dry_limit": .0001,
                "land_strickler": 10.0, "water_strickler": 30.0, "friction_depth_limit": 20.0, "wave_tolerance_flag": .2}
    settings = {**defaults, **(parameters or {})}
    if not 0.0 <= float(settings["damping"]) <= .4:
        raise ValueError("Wave damping must be between 0 and 0.4.")
    if not 0.0 < float(settings["cfl_target"]) <= float(settings["cfl_max"]) <= 1.0:
        raise ValueError("Wave CFL target and maximum must satisfy 0 < target <= maximum <= 1.")
    if settings["limiter"] not in {"none", "minmod", "superbee", "mc", "vanleer"}:
        raise ValueError("Wave limiter is not supported by the bundled solver.")
    if any(float(settings[key]) <= 0.0 for key in ("dry_limit", "land_strickler", "water_strickler", "friction_depth_limit", "wave_tolerance_flag")):
        raise ValueError("Wave physical and wet/dry parameters must be positive.")
    gauge_config: dict[str, Any] = {"gauge_recording": bool(gauges)}
    for index, gauge in enumerate(gauges or []):
        try:
            x, y = float(gauge["x"]), float(gauge["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Wave gauge coordinates are invalid.") from exc
        if not (wave_domain["xmin"] <= x <= wave_domain["xmax"] and wave_domain["ymin"] <= y <= wave_domain["ymax"]):
            raise ValueError(f"Wave gauge {index + 1} is outside the Wave calculation domain.")
        gauge_config[str(index)] = {"x": x, "y": y, "name": str(gauge.get("name") or f"Gauge {index + 1}")}
    prepared = (
        prepare_wave_lake(
            lake_raster, lake_rings, water_level=float(water_level),
            cell_size=float(cell_size), domain=wave_domain, dry_tolerance=float(settings["dry_limit"]),
        )
        if prepared_lake is None
        else _validated_prepared_lake(
            prepared_lake, wave_domain, float(cell_size), float(water_level), float(settings["dry_limit"]),
        )
    )
    wave_raster = prepared.raster
    shoreline_faces = prepared.shoreline_faces
    stabilized_cells = prepared.stabilized_cells
    selected_radius = prepared.stabilization_radius_cells
    root = _new_wave_root(workspace)
    root.mkdir()
    topo = root / "Topo"
    wave = root / "Wave"
    topo.mkdir(); wave.mkdir(); coupling_dir = root / "CL"; coupling_dir.mkdir()
    write_topography(topo / "topography_lake.asc", wave_raster)
    _write_force_dry_mask(
        topo / "mask.asc", prepared.solver_wet, wave_domain, float(cell_size),
        nodata_value=int(float(wave_raster.metadata["nodata_value"])),
    )
    np.savetxt(coupling_dir / "shoreline_faces.txt", shoreline_faces, fmt="%.12g",
               header="target_x target_y face_x face_y normal_into_lake_x normal_into_lake_y face_length")
    configuration = _wave_config(wave_domain, float(cell_size), float(water_level), duration=duration, output_count=output_count, parameters=settings)
    configuration["gauges"] = gauge_config
    configuration["coupling"] = {"mode": "internal_shoreline", "shoreline_faces": "CL/shoreline_faces.txt",
                                  "inflow": "CL/internal_inflow.data"}
    configuration["topo_files"]["shoreline_guard_cells"] = stabilized_cells
    configuration["topo_files"]["shoreline_guard_rim_cells"] = selected_radius
    (root / "impulse_configuration.yaml").write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")
    now = _now()
    _write_marker(root, {"format": WAVE_FORMAT, "status": "prepared", "created_at": now, "updated_at": now,
                         "temporal_origin_iso": source_temporal_origin,
                         "wave_directory": "Wave", "source_avac_run": str(avac_root),
                         "source_avac_updated_at": source.get("updated_at"), "configuration": "impulse_configuration.yaml",
                         "source_duration_seconds": duration, "source_output_intervals": output_count,
                         "wave_domain": wave_domain, "wave_parameters": settings, "gauges": gauge_config,
                         "coupling_mode": "internal_shoreline", "shoreline_faces": int(shoreline_faces.shape[0]),
                         "shoreline_guard_cells": stabilized_cells,
                         "shoreline_guard_rim_cells": selected_radius,
                         "crs_authid": lake_raster.crs_authid})
    return root
