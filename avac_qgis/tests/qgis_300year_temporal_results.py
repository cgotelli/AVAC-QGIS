"""Materialize and load one temporal product from the fresh 300-year run."""

from __future__ import annotations

import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.utils import loadPlugin, plugins, startPlugin


ROOT = Path(os.environ["AVAC_QGIS_300_RUN_ROOT"])
VARIABLE = os.environ.get("AVAC_QGIS_TEMPORAL_VARIABLE", "depth")


def fail(message: str) -> None:
    print(f"QGIS_300YEAR_TEMPORAL_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def ready() -> None:
    manifest = dock._results_manifest
    product = manifest.get("temporal", {}).get(VARIABLE) if manifest else None
    if not product or product.get("path") != f"temporal_{VARIABLE}.tif":
        fail(f"temporal {VARIABLE} was not loaded"); return
    if len(manifest.get("simulation_time_seconds", [])) != 120:
        fail("temporal axis did not retain all 120 frames"); return
    print(
        f"QGIS_300YEAR_TEMPORAL=True variable={VARIABLE} "
        f"frames={len(manifest['simulation_time_seconds'])} range={product['range']}", flush=True,
    )
    QCoreApplication.quit()


def run() -> None:
    global dock
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable"); return
        startPlugin("avac_qgis")
    plugins["avac_qgis"].show_dock(); dock = plugins["avac_qgis"].dock
    dock.results_run_root.setText(str(ROOT))
    index = dock.temporal_variable.findData(VARIABLE)
    if index < 0:
        fail(f"temporal variable unavailable: {VARIABLE}"); return
    dock.temporal_variable.setCurrentIndex(index)
    dock.load_temporal_button.click()
    if dock._results_task is None:
        fail("temporal result task was not created"); return
    dock._results_task.taskCompleted.connect(ready)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()[-1500:]))


QTimer.singleShot(1000, run)
