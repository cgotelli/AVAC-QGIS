"""Internal shoreline coupling conversion regression tests."""

from __future__ import annotations

import numpy as np
import pytest

from avac_qgis.core.wave_boundaries import (
    _finite_boundary_state,
    _sample_conserved_components,
    _source_rates,
    _write_internal_inflow,
)


def test_only_inward_flux_becomes_density_scaled_water_source(tmp_path):
    faces = np.array([
        [0.5, 0.5, 0.0, 0.5, 1.0, 0.0, 1.0],
        [0.5, 0.5, 0.5, 0.0, 0.0, 1.0, 1.0],
        [1.5, 0.5, 2.0, 0.5, -1.0, 0.0, 1.0],
    ])
    cells, rates, active, replaced = _source_rates(
        faces,
        np.array([2.0, 2.0, 2.0]),
        np.array([4.0, 0.0, 4.0]),
        np.array([0.0, 2.0, 0.0]),
        damping=.25, cell_size=1.0, epsilon=1e-6,
    )
    assert active == 2 and replaced == 0
    assert np.array_equal(cells, np.array([[.5, .5]]))
    # Two 1 m faces carry 1.0 and 0.5 m3/s water; momentum follows AVAC velocity.
    # These are integrated rates, not rates per base-grid cell area.
    assert np.allclose(rates, np.array([[1.5, 2.0, .5]]))
    path = tmp_path / "internal_inflow.data"
    all_rates = np.stack((rates, rates * 2.0))
    _write_internal_inflow(path, np.array([0.0, 1.0]), cells, all_rates)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["2", "2 1", "0 1"]
    assert len(lines) == 6


def test_conservative_source_rates_do_not_depend_on_base_cell_area():
    face = np.array([[2.0, 2.0, 1.0, 2.0, 1.0, 0.0, 2.0]])
    _, coarse, _, _ = _source_rates(
        face, np.array([2.0]), np.array([4.0]), np.array([0.0]),
        damping=.25, cell_size=2.0, epsilon=1e-6,
    )
    _, fine, _, _ = _source_rates(
        face, np.array([2.0]), np.array([4.0]), np.array([0.0]),
        damping=.25, cell_size=.5, epsilon=1e-6,
    )
    assert np.allclose(coarse, np.array([[2.0, 4.0, 0.0]]))
    assert np.array_equal(fine, coarse)


def test_nonfinite_samples_are_zeroed():
    depth, hu, hv, replaced = _finite_boundary_state(
        np.array([1.0, np.nan]), np.array([0.5, 1.0]), np.array([0.0, 2.0]), epsilon=1e-6,
    )
    assert replaced == 1
    assert np.isfinite(depth).all() and np.isfinite(hu).all() and np.isfinite(hv).all()


def test_component_sampling_is_scipy_free_and_preserves_no_coverage_vectors():
    class Grid:
        c_centers = np.meshgrid(np.array([.5, 1.5]), np.array([.5, 1.5]), indexing="ij")

    class State:
        grid = Grid()
        q = np.array([
            [[1., 2.], [3., 4.]],
            [[10., 20.], [30., 40.]],
            [[100., 200.], [300., 400.]],
        ])

    class Solution:
        states = [State()]

    x = np.array([1., 4.])
    h, hu, hv = _sample_conserved_components(Solution(), x, np.array([1., 4.]))
    assert np.allclose((h[0], hu[0], hv[0]), (2.5, 25., 250.))
    assert np.isnan(h[1]) and np.isnan(hu[1]) and np.isnan(hv[1])


def test_source_rates_normalizes_one_face_scalar_and_reports_other_mismatches():
    face = np.array([[.5, .5, 0., .5, 1., 0., 1.]])
    cells, rates, active, replaced = _source_rates(
        face, np.array(2.), np.array(4.), np.array(0.),
        damping=.25, cell_size=1., epsilon=1e-6,
    )
    assert active == 1 and replaced == 0
    assert np.array_equal(cells, np.array([[.5, .5]]))
    assert np.allclose(rates, np.array([[1., 2., 0.]]))
    with pytest.raises(ValueError, match="depth samples .* do not match"):
        _source_rates(
            np.vstack((face, face)), np.array(2.), np.array([4., 4.]), np.array([0., 0.]),
            damping=.25, cell_size=1., epsilon=1e-6,
        )
