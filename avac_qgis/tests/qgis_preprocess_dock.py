"""Exercise background isolated-run preparation through the normal AVAC dock."""

from __future__ import annotations

import filecmp
import os
from pathlib import Path

import numpy as np

from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import plugins

from avac_qgis.core.preprocessing import QINIT_BINARY_HEADER, QINIT_BINARY_MAGIC


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
ROOT = Path(os.environ["AVAC_QGIS_DOCK_PREPROCESS_ROOT"])
REFERENCE = Path(os.environ["AVAC_GUI_REFERENCE_ROOT"])


def run() -> None:
    plugin = plugins.get("avac_qgis")
    assert plugin is not None, "AVAC was not loaded from the normal profile"
    plugin.show_dock()
    dock = plugin.dock
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "Canonical DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "Canonical release", "ogr")
    QgsProject.instance().addMapLayers([dem, release])
    dock.dem_layer.setLayer(dem)
    dock.release_layer.setLayer(release)
    dock.run_root.setText(str(ROOT))
    dock.configuration_template.setText(str(CASE / "AVAC" / "AVAC_configuration100.yaml"))
    dock._set_controlled_parameters({
        "release.d0": 1.6, "release.correction_elevation": True, "release.correction_slope": True,
    })
    dock.prepare_inputs_button.click()
    task = dock._preparation_task
    assert task is not None, "the dock did not create a QgsTask"
    task.taskCompleted.connect(lambda: complete(dock))
    task.taskTerminated.connect(lambda: failed(dock))


def complete(dock) -> None:
    assert filecmp.cmp(ROOT / "Topo" / "topography.asc", REFERENCE / "topography.asc", shallow=False)
    binary = ROOT / "AVAC" / "init.avacbin"
    with binary.open("rb") as handle:
        header = QINIT_BINARY_HEADER.unpack(handle.read(QINIT_BINARY_HEADER.size))
        binary_values = np.fromfile(handle, dtype="<f8")
    reference_values = np.loadtxt(REFERENCE / "init.xyz", usecols=2)
    assert header[0] == QINIT_BINARY_MAGIC
    assert binary_values.size == header[1] * header[2]
    assert np.array_equal(binary_values, reference_values)
    assert (ROOT / ".avac_qgis_run.json").is_file()
    assert dock.run_prepared_button.isEnabled()
    print(f"QGIS_DOCK_PREPARED_STATUS={dock.status.text()}", flush=True)
    print("QGIS_DOCK_PREPROCESS=True", flush=True)
    QCoreApplication.quit()


def failed(dock) -> None:
    print(f"QGIS_DOCK_PREPROCESS_FAILURE={dock.log.toPlainText()}", flush=True)
    QCoreApplication.quit()


QTimer.singleShot(0, run)
