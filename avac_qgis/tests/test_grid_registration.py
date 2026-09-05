"""Regression coverage for AVAC's QGIS terrain/release/qinit coordinates."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import yaml

from avac_qgis.core.preprocessing import (
    AvacRaster,
    QINIT_BINARY_HEADER,
    QINIT_BINARY_MAGIC,
    configuration_for_raster,
    geoclaw_overlay_topography,
    geoclaw_topography_halo,
    prepare_inputs,
    raster_from_qgis_layer,
    read_avac_topography,
    release_coverage_from_rings,
    write_init_binary,
    write_topography,
)


TEMPLATE = Path(__file__).resolve().parents[1] / "resources" / "AVAC_configuration100.yaml"


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


def _registered_raster(
    ncols: int = 4,
    nrows: int = 4,
    cell_size: float = 1.0,
) -> AvacRaster:
    """Small QGIS-style raster with physical edges and centre coordinates."""
    xmin, ymin = 0.0, 0.0
    xmax, ymax = ncols * cell_size, nrows * cell_size
    return AvacRaster(
        xmin + (np.arange(ncols, dtype=float) + 0.5) * cell_size,
        ymin + (np.arange(nrows, dtype=float) + 0.5) * cell_size,
        np.arange(nrows * ncols, dtype=float).reshape((nrows, ncols)),
        {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "ncols": ncols,
            "nrows": nrows,
            "cellsize": cell_size,
            "nodata_value": -9999.0,
        },
        "EPSG:2056",
        1,
    )


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


def test_full_qgis_domain_has_geoclaw_terrain_support_without_qinit_padding(tmp_path) -> None:
    """The former upper/right loss is fixed without moving the QGIS grid."""
    raster = _registered_raster()
    configuration = configuration_for_raster(
        {"computation": {"cell_size": 2.0}, "dem_extent": {}, "gauges": {}}, raster,
    )
    extent = configuration["dem_extent"]
    assert extent == {
        "xmin": 0.0,
        "xmax": 4.0,
        "ymin": 0.0,
        "ymax": 4.0,
        "nbx": 2,
        "nby": 2,
        "cell_size": 2.0,
        "nodata_value": -9999.0,
    }

    halo = geoclaw_topography_halo(raster)
    assert halo.z.shape == (6, 6)
    assert np.array_equal(halo.z, np.pad(raster.z, ((1, 1), (1, 1)), mode="edge"))
    assert np.array_equal(halo.x, np.array([-.5, .5, 1.5, 2.5, 3.5, 4.5]))
    assert np.array_equal(halo.y, np.array([-.5, .5, 1.5, 2.5, 3.5, 4.5]))
    assert halo.metadata["xmin"] == -1.0 and halo.metadata["xmax"] == 5.0
    assert halo.metadata["ymin"] == -1.0 and halo.metadata["ymax"] == 5.0

    topography = tmp_path / "topography.asc"
    write_topography(topography, halo)
    restored = read_avac_topography(topography, raster.crs_authid)
    assert np.array_equal(restored.x, halo.x)
    assert np.array_equal(restored.y, halo.y)
    # GeoClaw treats these positions as interpolation nodes.  They bracket
    # every solver edge, unlike the unpadded QGIS cell centres.
    assert restored.x[0] < extent["xmin"] < extent["xmax"] < restored.x[-1]
    assert restored.y[0] < extent["ymin"] < extent["ymax"] < restored.y[-1]

    # qinit deliberately remains the original 4-by-4 cell grid; the terrain
    # support halo is not a source of initialized mass.
    qinit = tmp_path / "init.avacbin"
    write_init_binary(qinit, raster, np.ones_like(raster.z))
    with qinit.open("rb") as handle:
        header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
    _magic, ncols, nrows, _components, _flags, xlow, yhigh, dx, dy = header
    assert (ncols, nrows) == (4, 4)
    assert (xlow - .5 * dx, xlow + (ncols - .5) * dx) == (0.0, 4.0)
    assert (yhigh - (nrows - .5) * dy, yhigh + .5 * dy) == (0.0, 4.0)


def test_prepare_inputs_retains_a_release_in_the_former_top_right_loss_cell(tmp_path) -> None:
    raster = _registered_raster(20, 20)
    # This cell was outside the old truncated solver configuration.
    upper_right = np.array([
        [19.0, 19.0], [20.0, 19.0], [20.0, 20.0], [19.0, 20.0], [19.0, 19.0],
    ])
    release = {
        "d0": 1.0,
        "z_ref": 0.0,
        "gradient_hypso": 0.0,
        "theta_cr": 30.0,
        "nu": 0.2,
        "correction_elevation": False,
        "correction_slope": False,
    }
    prepared = prepare_inputs(tmp_path / "run", raster, [(upper_right, [])], TEMPLATE, release)

    assert prepared.coverage[-1, -1] == pytest.approx(1.0)
    assert prepared.depth[-1, -1] == pytest.approx(1.0)
    assert np.count_nonzero(prepared.depth) == 1

    generated = yaml.safe_load(prepared.configuration_path.read_text(encoding="utf-8"))
    assert generated["dem_extent"]["xmin"] == 0.0
    assert generated["dem_extent"]["xmax"] == 20.0
    assert generated["dem_extent"]["ymin"] == 0.0
    assert generated["dem_extent"]["ymax"] == 20.0

    terrain = read_avac_topography(prepared.topo_path, raster.crs_authid)
    assert terrain.z.shape == (22, 22)
    assert terrain.x[0] < 0.0 < 20.0 < terrain.x[-1]
    assert terrain.y[0] < 0.0 < 20.0 < terrain.y[-1]

    with prepared.init_path.open("rb") as handle:
        header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
        payload = np.fromfile(handle, dtype="<f8").reshape((20, 20))
    _magic, ncols, nrows, _components, _flags, xlow, yhigh, dx, dy = header
    assert (ncols, nrows) == (20, 20)
    assert (xlow - .5 * dx, xlow + (ncols - .5) * dx) == (0.0, 20.0)
    assert (yhigh - (nrows - .5) * dy, yhigh + .5 * dy) == (0.0, 20.0)
    # qinit is north-to-south, so the source grid's north-east cell is [0, -1].
    assert payload[0, -1] == pytest.approx(1.0)
    assert np.count_nonzero(payload) == 1


def test_fine_overlay_closes_geoclaw_node_support_at_the_qgis_footprint(tmp_path) -> None:
    """A fine topofile must not override coarse terrain outside its DEM."""
    fine = AvacRaster(
        np.array([1.5, 2.5]),
        np.array([11.5, 12.5]),
        np.array([[1.0, 3.0], [5.0, 7.0]]),
        {
            "xmin": 1.0, "xmax": 3.0, "ymin": 11.0, "ymax": 13.0,
            "ncols": 2, "nrows": 2, "cellsize": 1.0, "nodata_value": -9999.0,
        },
        "EPSG:2056",
        1,
    )
    overlay = geoclaw_overlay_topography(fine)

    # Topotype-3 shifts the stored lower corner by half its 0.5 m spacing,
    # hence the nodes themselves span exactly the QGIS outer edges [1, 3]
    # rather than an extrapolated half-cell fringe.
    assert np.array_equal(overlay.x, np.array([1.0, 1.5, 2.0, 2.5, 3.0]))
    assert np.array_equal(overlay.y, np.array([11.0, 11.5, 12.0, 12.5, 13.0]))
    assert overlay.metadata["xmin"] == pytest.approx(0.75)
    assert overlay.metadata["xmax"] == pytest.approx(3.25)
    np.testing.assert_allclose(
        overlay.z,
        np.array([
            [1.0, 1.0, 2.0, 3.0, 3.0],
            [1.0, 1.0, 2.0, 3.0, 3.0],
            [3.0, 3.0, 4.0, 5.0, 5.0],
            [5.0, 5.0, 6.0, 7.0, 7.0],
            [5.0, 5.0, 6.0, 7.0, 7.0],
        ]),
    )

    path = tmp_path / "fine_topography.asc"
    write_topography(path, overlay)
    restored = read_avac_topography(path, fine.crs_authid)
    assert np.array_equal(restored.x, overlay.x)
    assert np.array_equal(restored.y, overlay.y)
    np.testing.assert_allclose(restored.z, overlay.z)


def test_prepare_inputs_keeps_fine_raster_bounds_with_closed_terrain_support(tmp_path) -> None:
    main = _registered_raster(20, 20)
    fine = _registered_raster(40, 40, 0.5)
    release = {
        "d0": 1.0,
        "z_ref": 0.0,
        "gradient_hypso": 0.0,
        "theta_cr": 30.0,
        "nu": 0.2,
        "correction_elevation": False,
        "correction_slope": False,
    }
    ring = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]])
    prepared = prepare_inputs(tmp_path / "run", main, [(ring, [])], TEMPLATE, release, fine_raster=fine)

    generated = yaml.safe_load(prepared.configuration_path.read_text(encoding="utf-8"))
    fine_dict = generated["refinement"]["fine_dict"]
    assert fine_dict["xmin"] == 0.0 and fine_dict["xmax"] == 20.0
    assert fine_dict["ymin"] == 0.0 and fine_dict["ymax"] == 20.0
    assert (fine_dict["nbx"], fine_dict["nby"], fine_dict["cell_size"]) == (40, 40, 0.5)

    fine_terrain = read_avac_topography(tmp_path / "run" / "Topo" / "fine_topography.asc", main.crs_authid)
    # The half-spaced nodes reach, but never extend beyond, the fine QGIS
    # footprint. This avoids an edge-padded fine terrain replacing the main
    # DEM in a strip outside [0, 20] by [0, 20].
    assert fine_terrain.z.shape == (81, 81)
    assert np.isclose(fine_terrain.x[0], 0.0) and np.isclose(fine_terrain.x[-1], 20.0)
    assert np.isclose(fine_terrain.y[0], 0.0) and np.isclose(fine_terrain.y[-1], 20.0)
    assert fine_terrain.metadata["xmin"] == -0.125 and fine_terrain.metadata["xmax"] == 20.125
    assert fine_terrain.metadata["ymin"] == -0.125 and fine_terrain.metadata["ymax"] == 20.125


def test_nondivisible_qgis_extent_is_rejected_instead_of_cropping_or_padding() -> None:
    with pytest.raises(ValueError, match="must each be divisible"):
        configuration_for_raster(
            {"computation": {"cell_size": 2.0}, "dem_extent": {}, "gauges": {}},
            _registered_raster(5, 4),
        )


def test_metadata_extent_uses_the_same_integer_grid_tolerance_as_setrun() -> None:
    """Preparation must not emit a domain the backend then rejects."""
    metadata = {
        "xmin": 0.0,
        # A former span-scaled tolerance accepted this 0.1 mm inconsistency
        # for a 100 km grid, but the backend correctly sees 50000.00005
        # two-metre cells rather than an integer number of cells.
        "xmax": 100000.0001,
        "ymin": 0.0,
        "ymax": 2.0,
        "ncols": 100000,
        "nrows": 2,
        "cellsize": 1.0,
        "nodata_value": -9999.0,
    }
    malformed = AvacRaster(
        np.empty(0), np.empty(0), np.empty((0, 0)), metadata, "EPSG:2056", 1,
    )
    with pytest.raises(ValueError, match="do not describe one regular"):
        configuration_for_raster(
            {"computation": {"cell_size": 2.0}, "dem_extent": {}, "gauges": {}}, malformed,
        )


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
