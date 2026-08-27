"""Materialize a reference using the standalone GUI's current preprocessing code.

This is a dependency-light transcription of the relevant functions because the
standalone GUI imports PyQt6, while the verified AVAC Conda environment does
not.  Algorithmic statements and formatting intentionally match the source.
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import yaml
from matplotlib.path import Path as MplPath


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
ROOT = Path(os.environ["AVAC_GUI_REFERENCE_ROOT"])
CONFIGURATION = Path(os.environ.get("AVAC_QGIS_CANONICAL_CONFIGURATION", CASE / "AVAC" / "AVAC_configuration300.yaml"))


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
    return np.linspace(xmin, xmax, ncols), np.linspace(ymin, ymax, nrows), grid[::-1, :], {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax, "ncols": ncols, "nrows": nrows, "cellsize": cell, "nodata_value": nodata}


def mask(frame, x, y):
    xx, yy = np.meshgrid(x, y)
    points = np.column_stack((xx.ravel(), yy.ravel()))
    inside_any = np.zeros(points.shape[0], dtype=bool)
    for geom in frame.geometry:
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms) if geom.geom_type == "MultiPolygon" else []
        for poly in polygons:
            # Matplotlib's planar predicate needs X/Y.  The canonical ZA has
            # a third (Z) coordinate, which carries no release-area meaning.
            inside = MplPath(np.asarray(poly.exterior.coords)[:, :2]).contains_points(points)
            for interior in poly.interiors:
                inside &= ~MplPath(np.asarray(interior.coords)[:, :2]).contains_points(points)
            inside_any |= inside
    return inside_any.reshape((y.size, x.size))


def initial_depth(z, zone_mask, metadata, release):
    depth = np.zeros_like(z, dtype=float)
    d0, z_ref = float(release["d0"]), float(release["z_ref"])
    gradient_hypso, theta_cr, nu = float(release["gradient_hypso"]), float(release["theta_cr"]), float(release["nu"])
    valid = np.isfinite(z); z_fill = np.nan_to_num(z, nan=float(np.nanmean(z[valid])))
    grad_y, grad_x = np.gradient(z_fill, float(metadata["cellsize"])); slope = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    q_angle = np.arctan(slope); denominator = np.sin(q_angle) - nu * np.cos(q_angle)
    factor1 = np.zeros_like(slope); safe = (q_angle > np.deg2rad(25.0)) & (np.abs(denominator) > 1e-12)
    factor1[safe] = (np.sin(np.deg2rad(theta_cr)) - nu * np.cos(np.deg2rad(theta_cr))) / denominator[safe]
    factor2 = (z - z_ref) * gradient_hypso / 100.0
    depth[zone_mask] = ((d0 + factor2) * factor1)[zone_mask]
    depth[~np.isfinite(depth)] = 0.0
    return depth


def write_topography(path, z, metadata):
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"ncols {z.shape[1]}\nnrows {z.shape[0]}\nxllcorner {float(metadata['xmin'])}\nyllcorner {float(metadata['ymin'])}\ncellsize {float(metadata['cellsize'])}\nNODATA_value {float(metadata['nodata_value'])}\n")
        for row in np.flipud(np.where(np.isfinite(z), z, metadata["nodata_value"])):
            handle.write(" ".join(f"{float(value):.10g}" for value in row) + "\n")


def write_init(path, x, y, depth):
    with path.open("w", encoding="utf-8") as handle:
        for j in range(y.size - 1, -1, -1):
            for i, xv in enumerate(x):
                handle.write(f"{xv:.12g} {y[j]:.12g} {float(depth[j, i]) if np.isfinite(depth[j, i]) else 0.0:.12g}\n")


ROOT.mkdir(parents=True, exist_ok=False)
x, y, z, metadata = read_ascii_raster(CASE / "Topo" / "topo1m_simple.asc")
polygons = gpd.read_file(CASE / "Topo" / "ZA.shp")
release = yaml.safe_load(CONFIGURATION.read_text(encoding="utf-8"))["release"]
zone_mask = mask(polygons, x, y)
depth = initial_depth(z, zone_mask, metadata, release)
write_topography(ROOT / "topography.asc", z, metadata)
write_init(ROOT / "init.xyz", x, y, depth)
np.save(ROOT / "mask.npy", zone_mask)
np.save(ROOT / "depth.npy", depth)
print(f"REFERENCE_PREPROCESS configuration={CONFIGURATION.name} cells={int(zone_mask.sum())} nonzero={int(np.count_nonzero(depth))} min={depth.min():.12g} max={depth.max():.12g} sum={depth.sum():.12g}")
