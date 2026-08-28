from __future__ import annotations

import numpy as np
import pytest

from avac_qgis.core.lake_polygon import connected_lake_mask, seed_cell, write_lake_polygon
from avac_qgis.core.preprocessing import AvacRaster


def _raster(values: np.ndarray) -> AvacRaster:
    rows, columns = values.shape
    return AvacRaster(
        np.arange(columns, dtype=float) + .5,
        np.arange(rows, dtype=float) + .5,
        np.asarray(values, dtype=float),
        {
            "xmin": 0., "xmax": float(columns), "ymin": 0., "ymax": float(rows),
            "ncols": columns, "nrows": rows, "cellsize": 1., "nodata_value": -9999.,
        },
        "EPSG:2056",
        1,
    )


def test_seeded_lake_uses_only_the_selected_four_connected_basin():
    elevations = np.full((7, 9), 10.)
    elevations[2:5, 2:5] = 4.
    elevations[3, 5] = 4.  # east-west face connection
    elevations[1, 7] = 4.  # disconnected depression below the same level
    raster = _raster(elevations)

    seed = seed_cell(raster, 3.2, 3.8)
    mask = connected_lake_mask(raster.z, seed, 5.)

    assert seed == (3, 3)
    assert np.count_nonzero(mask) == 10
    assert mask[3, 5]
    assert not mask[1, 7]


def test_lake_seed_must_be_wet_and_contour_must_close_inside_dem():
    elevations = np.full((5, 5), 10.)
    elevations[2, 2] = 6.
    with pytest.raises(ValueError, match="above the 5 m water level"):
        connected_lake_mask(elevations, (2, 2), 5.)

    elevations[2, 2] = 4.
    elevations[2, 1] = 4.
    elevations[2, 0] = 4.
    with pytest.raises(ValueError, match="reaches the terrain DEM edge"):
        connected_lake_mask(elevations, (2, 2), 5.)

    open_window = connected_lake_mask(elevations, (2, 2), 5., require_closed=False)
    assert open_window[2, 0]


def test_seed_cell_rejects_points_outside_dem():
    raster = _raster(np.ones((3, 4)))
    with pytest.raises(ValueError, match="outside the terrain DEM"):
        seed_cell(raster, 4., 1.)


def test_connected_lake_is_written_as_one_persistent_polygon(tmp_path):
    pytest.importorskip("osgeo")
    from osgeo import ogr

    elevations = np.full((7, 7), 10.)
    elevations[2:5, 2:5] = 4.
    raster = _raster(elevations)
    mask = connected_lake_mask(elevations, (3, 3), 5.)
    path = write_lake_polygon(
        tmp_path / "lake.gpkg", raster, mask,
        water_level=5., seed_x=3.5, seed_y=3.5,
    )

    dataset = ogr.Open(str(path))
    assert dataset is not None
    layer = dataset.GetLayerByName("lake")
    assert layer.GetFeatureCount() == 1
    feature = layer.GetNextFeature()
    assert feature.GetField("inside") == 1
    assert feature.GetField("water_m") == 5.
    assert feature.GetField("cells") == 9
