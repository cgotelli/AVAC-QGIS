"""Portable AVAC binary initial-condition format regression."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from avac_qgis.core.preprocessing import (
    AvacRaster,
    QINIT_BINARY_HEADER,
    QINIT_BINARY_MAGIC,
    write_init_binary,
)


def main() -> None:
    raster = AvacRaster(
        # qinit headers store the centres of the first/southern-last cells,
        # while raster metadata stores its outer edges.
        np.array([11.0, 13.0, 15.0]),
        np.array([21.0, 23.0]),
        np.zeros((2, 3)),
        {"xmin": 10.0, "xmax": 16.0, "ymin": 20.0, "ymax": 24.0,
         "ncols": 3, "nrows": 2, "cellsize": 2.0, "nodata_value": -9999.0},
        "EPSG:2056",
        1,
    )
    depth = np.array([[1.2345678901234, np.nan, 3.0], [4.0, 5.0, 6.0]])
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "init.avacbin"
        write_init_binary(path, raster, depth)
        with path.open("rb") as handle:
            header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
            payload = np.fromfile(handle, dtype="<f8")
        assert header == (QINIT_BINARY_MAGIC, 3, 2, 1, 0, 11.0, 23.0, 2.0, 2.0)
        assert path.stat().st_size == QINIT_BINARY_HEADER.size + depth.size * 8
        assert np.array_equal(payload.reshape((2, 3)), np.array([
            [4.0, 5.0, 6.0],
            [1.23456789012, 0.0, 3.0],
        ]))
    print("binary qinit header/order/precision: PASS")


if __name__ == "__main__":
    main()
