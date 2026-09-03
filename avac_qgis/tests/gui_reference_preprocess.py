"""Materialize a QGIS-independent oracle for the current preprocessing path.

The reference deliberately uses the same pure fractional-release routines as
the plugin.  Its purpose is to compare QGIS raster/geometry ingestion and file
formatting, not to preserve the obsolete centre-point Boolean release mask.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import yaml

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from avac_qgis.core.preprocessing import (  # noqa: E402
    AvacRaster,
    geoclaw_topography_halo,
    initial_depth_from_release,
    release_coverage_from_rings,
    write_init_xyz,
    write_topography,
)


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")


def read_ascii_raster(path: Path):
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    meta = {}
    for line in lines[:12]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].lower().rstrip(":") in {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}:
            meta[parts[0].lower().rstrip(":")] = float(parts[1])
    skip = next(index for index, line in enumerate(lines) if line.strip() and line.strip().split()[0].replace(".", "", 1).replace("-", "", 1).isdigit())
    grid = np.genfromtxt(path, skip_header=skip)
    nodata = meta.get("nodata_value", -9999)
    grid = np.where(np.isclose(grid, nodata), np.nan, grid)
    ncols, nrows, cell = int(meta["ncols"]), int(meta["nrows"]), meta["cellsize"]
    xmin, ymin = meta["xllcorner"], meta["yllcorner"]
    xmax, ymax = xmin + ncols * cell, ymin + nrows * cell
    # ESRI ``xllcorner``/``yllcorner`` values are outer cell edges.  AVAC's
    # qinit and release fields consume the corresponding cell centres.  The
    # production topography writer adds its GeoClaw-only terrain halo later.
    x = xmin + (np.arange(ncols, dtype=float) + .5) * cell
    y = ymin + (np.arange(nrows, dtype=float) + .5) * cell
    return x, y, grid[::-1, :], {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax, "ncols": ncols, "nrows": nrows, "cellsize": cell, "nodata_value": nodata}


def rings_from_geodataframe(frame):
    """Convert GeoPandas Polygon/MultiPolygon values to preprocessing rings."""
    rings = []
    for geom in frame.geometry:
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms) if geom.geom_type == "MultiPolygon" else []
        for poly in polygons:
            exterior = np.asarray(poly.exterior.coords, dtype=float)[:, :2]
            holes = [np.asarray(interior.coords, dtype=float)[:, :2] for interior in poly.interiors]
            if exterior.shape[0] >= 3:
                rings.append((exterior, holes))
    return rings


def fractional_release_fields(x, y, z, metadata, rings, release):
    """Return the exact current-plugin coverage and depth fields."""
    raster = AvacRaster(x, y, z, metadata, "", 1)
    coverage = release_coverage_from_rings(rings, x, y, float(metadata["cellsize"]))
    return coverage, initial_depth_from_release(raster, coverage, release)


def main() -> None:
    root = Path(os.environ["AVAC_GUI_REFERENCE_ROOT"])
    configuration = Path(os.environ.get(
        "AVAC_QGIS_CANONICAL_CONFIGURATION", CASE / "AVAC" / "AVAC_configuration300.yaml",
    ))
    root.mkdir(parents=True, exist_ok=False)
    x, y, z, metadata = read_ascii_raster(CASE / "Topo" / "topo1m_simple.asc")
    release = yaml.safe_load(configuration.read_text(encoding="utf-8"))["release"]
    coverage, depth = fractional_release_fields(
        x, y, z, metadata, rings_from_geodataframe(gpd.read_file(CASE / "Topo" / "ZA.shp")), release,
    )
    mask = coverage > 0.0
    raster = AvacRaster(x, y, z, metadata, "", 1)
    # GeoClaw treats topotype-3 elevations as nodal values after moving the
    # ESRI lower-left coordinate to the first sample centre.  The halo is
    # terrain-only: qinit retains the original QGIS cell grid.
    write_topography(root / "topography.asc", geoclaw_topography_halo(raster))
    write_init_xyz(root / "init.xyz", raster, depth)
    np.save(root / "coverage.npy", coverage)
    np.save(root / "mask.npy", mask)
    np.save(root / "depth.npy", depth)
    print(
        f"REFERENCE_PREPROCESS configuration={configuration.name} covered_cells={int(mask.sum())} "
        f"fractional_equivalent_cells={coverage.sum():.12g} nonzero={int(np.count_nonzero(depth))} "
        f"min={depth.min():.12g} max={depth.max():.12g} sum={depth.sum():.12g}"
    )


if __name__ == "__main__":
    main()
