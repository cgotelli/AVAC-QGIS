from __future__ import annotations

import numpy as np
import pytest

from avac4qgis_validation.kerswell import undisturbed_rear_position


def test_rear_position_ignores_small_amr_depth_perturbations() -> None:
    x = np.arange(-4.0, 1.0)
    depth = np.asarray([1.0, 1.0 - 4.0e-4, 1.0 + 7.0e-4, 0.996, 0.8])

    assert undisturbed_rear_position(x, depth, 1.0) == pytest.approx(-2.0)


def test_rear_position_is_postprocessing_only() -> None:
    x = np.asarray([-2.0, -1.0, 0.0])
    depth = np.asarray([1.0, 0.9995, 0.8])
    depth_before = depth.copy()

    undisturbed_rear_position(x, depth, 1.0)

    np.testing.assert_array_equal(depth, depth_before)


@pytest.mark.parametrize("reference_depth,relative_tolerance", [(0.0, 1.0e-3), (1.0, 0.0)])
def test_rear_position_rejects_nonpositive_controls(
    reference_depth: float,
    relative_tolerance: float,
) -> None:
    with pytest.raises(ValueError):
        undisturbed_rear_position(
            np.asarray([0.0]),
            np.asarray([1.0]),
            reference_depth,
            relative_tolerance=relative_tolerance,
        )
