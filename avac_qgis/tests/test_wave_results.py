import numpy as np

from avac_qgis.core.wave_results import wave_temporal_values


def test_water_elevation_is_eta_only_in_wet_cells():
    bed = np.array([[1968.0, 1971.0], [1969.5, 1970.0]])
    depth = np.array([[2.0, 0.0], [0.5, 0.00001]])
    initial_surface = np.full((2, 2), 1970.0)

    elevation = wave_temporal_values("water_elevation", bed, depth, initial_surface)

    assert elevation[0, 0] == 1970.0
    assert elevation[1, 0] == 1970.0
    assert np.isnan(elevation[0, 1])
    assert np.isnan(elevation[1, 1])


def test_wave_depth_and_displacement_remain_distinct():
    bed = np.array([[10.0]])
    depth = np.array([[2.5]])
    initial_surface = np.array([[11.0]])

    assert wave_temporal_values("depth", bed, depth, initial_surface)[0, 0] == 2.5
    assert wave_temporal_values("surface_displacement", bed, depth, initial_surface)[0, 0] == 1.5
