"""FGmax centre-registration contracts for AVAC result rasters.

GeoClaw ``point_style = 2`` fixed grids specify *sample points*: ``x1`` and
``x2`` are the first and final sample coordinates, not control-volume edges.
AVAC's QGIS result writer subsequently interprets those coordinates as raster
centres.  These tests exercise ``setrun`` with a small fake Clawpack surface
so that an edge-based FGmax grid cannot silently return as an N+1, one-cell
stretched GeoTIFF.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avac_qgis.core.results import GridGeometry, geometry_from_axes
from avac_qgis.core.preprocessing import AvacRaster, configuration_for_raster


ROOT = Path(__file__).resolve().parents[2]
SETRUN_PATH = ROOT / "avac-main" / "src" / "AVAC" / "setrun.py"


class _FGmaxGrid:
    """Minimal fixed-grid record used by the setrun registration tests."""


class _FGoutGrid:
    """Minimal fixed-grid record used while setrun builds its FGout product."""


class _UserData:
    def __init__(self) -> None:
        self.parameters: list[tuple[str, object, str]] = []

    def add_param(self, name: str, value: object, description: str) -> None:
        self.parameters.append((name, value, description))


class _RunData:
    """Only the public data records reached by AVAC ``setrun``."""

    def __init__(self, *_args: object) -> None:
        self.clawdata = SimpleNamespace(
            lower=[None, None], upper=[None, None], num_cells=[None, None],
            bc_lower=[None, None], bc_upper=[None, None],
        )
        self.amrdata = SimpleNamespace()
        self.regiondata = SimpleNamespace(regions=[])
        self.gaugedata = SimpleNamespace(gauges=[])
        self.fgmax_data = SimpleNamespace(fgmax_grids=[])
        self.fgout_data = SimpleNamespace(fgout_grids=[])

    def new_UserData(self, **_kwargs: object) -> _UserData:
        return _UserData()


def _load_setrun(monkeypatch: pytest.MonkeyPatch):
    """Import the AVAC setup module without importing an installed Clawpack."""
    clawpack = types.ModuleType("clawpack")
    geoclaw = types.ModuleType("clawpack.geoclaw")
    clawutil = types.ModuleType("clawpack.clawutil")
    fgmax_tools = types.ModuleType("clawpack.geoclaw.fgmax_tools")
    fgout_tools = types.ModuleType("clawpack.geoclaw.fgout_tools")
    data = types.ModuleType("clawpack.clawutil.data")
    fgmax_tools.FGmaxGrid = _FGmaxGrid
    fgout_tools.FGoutGrid = _FGoutGrid
    data.ClawRunData = _RunData
    geoclaw.fgmax_tools = fgmax_tools
    geoclaw.fgout_tools = fgout_tools
    clawutil.data = data
    clawpack.geoclaw = geoclaw
    clawpack.clawutil = clawutil
    for name, module in {
        "clawpack": clawpack,
        "clawpack.geoclaw": geoclaw,
        "clawpack.geoclaw.fgmax_tools": fgmax_tools,
        "clawpack.geoclaw.fgout_tools": fgout_tools,
        "clawpack.clawutil": clawutil,
        "clawpack.clawutil.data": data,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    name = "avac_setrun_fgmax_registration_test"
    spec = importlib.util.spec_from_file_location(name, SETRUN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    # FGmax geometry is the subject under test; GeoClaw physical/topography
    # setup is independent and requires a much larger runtime surface.
    monkeypatch.setattr(module, "setgeo", lambda rundata: rundata)
    return module


def _configure(module, *, result_grid: dict[str, float | int] | None = None, zoom: bool = False) -> None:
    """Supply the minimal complete real-world configuration used by setrun."""
    module.Files = {"topo_source": "real_world", "type_init": 1}
    module.topo_source = "real_world"
    module.ResultGrid = result_grid
    module.DEM = {
        "xmin": 0.0, "xmax": 10.0, "ymin": 20.0, "ymax": 28.0,
        "nodata_value": -9999.0,
    }
    module.Param = {
        "cell_size": 2.0, "t_max": 10.0, "nb_simul": 2,
        "max_iter": 1000, "cfl_target": 0.5, "cfl_max": 1.0,
        "limiter": "vanleer", "boundary": 1, "refinement": 2 if zoom else 1,
    }
    module.OUT = {"output_format": "binary32", "verbosity": 0}
    module.Movie = {"n_out": 2}
    module.Refine = {
        "topo_refinement": zoom,
        "fine_dict": {"xmin": 2.0, "xmax": 8.0, "ymin": 22.0, "ymax": 26.0, "cell_size": 1.0},
    }
    module.Gauges = {"gauge_recording": False, "gauges": []}
    module.Release = {}
    module.Rheol = {"mu": 0.2, "xi": 1000.0, "C": 0.0, "z_breaks": [], "rho": 300.0, "model": "Voellmy"}


def _sample_count(first: float, last: float, spacing: float) -> int:
    """GeoClaw's point_style=2 number of samples for an inclusive axis."""
    return int(round((last - first) / spacing)) + 1


