"""End-to-end derived-raster validation against the AVAC/Clawpack reader."""

from __future__ import annotations

import time
import os
from pathlib import Path

import numpy as np
from osgeo import gdal
from qgis.PyQt.QtCore import QCoreApplication, QDateTime, Qt, QTimer
from qgis.core import QgsDateTimeRange, QgsRasterLayer, QgsRasterLayerTemporalProperties

from avac_qgis.core.results import (
    EPOCH_ISO, RESULT_DIRECTORY, _load_fgmax, _load_fgout, discover_results, materialize_results,
)


ROOT = Path(os.environ.get("AVAC_QGIS_RESULTS_ROOT", "/private/tmp/avac-task5-reference.xYbL9r"))


def raster_array(path: Path, band: int = 1) -> np.ndarray:
    dataset = gdal.Open(str(path))
    data = dataset.GetRasterBand(band).ReadAsArray().astype(float)
    dataset = None
    return np.where(np.flipud(data) == -9999.0, np.nan, np.flipud(data))


def comparison(actual: np.ndarray, expected: np.ndarray) -> tuple[float, int]:
    finite = np.isfinite(actual) & np.isfinite(expected)
    nodata_mismatch = np.count_nonzero(np.isfinite(actual) != np.isfinite(expected))
    difference = np.abs(actual[finite] - expected[finite])
    return (float(difference.max()) if difference.size else 0.0, int(np.count_nonzero(difference) + nodata_mismatch))


def check() -> None:
    try:
        discovered = discover_results(ROOT)
        timings = {}
        started = time.monotonic()
        manifest = materialize_results(discovered, ())
        timings["static"] = time.monotonic() - started
        variables = tuple(filter(None, os.environ.get("AVAC_QGIS_RESULT_VARIABLES", "depth,velocity,pressure").split(",")))
        for variable in variables:
            started = time.monotonic()
            manifest = materialize_results(discovered, (variable,))
            timings[variable] = time.monotonic() - started
        derived = ROOT / RESULT_DIRECTORY
        x, y, static = _load_fgmax(discovered)
        for name, expected in static.items():
            actual = raster_array(derived / manifest["static"][name]["path"])
            max_abs, differing = comparison(actual, expected)
            print(f"STATIC {name} shape={actual.shape} max_abs={max_abs:.12g} differing={differing}", flush=True)
        selected = sorted({0, len(discovered.frames) // 2, len(discovered.frames) - 1})
        for index in selected:
            descriptor = discovered.frames[index]
            actual_time, _x, _y, expected = _load_fgout(discovered, descriptor.frame_id)
            for variable, array in expected.items():
                if variable not in variables:
                    continue
                actual = raster_array(derived / manifest["temporal"][f"fgout0001_{variable}"]["path"], index + 1)
                max_abs, differing = comparison(actual, array)
                print(
                    f"TEMPORAL {variable} frame={descriptor.frame_id} time={actual_time:g} "
                    f"shape={actual.shape} min={np.nanmin(array):.12g} max={np.nanmax(array):.12g} "
                    f"max_abs={max_abs:.12g} differing={differing}", flush=True
                )
        temporal = derived / manifest["temporal"][f"fgout0001_{variables[0]}"]["path"]
        dataset = gdal.Open(str(temporal))
        descriptions = [dataset.GetRasterBand(band).GetDescription() for band in range(1, dataset.RasterCount + 1)]
        band_times = [dataset.GetRasterBand(band).GetMetadataItem("AVAC_SIMULATION_TIME_SECONDS") for band in range(1, dataset.RasterCount + 1)]
        band_starts = [dataset.GetRasterBand(band).GetMetadataItem("AVAC_TEMPORAL_START_ISO8601") for band in range(1, dataset.RasterCount + 1)]
        dataset = None
        if len(set(descriptions)) != len(descriptions) or len(set(band_starts)) != len(band_starts):
            raise ValueError(f"Temporal bands are not uniquely described: descriptions={descriptions} starts={band_starts}")
        if [float(value) for value in band_times] != [float(value) for value in manifest["simulation_time_seconds"]]:
            raise ValueError(f"GeoTIFF band times do not match manifest: {band_times}")
        if manifest.get("temporal_origin_iso") == EPOCH_ISO:
            raise ValueError("Temporal materialization retained the arbitrary legacy epoch")
        layer = QgsRasterLayer(str(temporal), "Temporal test")
        props = layer.temporalProperties()
        props.setIsActive(True)
        props.setMode(QgsRasterLayerTemporalProperties.FixedRangePerBand)
        epoch = QDateTime.fromString(manifest["temporal_origin_iso"], Qt.ISODate)
        props.setFixedRangePerBand({
            band: QgsDateTimeRange(epoch.addMSecs(round(seconds * 1000)), epoch.addMSecs(round(seconds * 1000 + 1)))
            for band, seconds in enumerate(manifest["simulation_time_seconds"], 1)
        })
        print(f"MATERIALIZATION frames={len(discovered.frames)} timings={timings} bytes={sum(p.stat().st_size for p in derived.glob('*.tif'))} temporal_valid={layer.isValid()} temporal_active={props.isActive()} bands={layer.bandCount()} extent={layer.extent().toString()}", flush=True)
    except Exception:  # noqa: BLE001
        import traceback
        print("RESULT_MATERIALIZE_FAILURE\n" + traceback.format_exc(), flush=True)
    QCoreApplication.quit()


QTimer.singleShot(0, check)
