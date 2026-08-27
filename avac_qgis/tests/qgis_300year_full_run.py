"""Fresh normal-plugin 300-year AVAC run with static result loading."""

from __future__ import annotations

import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import loadPlugin, plugins, startPlugin

from avac_qgis.core.configuration import controlled_values, load_complete_configuration


CASE = Path(os.environ.get("AVAC_QGIS_CASE", "/Users/cmgotelli/Downloads/Lac_Clusaz"))
ROOT = Path(os.environ["AVAC_QGIS_300_RUN_ROOT"])


def fail(message: str) -> None:
    print(f"QGIS_300YEAR_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def results_ready() -> None:
    manifest = dock._results_manifest
    output = ROOT / "AVAC" / "_output"
    if manifest is None or not manifest.get("static"):
        fail("static result manifest was not loaded"); return
    if len(list(output.glob("fort.t*"))) != 121 or len(list(output.glob("fgout0001.t*"))) != 120:
        fail("full-duration frame counts are incomplete"); return
    print(
        "QGIS_300YEAR=True "
        f"solver_frames={len(list(output.glob('fort.t*')))} "
        f"fgout_frames={len(list(output.glob('fgout0001.t*')))} "
        f"static={sorted(manifest['static'])}", flush=True,
    )
    QCoreApplication.quit()


def complete(exit_code: int, normal: bool) -> None:
    if exit_code != 0 or not normal:
        fail(f"runner exit={exit_code} normal={normal} log={dock.log.toPlainText()[-1500:]}"); return
    config = (ROOT / "AVAC" / "AVAC_configuration.yaml").read_text(encoding="utf-8")
    for text in ("t_max: 120", "nb_simul: 120", "n_out: 120", "d0: 1.75", "mu: 0.225", "xi: 1200"):
        if text not in config:
            fail(f"missing 300-year configuration value {text}"); return
    dock.results_run_root.setText(str(ROOT))
    dock.load_summary_button.click()
    if dock._results_task is None:
        fail("static result task was not created"); return
    dock._results_task.taskCompleted.connect(results_ready)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()[-1500:]))


def prepared() -> None:
    if not dock.run_prepared_button.isEnabled():
        fail("prepared 300-year run was not enabled"); return
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
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "300-year DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "300-year release", "ogr")
    QgsProject.instance().addMapLayers([dem, release])
    dock.dem_layer.setLayer(dem); dock.release_layer.setLayer(release)
    # Deliberately do not configure Advanced / Development fields: this is the
    # normal packaged-runtime route under the dock's default workflow.
    template = CASE / "AVAC" / "AVAC_configuration300.yaml"
    dock._set_controlled_parameters(controlled_values(load_complete_configuration(template)))
    dock.run_root.setText(str(ROOT)); dock.configuration_template.setText(str(template))
    dock.prepare_inputs_button.click()
    if dock._preparation_task is None:
        fail("preparation task was not created"); return
    dock._preparation_task.taskCompleted.connect(prepared)
    dock._preparation_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()[-1500:]))


QTimer.singleShot(1000, run)
