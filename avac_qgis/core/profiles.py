"""Reusable, CRS-agnostic AVAC profile sampling and CSV serialization.

QGIS owns geometry editing and coordinate transformation.  This module works
only with an already-transformed polyline and regular raster axes, which keeps
the numerical sampling rule testable without a QGIS GUI session.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


VARIABLE_UNITS = {
    "depth": "m",
    "velocity": "m/s",
    "pressure": "kPa",
    "snow_surface_elevation": "m",
    "water_elevation": "m",
    "surface_displacement": "m",
}
CSV_VALUE_COLUMNS = {
    "depth": "depth_m",
    "velocity": "velocity_ms",
    "pressure": "pressure_kpa",
    "snow_surface_elevation": "snow_surface_elevation_m",
    "water_elevation": "water_elevation_m",
    "surface_displacement": "surface_displacement_m",
}


@dataclass(frozen=True)
class ProfileDataset:
    """Ordered samples for one AVAC variable along one profile line."""

    distance_m: np.ndarray
    x: np.ndarray
    y: np.ndarray
    values: np.ndarray
    variable: str
    source: str
    simulation_time_s: float | None = None
    profile_name: str = "Profile"

    @property
    def unit(self) -> str:
        return VARIABLE_UNITS[self.variable]


def raster_spacing(x: np.ndarray, y: np.ndarray) -> float:
    """Return a defensible automatic spacing: the smaller raster cell size."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.size < 2 or y.size < 2:
        raise ValueError("A profile raster needs at least two x and y coordinates.")
    dx, dy = abs(float(np.median(np.diff(x)))), abs(float(np.median(np.diff(y))))
    if not np.isfinite([dx, dy]).all() or dx <= 0 or dy <= 0:
        raise ValueError("Profile raster axes must be regularly increasing.")
    return min(dx, dy)


