"""Normal-profile Prepare -> Run Prepared AVAC end-to-end regression harness."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import loadPlugin, plugins, startPlugin


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
ROOT = Path(os.environ["AVAC_QGIS_PREPARED_RUN_ROOT"])
CLAW = CASE / "clawpack-v5.14.0"
PYTHON = Path("/Users/cmgotelli/anaconda3/envs/lac-clusaz-notebooks/bin/python")
progress_samples: list[tuple[int, int]] = []


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fail(message: str) -> None:
    print(f"QGIS_PREPARED_RUN_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def completed() -> None:
    prepared = ROOT / "AVAC"
    print(f"QGIS_PREPARED_INPUT_TOPO_SHA256={digest(ROOT / 'Topo' / 'topography.asc')}", flush=True)
    print(f"QGIS_PREPARED_INPUT_INIT_SHA256={digest(prepared / 'init.avacbin')}", flush=True)
    print(f"QGIS_PREPARED_CONFIG_SHA256={digest(prepared / 'AVAC_configuration.yaml')}", flush=True)
    print(f"QGIS_PREPARED_MARKER={ (ROOT / '.avac_qgis_run.json').read_text().strip() }", flush=True)
    dock.runner.progress.connect(lambda current, total: progress_samples.append((current, total)))
    dock.runner.finished.connect(finished)
    dock.run_prepared_button.click()


def finished(exit_code: int, normal_exit: bool) -> None:
    print(f"QGIS_PREPARED_EXIT_CODE={exit_code}", flush=True)
    print(f"QGIS_PREPARED_NORMAL_EXIT={normal_exit}", flush=True)
    print(f"QGIS_PREPARED_PROGRESS_SAMPLES={progress_samples}", flush=True)
    print(f"QGIS_PREPARED_LOG_BEGIN\n{dock.log.toPlainText()}\nQGIS_PREPARED_LOG_END", flush=True)
    QCoreApplication.quit()


def run() -> None:
    global dock
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin was not discoverable in the normal QGIS profile")
            return
        startPlugin("avac_qgis")
    plugin = plugins.get("avac_qgis")
    if plugin is None:
        fail("plugin did not initialise")
        return
    plugin.show_dock()
    dock = plugin.dock
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "Canonical DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "Canonical release", "ogr")
    if not dem.isValid() or not release.isValid():
        fail("canonical QGIS inputs did not load")
        return
    QgsProject.instance().addMapLayers([dem, release])
    dock.avac_dir.setText(str(CASE / "AVAC"))
    dock.claw_root.setText(str(CLAW))
    dock.claw_python.setText(str(PYTHON))
    dock.dem_layer.setLayer(dem)
    dock.release_layer.setLayer(release)
    dock.run_root.setText(str(ROOT))
    dock.configuration_template.setText(str(CASE / "AVAC" / "AVAC_configuration100.yaml"))
    dock.release_d0.setValue(1.6)
    dock.elevation_correction.setChecked(True)
    dock.slope_correction.setChecked(True)
    dock.prepare_inputs_button.click()
    task = dock._preparation_task
    if task is None:
        fail("Prepare AVAC Run did not start a QgsTask")
        return
    task.taskCompleted.connect(completed)
    task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()))


QTimer.singleShot(1000, run)
