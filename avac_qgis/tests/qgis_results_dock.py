"""Exercise results reopening, layer loading, and temporal-band setup in QGIS."""

from __future__ import annotations

from pathlib import Path
import os

from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QSettings, Qt, QTimer
from qgis.PyQt.QtWidgets import QAction
from qgis.core import Qgis, QgsDateTimeRange, QgsProject
from avac_qgis.core.results import EPOCH_ISO
from qgis.utils import iface, loadPlugin, plugins, startPlugin


ROOT = Path("/private/tmp/avac-task5-reference.xYbL9r")
original_cwd: str | None = None


def fail(message: str) -> None:
    print(f"QGIS_RESULTS_DOCK_FAILURE={message}", flush=True)
    if original_cwd is not None:
        os.chdir(original_cwd)
    QCoreApplication.quit()


def completed() -> None:
    names = [layer.name() for layer in QgsProject.instance().mapLayers().values()]
    temporal = next((layer for layer in QgsProject.instance().mapLayers().values() if layer.name().startswith("AVAC Depth (Temporal)")), None)
    if temporal is None:
        fail(f"temporal layer was not loaded; layers={names}")
        return
    props = temporal.temporalProperties()
    ranges = props.fixedRangePerBand()
    origins = {value.begin().toString(Qt.ISODateWithMs) for value in ranges.values()}
    if len(origins) != temporal.bandCount() or temporal.customProperty("avac/temporal_origin_iso") == EPOCH_ISO:
        fail(f"temporal bands do not have unique meaningful starts: {sorted(origins)}")
        return
    bands = [props.bandForTemporalRange(temporal, ranges[index]) for index in range(1, temporal.bandCount() + 1)]
    filtered = [list(props.filteredBandsForTemporalRange(temporal, ranges[index])) for index in range(1, temporal.bandCount() + 1)]
    if bands != list(range(1, temporal.bandCount() + 1)) or filtered != [[index] for index in range(1, temporal.bandCount() + 1)]:
        fail(f"temporal band mapping is not one-to-one: bands={bands} filtered={filtered}")
        return
    controller, canvas_controller, widget = dock._temporal_controller()
    if controller is None or controller != canvas_controller:
        fail("Temporal Controller navigation object is not the controller connected to the map canvas")
        return
    temporal_action = iface.mainWindow().findChild(QAction, "mActionTemporalController")
    if temporal_action is not None and not temporal_action.isChecked():
        fail("Temporal Controller panel was not opened automatically")
        return
    expected_count = temporal.bandCount()
    if controller.navigationMode() != Qgis.TemporalNavigationMode.Animated:
        fail(f"canvas controller is not Animated: mode={controller.navigationMode()}")
        return
    if controller.temporalRangeCumulative():
        fail("canvas controller is cumulative")
        return
    controller_ranges = [controller.dateTimeRangeForFrameNumber(index) for index in range(controller.totalFrameCount())]
    controller_bands = [props.bandForTemporalRange(temporal, item) for item in controller_ranges]
    controller_filtered = [list(props.filteredBandsForTemporalRange(temporal, item)) for item in controller_ranges]
    if controller.totalFrameCount() != expected_count:
        fail(f"canvas controller frame count is wrong: frames={controller.totalFrameCount()} bands={expected_count}")
        return
    if controller_bands != list(range(1, expected_count + 1)) or controller_filtered != [[index] for index in range(1, expected_count + 1)]:
        fail(
            "actual canvas controller ranges do not resolve one-to-one: "
            f"bands={controller_bands} filtered={controller_filtered}"
        )
        return
    # This exercises the live navigation object which drives the canvas,
    # rather than only constructing synthetic QgsDateTimeRanges.
    for frame in range(min(4, expected_count)):
        controller.setCurrentFrameNumber(frame)
        QCoreApplication.processEvents()
        iface.mapCanvas().refresh()
        QCoreApplication.processEvents()
        current = controller.dateTimeRangeForFrameNumber(controller.currentFrameNumber())
        if props.bandForTemporalRange(temporal, current) != frame + 1:
            fail(f"manual canvas frame step {frame} did not resolve band {frame + 1}")
            return
    global preserved_range
    preserved_range = ranges[2]
    QgsProject.instance().timeSettings().setTemporalRange(preserved_range)
    print(
        "QGIS_DEPTH_LOADED=True "
        f"bands={bands} filtered={filtered} controller_frames={controller.totalFrameCount()} "
        f"controller_bands={controller_bands} controller_filtered={controller_filtered}",
        flush=True,
    )
    dock.temporal_variable.setCurrentIndex(1)  # Velocity
    dock.load_temporal_button.click()
    dock._results_task.taskCompleted.connect(velocity_completed)


def velocity_completed() -> None:
    names = [layer.name() for layer in QgsProject.instance().mapLayers().values()]
    velocity = next((layer for layer in QgsProject.instance().mapLayers().values() if layer.name().startswith("AVAC Velocity (Temporal)")), None)
    if velocity is None:
        fail(f"velocity layer missing; layers={names}")
        return
    retained = QgsProject.instance().timeSettings().temporalRange() == preserved_range
    print(f"QGIS_VELOCITY_SWITCH=True layers={names} retained_time={retained} variable={velocity.customProperty('avac/temporal_variable')}", flush=True)
    dock.temporal_variable.setCurrentIndex(2)  # Pressure
    dock.load_temporal_button.click()
    dock._results_task.taskCompleted.connect(pressure_completed)


def pressure_completed() -> None:
    names = [layer.name() for layer in QgsProject.instance().mapLayers().values()]
    pressure = next((layer for layer in QgsProject.instance().mapLayers().values() if layer.name().startswith("AVAC Pressure (Temporal)")), None)
    if pressure is None:
        fail(f"pressure layer missing; layers={names}")
        return
    retained = QgsProject.instance().timeSettings().temporalRange() == preserved_range
    print(f"QGIS_TEMPORAL_PRESSURE=True layers={names} retained_time={retained} variable={pressure.customProperty('avac/temporal_variable')}", flush=True)
    dock.summary_map.setCurrentIndex(dock.summary_map.findData("max_depth"))
    dock.load_summary_button.click()
    dock._results_task.taskCompleted.connect(static_completed)


def static_completed() -> None:
    names = {layer.name() for layer in QgsProject.instance().mapLayers().values()}
    required = "AVAC Maximum Depth"
    if not any(name.startswith(required) for name in names):
        fail(f"static result layer missing: {required}")
        return
    print(f"QGIS_RESULTS_DOCK=True static_layer={required} retained_time={QgsProject.instance().timeSettings().temporalRange() == preserved_range} status={dock.status.text()}", flush=True)
    if original_cwd is not None:
        os.chdir(original_cwd)
    QCoreApplication.quit()


def run() -> None:
    global dock
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable")
            return
        startPlugin("avac_qgis")
    plugin = plugins.get("avac_qgis")
    # Reopen regression: QGIS may restart with '/' as its cwd. Temporal result
    # decoding must not let PyClaw create cwd-relative pyclaw.log there.
    global original_cwd
    original_cwd = os.getcwd()
    os.chdir("/")
    plugin.show_dock()
    dock = plugin.dock
    dock.results_run_root.setText(str(ROOT))
    dock.load_temporal_button.click()
    task = dock._results_task
    if task is None:
        fail("results task did not start")
        return
    task.taskCompleted.connect(completed)
    task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()))


QTimer.singleShot(1000, run)
