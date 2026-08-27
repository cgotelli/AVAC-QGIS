"""Load static products from the fresh Task 12 300-year run through the dock."""

from __future__ import annotations

import os
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.utils import loadPlugin, plugins, startPlugin


ROOT = Path(os.environ["AVAC_QGIS_300_RUN_ROOT"])


def fail(message: str) -> None:
    print(f"QGIS_300YEAR_STATIC_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def ready() -> None:
    manifest = dock._results_manifest
    static = sorted(manifest.get("static", {})) if manifest else []
    if not {"max_depth", "max_velocity", "max_pressure"}.issubset(static):
        fail(f"missing expected static products: {static}"); return
    print(f"QGIS_300YEAR_STATIC=True products={static}", flush=True)
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
    dock.load_summary_button.click()
    if dock._results_task is None:
        fail("static result task was not created"); return
    dock._results_task.taskCompleted.connect(ready)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()[-1500:]))


QTimer.singleShot(1000, run)
