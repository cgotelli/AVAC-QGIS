"""Shared altitude-zone classification used by the AVAC rheology preview."""

from __future__ import annotations

import numpy as np


def altitude_zone_ids(elevation: np.ndarray, lower_bounds) -> np.ndarray:
    """Return one-based AVAC rheology zone IDs for finite DEM elevations.

    Zone 1 applies below the first configured lower bound.  At each bound the
    next zone applies, matching the solver's ``z >= lower_bound`` convention.
    Zero is reserved for DEM NoData cells.
    """
    values = np.asarray(elevation, dtype=float)
    bounds = np.asarray(list(lower_bounds), dtype=float)
    if bounds.ndim != 1 or not np.all(np.isfinite(bounds)):
        raise ValueError("Rheology-zone lower elevations must be finite values.")
    if bounds.size and np.any(np.diff(bounds) <= 0.0):
        raise ValueError("Rheology-zone lower elevations must be strictly ascending.")
    result = np.zeros(values.shape, dtype=np.uint16)
    finite = np.isfinite(values)
    result[finite] = np.searchsorted(bounds, values[finite], side="right").astype(np.uint16) + 1
    return result