def sample_polyline_positions(coords: Iterable[Iterable[float]], spacing: float | None = None, *, count: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample a polyline by cumulative distance, always including both ends.

    ``count`` is retained for exact regression reproduction of the standalone
    GUI's 1,000 equally spaced positions.  Normal QGIS use supplies spacing.
    """
    points = np.asarray(list(coords), dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] < 2:
        raise ValueError("A profile must contain at least two coordinates.")
    points = points[:, :2]
    # QGIS/Shapefile polylines can legitimately repeat a terminal or interior
    # vertex.  Ignore zero-length consecutive segments for sampling without
    # changing the source feature.
    keep = np.r_[True, np.any(np.diff(points, axis=0) != 0.0, axis=1)]
    points = points[keep]
    if points.shape[0] < 2:
        raise ValueError("A profile must contain at least two distinct coordinates.")
    segments = np.diff(points, axis=0)
    lengths = np.hypot(segments[:, 0], segments[:, 1])
    cumulative = np.insert(np.cumsum(lengths), 0, 0.0)
    total = float(cumulative[-1])
    if not np.isfinite(total) or total <= 0:
        raise ValueError("A profile must have positive length.")
    if count is not None:
        if count < 2:
            raise ValueError("Profile sample count must be at least two.")
        distances = np.linspace(0.0, total, int(count))
    else:
        if spacing is None or not np.isfinite(spacing) or spacing <= 0:
            raise ValueError("Profile sample spacing must be positive.")
        # Ceiling keeps nominal spacing no coarser than the requested value.
        distances = np.linspace(0.0, total, int(np.ceil(total / spacing)) + 1)
    indices = np.searchsorted(cumulative, distances, side="right") - 1
    indices = np.clip(indices, 0, len(segments) - 1)
    starts = cumulative[indices]
    fractions = np.divide(distances - starts, lengths[indices], out=np.zeros_like(distances), where=lengths[indices] > 0)
    sampled = points[indices] + segments[indices] * fractions[:, None]
    return distances, sampled[:, 0], sampled[:, 1]


def bilinear_sample(x: np.ndarray, y: np.ndarray, values: np.ndarray, xq: np.ndarray, yq: np.ndarray) -> np.ndarray:
    """Sample cell-centre axes bilinearly; outside and NoData stay ``NaN``.

    Dry AVAC cells are ordinary numerical zero values and deliberately are not
    treated as NoData.  A bilinear footprint containing NoData returns NoData,
    avoiding invented values across an unavailable part of the result.
    """
    x, y, values = np.asarray(x, dtype=float), np.asarray(y, dtype=float), np.asarray(values, dtype=float)
    xq, yq = np.asarray(xq, dtype=float), np.asarray(yq, dtype=float)
    if values.shape != (y.size, x.size) or x.size < 2 or y.size < 2:
        raise ValueError("Profile array shape must match increasing regular x/y axes.")
    if not (np.all(np.diff(x) > 0) and np.all(np.diff(y) > 0)):
        raise ValueError("Profile raster axes must be strictly increasing.")
    result = np.full(xq.shape, np.nan, dtype=float)
    inside = (xq >= x[0]) & (xq <= x[-1]) & (yq >= y[0]) & (yq <= y[-1])
    if not np.any(inside):
        return result
    ids = np.flatnonzero(inside)
    ix = np.clip(np.searchsorted(x, xq[ids], side="right") - 1, 0, x.size - 2)
    iy = np.clip(np.searchsorted(y, yq[ids], side="right") - 1, 0, y.size - 2)
    tx = (xq[ids] - x[ix]) / (x[ix + 1] - x[ix])
    ty = (yq[ids] - y[iy]) / (y[iy + 1] - y[iy])
    z11, z21 = values[iy, ix], values[iy, ix + 1]
    z12, z22 = values[iy + 1, ix], values[iy + 1, ix + 1]
    sampled = (1 - tx) * (1 - ty) * z11 + tx * (1 - ty) * z21 + (1 - tx) * ty * z12 + tx * ty * z22
    sampled[~np.isfinite(z11) | ~np.isfinite(z21) | ~np.isfinite(z12) | ~np.isfinite(z22)] = np.nan
    result[ids] = sampled
    return result


def extract_profile(coords: Iterable[Iterable[float]], x: np.ndarray, y: np.ndarray, values: np.ndarray, variable: str, source: str, *, spacing: float | None = None, count: int | None = None, simulation_time_s: float | None = None, profile_name: str = "Profile") -> ProfileDataset:
    """Return one ordered, bilinearly sampled AVAC profile dataset."""
    if variable not in VARIABLE_UNITS:
        raise ValueError(f"Unsupported AVAC profile variable: {variable}")
    if count is None and spacing is None:
        spacing = raster_spacing(x, y)
    distance, xq, yq = sample_polyline_positions(coords, spacing, count=count)
    sampled = bilinear_sample(x, y, values, xq, yq)
    return ProfileDataset(distance, xq, yq, sampled, variable, source, simulation_time_s, profile_name)


def write_profile_csv(path: str | Path, dataset: ProfileDataset) -> Path:
    """Write simple interoperable CSV with explicit AVAC scientific metadata."""
    path = Path(path)
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("# AVAC-QGIS profile\n")
        handle.write(f"# profile_name={dataset.profile_name}\n")
        handle.write(f"# source={dataset.source}\n")
        handle.write(f"# variable={dataset.variable}\n")
        handle.write(f"# unit={dataset.unit}\n")
        if dataset.simulation_time_s is not None:
            handle.write(f"# simulation_time_s={dataset.simulation_time_s:.12g}\n")
        writer = csv.writer(handle)
        writer.writerow(["distance_m", "x", "y", CSV_VALUE_COLUMNS[dataset.variable]])
        for distance, x_coord, y_coord, value in zip(dataset.distance_m, dataset.x, dataset.y, dataset.values):
            writer.writerow([f"{distance:.12g}", f"{x_coord:.12g}", f"{y_coord:.12g}", f"{value:.12g}" if np.isfinite(value) else ""])
    return path
