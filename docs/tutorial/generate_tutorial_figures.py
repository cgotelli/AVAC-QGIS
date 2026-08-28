"""Generate the screenshots and result examples used by the tutorial.

Run this script with QGIS Python. The interface screenshots always use the
two public tutorial inputs. Result examples additionally use a completed
workspace supplied with ``--workspace`` (or ``AVAC4QGIS_TUTORIAL_WORKSPACE``).

macOS example::

    PYTHONHOME=/Applications/QGIS.app/Contents/Frameworks \
    QT_QPA_PLATFORM=offscreen \
    PYTHONPATH="$(pwd):/Applications/QGIS.app/Contents/Resources/python" \
    /Applications/QGIS.app/Contents/MacOS/python3.12 \
    docs/tutorial/generate_tutorial_figures.py \
    --workspace /path/to/completed/tutorial/workspace
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import yaml
from osgeo import gdal
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QImage, QPainter
from qgis.core import (
    QgsApplication,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsHillshadeRenderer,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsMarkerSymbol,
    QgsPalettedRasterRenderer,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRectangle,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)

from avac_qgis.gui.dock import AvacDockWidget
from avac_qgis.gui.profile_plot import (
    TimeSeriesPlotWidget,
    write_wave_cross_section_png,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "images"
INPUT_DEM = ROOT / "tutorial" / "topo_cut_dam_1m.tif"
INPUT_RELEASE = ROOT / "tutorial" / "avalanches.geojson"


def _capture(widget, name: str) -> None:
    QgsApplication.processEvents()
    image = widget.grab()
    destination = OUTPUT / name
    if image.isNull() or not image.save(str(destination), "PNG"):
        raise RuntimeError(f"Could not write UI screenshot: {destination}")


def _style_raster(layer: QgsRasterLayer, items, band: int = 1) -> None:
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(float(value), QColor(color), str(label))
        for value, color, label in items
    ])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), int(band), shader))
    layer.triggerRepaint()


def _extent_with_margin(extent: QgsRectangle, fraction: float = 0.025) -> QgsRectangle:
    xpad = max(extent.width() * fraction, 1.0)
    ypad = max(extent.height() * fraction, 1.0)
    return QgsRectangle(
        extent.xMinimum() - xpad,
        extent.yMinimum() - ypad,
        extent.xMaximum() + xpad,
        extent.yMaximum() + ypad,
    )


def _render_map(name: str, layers, extent: QgsRectangle) -> None:
    settings = QgsMapSettings()
    settings.setLayers(list(layers))
    settings.setBackgroundColor(QColor("white"))
    settings.setOutputSize(QSize(1600, 1000))
    settings.setOutputDpi(144)
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:2056"))
    settings.setExtent(_extent_with_margin(extent))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    destination = OUTPUT / name
    if image.isNull() or not image.save(str(destination), "PNG"):
        raise RuntimeError(f"Could not render map: {destination}")


def _render_time_series_plot(name: str, times, values, label: str, unit: str) -> None:
    width, height = 1400, 700
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.white)
    widget = TimeSeriesPlotWidget(times, values, label, unit)
    widget.resize(width, height)
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    if not image.save(str(OUTPUT / name), "PNG"):
        raise RuntimeError(f"Could not write plot: {OUTPUT / name}")


def _first_matching(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No tutorial result matches {pattern} below {root}")
    return matches[-1]


def _completed_products(workspace: Path) -> dict[str, Path]:
    run_marker = _first_matching(workspace, "runs/*/.avac_qgis_run.json")
    runs = sorted(
        path for path in workspace.glob("runs/*/.avac_qgis_run.json")
        if json.loads(path.read_text(encoding="utf-8")).get("status") == "completed"
    )
    if runs:
        run_marker = runs[-1]
    run = run_marker.parent

    wave_results = sorted(workspace.glob("wave_runs/*/qgis_wave_results/results.json"))
    if not wave_results:
        raise FileNotFoundError("The tutorial workspace has no prepared WAVE result products.")
    wave = wave_results[-1].parents[1]
    return {
        "run": run,
        "wave": wave,
        "max_depth": run / "qgis_results" / "max_depth.tif",
        "avac_temporal": run / "qgis_results" / "temporal_fgout0001_depth.tif",
        "max_rise": wave / "qgis_wave_results" / "maximum_surface_rise.tif",
        "snow_outside": wave / "qgis_wave_results" / "temporal_avac_depth_lake_zero.tif",
        "displacement": wave / "qgis_wave_results" / "temporal_surface_displacement.tif",
        "water_elevation": wave / "qgis_wave_results" / "temporal_water_elevation.tif",
        "topography": wave / "Topo" / "topography_lake.asc",
        "volume": wave / "qgis_wave_results" / "lake_volume_history.csv",
    }


def _temporary_matching_raster(
    path: Path,
    source,
    data_type: int,
    *,
    nodata: float,
):
    """Create a compressed one-band raster aligned exactly with ``source``."""
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path), source.RasterXSize, source.RasterYSize, 1, data_type,
        options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    if dataset is None:
        raise RuntimeError(f"Could not create tutorial raster: {path}")
    dataset.SetGeoTransform(source.GetGeoTransform())
    dataset.SetProjection(source.GetProjection())
    dataset.GetRasterBand(1).SetNoDataValue(nodata)
    dataset.GetRasterBand(1).Fill(nodata)
    return dataset


def _generate_avac_preview_examples(dem: QgsRasterLayer) -> None:
    """Render the two spatial checks performed before AVAC preparation."""
    source = gdal.Open(str(INPUT_DEM), gdal.GA_ReadOnly)
    release_source = gdal.OpenEx(str(INPUT_RELEASE), gdal.OF_VECTOR)
    if source is None or release_source is None:
        raise RuntimeError("Could not open the tutorial DEM or release polygons.")
    with TemporaryDirectory(prefix="avac4qgis_tutorial_") as temporary:
        temporary = Path(temporary)

        depth_path = temporary / "initial_depth_preview.tif"
        depth_ds = _temporary_matching_raster(
            depth_path, source, gdal.GDT_Float32, nodata=0.0,
        )
        release_layer = release_source.GetLayer(0)
        if gdal.RasterizeLayer(
            depth_ds, [1], release_layer, burn_values=[0.4],
            options=["ALL_TOUCHED=FALSE"],
        ) != 0:
            raise RuntimeError("Could not rasterize the tutorial release depth.")
        depth_ds.FlushCache()
        depth_ds = None
        depth = QgsRasterLayer(str(depth_path), "Preview Initial Depth")
        _style_raster(depth, [
            (0.0, QColor(255, 255, 255, 0), "0"),
            (0.05, "#fff7bc", "0.05"),
            (0.20, "#fec44f", "0.20"),
            (0.40, "#d7301f", "0.40"),
        ])
        release_outline = QgsVectorLayer(
            str(INPUT_RELEASE), "Release polygon outlines", "ogr",
        )
        release_outline.renderer().setSymbol(QgsFillSymbol.createSimple({
            "color": "255,255,255,0",
            "outline_color": "150,0,0,255",
            "outline_width": "0.8",
        }))
        _render_map(
            "result_initial_depth_preview.png",
            [release_outline, depth, dem],
            dem.extent(),
        )

        zones_path = temporary / "rheology_zones.tif"
        zones_ds = _temporary_matching_raster(
            zones_path, source, gdal.GDT_UInt16, nodata=0,
        )
        input_band = source.GetRasterBand(1)
        output_band = zones_ds.GetRasterBand(1)
        input_nodata = input_band.GetNoDataValue()
        width, height = source.RasterXSize, source.RasterYSize
        chunk_rows = max(1, min(256, 2_000_000 // max(width, 1)))
        for row in range(0, height, chunk_rows):
            count = min(chunk_rows, height - row)
            elevation = input_band.ReadAsArray(0, row, width, count).astype(float)
            valid = np.isfinite(elevation)
            if input_nodata is not None:
                valid &= elevation != input_nodata
            values = np.zeros(elevation.shape, dtype=np.uint16)
            values[valid & (elevation < 1680.0)] = 1
            values[valid & (elevation >= 1680.0)] = 2
            output_band.WriteArray(values, 0, row)
        zones_ds.FlushCache()
        zones_ds = None
        zones = QgsRasterLayer(str(zones_path), "AVAC Rheology Zones")
        zones.setRenderer(QgsPalettedRasterRenderer(
            zones.dataProvider(), 1, [
                QgsPalettedRasterRenderer.Class(
                    1, QColor("#3b7ddd"),
                    "Zone 1 — z < 1680 m (mu 0.30; xi 600 m/s2)",
                ),
                QgsPalettedRasterRenderer.Class(
                    2, QColor("#35a853"),
                    "Zone 2 — z >= 1680 m (mu 0.225; xi 1200 m/s2)",
                ),
            ],
        ))
        zones.setOpacity(0.68)
        _render_map("result_rheology_zones.png", [zones, dem], dem.extent())

    release_source = None
    source = None


def _generate_lake_examples(
    dem: QgsRasterLayer,
    lake: QgsVectorLayer,
    workspace: Path,
) -> None:
    """Show the seed point, connected basin, and exact WAVE-grid preview."""
    feature = next(lake.getFeatures(), None)
    if feature is None:
        raise RuntimeError("The tutorial lake polygon contains no feature.")
    seed_x = float(feature["seed_x"])
    seed_y = float(feature["seed_y"])
    seed = QgsVectorLayer("Point?crs=EPSG:2056", "Clicked lake seed point", "memory")
    seed_feature = QgsFeature()
    seed_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(seed_x, seed_y)))
    seed.dataProvider().addFeature(seed_feature)
    seed.renderer().setSymbol(QgsMarkerSymbol.createSimple({
        "name": "star",
        "color": "255,190,0,255",
        "outline_color": "120,55,0,255",
        "outline_width": "0.8",
        "size": "5.5",
    }))
    _render_map(
        "tutorial_lake_polygon_seed.png",
        [seed, lake, dem],
        lake.extent(),
    )

    preview_path = workspace / "qgis_previews" / "wave_water_level_preview.tif"
    preview = QgsRasterLayer(str(preview_path), "Preview Water Level")
    if not preview.isValid():
        raise RuntimeError(f"The tutorial water-level preview is unavailable: {preview_path}")
    _style_raster(preview, [
        (0.0, QColor(255, 255, 255, 0), "0"),
        (0.20, "#deebf7", "0.2"),
        (5.0, "#9ecae1", "5"),
        (25.0, "#4292c6", "25"),
        (120.0, "#084594", "120"),
    ])
    _render_map(
        "tutorial_water_level_preview.png",
        [lake, preview, dem],
        lake.extent(),
    )


def _generate_result_examples(
    dem: QgsRasterLayer,
    workspace: Path,
    lake: QgsVectorLayer | None,
) -> None:
    product = _completed_products(workspace)

    max_depth = QgsRasterLayer(str(product["max_depth"]), "AVAC maximum depth")
    _style_raster(max_depth, [
        (0.0, QColor(255, 255, 255, 0), "0"),
        (0.05, "#fff7bc", "0.05"),
        (1.0, "#fec44f", "1"),
        (3.0, "#d7301f", "3"),
    ])
    _render_map("result_summary_avac_max_depth.png", [max_depth, dem], max_depth.extent())

    max_rise = QgsRasterLayer(str(product["max_rise"]), "WAVE maximum surface rise")
    _style_raster(max_rise, [
        (0.0, QColor(255, 255, 255, 0), "0"),
        (0.05, "#deebf7", "0.05"),
        (1.0, "#6baed6", "1"),
        (5.0, "#08306b", "5"),
    ])
    _render_map("result_summary_wave_rise.png", [max_rise, dem], max_rise.extent())

    displacement_path = product["displacement"]
    displacement_ds = gdal.Open(str(displacement_path), gdal.GA_ReadOnly)
    snow_ds = gdal.Open(str(product["snow_outside"]), gdal.GA_ReadOnly)
    if displacement_ds is None or snow_ds is None:
        raise RuntimeError("Could not open tutorial temporal products.")
    frame = min(21, displacement_ds.RasterCount, snow_ds.RasterCount)
    displacement = QgsRasterLayer(str(displacement_path), "WAVE surface displacement")
    displacement_renderer_items = [
        (-2.0, "#2166ac", "-2"),
        (-0.001, "#d1e5f0", "-0.001"),
        (0.0, QColor(255, 255, 255, 0), "0"),
        (0.001, "#fddbc7", "0.001"),
        (2.0, "#b2182b", "2"),
    ]
    _style_raster(displacement, displacement_renderer_items, frame)
    snow = QgsRasterLayer(str(product["snow_outside"]), "AVAC snow depth outside lake")
    _style_raster(snow, [
        (0.0, QColor(255, 255, 255, 0), "0"),
        (0.05, "#ffffb2", "0.05"),
        (1.0, "#fecc5c", "1"),
        (3.0, "#e31a1c", "3"),
    ], frame)
    combined_layers = [snow, displacement, dem]
    if lake is not None:
        combined_layers.insert(0, lake)
    _render_map("result_temporal_combined.png", combined_layers, displacement.extent())

    rise_ds = gdal.Open(str(product["max_rise"]), gdal.GA_ReadOnly)
    water_ds = gdal.Open(str(product["water_elevation"]), gdal.GA_ReadOnly)
    topo_ds = gdal.Open(str(product["topography"]), gdal.GA_ReadOnly)
    if rise_ds is None or water_ds is None or topo_ds is None:
        raise RuntimeError("Could not open tutorial profile products.")
    rise = rise_ds.GetRasterBand(1).ReadAsArray().astype(float)
    rise_nodata = rise_ds.GetRasterBand(1).GetNoDataValue()
    initial = water_ds.GetRasterBand(1).ReadAsArray().astype(float)
    water_nodata = water_ds.GetRasterBand(1).GetNoDataValue()
    valid_initial = np.isfinite(initial)
    if water_nodata is not None:
        valid_initial &= initial != water_nodata
    valid_rise = np.isfinite(rise) & valid_initial
    if rise_nodata is not None:
        valid_rise &= rise != rise_nodata
    row, column = np.unravel_index(np.nanargmax(np.where(valid_rise, rise, np.nan)), rise.shape)

    gauge = []
    for band in range(1, displacement_ds.RasterCount + 1):
        value = float(displacement_ds.GetRasterBand(band).ReadAsArray(column, row, 1, 1)[0, 0])
        nodata = displacement_ds.GetRasterBand(band).GetNoDataValue()
        gauge.append(np.nan if nodata is not None and value == nodata else value)
    times = np.arange(displacement_ds.RasterCount, dtype=float)
    _render_time_series_plot(
        "result_gauge_history.png", times, gauge,
        "Surface displacement", "m",
    )

    peak_band = int(np.nanargmax(np.asarray(gauge))) + 1
    surface = water_ds.GetRasterBand(peak_band).ReadAsArray().astype(float)
    surface_nodata = water_ds.GetRasterBand(peak_band).GetNoDataValue()
    topography = topo_ds.GetRasterBand(1).ReadAsArray().astype(float)[1:-1, 1:-1]
    if topography.shape != surface.shape:
        raise RuntimeError("Tutorial topography and water grids do not align.")
    # Keep the section close to the impact zone so that the water column is
    # legible at document scale instead of being flattened by the full-valley
    # relief range.
    start = max(0, column - 70)
    stop = min(surface.shape[1], column + 71)
    ground_line = topography[row, start:stop]
    surface_line = surface[row, start:stop]
    if surface_nodata is not None:
        surface_line = np.where(surface_line == surface_nodata, ground_line, surface_line)
    surface_line = np.where(np.isfinite(surface_line), surface_line, ground_line)
    distance = np.arange(stop - start, dtype=float) * abs(water_ds.GetGeoTransform()[1])
    write_wave_cross_section_png(
        OUTPUT / "result_profile.png",
        distance,
        ground_line,
        surface_line,
        f"Water-surface profile at t = {peak_band - 1:g} s",
        width=1400,
    )

    transform = water_ds.GetGeoTransform()
    y = transform[3] + (row + 0.5) * transform[5]
    x_start = transform[0] + (start + 0.5) * transform[1]
    x_stop = transform[0] + (stop - 0.5) * transform[1]
    profile_line = QgsVectorLayer("LineString?crs=EPSG:2056", "Profile line", "memory")
    profile_feature = QgsFeature()
    profile_feature.setGeometry(QgsGeometry.fromPolylineXY([
        QgsPointXY(x_start, y), QgsPointXY(x_stop, y),
    ]))
    profile_line.dataProvider().addFeature(profile_feature)
    profile_line.renderer().setSymbol(QgsLineSymbol.createSimple({
        "color": "205,70,25,255", "width": "1.6",
    }))
    location_extent = lake.extent() if lake is not None else profile_line.extent()
    location_base = [dem] if lake is None else [lake, dem]
    _render_map(
        "result_profile_location.png",
        [profile_line, *location_base],
        location_extent,
    )

    gauge_x = transform[0] + (column + 0.5) * transform[1]
    gauge_y = transform[3] + (row + 0.5) * transform[5]
    gauge_point = QgsVectorLayer("Point?crs=EPSG:2056", "Gauge point", "memory")
    gauge_feature = QgsFeature()
    gauge_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(gauge_x, gauge_y)))
    gauge_point.dataProvider().addFeature(gauge_feature)
    gauge_point.renderer().setSymbol(QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "255,190,0,255",
        "outline_color": "150,20,20,255",
        "outline_width": "0.9",
        "size": "5.5",
    }))
    _render_map(
        "result_gauge_location.png",
        [gauge_point, *location_base],
        location_extent,
    )

    with product["volume"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    volume_times = np.asarray([float(record["simulation_time_s"]) for record in rows])
    volumes = np.asarray([float(record["lake_water_volume_m3"]) for record in rows])
    _render_time_series_plot(
        "result_lake_volume.png", volume_times, volumes,
        "Lake water volume", "m3",
    )


def _generate_ui_screenshots(dem: QgsRasterLayer, release: QgsVectorLayer, workspace: Path | None) -> None:
    dock = AvacDockWidget()
    try:
        dock.resize(1180, 900)
        dock.workspace_root.setText("Choose a writable tutorial workspace")
        dock.dem_layer.setLayer(dem)
        dock.release_layer.setLayer(release)
        dock.show()
        _capture(dock, "tutorial_overview.png")

        dock.workflow_tabs.setCurrentWidget(dock.inputs_scroll)
        dock.rheology_zones.setPlainText(
            "0.30, 600, 0,\n0.225, 1200, 0, 1680"
        )
        for index, name in enumerate((
            "tutorial_avac_inputs.png",
            "tutorial_avac_release.png",
            "tutorial_avac_rheology.png",
            "tutorial_avac_numerical.png",
        )):
            dock.parameter_toolbox.setCurrentIndex(index)
            _capture(dock.workflow_tabs, name)

        dock.workflow_tabs.setCurrentWidget(dock.run_scroll)
        _capture(dock.workflow_tabs, "tutorial_avac_run.png")

        dock.wave_extension_toggle.setChecked(True)
        dock.wave_lake_dem.setLayer(dem)
        lake_layers = list(QgsProject.instance().mapLayersByName("Tutorial lake polygon"))
        if lake_layers:
            dock.wave_lake_boundary.setLayer(lake_layers[0])
        if workspace is not None:
            dock.workspace_root.setText(str(workspace))
            dock.refresh_wave_avac_runs()
            dock.refresh_results_runs()
            dock.refresh_wave_results_runs()
            wave_configs = sorted(workspace.glob("wave_runs/*/impulse_configuration.yaml"))
            if wave_configs:
                configuration = yaml.safe_load(wave_configs[-1].read_text(encoding="utf-8")) or {}
                lake = configuration.get("lake") or {}
                computation = configuration.get("computation") or {}
                if lake.get("water_level") is not None:
                    dock.wave_water_level.setValue(float(lake["water_level"]))
                if computation.get("cell_size") is not None:
                    dock.wave_cell_size.setValue(float(computation["cell_size"]))
            dock.results_progress.setRange(0, 1)
            dock.results_progress.setValue(1)
            dock.results_progress.setFormat("Completed results available")
        dock.workflow_tabs.setCurrentWidget(dock.wave_setup_scroll)
        for index, name in enumerate((
            "tutorial_wave_source.png",
            "tutorial_wave_lake.png",
            "tutorial_wave_model.png",
        )):
            dock.wave_parameter_toolbox.setCurrentIndex(index)
            _capture(dock.workflow_tabs, name)

        dock.workflow_tabs.setCurrentWidget(dock.wave_run_scroll)
        _capture(dock.workflow_tabs, "tutorial_wave_run.png")

        dock.workflow_tabs.setCurrentWidget(dock.results_scroll)
        for index, name in enumerate((
            "tutorial_results_runs.png",
            "tutorial_results_summary.png",
            "tutorial_results_temporal.png",
            "tutorial_results_profile.png",
            "tutorial_results_gauges.png",
            "tutorial_results_volume.png",
        )):
            if index < dock.results_toolbox.count():
                dock.results_toolbox.setCurrentIndex(index)
                _capture(dock.workflow_tabs, name)
    finally:
        dock.shutdown()
        dock.close()
        dock.deleteLater()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(os.environ["AVAC4QGIS_TUTORIAL_WORKSPACE"]) if os.environ.get("AVAC4QGIS_TUTORIAL_WORKSPACE") else None,
        help="completed AVAC4QGIS workspace used for authentic result examples",
    )
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve() if args.workspace else None
    if workspace is not None and not workspace.is_dir():
        raise SystemExit(f"Tutorial workspace does not exist: {workspace}")
    if not INPUT_DEM.is_file() or not INPUT_RELEASE.is_file():
        raise SystemExit("The public tutorial DEM and release layer are missing.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    application = QgsApplication([], False)
    application.initQgis()
    try:
        project = QgsProject.instance()
        dem = QgsRasterLayer(str(INPUT_DEM), "Tutorial terrain DEM")
        release = QgsVectorLayer(str(INPUT_RELEASE), "Tutorial avalanche release polygons", "ogr")
        if not dem.isValid() or not release.isValid():
            raise RuntimeError("The tutorial DEM or release layer could not be loaded in QGIS.")
        project.addMapLayers([dem, release])
        release.renderer().setSymbol(QgsFillSymbol.createSimple({
            "color": "230,40,40,90",
            "outline_color": "180,0,0,255",
            "outline_width": "0.7",
        }))
        hillshade = QgsHillshadeRenderer(dem.dataProvider(), 1, 315.0, 45.0)
        hillshade.setMultiDirectional(True)
        hillshade.setZFactor(1.0)
        dem.setRenderer(hillshade)
        dem.triggerRepaint()
        _render_map("tutorial_input_layers.png", [release, dem], dem.extent())
        _generate_avac_preview_examples(dem)

        if workspace is not None:
            lake = None
            lake_candidates = sorted((workspace / "derived_inputs").glob("*.gpkg"))
            if lake_candidates:
                lake = QgsVectorLayer(str(lake_candidates[-1]), "Tutorial lake polygon", "ogr")
                if lake.isValid():
                    lake.renderer().setSymbol(QgsFillSymbol.createSimple({
                        "color": "120,190,235,42",
                        "outline_color": "70,160,215,230",
                        "outline_width": "0.9",
                    }))
                    project.addMapLayer(lake)
                    _generate_lake_examples(dem, lake, workspace)
                else:
                    lake = None
            _generate_result_examples(dem, workspace, lake)
        _generate_ui_screenshots(dem, release, workspace)
    finally:
        application.exitQgis()


if __name__ == "__main__":
    main()
