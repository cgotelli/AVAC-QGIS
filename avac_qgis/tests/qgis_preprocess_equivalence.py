"""QGIS-runtime equivalence test for the canonical Lac Clusaz GUI case.

Requires AVAC_QGIS_PREPROCESS_ROOT to name an empty writable directory.
"""

from __future__ import annotations

import filecmp
import os
from pathlib import Path

import numpy as np
import yaml
from matplotlib.path import Path as MplPath
from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer, QgsVectorLayer

from avac_qgis.core.preprocessing import (
    prepare_inputs, raster_from_qgis_layer, release_mask_from_rings, rings_from_qgis_layer,
)


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
DEM_PATH = CASE / "Topo" / "topo1m_simple.asc"
RELEASE_PATH = CASE / "Topo" / "ZA.shp"
TEMPLATE = Path(os.environ.get("AVAC_QGIS_CANONICAL_CONFIGURATION", CASE / "AVAC" / "AVAC_configuration300.yaml"))
REFERENCE_ROOT = Path(os.environ["AVAC_GUI_REFERENCE_ROOT"])
REFERENCE_TOPO = REFERENCE_ROOT / "topography.asc"
REFERENCE_INIT = REFERENCE_ROOT / "init.xyz"
RUN_ROOT = Path(os.environ["AVAC_QGIS_PREPROCESS_ROOT"])


def legacy_ascii_mask(x: np.ndarray, y: np.ndarray, rings) -> np.ndarray:
    """Direct copy of the standalone RunSimulationTab mask logic."""
    xx, yy = np.meshgrid(x, y)
    points = np.column_stack((xx.ravel(), yy.ravel()))
    inside_any = np.zeros(points.shape[0], dtype=bool)
    for exterior, holes in rings:
        candidate = (
            (points[:, 0] >= exterior[:, 0].min()) & (points[:, 0] <= exterior[:, 0].max()) &
            (points[:, 1] >= exterior[:, 1].min()) & (points[:, 1] <= exterior[:, 1].max())
        )
        inside_poly = np.zeros(points.shape[0], dtype=bool)
        inside_poly[candidate] = MplPath(exterior).contains_points(points[candidate])
        for hole in holes:
            candidate_hole = inside_poly & (points[:, 0] >= hole[:, 0].min()) & (points[:, 0] <= hole[:, 0].max()) & (points[:, 1] >= hole[:, 1].min()) & (points[:, 1] <= hole[:, 1].max())
            inside_poly[candidate_hole] &= ~MplPath(hole).contains_points(points[candidate_hole])
        inside_any |= inside_poly
    return inside_any.reshape((y.size, x.size))


def init_metrics(path: Path) -> tuple[int, int, float, float, float]:
    rows = nonzero = 0
    total = 0.0
    minimum = float("inf")
    maximum = 0.0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            _x, _y, value = line.split()
            depth = float(value)
            rows += 1
            if depth != 0.0:
                nonzero += 1
                total += depth
                minimum = min(minimum, depth)
                maximum = max(maximum, depth)
    return rows, nonzero, minimum if nonzero else 0.0, maximum, total


def check() -> None:
    try:
        _check()
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("QGIS_PREPROCESS_FAILURE:\n" + traceback.format_exc(), flush=True)
        QCoreApplication.quit()


def _check() -> None:
    dem = QgsRasterLayer(str(DEM_PATH), "Canonical AVAC DEM")
    release = QgsVectorLayer(str(RELEASE_PATH), "Canonical AVAC release", "ogr")
    # ESRI ASCII grids carry no CRS.  The canonical Lac Clusaz case documents
    # EPSG:2154; assigning it here is an explicit QGIS user/project action.
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    assert dem.isValid(), "canonical DEM did not load in QGIS"
    assert release.isValid(), "canonical release layer did not load in QGIS"
    raster = raster_from_qgis_layer(dem)
    rings = rings_from_qgis_layer(release, dem.crs())
    legacy_mask = legacy_ascii_mask(raster.x, raster.y, rings)
    qgis_mask = release_mask_from_rings(rings, raster.x, raster.y)
    assert np.array_equal(legacy_mask, qgis_mask), "release mask differs cell-by-cell"
    boundary_ring = [(np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.], [0., 0.]]), [])]
    boundary_mask = release_mask_from_rings(boundary_ring, np.array([0., .5, 1.]), np.array([0., .5, 1.]))
    assert np.array_equal(boundary_mask, np.array([[False, False, False], [True, True, True], [True, True, True]]))
    assert raster.z.shape == (1999, 2999), raster.z.shape
    assert raster.crs_authid == "EPSG:2154", raster.crs_authid

    release_parameters = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["release"]
    prepared = prepare_inputs(RUN_ROOT, raster, rings, TEMPLATE, release_parameters)
    assert filecmp.cmp(prepared.topo_path, REFERENCE_TOPO, shallow=False), "topography.asc differs from GUI reference"
    assert filecmp.cmp(prepared.init_path, REFERENCE_INIT, shallow=False), "init.xyz differs from GUI reference"
    reference_mask = np.load(REFERENCE_ROOT / "mask.npy")
    reference_depth = np.load(REFERENCE_ROOT / "depth.npy")
    assert np.array_equal(qgis_mask, reference_mask), "release mask differs from reference cell-by-cell"
    assert np.array_equal(prepared.depth, reference_depth), "initial depth differs from reference cell-by-cell"
    generated = yaml.safe_load(prepared.configuration_path.read_text())
    template = yaml.safe_load(TEMPLATE.read_text())
    for key in ("rheology", "output", "animation", "refinement", "gauges"):
        assert generated[key] == template[key], f"template section changed: {key}"
    expected_computation = dict(template["computation"])
    expected_computation["topo_dir"] = str(prepared.topo_path.parent)
    assert generated["computation"] == expected_computation
    assert generated["file_names"]["topo_source"] == "real_world"
    assert generated["release"] == release_parameters
    rows, nonzero, minimum, maximum, total = init_metrics(prepared.init_path)
    assert rows == raster.z.size == 5_995_001, (rows, raster.z.shape)
    print(f"DEM shape={raster.z.shape} extent={raster.metadata['xmin']},{raster.metadata['xmax']},{raster.metadata['ymin']},{raster.metadata['ymax']} cellsize={raster.metadata['cellsize']} CRS={raster.crs_authid}", flush=True)
    print(f"RELEASE_MASK reference_equal=True cells={int(qgis_mask.sum())}", flush=True)
    print(f"INITIAL_DEPTH reference_equal=True rows={rows} nonzero={nonzero} min={minimum:.12g} max={maximum:.12g} sum={total:.12g}", flush=True)
    print("TOPOGRAPHY byte_identical=True", flush=True)
    print("INIT_XYZ byte_identical=True", flush=True)
    print("YAML template_preservation=True", flush=True)
    QCoreApplication.quit()


QTimer.singleShot(0, check)
