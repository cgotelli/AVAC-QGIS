"""Load each archived ISeeSnow Case through the actual AVAC4QGIS dock.

Run with QGIS 3.44 using ``QGIS --noplugins --code``.  This verifies both
Case restoration and discovery of the archive-layout completed ``Run``.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsProject

PLUGIN_ROOT = Path(os.environ.get("AVAC_QGIS_PLUGIN_ROOT", Path(__file__).resolve().parents[2]))
VALIDATION_ROOT = Path(os.environ.get("AVAC_QGIS_ISEESNOW_ROOT", PLUGIN_ROOT / "Validation-ISeeSnow"))
sys.path.insert(0, str(PLUGIN_ROOT))

from avac_qgis.core.preprocessing import raster_from_qgis_layer, rings_from_qgis_layer  # noqa: E402
from avac_qgis.gui.dock import AvacDockWidget  # noqa: E402


def fail(message: str) -> None:
    print(f"QGIS_ISEESNOW_CASE_FAILURE={message}", flush=True)
    traceback.print_exc()
    QCoreApplication.quit()
    os._exit(1)


def verify() -> None:
    try:
        dock = AvacDockWidget()
        for case_name in ("IdealizedTopo", "RealTopo", "CoulombOnly"):
            QgsProject.instance().clear()
            path = next((VALIDATION_ROOT / case_name).glob("AVAC4QGIS_ISeeSnow_*_Case.yaml"))
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "YAML (*.yaml)")):
                dock.load_plugin_configuration()
            if not dock.status.text().startswith("Loaded complete AVAC4QGIS configuration"):
                raise AssertionError(f"{case_name} did not load: {dock.status.text()}")
            run_root = VALIDATION_ROOT / case_name / "Run"
            if dock.results_run_selector.count() != 1 or Path(dock.results_run_selector.currentData()) != run_root:
                raise AssertionError(f"{case_name} completed Run was not selected: count={dock.results_run_selector.count()}")
            if not dock.results_run_selector.currentText().startswith(f"ISeeSnow — {case_name}"):
                raise AssertionError(f"{case_name} has an unclear completed-run label: {dock.results_run_selector.currentText()}")
            if f"Benchmark: ISeeSnow" not in dock.results_summary.text() or "Simulation: 1200" not in dock.results_summary.text():
                raise AssertionError(f"{case_name} summary is incomplete: {dock.results_summary.text()}")
            dem, release = dock.dem_layer.currentLayer(), dock.release_layer.currentLayer()
            if dem is None or release is None or not dem.crs().isValid() or not release.crs().isValid():
                raise AssertionError(f"{case_name} did not restore valid input layers")
            raster = raster_from_qgis_layer(dem)
            rings = rings_from_qgis_layer(release, dem.crs())
            if not raster.crs_authid or not rings:
                raise AssertionError(f"{case_name} cannot prepare from the restored inputs")
            dock.validate_preprocessing_inputs()
            if not dock.status.text().startswith("Inputs valid."):
                raise AssertionError(f"{case_name} plugin validation failed: {dock.status.text()}")
            print(
                f"QGIS_ISEESNOW_CASE=True case={case_name} run={run_root.name} "
                f"crs={dem.crs().authid() or 'local-cartesian'}",
                flush=True,
            )
        dock.shutdown()
        print("QGIS_ISEESNOW_CASE_ALL=True", flush=True)
        QCoreApplication.quit()
        os._exit(0)
    except BaseException as exc:  # noqa: BLE001
        fail(str(exc))


QTimer.singleShot(1000, verify)
