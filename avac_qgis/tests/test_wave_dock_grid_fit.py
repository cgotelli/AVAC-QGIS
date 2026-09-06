"""Exercise actual WAVE dock methods with light QGIS surface stubs."""

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest


DOCK = Path(__file__).resolve().parents[1] / "gui" / "dock.py"


class Rectangle:
    def __init__(self, xmin, ymin, xmax, ymax):
        self.bounds = (xmin, ymin, xmax, ymax)

    def xMinimum(self):
        return self.bounds[0]

    def yMinimum(self):
        return self.bounds[1]

    def xMaximum(self):
        return self.bounds[2]

    def yMaximum(self):
        return self.bounds[3]


class Terrain:
    def __init__(self, bounds, resolution=(1., 1.)):
        self.bounds = Rectangle(*bounds)
        self.resolution = resolution

    def isValid(self):
        return True

    def rasterUnitsPerPixelX(self):
        return self.resolution[0]

    def rasterUnitsPerPixelY(self):
        return self.resolution[1]

    def extent(self):
        return self.bounds

    def crs(self):
        return "EPSG:2056"

    def id(self):
        return "terrain"

    def source(self):
        return "terrain.tif"

    def width(self):
        return 40

    def height(self):
        return 40

    def bandCount(self):
        return 1


class Value:
    def __init__(self, selected):
        self.selected = selected

    def value(self):
        return self.selected


class Choice:
    def __init__(self, layer):
        self.layer = layer

    def currentLayer(self):
        return self.layer

    def setLayer(self, layer):
        self.layer = layer


@pytest.fixture
def dock_probe():
    from avac_qgis.core.preprocessing import AvacRaster, trim_raster_to_computational_grid

    # Keep this GUI-method test independent of platform release descriptors.
    # Compile the real metadata-only helper with its real raster dependencies.
    wave_project = DOCK.parents[1] / "core" / "wave_project.py"
    core_tree = ast.parse(wave_project.read_text(encoding="utf-8"))
    core_helper = next(node for node in core_tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "fit_wave_domain")
    core_namespace = {"np": np, "Any": Any, "AvacRaster": AvacRaster,
                      "trim_raster_to_computational_grid": trim_raster_to_computational_grid}
    exec(compile(ast.Module(body=[core_helper], type_ignores=[]), str(wave_project), "exec"), core_namespace)
    fit_wave_domain = core_namespace["fit_wave_domain"]

    tree = ast.parse(DOCK.read_text(encoding="utf-8"))
    dock_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and
                      any(isinstance(child, ast.FunctionDef) and child.name == "_validated_wave_domain"
                          for child in node.body))
    names = {"_validated_wave_domain", "_wave_grid_summary", "_wave_setup_terrain",
             "_wave_water_preview_input_signature", "_compute_wave_water_preview"}
    methods = [node for node in dock_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"np": np, "Path": Path, "hashlib": hashlib, "fit_wave_domain": fit_wave_domain,
                 "QgsRectangle": Rectangle, "PreparedWaveLake": SimpleNamespace}
    compiled = ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[]))
    exec(compile(compiled, str(DOCK), "exec"), namespace)
    probe_type = type("WaveDockProbe", (), {name: namespace[name] for name in names})

    def make(domain, terrain_bounds=(0., 0., 40., 40.), cell=4., resolution=(1., 1.)):
        probe = probe_type()
        probe._wave_domain = lambda: dict(domain)
        probe.wave_lake_dem = Choice(Terrain(terrain_bounds, resolution))
        probe.wave_cell_size = Value(cell)
        return probe, namespace

    return make


@pytest.mark.parametrize("domain,expected", [
    ({"xmin": 0., "xmax": 23., "ymin": 0., "ymax": 22.},
     {"xmin": 1., "xmax": 21., "ymin": 1., "ymax": 21.}),
    ({"xmin": 3., "xmax": 26., "ymin": 4., "ymax": 26.},
     {"xmin": 4., "xmax": 24., "ymin": 5., "ymax": 25.}),
    ({"xmin": 0., "xmax": 20., "ymin": 0., "ymax": 24.},
     {"xmin": 0., "xmax": 20., "ymin": 0., "ymax": 24.}),
])
def test_gui_fits_completed_avac_domain_and_reports_retained_grid(dock_probe, domain, expected):
    probe, _ = dock_probe(domain)
    fitted = probe._validated_wave_domain()
    assert fitted == expected
    summary = probe._wave_grid_summary(fitted, 4.)
    assert "5 ×" in summary and "at 4 m" in summary
    assert ("trimmed inward" in summary) == (domain != expected)
    assert f"X [{expected['xmin']:g}, {expected['xmax']:g}]" in summary
    assert f"Y [{expected['ymin']:g}, {expected['ymax']:g}]" in summary


@pytest.mark.parametrize("resolution", [(1., 2.), (np.nan, 1.), (1., np.inf), (0., 0.)])
def test_gui_rejects_invalid_dem_cells_before_fitting(dock_probe, resolution):
    probe, namespace = dock_probe({"xmin": 0., "xmax": 20., "ymin": 0., "ymax": 20.}, resolution=resolution)
    namespace["fit_wave_domain"] = lambda *_args: pytest.fail("invalid terrain reached domain fitter")
    with pytest.raises(ValueError, match="positive finite square cells"):
        probe._validated_wave_domain()


def test_preview_reads_fitted_halo_and_caches_the_same_domain(dock_probe):
    original = {"xmin": 0., "xmax": 23., "ymin": 0., "ymax": 22.}
    fitted = {"xmin": 1., "xmax": 21., "ymin": 1., "ymax": 21.}
    probe, namespace = dock_probe(original)
    boundary = SimpleNamespace(isValid=lambda: True, getFeatures=lambda: [], id=lambda: "lake",
                               source=lambda: "lake.geojson", featureCount=lambda: 0)
    probe.wave_lake_boundary = Choice(boundary)
    probe.workspace_root = SimpleNamespace(text=lambda: "/tmp/wave-grid-test")
    probe.wave_water_level = Value(10.)
    probe.wave_dry_limit = Value(.001)
    probe.wave_setup_status = SimpleNamespace(setText=lambda text: messages.append(text))
    probe._render_wave_water_preview = lambda prepared: (25, 2.)
    messages, reads, prepares = [], [], []
    native = object()

    def read_native(layer, *, extent):
        reads.append(extent.bounds)
        return native

    def prepare(native_raster, rings, **kwargs):
        assert native_raster is native
        assert rings == "lake-rings"
        prepares.append(kwargs)
        return SimpleNamespace(domain=kwargs["domain"], cell_size=kwargs["cell_size"])

    namespace["raster_from_qgis_layer"] = read_native
    namespace["rings_from_qgis_layer"] = lambda *_args: "lake-rings"
    namespace["prepare_wave_lake"] = prepare
    prepared = probe._compute_wave_water_preview()
    assert reads == [(-3., -3., 25., 25.)]
    assert prepares[0]["domain"] == fitted
    assert prepared.domain == fitted
    assert probe._wave_lake_preview is prepared
    assert "trimmed inward" in messages[0]
    assert probe._wave_lake_preview_signature == probe._wave_water_preview_input_signature()
    probe.wave_cell_size.selected = 2.
    assert probe._wave_lake_preview_signature != probe._wave_water_preview_input_signature()
