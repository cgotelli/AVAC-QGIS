from __future__ import annotations

import numpy as np
import pytest

from avac_qgis.core.preprocessing import (
    AvacRaster,
    PreparationCancelled,
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


def test_boundary_only_coverage_matches_direct_full_grid_sampling() -> None:
    """The fast path must retain the former subcell union definition exactly."""
    x = np.arange(7, dtype=float) + 0.5
    y = np.arange(6, dtype=float) + 0.5
    triangle = np.array([[0.2, 0.1], [6.7, 1.8], [2.3, 5.9], [0.2, 0.1]])
    rectangle = np.array([[3.1, 1.1], [6.4, 1.1], [6.4, 4.7], [3.1, 4.7], [3.1, 1.1]])
    hole = np.array([[4.0, 2.0], [5.0, 2.0], [5.0, 3.0], [4.0, 3.0], [4.0, 2.0]])
    rings = [(triangle, []), (rectangle, [hole])]
    samples = 8

    offsets = ((np.arange(samples, dtype=float) + 0.5) / samples - 0.5)
    offset_x, offset_y = np.meshgrid(offsets, offsets)
    expected = np.zeros((y.size, x.size), dtype=float)
    from matplotlib.path import Path as MplPath
    for row, y_value in enumerate(y):
        for column, x_value in enumerate(x):
            points = np.column_stack((x_value + offset_x.ravel(), y_value + offset_y.ravel()))
            inside_any = np.zeros(points.shape[0], dtype=bool)
            for exterior, holes in rings:
                inside = MplPath(exterior).contains_points(points)
                for interior in holes:
                    inside &= ~MplPath(interior).contains_points(points)
                inside_any |= inside
            expected[row, column] = np.mean(inside_any)

    updates: list[float] = []
    actual = release_coverage_from_rings(
        rings, x, y, 1.0, subsamples=samples, progress=updates.append,
    )
    assert np.array_equal(actual, expected)
    assert updates[-1] == 1.0
    assert np.all(np.diff(updates) >= 0.0)


def test_release_coverage_honors_cancellation() -> None:
    square = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]])
    with pytest.raises(PreparationCancelled):
        release_coverage_from_rings(
            [(square, [])], np.array([0.5, 1.5]), np.array([0.5, 1.5]), 1.0,
            cancelled=lambda: True,
        )


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
