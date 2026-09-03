"""QGIS-runtime preprocessing test for the canonical Lac Clusaz case.

Requires AVAC_QGIS_PREPROCESS_ROOT to name an empty writable directory.
"""

from __future__ import annotations

from copy import deepcopy
import filecmp
import os
from pathlib import Path
import tempfile

import numpy as np
import yaml
from matplotlib.path import Path as MplPath
from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer, QgsVectorLayer

from avac_qgis.core.preprocessing import (
    QINIT_BINARY_HEADER, QINIT_BINARY_MAGIC, configuration_for_raster,
    initial_depth_from_release, prepare_inputs, raster_from_qgis_layer,
    release_coverage_from_rings, release_mask_from_rings,
    rings_from_qgis_layer,
)


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
DEM_PATH = CASE / "Topo" / "topo1m_simple.asc"
RELEASE_PATH = CASE / "Topo" / "ZA.shp"
TEMPLATE = Path(os.environ.get("AVAC_QGIS_CANONICAL_CONFIGURATION", CASE / "AVAC" / "AVAC_configuration300.yaml"))
REFERENCE_ROOT = Path(os.environ["AVAC_GUI_REFERENCE_ROOT"])
REFERENCE_TOPO = REFERENCE_ROOT / "topography.asc"
RUN_ROOT = Path(os.environ["AVAC_QGIS_PREPROCESS_ROOT"])


