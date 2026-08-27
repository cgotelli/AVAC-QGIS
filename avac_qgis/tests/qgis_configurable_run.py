"""Run one deliberately non-default configured AVAC case through the QGIS dock."""

from __future__ import annotations

import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import loadPlugin, plugins, startPlugin


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
ROOT = Path(os.environ["AVAC_QGIS_CONFIG_RUN_ROOT"])


def fail(message: str) -> None:
    print(f"QGIS_CONFIGURABLE_RUN_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def complete(exit_code: int, normal: bool) -> None:
    if exit_code != 0 or not normal:
        fail(f"runner exit={exit_code} normal={normal} log={dock.log.toPlainText()[-1000:]}"); return
    output = ROOT / "AVAC" / "_output"
    fgout = sorted(output.glob("fgout0001.t*"))
    solver_frames = sorted(output.glob("fort.t*"))
    config = (ROOT / "AVAC" / "AVAC_configuration.yaml").read_text(encoding="utf-8")
    if len(fgout) != 4 or len(solver_frames) != 4 or "t_max: 7" not in config or "nb_simul: 3" not in config or "n_out: 4" not in config:
        fail(f"unexpected configured output: solver={len(solver_frames)} fgout={len(fgout)}"); return
    dock.results_run_root.setText(str(ROOT))
    dock.temporal_variable.setCurrentIndex(0)
    dock.load_temporal_button.click()
    dock._results_task.taskCompleted.connect(results_ready)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()))


def results_ready() -> None:
    manifest = dock._results_manifest
    if manifest is None or len(manifest["simulation_time_seconds"]) != 4:
        fail("temporal result discovery did not retain four actual frames"); return
    output = ROOT / "AVAC" / "_output"
    print(
        f"QGIS_CONFIGURABLE_RUN=True solver_frames={len(list(output.glob('fort.t*')))} "
        f"fgout_frames={len(list(output.glob('fgout0001.t*')))} "
        f"times={manifest['simulation_time_seconds']}",
        flush=True,
    )
    QCoreApplication.quit()


def prepared() -> None:
    if not dock.run_prepared_button.isEnabled():
        fail("prepared run was not enabled"); return
    dock.runner.finished.connect(complete)
    dock.run_prepared_case()


def run() -> None:
    global dock
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable"); return
        startPlugin("avac_qgis")
    plugins["avac_qgis"].show_dock(); dock = plugins["avac_qgis"].dock
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "Configurable DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "Configurable release", "ogr")
    QgsProject.instance().addMapLayers([dem, release])
    dock.dem_layer.setLayer(dem); dock.release_layer.setLayer(release)
    dock.run_root.setText(str(ROOT)); dock.configuration_template.setText(str(CASE / "AVAC" / "AVAC_configuration100.yaml"))
    dock._set_controlled_parameters({"computation.t_max": 7, "computation.nb_simul": 3, "animation.n_out": 4})
    dock.prepare_inputs_button.click()
    if dock._preparation_task is None:
        fail("preparation task was not created"); return
    dock._preparation_task.taskCompleted.connect(prepared)
    dock._preparation_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()))


QTimer.singleShot(1000, run)
