"""QGIS 3.44 isolation regression for a native fixed-range-per-band raster.

Run through the QGIS desktop application's Python ``--code`` facility.  It
uses the live Temporal Controller widget and its connected map-canvas
controller, not a standalone QgsTemporalNavigationObject.
"""

from __future__ import annotations

from pathlib import Path
import tempfile

import numpy as np
from osgeo import gdal
from qgis.PyQt.QtCore import QCoreApplication, QDateTime, Qt, QTimer
from qgis.core import Qgis, QgsDateTimeRange, QgsInterval, QgsProject, QgsRasterLayer, QgsRasterLayerTemporalProperties
from qgis.gui import QgsTemporalControllerWidget
from qgis.utils import iface


def fail(message: str) -> None:
    print(f"QGIS_NATIVE_TEMPORAL_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def run() -> None:
    temporary = tempfile.TemporaryDirectory(prefix="avac-qgis-native-temporal-")
    path = Path(temporary.name) / "three_states.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 2, 2, 3, gdal.GDT_Float32)
    for band, value in enumerate((1.0, 2.0, 3.0), 1):
        dataset.GetRasterBand(band).WriteArray(np.full((2, 2), value, dtype=np.float32))
    dataset = None
    layer = QgsRasterLayer(str(path), "native temporal diagnostic")
    if not layer.isValid():
        fail("unable to create three-band diagnostic GeoTIFF")
        return
    QgsProject.instance().addMapLayer(layer)
    epoch = QDateTime.fromString("2000-01-01T00:00:00Z", Qt.ISODate)
    ranges = {
        band: QgsDateTimeRange(epoch.addSecs(band - 1), epoch.addSecs(band), True, False)
        for band in range(1, 4)
    }
    properties = layer.temporalProperties()
    properties.setIsActive(True)
    properties.setMode(QgsRasterLayerTemporalProperties.FixedRangePerBand)
    properties.setIntervalHandlingMethod(Qgis.TemporalIntervalMatchMethod.MatchUsingWholeRange)
    properties.setFixedRangePerBand(ranges)
    widget = iface.mainWindow().findChild(QgsTemporalControllerWidget)
    canvas_controller = iface.mapCanvas().temporalController()
    if widget is None or widget.temporalController() != canvas_controller:
        fail("visible Temporal Controller is not connected to map canvas")
        return
    controller = widget.temporalController()
    controller.setNavigationMode(Qgis.TemporalNavigationMode.Animated)
    controller.setTemporalRangeCumulative(False)
    controller.setAvailableTemporalRanges([])
    controller.setTemporalExtents(QgsDateTimeRange(epoch, epoch.addSecs(3), True, False))
    controller.setFrameDuration(QgsInterval(1, Qgis.TemporalUnit.Seconds))
    resolved, samples = [], []
    point = layer.extent().center()
    for frame in range(3):
        controller.setCurrentFrameNumber(frame)
        QCoreApplication.processEvents()
        frame_range = controller.dateTimeRangeForFrameNumber(frame)
        band = properties.bandForTemporalRange(layer, frame_range)
        resolved.append(band)
        samples.append(layer.dataProvider().sample(point, band)[0])
        iface.mapCanvas().refresh()
        QCoreApplication.processEvents()
    if controller.totalFrameCount() != 3 or resolved != [1, 2, 3] or samples != [1.0, 2.0, 3.0]:
        fail(f"frames={controller.totalFrameCount()} resolved={resolved} samples={samples}")
        return
    print("QGIS_NATIVE_TEMPORAL=True frames=3 resolved=[1, 2, 3] samples=[1.0, 2.0, 3.0]", flush=True)
    QgsProject.instance().removeMapLayer(layer.id())
    temporary.cleanup()
    QCoreApplication.quit()


QTimer.singleShot(1000, run)