def test_default_fgmax_samples_are_solver_cell_centres(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_setrun(monkeypatch)
    _configure(module)

    rundata = module.setrun()
    grid = rundata.fgmax_data.fgmax_grids[0]

    assert (grid.x1, grid.x2, grid.y1, grid.y2) == (1.0, 9.0, 21.0, 27.0)
    assert _sample_count(grid.x1, grid.x2, grid.dx) == rundata.clawdata.num_cells[0] == 5
    assert _sample_count(grid.y1, grid.y2, grid.dy) == rundata.clawdata.num_cells[1] == 4
    # ``_load_fgmax`` returns the inclusive point coordinates, and the QGIS
    # writer subsequently converts them back into cell edges.  This is the
    # complete no-shift/no-stretch registration contract.
    x = np.linspace(grid.x1, grid.x2, _sample_count(grid.x1, grid.x2, grid.dx))
    y = np.linspace(grid.y1, grid.y2, _sample_count(grid.y1, grid.y2, grid.dy))
    assert geometry_from_axes(x, y) == GridGeometry(5, 4, 0.0, 10.0, 20.0, 28.0, 2.0, 2.0)


def test_explicit_result_grid_remains_cell_centre_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_setrun(monkeypatch)
    _configure(module, result_grid={
        "xllcenter": 1.0, "yllcenter": 21.0, "ncols": 5, "nrows": 4, "cell_size": 2.0,
    })

    grid = module.setrun().fgmax_data.fgmax_grids[0]

    assert (grid.x1, grid.x2, grid.y1, grid.y2) == (1.0, 9.0, 21.0, 27.0)
    assert _sample_count(grid.x1, grid.x2, grid.dx) == 5
    assert _sample_count(grid.y1, grid.y2, grid.dy) == 4


def test_zoom_fgmax_samples_are_refinement_cell_centres(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_setrun(monkeypatch)
    _configure(module, zoom=True)

    grid = module.setrun().fgmax_data.fgmax_grids[1]

    assert (grid.x1, grid.x2, grid.y1, grid.y2) == (2.5, 7.5, 22.5, 25.5)
    assert _sample_count(grid.x1, grid.x2, grid.dx) == 6
    assert _sample_count(grid.y1, grid.y2, grid.dy) == 4


def test_qgis_preparation_rejects_a_one_sample_fgmax_axis() -> None:
    """FGmax point_style=2 cannot represent a one-column/row raster.

    GeoClaw constructs its point spacing with ``(x2-x1)/(nx-1)`` and AVAC's
    GIS materializer likewise needs two coordinates to infer cell edges.  A
    prepared plugin run must reject this configuration instead of failing
    later in the native solver or producing an ungeoreferenceable product.
    """
    raster = AvacRaster(
        np.array([1.5, 4.5, 7.5]), np.array([1.5, 4.5, 7.5]), np.zeros((3, 3)),
        {
            "xmin": 0.0, "xmax": 9.0, "ymin": 0.0, "ymax": 9.0,
            "ncols": 3, "nrows": 3, "cellsize": 3.0, "nodata_value": -9999.0,
        },
        "EPSG:2056", 1,
    )
    configuration = {"computation": {"cell_size": 9.0}, "dem_extent": {}, "gauges": {}}

    with pytest.raises(ValueError, match="at least two computational cells"):
        configuration_for_raster(configuration, raster)


def test_setrun_rejects_a_one_cell_axis_in_hand_authored_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native setup keeps the same guard when QGIS preparation is bypassed."""
    module = _load_setrun(monkeypatch)
    _configure(module)
    # One 2-m x cell but four y cells: enough to expose the x ``nx - 1``
    # division in GeoClaw FGmax without relying on QGIS-side validation.
    module.DEM["xmax"] = 2.0

    with pytest.raises(ValueError, match="at least two computational cells"):
        module.setrun()
