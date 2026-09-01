from __future__ import annotations

import numpy as np
import pytest

from avac_qgis.core.preprocessing import (
    AvacRaster,
    initial_depth_from_release,
    release_coverage_from_rings,
)


def test_release_coverage_preserves_fractional_boundary_area_and_union() -> None:
    x = np.array([0.0, 1.0])
    y = np.array([0.0, 1.0])
    rectangle = np.array([
        [-0.5, -0.5], [0.25, -0.5], [0.25, 0.5], [-0.5, 0.5], [-0.5, -0.5],
    ])
    # Supplying the same polygon twice must still represent its geometric
    # union, not double the initialized release volume.
    coverage = release_coverage_from_rings(
        [(rectangle, []), (rectangle, [])], x, y, 1.0,
    )
    assert coverage == pytest.approx(np.array([[0.75, 0.0], [0.0, 0.0]]))
    assert float(np.sum(coverage)) == pytest.approx(0.75)


def test_release_coverage_subtracts_holes() -> None:
    x = np.array([0.0])
    y = np.array([0.0])
    exterior = np.array([
        [-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [-0.5, -0.5],
    ])
    hole = np.array([
        [-0.25, -0.25], [0.25, -0.25], [0.25, 0.25], [-0.25, 0.25], [-0.25, -0.25],
    ])
    coverage = release_coverage_from_rings([(exterior, [hole])], x, y, 1.0)
    assert coverage[0, 0] == pytest.approx(0.75)


def test_initial_depth_uses_cell_average_release_fraction() -> None:
    raster = AvacRaster(
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
        np.zeros((2, 2)),
        {"cellsize": 1.0, "ncols": 2, "nrows": 2, "nodata_value": -9999.0},
        "LOCAL_CS[\"test\"]",
        1,
    )
    coverage = np.array([[0.25, 1.0], [0.0, 0.5]])
    depth = initial_depth_from_release(
        raster,
        coverage,
        {
            "d0": 2.0,
            "z_ref": 0.0,
            "gradient_hypso": 0.0,
            "theta_cr": 30.0,
            "nu": 0.2,
            "correction_elevation": False,
            "correction_slope": False,
        },
    )
    assert depth == pytest.approx(np.array([[0.5, 2.0], [0.0, 1.0]]))


def test_initial_depth_rejects_invalid_release_fraction() -> None:
    raster = AvacRaster(
        np.array([0.0]), np.array([0.0]), np.zeros((1, 1)),
        {"cellsize": 1.0, "ncols": 1, "nrows": 1, "nodata_value": -9999.0},
        "LOCAL_CS[\"test\"]", 1,
    )
    with pytest.raises(ValueError, match="between zero and one"):
        initial_depth_from_release(raster, np.array([[1.1]]), {"d0": 1.0})