def canonical_compatible_template(raster):
    """Reject the documented 2 m setup, then make a test-only 1 m copy.

    The canonical QGIS raster is 2999 by 1999 cells at 1 m.  Its old 2 m
    template cannot cover that physical rectangle exactly: using it would
    either discard the top/right release cells or invent terrain outside the
    raster.  Production correctly rejects that input.  This manual QGIS test
    records the rejection and uses a temporary 1 m template only so the
    remaining ingestion/preparation route is still exercised.
    """
    source_template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(source_template, dict), "canonical configuration is not a YAML mapping"
    source_cell = float(raster.metadata["cellsize"])
    configured_cell = float(source_template["computation"]["cell_size"])
    assert np.isclose(source_cell, 1.0), source_cell
    assert np.isclose(configured_cell, 2.0), configured_cell
    try:
        configuration_for_raster(source_template, raster)
    except ValueError as exc:
        assert "must each be divisible" in str(exc), str(exc)
    else:
        raise AssertionError("The non-divisible canonical 2 m configuration was unexpectedly accepted.")

    compatible_template = deepcopy(source_template)
    compatible_template["computation"]["cell_size"] = source_cell
    return compatible_template


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
    with path.open("rb") as handle:
        prefix = handle.read(len(QINIT_BINARY_MAGIC))
        if prefix == QINIT_BINARY_MAGIC:
            handle.seek(0)
            header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
            values = np.fromfile(handle, dtype="<f8")
            assert values.size == header[1] * header[2]
            present = values[values != 0.0]
            return (
                values.size,
                present.size,
                float(present.min()) if present.size else 0.0,
                float(present.max()) if present.size else 0.0,
                float(present.sum()),
            )

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
    cell = float(raster.metadata["cellsize"])
    assert np.isclose(raster.x[0] - .5 * cell, raster.metadata["xmin"])
    assert np.isclose(raster.x[-1] + .5 * cell, raster.metadata["xmax"])
    assert np.isclose(raster.y[0] - .5 * cell, raster.metadata["ymin"])
    assert np.isclose(raster.y[-1] + .5 * cell, raster.metadata["ymax"])
    rings = rings_from_qgis_layer(release, dem.crs())
    legacy_mask = legacy_ascii_mask(raster.x, raster.y, rings)
    qgis_mask = release_mask_from_rings(rings, raster.x, raster.y)
    assert np.array_equal(legacy_mask, qgis_mask), "release mask differs cell-by-cell"
    boundary_ring = [(np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.], [0., 0.]]), [])]
    boundary_mask = release_mask_from_rings(boundary_ring, np.array([0., .5, 1.]), np.array([0., .5, 1.]))
    assert np.array_equal(boundary_mask, np.array([[False, False, False], [True, True, True], [True, True, True]]))
    assert raster.z.shape == (1999, 2999), raster.z.shape
    assert raster.crs_authid == "EPSG:2154", raster.crs_authid

    template = canonical_compatible_template(raster)
    # Keep the adaptation out of the requested empty run directory.  It is a
    # regression harness artifact, never a production configuration rewrite.
    with tempfile.TemporaryDirectory(prefix="avac-qgis-canonical-") as temporary_root:
        compatible_template_path = Path(temporary_root) / "AVAC_configuration300_1m.yaml"
        compatible_template_path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
        release_parameters = template["release"]
        prepared = prepare_inputs(RUN_ROOT, raster, rings, compatible_template_path, release_parameters)
        assert filecmp.cmp(prepared.topo_path, REFERENCE_TOPO, shallow=False), "topography.asc differs from GUI reference"
        with prepared.topo_path.open(encoding="utf-8") as handle:
            topo_header = {
                fields[0].lower(): fields[1]
                for fields in (line.split(maxsplit=1) for line in (handle.readline() for _ in range(6)))
            }
        cell = float(raster.metadata["cellsize"])
        assert int(topo_header["ncols"]) == raster.x.size + 2
        assert int(topo_header["nrows"]) == raster.y.size + 2
        assert np.isclose(float(topo_header["xllcorner"]), float(raster.metadata["xmin"]) - cell)
        assert np.isclose(float(topo_header["yllcorner"]), float(raster.metadata["ymin"]) - cell)
        with prepared.init_path.open("rb") as handle:
            qinit_header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
        magic, ncols, nrows, components, _flags, xlow, yhigh, dx, dy = qinit_header
        assert (magic, ncols, nrows, components) == (QINIT_BINARY_MAGIC, raster.x.size, raster.y.size, 1)
        assert np.isclose(xlow, raster.x[0]) and np.isclose(yhigh, raster.y[-1])
        assert np.isclose(xlow - .5 * dx, raster.metadata["xmin"])
        assert np.isclose(xlow + (ncols - .5) * dx, raster.metadata["xmax"])
        assert np.isclose(yhigh - (nrows - .5) * dy, raster.metadata["ymin"])
        assert np.isclose(yhigh + .5 * dy, raster.metadata["ymax"])
        prepared_metrics = init_metrics(prepared.init_path)
        reference_coverage = np.load(REFERENCE_ROOT / "coverage.npy")
        reference_mask = np.load(REFERENCE_ROOT / "mask.npy")
        reference_depth = np.load(REFERENCE_ROOT / "depth.npy")
        expected_coverage = release_coverage_from_rings(
            rings, raster.x, raster.y, float(raster.metadata["cellsize"]),
        )
        assert np.array_equal(prepared.coverage, expected_coverage)
        assert np.array_equal(prepared.mask, expected_coverage > 0.0)
        assert np.array_equal(
            prepared.depth,
            initial_depth_from_release(raster, expected_coverage, release_parameters),
        )
        assert np.allclose(prepared.coverage, reference_coverage, rtol=0.0, atol=0.0), "fractional release coverage differs from reference"
        assert np.array_equal(prepared.mask, reference_mask), "release coverage support differs from reference"
        assert np.allclose(prepared.depth, reference_depth, rtol=0.0, atol=1e-12), "fractional initial depth differs from reference"
        generated = yaml.safe_load(prepared.configuration_path.read_text())
        for key in ("rheology", "output", "animation", "refinement", "gauges"):
            assert generated[key] == template[key], f"template section changed: {key}"
        expected_computation = dict(template["computation"])
        expected_computation["topo_dir"] = str(prepared.topo_path.parent)
        assert generated["computation"] == expected_computation
        assert generated["dem_extent"] == {
            "xmin": float(raster.metadata["xmin"]), "xmax": float(raster.metadata["xmax"]),
            "ymin": float(raster.metadata["ymin"]), "ymax": float(raster.metadata["ymax"]),
            "nbx": raster.x.size, "nby": raster.y.size, "cell_size": cell,
            "nodata_value": float(raster.metadata["nodata_value"]),
        }
        assert generated["file_names"]["topo_source"] == "real_world"
        assert generated["release"] == release_parameters
        rows, nonzero, minimum, maximum, total = prepared_metrics
        assert rows == raster.z.size == 5_995_001, (rows, raster.z.shape)
        print(f"DEM shape={raster.z.shape} extent={raster.metadata['xmin']},{raster.metadata['xmax']},{raster.metadata['ymin']},{raster.metadata['ymax']} cellsize={raster.metadata['cellsize']} CRS={raster.crs_authid}", flush=True)
        print(
            f"RELEASE_MASK legacy_center_check=True cells={int(qgis_mask.sum())}; "
            f"fractional_equivalent_cells={prepared.coverage.sum():.12g}",
            flush=True,
        )
        print(f"INITIAL_DEPTH fractional_volume=True rows={rows} nonzero={nonzero} min={minimum:.12g} max={maximum:.12g} sum={total:.12g}", flush=True)
        print("GRID_CONTRACT canonical_2m_rejected=True regression_template_cell_size=1m full_qgis_domain=True", flush=True)
        print("TOPOGRAPHY byte_identical=True terrain_only_halo=True", flush=True)
        print("INIT_BINARY fractional_release_coverage=True", flush=True)
        print("YAML template_preservation=True", flush=True)
    QCoreApplication.quit()


QTimer.singleShot(0, check)
