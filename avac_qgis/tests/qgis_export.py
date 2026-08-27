"""Normal-QGIS rendering and four-frame ffmpeg export regression."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import QgsProject
from qgis.utils import loadPlugin, plugins, startPlugin

from avac_qgis.core.export import animation_frames, animation_provenance, locate_ffmpeg
from avac_qgis.core.results import RESULT_DIRECTORY


ROOT = Path(os.environ["AVAC_QGIS_EXPORT_RUN_ROOT"])
OUT = Path(tempfile.mkdtemp(prefix="avac_qgis_export_test_"))


def fail(message: str) -> None:
    print(f"QGIS_EXPORT_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def encoded(exit_code: int, normal: bool) -> None:
    if exit_code != 0 or not video.is_file():
        fail(f"ffmpeg exit={exit_code} normal={normal} log={dock.log.toPlainText()[-1500:]}"); return
    metadata = json.loads(video.with_suffix(".json").read_text())
    if metadata["frame_bands"] != [1, 2, 3, 4] or metadata["simulation_time_seconds"] != [0.0, 2.3333333, 4.6666667, 7.0]:
        fail(f"bad provenance={metadata}"); return
    ffprobe = locate_ffmpeg().with_name("ffprobe")
    probe = subprocess.run(
        [str(ffprobe), "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video)],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "4":
        fail(f"video frame count={probe.stdout!r} stderr={probe.stderr!r}"); return
    print(f"QGIS_EXPORT=True png={static_png.name},{temporal_png.name} video={video.name} bytes={video.stat().st_size} times={metadata['simulation_time_seconds']}", flush=True)
    plugins["avac_qgis"].unload()
    QCoreApplication.quit()


def start_animation() -> None:
    global video
    variable = "depth"
    layer, _name, unit, _time, product = dock._export_layer(variable)
    dock._animation_frames = animation_frames([float(v) for v in dock._results_manifest["simulation_time_seconds"]])
    dock._animation_temp_dir = OUT / "frames"; dock._animation_temp_dir.mkdir()
    video = OUT / "avac_depth_animation.mp4"
    dock._animation_output = video
    dock._animation_previous_range = QgsProject.instance().timeSettings().temporalRange()
    extent = dock._export_extent_for(layer)
    dock._animation_metadata = animation_provenance(ROOT, variable, dock._animation_frames, 8, (extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum()), product["range"])
    dock._animation_metadata["unit"] = unit
    dock._animation_index = 0
    dock._animation_process.finished.connect(encoded)
    dock._render_next_animation_frame()


def temporal_loaded() -> None:
    global static_png, temporal_png
    try:
        temporal = dock._active_avac_temporal_layer()
        if temporal is None:
            fail("temporal layer missing"); return
        dock.export_extent.setCurrentIndex(1)
        dock.export_width.setValue(640)
        static = dock._add_raster(ROOT / RESULT_DIRECTORY / dock._results_manifest["static"]["max_depth"]["path"], "Export static", float(dock._results_manifest["static"]["max_depth"]["range"][1]), "m")
        static_png = OUT / "avac_max_depth.png"
        dock._render_export_png(static_png, static, "maximum depth", "m", None)
        dock._set_temporal_band(3)
        temporal_png = OUT / "avac_depth_t4.6666667.png"
        dock._render_export_png(temporal_png, temporal, "depth", "m", 4.6666667)
        if not static_png.is_file() or not temporal_png.is_file():
            fail("PNG output missing"); return
        QTimer.singleShot(0, start_animation)
    except Exception as exc:  # noqa: BLE001
        fail(repr(exc))


def run() -> None:
    global dock
    if locate_ffmpeg() is None:
        fail("development ffmpeg missing"); return
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable"); return
        startPlugin("avac_qgis")
    plugins["avac_qgis"].show_dock(); dock = plugins["avac_qgis"].dock
    dock.results_run_root.setText(str(ROOT))
    dock.temporal_variable.setCurrentIndex(0)
    dock.load_temporal_button.click()
    dock._results_task.taskCompleted.connect(temporal_loaded)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.status.text()))


QTimer.singleShot(1000, run)
