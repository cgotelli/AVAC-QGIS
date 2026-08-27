"""Normal-QGIS profile selection, CRS transform, static/temporal extraction."""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import time

import numpy as np
import yaml

from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QSettings, Qt, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDateTimeRange, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.utils import loadPlugin, plugins, startPlugin

from avac_qgis.core.profiles import bilinear_sample, sample_polyline_positions
from avac_qgis.core.profiles import write_profile_csv
from avac_qgis.core.results import _load_fgmax, _load_fgout, discover_results
from avac_qgis.gui.profile_plot import ProfilePlotDialog


ROOT = Path("/private/tmp/avac-task5-reference.xYbL9r")
PROFILE = "/Users/cmgotelli/Downloads/Lac_Clusaz/Topo/profil.shp"


def fail(message: str) -> None:
    print(f"QGIS_PROFILE_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def temporal_ready() -> None:
    epoch = QDateTime.fromString(dock._results_manifest["temporal_origin_iso"], Qt.ISODate)
    QgsProject.instance().timeSettings().setTemporalRange(QgsDateTimeRange(epoch.addMSecs(75503), epoch.addMSecs(75504)))
    dock.profile_source.setCurrentIndex(dock.profile_source.findData("frame"))
    dock.profile_variable.setCurrentIndex(dock.profile_variable.findData("avac:velocity"))
    started = time.perf_counter()
    dock.extract_profile()
    extract_seconds = time.perf_counter() - started
    profile = dock._last_profile
    if profile is None or profile.variable != "velocity" or profile.simulation_time_s is None:
        fail(f"temporal extraction failed: {dock.status.text()}")
        return
    print(f"QGIS_TEMPORAL_PROFILE=True samples={profile.values.size} time={profile.simulation_time_s:g} finite={int((profile.values == profile.values).sum())}", flush=True)
    started = time.perf_counter()
    dialog = ProfilePlotDialog(profile)
    dialog.close()
    plot_seconds = time.perf_counter() - started
    with tempfile.TemporaryDirectory() as directory:
        started = time.perf_counter()
        write_profile_csv(Path(directory) / "profile.csv", profile)
        csv_seconds = time.perf_counter() - started
    print(f"QGIS_PROFILE_PERFORMANCE extract_s={extract_seconds:.6f} plot_s={plot_seconds:.6f} csv_s={csv_seconds:.6f}", flush=True)
    validation_vectors()
    QCoreApplication.quit()


def validation_vectors() -> None:
    """Compare all values at the standalone GUI's exact 1,000 positions."""
    discovery = discover_results(ROOT)
    geometry = next(line_layer.getFeatures()).geometry().mergeLines().asPolyline()
    coords = np.array([(point.x(), point.y()) for point in geometry])
    _distance, xq, yq = sample_polyline_positions(coords, count=1000)
    manifest = json.loads((ROOT / "qgis_results" / "results.json").read_text())
    x, y, fields = _load_fgmax(discovery)
    extent = yaml.safe_load((ROOT / "AVAC" / "AVAC_configuration.yaml").read_text())["dem_extent"]
    legacy_x, legacy_y = np.linspace(extent["xmin"], extent["xmax"], x.size), np.linspace(extent["ymin"], extent["ymax"], y.size)

    def standalone_bilinear(values):
        """Literal arithmetic from standalone ResultsTab._sample_regular_grid."""
        ix = np.clip(np.searchsorted(legacy_x, xq, side="right") - 1, 0, legacy_x.size - 2)
        iy = np.clip(np.searchsorted(legacy_y, yq, side="right") - 1, 0, legacy_y.size - 2)
        tx = (xq - legacy_x[ix]) / (legacy_x[ix + 1] - legacy_x[ix])
        ty = (yq - legacy_y[iy]) / (legacy_y[iy + 1] - legacy_y[iy])
        return ((1 - tx) * (1 - ty) * values[iy, ix] + tx * (1 - ty) * values[iy, ix + 1]
                + (1 - tx) * ty * values[iy + 1, ix] + tx * ty * values[iy + 1, ix + 1])

    for variable, key in (("depth", "max_depth"), ("velocity", "max_velocity"), ("pressure", "max_pressure")):
        expected = standalone_bilinear(fields[key])
        actual = bilinear_sample(legacy_x, legacy_y, fields[key], xq, yq)
        print(f"PROFILE_STATIC_VALIDATION {variable} samples={actual.size} max_abs={np.nanmax(abs(actual - expected)):.12g} mean_abs={np.nanmean(abs(actual - expected)):.12g} endpoints={actual[0]:.12g},{actual[-1]:.12g} nodata={int((~np.isfinite(actual)).sum())}", flush=True)
        rx, ry, raster = dock._raster_band_axes(ROOT / "qgis_results" / manifest["static"][key]["path"], 1)
        qgis_values, raw_values = bilinear_sample(rx, ry, raster, xq, yq), bilinear_sample(x, y, fields[key], xq, yq)
        print(f"PROFILE_STATIC_RASTER {variable} max_abs={np.nanmax(abs(qgis_values - raw_values)):.12g} mean_abs={np.nanmean(abs(qgis_values - raw_values)):.12g}", flush=True)
    descriptor = discovery.frames[75]
    actual_time, x, y, fields = _load_fgout(discovery, descriptor.frame_id)
    for variable in ("depth", "velocity", "pressure"):
        expected = bilinear_sample(x, y, fields[variable], xq, yq)
        path = ROOT / "qgis_results" / manifest["temporal"][f"fgout0001_{variable}"]["path"]
        rx, ry, raster = dock._raster_band_axes(path, 76)
        actual = bilinear_sample(rx, ry, raster, xq, yq)
        print(f"PROFILE_TEMPORAL_VALIDATION {variable} time={actual_time:.12g} samples={actual.size} max_abs={np.nanmax(abs(actual - expected)):.12g} mean_abs={np.nanmean(abs(actual - expected)):.12g} endpoints={actual[0]:.12g},{actual[-1]:.12g} nodata={int((~np.isfinite(actual)).sum())}", flush=True)


def static_ready() -> None:
    dock.refresh_profile_layers()
    index = dock.profile_line_layer.findData(transformed_line.id())
    if index < 0:
        fail("ordinary project line layer is missing from Profile layer selector")
        return
    dock.profile_line_layer.setCurrentIndex(index)
    dock._refresh_profile_features(transformed_line)
    dock.temporal_variable.setCurrentIndex(1)
    dock.load_temporal_button.click()
    dock._results_task.taskCompleted.connect(temporal_ready)


def run() -> None:
    global dock, line_layer, transformed_line
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("plugin not discoverable")
            return
        startPlugin("avac_qgis")
    line_layer = QgsVectorLayer(PROFILE, "Profiles", "ogr")
    if not line_layer.isValid():
        fail("profile shapefile unavailable")
        return
    QgsProject.instance().addMapLayer(line_layer)
    first = next(line_layer.getFeatures())
    line_layer.selectByIds([first.id()])
    transformed_line = QgsVectorLayer("LineString?crs=EPSG:4326", "Profile in WGS 84", "memory")
    transformed = QgsGeometry(first.geometry())
    transformed.transform(QgsCoordinateTransform(line_layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()))
    feature = QgsFeature(transformed_line.fields())
    feature.setGeometry(transformed)
    transformed_line.dataProvider().addFeatures([feature])
    transformed_line.updateExtents()
    transformed_line.selectByIds([next(transformed_line.getFeatures()).id()])
    QgsProject.instance().addMapLayer(transformed_line)
    plugins["avac_qgis"].show_dock()
    dock = plugins["avac_qgis"].dock
    dock.results_run_root.setText(str(ROOT))
    dock.load_summary_button.click()
    dock._results_task.taskCompleted.connect(static_ready)
    dock._results_task.taskTerminated.connect(lambda: fail(dock.log.toPlainText()))


QTimer.singleShot(1000, run)
