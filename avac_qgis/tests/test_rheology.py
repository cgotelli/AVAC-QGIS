from __future__ import annotations

import numpy as np
import pytest

from avac_qgis.core.configuration import controlled_values, load_complete_configuration
from avac_qgis.core.rheology import altitude_zone_ids


def test_altitude_zone_ids_match_solver_lower_bound_convention():
    elevations = np.array([[np.nan, 1500.0, 1680.0], [1680.1, 1900.0, 2500.0]])

    result = altitude_zone_ids(elevations, [1680.0, 1900.0])

    assert result.dtype == np.uint16
    assert np.array_equal(result, np.array([[0, 1, 2], [2, 3, 3]], dtype=np.uint16))


def test_altitude_zone_ids_rejects_nonascending_thresholds():
    with pytest.raises(ValueError, match="strictly ascending"):
        altitude_zone_ids(np.array([[1200.0]]), [1700.0, 1700.0])


def test_lac_lachat_two_zone_configuration_classifies_high_terrain():
    """The published two-zone case must retain its >= 1680 m upper zone."""
    from pathlib import Path

    config = Path(__file__).resolve().parents[2] / "avac-main" / "src" / "AVAC" / "AVAC_configuration300.yaml"
    values = controlled_values(load_complete_configuration(config))

    assert values["rheology.z_breaks"] == [1680]
    assert np.array_equal(
        altitude_zone_ids(np.array([[1679.99, 1680.0, 2200.0]]), values["rheology.z_breaks"]),
        np.array([[1, 2, 2]], dtype=np.uint16),
    )
