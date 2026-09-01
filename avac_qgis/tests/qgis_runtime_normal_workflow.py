"""Clean-profile normal dock test for the bundled runtime short simulation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsVectorLayer


WORKSPACE = Path(os.environ["AVAC_QGIS_WORKSPACE"]).resolve()
DEM = Path(os.environ["AVAC_QGIS_DEM"]).resolve()
RELEASE = Path(os.environ["AVAC_QGIS_RELEASE"]).resolve()
WORKSPACE_ROOT = Path(os.environ["AVAC_QGIS_WORKSPACE_ROOT"]).resolve()
RESULT = Path(os.environ["AVAC_QGIS_RESULT"]).resolve()
sys.path.insert(0, str(WORKSPACE))

from avac_qgis.gui.dock import AvacDockWidget  # noqa: E402
from avac_qgis.core.runtime import platform_key  # noqa: E402
from avac_qgis.core.runtime_assets import RUNTIME_VERSION, runtime_install_root  # noqa: E402
from avac_qgis.core.run_project import read_run_metadata  # noqa: E402


dock: AvacDockWidget | None = None


def fail(message: str) -> None:
    print(f"QGIS_RUNTIME_NORMAL=FAIL {message}", flush=True)
    RESULT.write_text(f"FAIL {message}\n", encoding="utf-8")
    if dock is not None:
        dock.shutdown()
    QgsApplication.quit()


def after_run(code: int, normal: bool) -> None:
    assert dock is not None
    try:
        run_root = Path(dock.run_root.text()).resolve()
        avac = run_root / "AVAC"
        marker = read_run_metadata(run_root)
        output = avac / "_output"
        if code != 0 or not normal or marker.get("status") != "completed":
            raise RuntimeError(f"solver code={code} normal={normal} marker={marker.get('status')}")
        if len(list(output.glob("fort.t*"))) != 4 or len(list(output.glob("fort.q*"))) != 4:
            raise RuntimeError("short runtime solver did not write all fort frames")
        if not (output / "fgmax0001.txt").is_file() or len(list(output.glob("fgout0001.t*"))) != 4:
            raise RuntimeError("short runtime solver result set is incomplete")
        installed = runtime_install_root() / RUNTIME_VERSION / platform_key()
        if not (installed / "runtime-manifest.json").is_file():
            raise RuntimeError(f"runtime was not installed automatically: {installed}")
        print(
            f"QGIS_RUNTIME_NORMAL=PASS runtime={installed} output={output} "
            f"fort={len(list(output.glob('fort.t*')))} fgout={len(list(output.glob('fgout0001.t*')))}",
            flush=True,
        )
        RESULT.write_text("PASS\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        return
    dock.shutdown()
    QgsApplication.quit()


def after_prepare() -> None:
    assert dock is not None
    if dock.prepared_avac_dir is None:
        fail(f"preparation failed: {dock.status.text()}")
        return
    dock.runner.finished.connect(after_run)
    dock.run_prepared_case()


def start() -> None:
    global dock
    try:
        dem = QgsRasterLayer(str(DEM), "canonical DEM")
        release = QgsVectorLayer(str(RELEASE), "canonical release", "ogr")
        if not dem.isValid() or not release.isValid():
            raise RuntimeError("test input layers could not be loaded")
        # The source ESRI ASCII grid does not encode CRS.  This is the same
        # explicit user/project assignment made in the normal QGIS workflow.
        dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
        QgsProject.instance().addMapLayer(dem); QgsProject.instance().addMapLayer(release)
        dock = AvacDockWidget()
        dock.dem_layer.setLayer(dem); dock.release_layer.setLayer(release); dock.workspace_root.setText(str(WORKSPACE_ROOT))
        dock.parameter_controls["computation.t_max"].setValue(7)
        dock.parameter_controls["computation.nb_simul"].setValue(3)
        dock.parameter_controls["animation.n_out"].setValue(4)
        dock.prepare_preprocessing_inputs()
        if dock._preparation_task is None:
            raise RuntimeError(dock.status.text())
        dock._preparation_task.taskCompleted.connect(after_prepare)
        dock._preparation_task.taskTerminated.connect(lambda: fail(dock.status.text()))
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")


QTimer.singleShot(0, start)
