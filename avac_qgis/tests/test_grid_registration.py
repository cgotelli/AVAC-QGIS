"""Regression coverage for AVAC's QGIS terrain/release/qinit coordinates."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np

from avac_qgis.core.preprocessing import (
    QINIT_BINARY_HEADER,
    QINIT_BINARY_MAGIC,
    raster_from_qgis_layer,
    read_avac_topography,
    release_coverage_from_rings,
    write_init_binary,
    write_topography,
)


class _Extent:
    """Small QgsRectangle-compatible fixture with outer raster edges."""

    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        self.xmin, self.ymin, self.xmax, self.ymax = xmin, ymin, xmax, ymax

    def xMinimum(self) -> float:
        return self.xmin

    def xMaximum(self) -> float:
        return self.xmax

    def yMinimum(self) -> float:
        return self.ymin

    def yMaximum(self) -> float:
        return self.ymax

    def width(self) -> float:
        return self.xmax - self.xmin

    def height(self) -> float:
        return self.ymax - self.ymin

    def isNull(self) -> bool:
        return self.width() <= 0.0 or self.height() <= 0.0

    def intersect(self, other: "_Extent") -> "_Extent":
        return _Extent(
            max(self.xmin, other.xmin), max(self.ymin, other.ymin),
            min(self.xmax, other.xmax), min(self.ymax, other.ymax),
        )


class _Block:
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height

    def dataType(self):
        # Exercise the provider-value fallback so this fixture does not need
        # to imitate QGIS's native byte-buffer implementation.
        return None

    def data(self) -> bytes:
        return b""

    def value(self, row: int, column: int) -> float:
        return float(100 * row + column)


class _Provider:
    def __init__(self):
        self.block_calls: list[tuple[int, _Extent, int, int]] = []

    def bandCount(self) -> int:
        return 1

    def block(self, band: int, extent: _Extent, width: int, height: int) -> _Block:
        self.block_calls.append((band, extent, width, height))
        return _Block(width, height)

    def sourceHasNoDataValue(self, _band: int) -> bool:
        return False


class _Crs:
    def isValid(self) -> bool:
        return True

    def authid(self) -> str:
        return "EPSG:2056"

    def toWkt(self) -> str:
        return ""


class _Layer:
    def __init__(self, extent: _Extent, width: int, height: int):
        self._extent, self._width, self._height = extent, width, height
        self.provider = _Provider()

    def isValid(self) -> bool:
        return True

    def crs(self) -> _Crs:
        return _Crs()

    def dataProvider(self) -> _Provider:
        return self.provider

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def extent(self) -> _Extent:
        return self._extent

    def name(self) -> str:
        return "fixture DEM"


def _install_fake_qgis(monkeypatch) -> None:
    data_type = SimpleNamespace(
        Byte=object(), UInt16=object(), Int16=object(), UInt32=object(),
        Int32=object(), Float32=object(), Float64=object(),
    )
    core = ModuleType("qgis.core")
    core.Qgis = SimpleNamespace(DataType=data_type)
    package = ModuleType("qgis")
    package.core = core
    monkeypatch.setitem(sys.modules, "qgis", package)
    monkeypatch.setitem(sys.modules, "qgis.core", core)


def test_qgis_cells_release_topography_and_qinit_share_one_registration(tmp_path, monkeypatch) -> None:
    """A provider's edge extent must become centre axes everywhere downstream."""
    _install_fake_qgis(monkeypatch)
    layer = _Layer(_Extent(100.0, 200.0, 110.0, 208.0), 5, 4)

    raster = raster_from_qgis_layer(layer)

    assert np.array_equal(raster.x, np.array([101.0, 103.0, 105.0, 107.0, 109.0]))
    assert np.array_equal(raster.y, np.array([201.0, 203.0, 205.0, 207.0]))
    assert raster.metadata == {
        "xmin": 100.0, "xmax": 110.0, "ymin": 200.0, "ymax": 208.0,
        "ncols": 5, "nrows": 4, "cellsize": 2.0, "nodata_value": -9999.0,
    }
    # Provider rows arrive north-to-south; AVAC arrays are south-to-north.
    assert raster.z[0, 0] == 300.0 and raster.z[-1, -1] == 4.0

    # The physical cell [104, 106] x [204, 206] is exactly one DEM cell.
    release = np.array([
        [104.0, 204.0], [106.0, 204.0], [106.0, 206.0],
        [104.0, 206.0], [104.0, 204.0],
    ])
    coverage = release_coverage_from_rings([(release, [])], raster.x, raster.y, 2.0)
    assert coverage[2, 2] == 1.0
    assert float(np.sum(coverage)) == 1.0

    topography = tmp_path / "topography.asc"
    qinit = tmp_path / "init.avacbin"
    write_topography(topography, raster)
    write_init_binary(qinit, raster, coverage)

    # The terrain header retains outer edges, but a qinit binary stores the
    # centres of its first west and north cells.  The implied source-cell
    # envelopes must be identical; this catches both the former shift and its
    # endpoint-induced stretch.
    lines = topography.read_text(encoding="utf-8").splitlines()
    assert lines[:5] == [
        "ncols 5", "nrows 4", "xllcorner 100.0", "yllcorner 200.0", "cellsize 2.0",
    ]
    restored = read_avac_topography(topography, "EPSG:2056")
    assert np.array_equal(restored.x, raster.x)
    assert np.array_equal(restored.y, raster.y)
    assert restored.metadata == raster.metadata

    with qinit.open("rb") as handle:
        header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
    magic, ncols, nrows, components, _flags, xlow, yhigh, dx, dy = header
    assert (magic, ncols, nrows, components, dx, dy) == (QINIT_BINARY_MAGIC, 5, 4, 1, 2.0, 2.0)
    assert (xlow - .5 * dx, xlow + (ncols - .5) * dx) == (100.0, 110.0)
    assert (yhigh - (nrows - .5) * dy, yhigh + .5 * dy) == (200.0, 208.0)


def test_qgis_explicit_grid_size_uses_n_cells_not_n_plus_one_samples(monkeypatch) -> None:
    """Explicit coarsening keeps centre spacing and source-extent coverage."""
    _install_fake_qgis(monkeypatch)
    layer = _Layer(_Extent(0.0, 0.0, 12.0, 8.0), 12, 8)

    raster = raster_from_qgis_layer(layer, grid_cell_size=2.0)

    assert layer.provider.block_calls[-1][2:] == (6, 4)
    assert np.array_equal(raster.x, np.array([1.0, 3.0, 5.0, 7.0, 9.0, 11.0]))
    assert np.array_equal(raster.y, np.array([1.0, 3.0, 5.0, 7.0]))
    assert raster.metadata["cellsize"] == 2.0
    assert raster.metadata["xmin"] == 0.0 and raster.metadata["xmax"] == 12.0
    assert raster.metadata["ymin"] == 0.0 and raster.metadata["ymax"] == 8.0

    cropped = raster_from_qgis_layer(
        layer, extent=_Extent(2.0, 2.0, 10.0, 6.0), grid_cell_size=2.0,
    )
    assert layer.provider.block_calls[-1][2:] == (4, 2)
    assert np.array_equal(cropped.x, np.array([3.0, 5.0, 7.0, 9.0]))
    assert np.array_equal(cropped.y, np.array([3.0, 5.0]))
    assert cropped.metadata["xmin"] == 2.0 and cropped.metadata["xmax"] == 10.0
    assert cropped.metadata["ymin"] == 2.0 and cropped.metadata["ymax"] == 6.0
