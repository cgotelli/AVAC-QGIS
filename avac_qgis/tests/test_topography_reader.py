"""Round-trip checks for the solver-format AVAC topography reader."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from avac_qgis.core.preprocessing import AvacRaster, read_avac_topography, write_topography


with TemporaryDirectory() as temporary:
    source = Path(temporary) / "topography.asc"
    raster = AvacRaster(
        # Axes name values at cell centres; topotype-3 headers retain the
        # outer cell corners at 100/200.
        np.array([101.0, 103.0, 105.0]), np.array([201.0, 203.0]),
        np.array([[1.0, np.nan, 3.0], [4.0, 5.0, 6.0]]),
        {"xmin": 100.0, "xmax": 106.0, "ymin": 200.0, "ymax": 204.0,
         "ncols": 3, "nrows": 2, "cellsize": 2.0, "nodata_value": -9999.0},
        "EPSG:2056", 1,
    )
    write_topography(source, raster)
    restored = read_avac_topography(source, "EPSG:2056")
    assert np.array_equal(restored.x, raster.x)
    assert np.array_equal(restored.y, raster.y)
    assert np.allclose(restored.z, raster.z, equal_nan=True)
    assert restored.crs_authid == "EPSG:2056"

print("AVAC solver-format topography reader: PASS")
