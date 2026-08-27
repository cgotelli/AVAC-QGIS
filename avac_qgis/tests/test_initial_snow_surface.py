"""Pure regression checks for the truthful AVAC t=0 snow-surface view."""

from __future__ import annotations

import numpy as np
from types import SimpleNamespace

from avac_qgis.core.preprocessing import AvacRaster, initial_snow_surface_elevation
from avac_qgis.core.results import _avac_frame_fields


raster = AvacRaster(
    np.array([0.5, 1.5]), np.array([0.5, 1.5]),
    np.array([[1000.0, 1001.0], [np.nan, 1003.0]]),
    {
        "xmin": 0.0, "xmax": 2.0, "ymin": 0.0, "ymax": 2.0,
        "ncols": 2, "nrows": 2, "cellsize": 1.0, "nodata_value": -9999.0,
    },
    "EPSG:2056", 1,
)
depth = np.array([[1.5, 0.0], [4.0, 2.0]])
surface = initial_snow_surface_elevation(raster, depth)
assert np.allclose(surface[[0, 0, 1], [0, 1, 1]], [1001.5, 1001.0, 1005.0])
assert np.isnan(surface[1, 0])

try:
    initial_snow_surface_elevation(raster, np.zeros((1, 1)))
except ValueError as exc:
    assert "shape does not match" in str(exc)
else:
    raise AssertionError("mismatched initial depth should be rejected")

print("initial AVAC snow-surface elevation: PASS")

# FGout arrays may be stored x-major.  The temporal materializer must orient
# eta exactly like depth and preserve the absolute surface elevation range.
frame = SimpleNamespace(
    x=np.array([10.0, 12.0, 14.0]),
    y=np.array([20.0, 22.0]),
    h=np.array([[1.0, 0.0], [2.0, 3.0], [0.0, 4.0]]),
    s=np.array([[5.0, 0.0], [6.0, 7.0], [0.0, 8.0]]),
    eta=np.array([[1001.0, 1000.0], [1004.0, 1005.0], [1004.0, 1009.0]]),
)
x, y, fields = _avac_frame_fields(frame, 300.0, 7)
assert fields["depth"].shape == fields["snow_surface_elevation"].shape == (2, 3)
assert np.array_equal(fields["snow_surface_elevation"], frame.eta.T)
assert np.array_equal(x, frame.x) and np.array_equal(y, frame.y)

print("temporal AVAC snow-surface elevation orientation: PASS")
