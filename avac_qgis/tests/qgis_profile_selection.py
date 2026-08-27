"""QGIS regression for ordinary one- and multi-feature profile layers."""

from __future__ import annotations

import sys
from pathlib import Path

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from avac_qgis.gui.dock import AvacDockWidget  # noqa: E402


def line_feature(points):
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*point) for point in points]))
    return feature


def verify() -> None:
    dock = AvacDockWidget()
    single = QgsVectorLayer("LineString?crs=EPSG:2154", "profil", "memory")
    # Exact supplied profil.shp geometry, including its duplicate terminal point.
    single.dataProvider().addFeatures([line_feature([
        (965560.025847458, 6536375.762824026), (965893.4254486539, 6536163.74657278),
        (966694.5555583234, 6535686.30539631), (966694.5555583234, 6535686.30539631),
    ])])
    multi = QgsVectorLayer("LineString?crs=EPSG:2154", "profiles", "memory")
    multi.dataProvider().addFeatures([line_feature([(0, index), (1, index)]) for index in range(3)])
    QgsProject.instance().addMapLayers([single, multi])
    dock.refresh_profile_layers()
    dock.profile_line_layer.setCurrentIndex(dock.profile_line_layer.findData(single.id()))
    assert dock.profile_feature.currentData() is not None
    assert "will be used automatically" in dock.profile_status.text()
    dock.profile_line_layer.setCurrentIndex(dock.profile_line_layer.findData(multi.id()))
    assert dock.profile_feature.currentData() is None and "select one feature" in dock.profile_status.text().lower()
    ids = [feature.id() for feature in multi.getFeatures()]
    multi.selectByIds([ids[0]])
    assert dock.profile_feature.currentData() == ids[0]
    multi.selectByIds(ids[:2])
    assert dock.profile_feature.currentData() is None and "only one" in dock.profile_status.text().lower()
    print("QGIS profile selection single-auto/multi-selection: PASS")
    dock.shutdown(); dock.deleteLater(); QgsApplication.quit()


QTimer.singleShot(0, verify)
