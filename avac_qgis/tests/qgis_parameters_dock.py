"""QGIS-runtime checks for complete configuration controls and preview task."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import loadPlugin, plugins, startPlugin

from avac_qgis.core.configuration import apply_controlled_values, controlled_values, load_complete_configuration


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
TEMPLATE = CASE / "AVAC" / "AVAC_configuration100.yaml"


def fail(message: str) -> None:
    print(f"QGIS_PARAMETERS_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def preview_complete() -> None:
    layer = next((layer for layer in QgsProject.instance().mapLayers().values() if layer.name() == "AVAC Initial Depth Preview"), None)
    if layer is None:
        fail(dock.status.text()); return
    print(f"QGIS_PARAMETERS_PREVIEW=True status={dock.status.text()}", flush=True)
    QCoreApplication.quit()


def run() -> None:
    global dock
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable"); return
        startPlugin("avac_qgis")
    plugins["avac_qgis"].show_dock(); dock = plugins["avac_qgis"].dock
    values = controlled_values(load_complete_configuration(TEMPLATE))
    dock._set_controlled_parameters(values)
    dock.configuration_template.setText(str(TEMPLATE))
    dock.parameter_controls["computation.t_max"].setValue(7)
    dock.parameter_controls["computation.nb_simul"].setValue(3)
    dock.parameter_controls["animation.n_out"].setValue(4)
    changed = dock._controlled_parameters()
    payload = apply_controlled_values(load_complete_configuration(TEMPLATE), changed)
    if (payload["computation"]["t_max"], payload["computation"]["nb_simul"], payload["animation"]["n_out"]) != (7, 3, 4):
        fail("duration/output mapping failed"); return
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "Canonical DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "Canonical release", "ogr")
    QgsProject.instance().addMapLayers([dem, release])
    dock.dem_layer.setLayer(dem); dock.release_layer.setLayer(release)
    dock.preview_initial_depth_button.click()
    if dock._preview_task is None:
        fail("preview task did not start"); return
    dock._preview_task.taskCompleted.connect(preview_complete)
    dock._preview_task.taskTerminated.connect(lambda: fail(dock.status.text()))
    print(f"QGIS_PARAMETERS_MAPPING=True t_max={payload['computation']['t_max']} solver_outputs={payload['computation']['nb_simul']} temporal_outputs={payload['animation']['n_out']}", flush=True)


QTimer.singleShot(1000, run)
