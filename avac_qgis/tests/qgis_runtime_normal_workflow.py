"""Clean-profile normal dock test for the bundled runtime short simulation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsVectorLayer


WORKSPACE = Path(os.environ["AVAC_QGIS_WORKSPACE"]).resolve()
DEM = Path(os.environ["AVAC_QGIS_DEM"]).resolve()
RELEASE = Path(os.environ["AVAC_QGIS_RELEASE"]).resolve()
WORKSPACE_ROOT = Path(os.environ["AVAC_QGIS_WORKSPACE_ROOT"]).resolve()
RESULT = Path(os.environ["AVAC_QGIS_RESULT"]).resolve()
sys.path.insert(0, str(WORKSPACE))

runtime_install_override = os.environ.get("AVAC_QGIS_TEST_RUNTIME_INSTALL_ROOT")
if runtime_install_override:
    # Keep the product's normal QStandardPaths behavior untouched while
    # allowing this clean-profile test to prove a genuinely fresh first-use
    # install, even on Windows where Qt resolves a Known Folder directly.
    import avac_qgis.core.runtime as runtime_module  # noqa: E402
    import avac_qgis.core.runtime_assets as runtime_assets_module  # noqa: E402
    import avac_qgis.core.workspace as workspace_module  # noqa: E402

    isolated_runtime_root = Path(runtime_install_override).resolve()
    if isolated_runtime_root.exists():
        raise RuntimeError(
            "AVAC_QGIS_TEST_RUNTIME_INSTALL_ROOT must not exist before the test: "
            f"{isolated_runtime_root}"
        )

    def isolated_runtime_install_root() -> Path:
        return isolated_runtime_root

    # Patch both the defining module and modules that import the function by
    # name.  A QGIS profile may have already imported one of them before this
    # --code script starts, even when third-party plugins are disabled.
    runtime_module.runtime_install_root = isolated_runtime_install_root
    runtime_assets_module.runtime_install_root = isolated_runtime_install_root
    workspace_module.runtime_install_root = isolated_runtime_install_root

from avac_qgis.gui.dock import AvacDockWidget  # noqa: E402
from avac_qgis.core.runtime import platform_key, validate_runtime  # noqa: E402
from avac_qgis.core.runtime_assets import (  # noqa: E402
    RUNTIME_VERSION,
    ensure_bundled_wave_runtime,
    runtime_install_root,
)
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
        avac_manifest = validate_runtime(installed, expected_version=RUNTIME_VERSION)
        import clawpack  # noqa: PLC0415

        clawpack_file = Path(clawpack.__file__).resolve()
        clawpack_root = (installed / avac_manifest["clawpack"]["root"]).resolve()
        try:
            clawpack_file.relative_to(clawpack_root)
        except ValueError as exc:
            raise RuntimeError(
                f"workflow imported Clawpack outside the managed runtime: {clawpack_file}"
            ) from exc
        wave_note = ""
        if os.environ.get("AVAC_QGIS_TEST_INSTALL_WAVE") == "1":
            wave_runtime = ensure_bundled_wave_runtime()
            wave_manifest = validate_runtime(wave_runtime)
            if not (wave_runtime / "backend" / "WAVE" / "setrun.py").is_file():
                raise RuntimeError("automatic Wave runtime install has no WAVE backend")
            if wave_manifest["solver"]["path"] != "bin/xgeoclaw.exe":
                raise RuntimeError("automatic Wave runtime installed an unexpected solver")
            wave_note = f" wave_runtime={wave_runtime}"
        print(
            f"QGIS_RUNTIME_NORMAL=PASS runtime={installed} output={output} "
            f"fort={len(list(output.glob('fort.t*')))} "
            f"fgout={len(list(output.glob('fgout0001.t*')))}{wave_note}",
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
        if not dem.crs().isValid() or not release.crs().isValid():
            raise RuntimeError("test inputs must declare valid coordinate reference systems")
        if dem.crs() != release.crs():
            raise RuntimeError("test DEM and release polygons must use the same CRS")
        QgsProject.instance().addMapLayer(dem); QgsProject.instance().addMapLayer(release)
        dock = AvacDockWidget()
        dock.dem_layer.setLayer(dem); dock.release_layer.setLayer(release); dock.workspace_root.setText(str(WORKSPACE_ROOT))
        # Package smoke fixtures use the native one-metre tutorial grid (or a
        # deterministic crop of it), avoiding any silent domain adjustment.
        dock.parameter_controls["computation.cell_size"].setValue(1)
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


def watchdog() -> None:
    if not RESULT.exists():
        fail("clean-profile runtime workflow exceeded five minutes")


QTimer.singleShot(0, start)
QTimer.singleShot(5 * 60 * 1000, watchdog)
