"""Regression tests for physically valid AVAC release-depth preparation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avac_qgis.core.configuration import (
    controlled_values as configuration_values,
    load_complete_configuration,
    validate_controlled_values,
)
from avac_qgis.core.preprocessing import (
    AvacRaster,
    QINIT_BINARY_HEADER,
    initial_depth_from_release,
    write_init_binary,
    write_init_xyz,
)


TEMPLATE = Path(__file__).resolve().parents[1] / "resources" / "AVAC_configuration100.yaml"


def _raster(values: np.ndarray | None = None) -> AvacRaster:
    terrain = np.asarray(values if values is not None else np.zeros((2, 2)), dtype=float)
    return AvacRaster(
        np.arange(terrain.shape[1], dtype=float),
        np.arange(terrain.shape[0], dtype=float),
        terrain,
        {
            "xmin": 0.0,
            "xmax": float(terrain.shape[1]),
            "ymin": 0.0,
            "ymax": float(terrain.shape[0]),
            "ncols": terrain.shape[1],
            "nrows": terrain.shape[0],
            "cellsize": 1.0,
            "nodata_value": -9999.0,
        },
        "EPSG:2056",
        1,
    )


def _release(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "d0": 1.0,
        "z_ref": 0.0,
        "gradient_hypso": 0.0,
        "theta_cr": 30.0,
        "nu": 0.2,
        "correction_elevation": False,
        "correction_slope": False,
    }
    parameters.update(overrides)
    return parameters


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("d0", np.nan),
        ("d0", np.inf),
        ("z_ref", np.nan),
        ("gradient_hypso", np.inf),
        ("theta_cr", np.nan),
        ("nu", -np.inf),
        ("correction_slope", "false"),
    ],
)
def test_initial_depth_rejects_nonfinite_or_invalid_release_inputs(parameter: str, value: object) -> None:
    with pytest.raises(ValueError, match="Invalid AVAC release parameters"):
        initial_depth_from_release(_raster(), np.ones((2, 2)), _release(**{parameter: value}))


def test_controlled_configuration_rejects_nonfinite_release_inputs() -> None:
    values = configuration_values(load_complete_configuration(TEMPLATE))
    values["release.d0"] = np.nan
    issues = validate_controlled_values(values)
    assert "Release d0 must be a finite number." in issues

    values = configuration_values(load_complete_configuration(TEMPLATE))
    values["release.d0"] = -0.01
    issues = validate_controlled_values(values)
    assert "Release d0 must be non-negative." in issues


def test_controlled_configuration_leaves_finite_correction_choices_to_candidate_check() -> None:
    values = configuration_values(load_complete_configuration(TEMPLATE))
    values.update({
        "release.z_ref": -250.0,
        "release.gradient_hypso": -0.3,
        "release.theta_cr": 105.0,
        "release.nu": 1.5,
    })
    assert not validate_controlled_values(values)


def test_hypsometric_correction_rejects_negative_candidate_before_fractional_scaling() -> None:
    coverage = np.array([[0.25, 0.0], [0.0, 1.0]])
    with pytest.raises(ValueError, match="negative candidate depth"):
        initial_depth_from_release(
            _raster(),
            coverage,
            _release(
                z_ref=2000.0,
                gradient_hypso=0.1,
                correction_elevation=True,
            ),
        )


def test_slope_correction_rejects_negative_candidate() -> None:
    # The 30 degree terrain slope is above the correction threshold.  This
    # parameter combination gives a negative De Quervain factor, which cannot
    # represent a mobile thickness and must not be written as qinit mass.
    slope = np.tan(np.deg2rad(30.0))
    terrain = np.array([[0.0, slope], [0.0, slope]])
    with pytest.raises(ValueError, match="negative candidate depth"):
        initial_depth_from_release(
            _raster(terrain),
            np.array([[0.25, 1.0], [0.0, 0.5]]),
            _release(theta_cr=50.0, nu=0.9, correction_slope=True),
        )


def test_release_over_nodata_terrain_is_rejected() -> None:
    terrain = np.array([[np.nan, 1.0], [1.0, 1.0]])
    with pytest.raises(ValueError, match="non-finite DEM elevation"):
        initial_depth_from_release(_raster(terrain), np.array([[0.5, 0.0], [0.0, 0.0]]), _release())


@pytest.mark.parametrize("invalid_depth", [np.array([[-0.1, 0.0], [0.0, 0.0]]), np.array([[np.nan, 0.0], [0.0, 0.0]])])
def test_qinit_writers_reject_invalid_depth_values_before_creating_files(tmp_path, invalid_depth: np.ndarray) -> None:
    raster = _raster()
    for writer, suffix in ((write_init_binary, ".avacbin"), (write_init_xyz, ".xyz")):
        path = tmp_path / f"init{suffix}"
        with pytest.raises(ValueError, match="finite and non-negative"):
            writer(path, raster, invalid_depth)
        assert not path.exists()


def test_binary_qinit_rounding_keeps_tiny_finite_depths_finite(tmp_path) -> None:
    raster = _raster()
    tiny = np.nextafter(0.0, 1.0)
    path = tmp_path / "tiny.avacbin"
    write_init_binary(path, raster, np.array([[tiny, 0.0], [0.0, 0.0]]))
    with path.open("rb") as handle:
        handle.read(QINIT_BINARY_HEADER.size)
        values = np.fromfile(handle, dtype="<f8")
    assert np.all(np.isfinite(values))
    assert np.all(values >= 0.0)
    assert tiny in values
