"""Manual QGIS runtime smoke test: run with QGIS --noplugins --code <this file>."""

from __future__ import annotations

import sys
import json
import os
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import yaml
from qgis.PyQt.QtWidgets import QFileDialog, QScrollArea, QSlider
from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsRectangle, QgsRasterLayer, QgsVectorLayer
from qgis.gui import QgsMapCanvas, QgsMapLayerComboBox

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avac_qgis.gui.dock import AvacDockWidget  # noqa: E402
from avac_qgis.core.configuration import controlled_values, load_complete_configuration  # noqa: E402
from avac_qgis.core.preprocessing import AvacRaster  # noqa: E402
from avac_qgis.core.preprocessing import raster_from_qgis_layer  # noqa: E402
from avac_qgis.core.wave_boundaries import _finite_boundary_state  # noqa: E402
from avac_qgis.core.wave_project import prepare_wave_scenario, terrain_for_wave_domain  # noqa: E402
from avac_qgis.core.avac_lake_depth import _write_lake_zero_product  # noqa: E402
from avac_qgis.core.runtime_assets import default_template_path  # noqa: E402
from avac_qgis.core.environment import available_cpu_cores  # noqa: E402
from avac_qgis.gui.profile_plot import write_wave_cross_section_png  # noqa: E402


def verify() -> None:
    # A QGIS profile can retain the old installed-plugin resource directory.
    # The current packaged built-in template must replace that stale path, but
    # only when it is recognizably the built-in filename.
    settings = QSettings()
    template_key = AvacDockWidget.SETTINGS_TEMPLATE
    previous_template = settings.value(template_key, None)
    settings.setValue(template_key, "/private/tmp/old-plugin/avac_qgis/resources/AVAC_configuration100.yaml")
    try:
        dock = AvacDockWidget()
        assert Path(dock.configuration_template.text()) == Path(default_template_path())

        # An unrelated user file with the same basename must remain explicit,
        # rather than being mistaken for a prior plugin installation.
        custom_template = "/private/tmp/custom-case/AVAC_configuration100.yaml"
        settings.setValue(template_key, custom_template)
        custom_dock = AvacDockWidget()
        assert custom_dock.configuration_template.text() == custom_template
    finally:
        if previous_template is None:
            settings.remove(template_key)
        else:
            settings.setValue(template_key, previous_template)
    assert dock.windowTitle() == "AVAC4QGIS"
    assert [dock.workflow_tabs.tabText(index) for index in range(dock.workflow_tabs.count())] == ["AVAC Parameters", "AVAC Run", "Results"]
    assert not dock.wave_extension_toggle.isChecked()
    assert not hasattr(dock, "results_source_selector")
    assert not hasattr(dock, "avac_domain_layer")
    dock.wave_extension_toggle.setChecked(True)
    assert [dock.workflow_tabs.tabText(index) for index in range(dock.workflow_tabs.count())] == ["AVAC Parameters", "AVAC Run", "WAVE Parameters", "WAVE Run", "Results"]
    assert not dock.wave_results_run_container.isHidden()
    assert dock.temporal_variable.findData("wave:depth") >= 0
    assert dock.temporal_variable.findData("wave:water_elevation") >= 0
    assert dock.temporal_variable.findData("wave:surface_displacement") >= 0
    assert dock.temporal_variable.findData("avac_lake:depth") >= 0
    assert dock.temporal_variable.findData("avac:snow_surface_elevation") >= 0
    assert dock.result_gauge_variable.findData("avac:depth") >= 0
    assert dock.result_gauge_variable.findData("avac:snow_surface_elevation") >= 0
    assert dock.result_gauge_variable.findData("wave:water_elevation") >= 0
    assert isinstance(dock.wave_lake_dem, QgsMapLayerComboBox)
    assert isinstance(dock.wave_lake_boundary, QgsMapLayerComboBox)
    assert dock.wave_lake_dem.allowEmptyLayer() and dock.wave_lake_dem.currentLayer() is None
    assert dock.wave_lake_boundary.allowEmptyLayer() and dock.wave_lake_boundary.currentLayer() is None
    assert isinstance(dock.wave_result_gauge_layer, QgsMapLayerComboBox)
    assert dock.wave_result_gauge_layer.allowEmptyLayer()
    assert dock.wave_prepare_progress.format() == "Not prepared"
    assert dock.prepare_progress.format() == "Not prepared"
    assert dock.wave_profile_line_layer is dock.profile_line_layer
    assert dock.wave_export_current_button.text() == "Export Current Map PNG"
    assert dock.wave_export_frames_button.text() == "Export Time Series Frames…"
    assert dock.export_legend.isChecked() and not dock.export_scale_bar.isChecked()
    assert dock.wave_export_legend.isChecked() and not dock.wave_export_scale_bar.isChecked()
    assert not hasattr(dock, "export_clip_avac")
    assert isinstance(dock.avac_frame_slider, QSlider)
    assert isinstance(dock.wave_frame_slider, QSlider)
    assert dock.avac_play_button.text() == "Play"
    assert dock.wave_play_button.text() == "Play"
    assert dock.help_button.toolTip() == "Open the AVAC4QGIS User Interface Guide"
    assert dock.wave_plot_volume_button.text() == "Plot Lake Volume History"
    assert not hasattr(dock, "wave_plot_outflow_button")
    assert dock.wave_execution_log.isReadOnly()
    assert dock.wave_execution_log.objectName() == "waveExecutionLog"
    assert dock.wave_execution_log.isHidden()
    assert dock.wave_log_toggle.text() == "Show Wave execution log"
    dock.wave_log_toggle.setChecked(True)
    assert not dock.wave_execution_log.isHidden()
    assert dock.wave_progress.format() == "No prepared Wave simulation"
    assert dock.wave_stop_button.text() == "Stop"
    assert not dock.wave_stop_button.isEnabled()
    assert dock.wave_domain_from_lake_button.text() == "Create from Lake Polygon"
    assert not hasattr(dock, "wave_domain_from_corners_button")
    assert not hasattr(dock, "wave_domain_corner_layer")
    assert dock.wave_preview_water_button.text() == "Preview Water Level"
    assert dock.wave_preview_domain_button.text() == "Preview Calculation Domain"
    # A Wave water-level preview reads only the lake envelope, rather than a
    # potentially huge terrain/bathymetry raster.
    small = QgsRasterLayer(str(Path(__file__).resolve().parents[2] / "avac-main" / "src" / "Topo" / "topography.asc"), "preview terrain")
    if small.isValid():
        clipped = raster_from_qgis_layer(small, extent=QgsRectangle(small.extent().xMinimum(), small.extent().yMinimum(), small.extent().center().x(), small.extent().center().y()))
        assert clipped.z.size < small.width() * small.height()
        dock.wave_lake_dem.setLayer(small)
    # Local large-case performance and GeoClaw terrain-coverage regression.
    # The source DEM has 288 million cells, while the selected Wave grid plus
    # its one-cell terrain halo remains a small window.
    large_case = Path("/Users/cmgotelli/Desktop/01/runs/run_20260813_184459/inputs/dem/Mauvoisin_fake_bathymetry_perpendicular.tif")
    if large_case.is_file():
        large = QgsRasterLayer(str(large_case), "large Wave terrain")
        started = time.monotonic()
        domain = {"xmin": 2592772.0, "xmax": 2593872.0, "ymin": 1088963.5, "ymax": 1094254.5}
        native = raster_from_qgis_layer(
            large, extent=QgsRectangle(domain["xmin"] - 5.5, domain["ymin"] - 5.5,
                                       domain["xmax"] + 5.5, domain["ymax"] + 5.5),
        )
        window = terrain_for_wave_domain(native, domain, 5.5)
        elapsed = time.monotonic() - started
        assert window.z.shape == (964, 202)
        assert window.metadata["xmin"] == domain["xmin"] - 5.5
        assert window.metadata["ymin"] == domain["ymin"] - 5.5
        assert np.isfinite(window.z[[0, -1], :]).any() and np.isfinite(window.z[:, [0, -1]]).any()
        assert elapsed < 5.0, f"solver-grid terrain window took {elapsed:.3f} s"
        print(f"Large Wave terrain window: {window.z.shape} in {elapsed:.3f} s")
    assert dock.wave_domain_buffer.value() == 20.0
    assert dock.wave_damping.value() == 0.3
    assert dock.wave_limiter.currentText() == "mc"
    assert dock.wave_load_map_button.text() == "Load Map"
    assert dock.wave_load_temporal_button.text() == "Load Time Series"
    assert dock.wave_check_button.text() == "Check Environment"
    assert dock.wave_validate_inputs_button.text() == "Validate Inputs"
    assert dock.prepare_wave_button.parentWidget() is dock.wave_run_scroll.widget()
    assert dock.avac_cpu_cores.minimum() == 1
    assert dock.avac_cpu_cores.maximum() == available_cpu_cores()
    assert dock.avac_cpu_cores.value() == available_cpu_cores()
    assert dock.wave_cpu_cores.minimum() == 1
    assert dock.wave_cpu_cores.maximum() == available_cpu_cores()
    assert dock.wave_cpu_cores.value() == available_cpu_cores()
    assert dock.load_plugin_configuration_button.text() == "Load Case"
    assert dock.save_plugin_configuration_button.text() == "Save Case"
    assert dock.load_wave_configuration_button.text() == "Load WAVE Configuration"
    assert dock.save_wave_configuration_button.text() == "Save WAVE Configuration"
    assert dock.rheology_visualize_button.text() == "Visualize Rheology Zones"
    assert dock.preview_initial_surface_button.text() == "Preview Initial Snow Surface"
    assert [dock.profile_source.itemData(index) for index in range(dock.profile_source.count())] == ["frame", "time_series", "maximum"]
    assert dock.profile_source.currentText() == "Selected frame"
    assert not hasattr(dock, "profile_plot_button")
    assert dock.wave_export_profile_series_button.text() == "Export Profile Time Series…"
    # WAVE's compiled force-dry reader requires numeric-first headers, unlike
    # the labelled ESRI-ASCII header required for AVAC topography files.
    with tempfile.TemporaryDirectory() as temporary:
        # Runtime regression: the dock's direct Frame Player must select a
        # multiband raster renderer input without QGIS Temporal Controller
        # filtering.  Undefined UI-only playback symbols are otherwise not
        # caught by a Python compilation test.
        from osgeo import gdal
        temporal_path = Path(temporary) / "temporal.tif"
        dataset = gdal.GetDriverByName("GTiff").Create(str(temporal_path), 2, 2, 2, gdal.GDT_Float32)
        dataset.SetGeoTransform((0., 1., 0., 2., 0., -1.))
        dataset.SetProjection(QgsCoordinateReferenceSystem("EPSG:2056").toWkt())
        dataset.GetRasterBand(1).WriteArray(np.ones((2, 2), dtype=np.float32))
        dataset.GetRasterBand(2).WriteArray(np.full((2, 2), 2., dtype=np.float32))
        dataset = None
        temporal_layer = QgsRasterLayer(str(temporal_path), "direct frame player")
        assert temporal_layer.isValid()
        dock._style_raster(temporal_layer, (-2., 2.), "m")
        renderer = temporal_layer.renderer()
        assert renderer.classificationMin() == -2. and renderer.classificationMax() == 2.
        legend_labels = [label for label, _color in renderer.legendSymbologyItems()]
        assert legend_labels and all(any(character.isdigit() for character in label) for label in legend_labels)
        temporal_layer.setCustomProperty("avac/temporal_variable", "depth")
        temporal_layer.setCustomProperty("avac/simulation_times_seconds", [0., 10.])
        temporal_layer.setCustomProperty("avac/temporal_origin_iso", "2026-01-01T00:00:00Z")
        QgsProject.instance().addMapLayer(temporal_layer)
        dock._register_frame_player("avac", temporal_layer, [0., 10.])
        dock._set_frame_player_frame("avac", 1)
        assert temporal_layer.renderer().inputBand() == 2
        assert not temporal_layer.temporalProperties().isActive()
        assert temporal_layer.customProperty("avac/frame_player_band") == 2

        workspace = Path(temporary) / "workspace"
        avac_run = workspace / "runs" / "completed"; output = avac_run / "AVAC" / "_output"
        output.mkdir(parents=True)
        (output / "fort.q0000").write_text("fixture\n", encoding="utf-8")
        (avac_run / ".avac_qgis_run.json").write_text(json.dumps({
            "format": 1, "status": "completed", "avac_directory": "AVAC",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }), encoding="utf-8")
        (avac_run / "AVAC" / "AVAC_configuration.yaml").write_text("computation:\n  t_max: 42\n  nb_simul: 21\n", encoding="utf-8")
        raster = AvacRaster(np.array([-.5, .5, 1.5, 2.5]), np.array([-.5, .5, 1.5, 2.5]), np.ones((4, 4)),
                            {"xmin": -1., "xmax": 3., "ymin": -1., "ymax": 3., "ncols": 4, "nrows": 4,
                             "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1)
        ring = [(np.array([[0., 0.], [2., 0.], [2., 2.], [0., 2.], [0., 0.]]), [])]
        wave_root = prepare_wave_scenario(
            workspace, avac_run, raster, ring, water_level=1.5, cell_size=1.,
            domain={"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.},
        )
        mask_header = (wave_root / "Topo" / "mask.asc").read_text(encoding="utf-8").splitlines()[:6]
        # The force-dry grid is solver-sized (the topography's interpolation
        # halo must not shift GeoClaw's one-based qinit lookup).
        assert int(mask_header[0].split()[0]) == 2 and int(mask_header[1].split()[0]) == 2
        assert float(mask_header[2].split()[0]) == -0.5 and float(mask_header[3].split()[0]) == 0.5
        wave_cfg = yaml.safe_load((wave_root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
        assert wave_cfg["computation"]["t_max"] == 42.0 and wave_cfg["computation"]["nb_simul"] == 21
        assert wave_cfg["computation"]["boundary"] == "extrap"
        assert wave_cfg["computation"]["mode"] == "internal_shoreline"
        assert (wave_root / "CL" / "shoreline_faces.txt").is_file()
        assert wave_cfg["lake"]["xmin"] == 0.0 and wave_cfg["lake"]["xmax"] == 2.0
        assert "postprocessing" not in wave_cfg
        assert json.loads((wave_root / ".avac_qgis_wave_run.json").read_text(encoding="utf-8"))["crs_authid"] == "EPSG:2056"
        # Regression: the former export-only AVAC clipping is now a derived
        # multi-band product.  It leaves the original raster unchanged and
        # zeros only AVAC cells intersecting the prepared WAVE lake footprint.
        lake_depth_source = Path(temporary) / "avac_depth_source.tif"
        dataset = gdal.GetDriverByName("GTiff").Create(str(lake_depth_source), 8, 8, 2, gdal.GDT_Float32)
        dataset.SetGeoTransform((-3., 1., 0., 5., 0., -1.))
        dataset.SetProjection(QgsCoordinateReferenceSystem("EPSG:2056").toWkt())
        dataset.GetRasterBand(1).WriteArray(np.full((8, 8), 3., dtype=np.float32))
        dataset.GetRasterBand(2).WriteArray(np.full((8, 8), 7., dtype=np.float32))
        dataset = None
        lake_depth_product = Path(temporary) / "avac_depth_lake_zero.tif"
        maximums, zeroed = _write_lake_zero_product(lake_depth_source, wave_root, lake_depth_product)
        source_dataset = gdal.Open(str(lake_depth_source)); product_dataset = gdal.Open(str(lake_depth_product))
        source_first = source_dataset.GetRasterBand(1).ReadAsArray()
        product_first = product_dataset.GetRasterBand(1).ReadAsArray()
        product_second = product_dataset.GetRasterBand(2).ReadAsArray()
        source_dataset = product_dataset = None
        assert zeroed > 0 and maximums == [3., 7.]
        assert np.all(source_first == 3.)
        assert np.count_nonzero(product_first == 0.) >= 4 and np.count_nonzero(product_second == 0.) >= 4
        assert product_first[0, 0] == 3. and product_first[-1, -1] == 3.
        dock.wave_run_root = wave_root
        # Dock-construction regression: load the derived layer through the
        # actual Results implementation, including temporal properties and
        # direct Frame Player registration.
        derived_destination = wave_root / "qgis_wave_results"
        derived_destination.mkdir(exist_ok=True)
        derived_path = derived_destination / "temporal_avac_depth_lake_zero.tif"
        gdal.Translate(str(derived_path), str(lake_depth_product))
        dock._avac_lake_depth_manifest = {
            "source_avac_run": str(avac_run), "temporal_origin_iso": "2026-01-01T00:00:00Z",
            "simulation_time_seconds": [0., 10.],
            "temporal": {"depth": {"path": derived_path.name, "range": [0., 7.], "unit": "m", "zeroed_avac_cells": zeroed}},
        }
        dock._load_avac_lake_depth_temporal(SimpleNamespace(run_root=avac_run, fgout_grid=1), dock._avac_lake_depth_manifest)
        derived_layer = dock._active_avac_lake_depth_layer()
        assert derived_layer is not None and derived_layer.bandCount() == 2
        assert derived_layer.customProperty("avac/display_label") == "WAVE Snow Depth Outside Lake"
        assert derived_layer.customProperty("avac/frame_player_band") == 1
        # The derived series has exactly the same two simulation times as
        # AVAC Depth and advances through the shared direct Frame Player even
        # when it is the only visible temporal layer.
        assert dock._layer_simulation_times(derived_layer) == [0., 10.]
        assert dock._frame_player_layers() == [derived_layer]
        dock.temporal_variable.setCurrentIndex(dock.temporal_variable.findData("avac_lake:depth"))
        assert dock._selected_frame_player_family() == "avac"
        dock.avac_play_button.click()
        assert dock._frame_player_timer.isActive()
        dock._advance_frame_player()
        assert derived_layer.renderer().inputBand() == 2
        assert derived_layer.customProperty("avac/frame_player_time_seconds") == 10.
        dock._pause_frame_player()

        # Regression: the WAVE time-series exporter must use the selected
        # scenario/variable and the same QGIS renderer loop as AVAC.  A stale
        # temporal layer from another scenario must not be selected merely
        # because it was added to the project first.
        class SmokeIface:
            def __init__(self):
                self.canvas = QgsMapCanvas()

            def mapCanvas(self):
                return self.canvas

        stale_wave_layer = QgsRasterLayer(str(temporal_path), "stale WAVE temporal export")
        stale_wave_layer.setCustomProperty("avac/temporal_variable", "wave_depth")
        stale_wave_layer.setCustomProperty("avac/wave_root", str(Path(temporary) / "other_wave_run"))
        QgsProject.instance().addMapLayer(stale_wave_layer)
        wave_temporal_layer = QgsRasterLayer(str(temporal_path), "WAVE temporal export")
        assert wave_temporal_layer.isValid()
        dock._style_raster(wave_temporal_layer, (0., 2.), "m")
        wave_temporal_layer.setCustomProperty("avac/temporal_variable", "wave_depth")
        wave_temporal_layer.setCustomProperty("avac/wave_root", str(wave_root))
        wave_temporal_layer.setCustomProperty("avac/temporal_origin_iso", "2026-01-01T00:00:00Z")
        wave_temporal_layer.setCustomProperty("avac/simulation_times_seconds", [0., 10.])
        QgsProject.instance().addMapLayer(wave_temporal_layer)
        dock._wave_results_manifest = {
            "simulation_time_seconds": [0., 10.],
            "temporal_origin_iso": "2026-01-01T00:00:00Z",
            "temporal": {"depth": {"path": "temporal_depth.tif", "range": [0., 2.], "unit": "m"}},
            "static": {},
        }
        dock._register_frame_player("wave", wave_temporal_layer, [0., 10.])
        dock.iface = SmokeIface()
        dock.iface.mapCanvas().setLayers([wave_temporal_layer, temporal_layer])
        dock.iface.mapCanvas().setExtent(wave_temporal_layer.extent())
        dock.wave_export_width.setValue(640)
        dock.wave_export_legend.setChecked(False)
        dock.wave_export_scale_bar.setChecked(False)
        dock.wave_export_every.setValue(1)
        export_directory = Path(temporary) / "wave_png_frames"
        export_directory.mkdir()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(export_directory)):
            dock.export_wave_temporal_frames()
        exported_wave_frames = sorted(export_directory.glob("wave_depth_frame_*.png"))
        assert len(exported_wave_frames) == 2 and all(path.stat().st_size > 0 for path in exported_wave_frames)
        assert (export_directory / "wave_frames.json").is_file()
        assert dock.wave_results_status.text().startswith("Exported 2 Wave PNG frames")
        assert dock._active_avac_temporal_layer() is temporal_layer

        dock._results_manifest = {
            "source_run": str(avac_run),
            "simulation_time_seconds": [0., 10.],
            "temporal_origin_iso": "2026-01-01T00:00:00Z",
            "temporal": {"fgout0001_depth": {"path": str(temporal_path), "range": [0., 2.], "unit": "m"}},
            "static": {},
        }
        dock.export_width.setValue(640)
        dock.export_legend.setChecked(False)
        dock.animation_every.setValue(1)
        avac_export_directory = Path(temporary) / "avac_png_frames"
        avac_export_directory.mkdir()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(avac_export_directory)):
            dock.export_temporal_frames()
        exported_avac_frames = sorted(avac_export_directory.glob("depth_frame_*.png"))
        assert len(exported_avac_frames) == 2 and all(path.stat().st_size > 0 for path in exported_avac_frames)
        avac_frames_payload = json.loads((avac_export_directory / "frames.json").read_text(encoding="utf-8"))
        assert "hide_avac_inside_lake_polygon" not in avac_frames_payload
        # One Gauge Histories workflow samples either solver and the selected
        # variable; AVAC is available even when the WAVE extension is off.
        gauge_layer = QgsVectorLayer("Point?crs=EPSG:2056", "result gauges", "memory")
        gauge_feature = QgsFeature(gauge_layer.fields())
        gauge_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(.5, .5)))
        gauge_layer.dataProvider().addFeature(gauge_feature)
        QgsProject.instance().addMapLayer(gauge_layer)
        dock.result_gauge_layer.setLayer(gauge_layer)
        dock.result_gauge_variable.setCurrentIndex(dock.result_gauge_variable.findData("avac:depth"))
        dock.sample_result_gauges()
        _name, gauge_times, gauge_values, family, variable, unit = dock._selected_result_gauge()
        assert family == "avac" and variable == "depth" and unit == "m"
        assert np.allclose(gauge_times, [0., 10.]) and np.allclose(gauge_values, [1., 2.])
        dock.iface = None
        profile_png = Path(temporary) / "wave_profile.png"
        write_wave_cross_section_png(profile_png, np.array([0., 1., 2.]), np.array([1., 1.2, 1.1]), np.array([1.4, 1.3, 1.6]), "Wave profile")
        assert profile_png.is_file() and profile_png.stat().st_size > 0

        # Regression: WAVE's own setup YAML and the complete plugin YAML must
        # restore persistent layer sources after QGIS project layers are gone.
        lake_path = Path(temporary) / "lake.geojson"
        lake_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": {
                "type": "Polygon", "coordinates": [[[0., 0.], [2., 0.], [2., 2.], [0., 2.], [0., 0.]]],
            }}],
        }), encoding="utf-8")
        lake_layer = QgsVectorLayer(str(lake_path), "persistent lake", "ogr")
        assert lake_layer.isValid()
        QgsProject.instance().addMapLayer(lake_layer)
        dock.workspace_root.setText(str(workspace))
        dock.dem_layer.setLayer(temporal_layer)
        dock.release_layer.setLayer(lake_layer)
        dock.wave_lake_dem.setLayer(temporal_layer)
        dock.wave_lake_boundary.setLayer(lake_layer)
        dock.wave_water_level.setValue(1.5)
        dock.wave_cell_size.setValue(1.)
        dock.wave_domain_xmin.setValue(0.)
        dock.wave_domain_xmax.setValue(2.)
        dock.wave_domain_ymin.setValue(0.)
        dock.wave_domain_ymax.setValue(2.)
        dock.wave_domain_buffer.setValue(7.)
        dock.wave_damping.setValue(.2)
        # The source-run selector normally lists completed workspace runs.
        # The small fixture intentionally has no AVAC solver raster output,
        # so insert its marked source explicitly to verify configuration
        # persistence without pretending it is a loadable AVAC result.
        dock.wave_avac_run_selector.addItem("fixture completed AVAC run", str(avac_run))
        source_index = dock.wave_avac_run_selector.findData(str(avac_run))
        assert source_index >= 0
        dock.wave_avac_run_selector.setCurrentIndex(source_index)

        wave_setup_path = Path(temporary) / "WAVE_configuration.yaml"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(wave_setup_path), "YAML (*.yaml)")):
            dock.save_wave_configuration()
        wave_payload = yaml.safe_load(wave_setup_path.read_text(encoding="utf-8"))
        assert wave_payload["format"] == dock.WAVE_SETUP_CONFIGURATION_FORMAT
        assert wave_payload["setup"]["model"]["damping"] == .2
        assert "outflow_edge" not in wave_payload["setup"]
        dock.wave_damping.setValue(.4)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(wave_setup_path), "YAML (*.yaml)")):
            dock.load_wave_configuration()
        assert dock.wave_damping.value() == .2

        full_setup_path = Path(temporary) / "AVAC4QGIS_configuration.yaml"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(full_setup_path), "YAML (*.yaml)")):
            dock.save_plugin_configuration()
        full_payload = yaml.safe_load(full_setup_path.read_text(encoding="utf-8"))
        assert full_payload["format"] == dock.PLUGIN_CONFIGURATION_FORMAT
        assert full_payload["wave"]["enabled"] is True
        assert full_payload["wave"]["setup"]["terrain"]["source"] == str(temporal_path)
        QgsProject.instance().clear()
        dock.wave_extension_toggle.setChecked(False)
        dock.workspace_root.clear()
        dock.wave_damping.setValue(.4)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(full_setup_path), "YAML (*.yaml)")):
            dock.load_plugin_configuration()
        assert dock.wave_extension_toggle.isChecked()
        assert dock.workspace_root.text() == str(workspace)
        assert dock.dem_layer.currentLayer() is not None and dock.dem_layer.currentLayer().source() == str(temporal_path)
        assert dock.release_layer.currentLayer() is not None and dock.release_layer.currentLayer().source() == str(lake_path)
        assert dock.wave_lake_dem.currentLayer() is not None and dock.wave_lake_dem.currentLayer().source() == str(temporal_path)
        assert dock.wave_lake_boundary.currentLayer() is not None and dock.wave_lake_boundary.currentLayer().source() == str(lake_path)
        assert dock.wave_damping.value() == .2
    depth, hu, hv, replaced = _finite_boundary_state(
        np.array([1., np.nan]), np.array([.5, 1.]), np.array([0., 2.]), epsilon=1e-6,
    )
    assert replaced == 1 and np.isfinite(depth).all() and np.isfinite(hu).all() and np.isfinite(hv).all()
    assert not dock.wave_run_button.isEnabled()
    # Results-layout regression: enabling WAVE adds Lake Volume after the
    # base toolbox is built.  Its page must receive the same allocated height
    # as every other Results page and remain inside the toolbox viewport.
    dock.resize(430, 800)
    dock.show()
    dock.workflow_tabs.setCurrentWidget(dock.results_scroll)
    lake_volume_index = dock.results_toolbox.indexOf(dock.wave_diagnostics_group)
    assert lake_volume_index >= 0 and dock.results_toolbox.itemText(lake_volume_index) == "Lake Volume"
    dock.results_toolbox.setCurrentIndex(lake_volume_index)
    QgsApplication.processEvents()
    lake_page = dock.wave_diagnostics_group
    assert lake_page.minimumHeight() >= lake_page.sizeHint().height()
    assert dock.results_toolbox.minimumHeight() >= lake_page.minimumHeight()
    assert lake_page.isVisible()
    assert lake_page.height() >= lake_page.minimumHeight()
    assert lake_page.geometry().bottom() < dock.results_toolbox.height()
    dock.wave_extension_toggle.setChecked(False)
    assert [dock.workflow_tabs.tabText(index) for index in range(dock.workflow_tabs.count())] == ["AVAC Parameters", "AVAC Run", "Results"]
    assert dock.wave_results_run_container.isHidden()
    assert dock.temporal_variable.findData("wave:depth") < 0
    assert dock.temporal_variable.findData("avac_lake:depth") < 0
    # Constrained dock regression: the fixed Working Directory/tab bar remain
    # outside each resizable tab scroll area, so no tab requires laptop-height
    # vertical real estate merely to construct its controls.
    dock.resize(360, 600)
    scrolls = (dock.inputs_scroll, dock.parameters_scroll, dock.run_scroll, dock.results_scroll)
    assert all(isinstance(scroll, QScrollArea) and scroll.widgetResizable() for scroll in scrolls)
    assert dock.workflow_tabs.currentWidget() is dock.inputs_scroll
    assert dock.inputs_scroll.widget().isAncestorOf(dock.dem_layer)
    assert dock.parameters_scroll.widget().isAncestorOf(dock.parameter_toolbox)
    assert dock.run_scroll.widget().isAncestorOf(dock.run_prepared_button)
    assert dock.results_scroll.widget().isAncestorOf(dock.profile_line_layer)
    assert dock.minimumHeight() < 600
    # Construction reaches every selector used by the Inputs and Profile UI;
    # this catches missing QGIS GUI/core imports that py_compile cannot see.
    assert isinstance(dock.dem_layer, QgsMapLayerComboBox)
    assert isinstance(dock.release_layer, QgsMapLayerComboBox)
    assert dock.profile_line_layer is not None
    assert dock.refresh_profile_layers_button.text() == "Refresh Layers"
    assert dock.run_prepared_button.parentWidget() is not dock.results_run_root.parentWidget()
    # Configuration restoration can refresh the Results-run list; button
    # enablement is therefore state-dependent here rather than a construction
    # invariant.
    assert not dock.advanced_toggle.isVisible()
    assert not dock.advanced_settings.isVisible()
    assert dock.results_run_selector is not None
    assert dock.summary_map is not None
    assert dock.summary_grid.itemData(0) == 1 and dock.summary_grid.count() == 1
    assert dock.parameter_controls["rheology.model"].findText("cohesive_Voellmy") >= 0
    assert dock.parameter_controls["rheology.C"] is not None
    assert dock.results_toolbox.count() == 5
    assert dock.wave_parameter_toolbox.count() == 4
    assert [dock.parameter_toolbox.itemText(index) for index in range(dock.parameter_toolbox.count())] == [
        "AVAC Inputs", "Release / initial conditions", "Rheology", "Simulation / numerical",
    ]
    assert dock._controlled_parameters()["output.delta_t"] == 1.0
    assert dock._controlled_parameters()["output.verbosity"] == 0
    assert dock.results_toolbox.widget(0).minimumHeight() >= 225
    assert dock.results_toolbox.widget(0).minimumHeight() >= dock.results_toolbox.widget(0).sizeHint().height()
    assert dock.results_toolbox.minimumHeight() > dock.results_toolbox.widget(0).minimumHeight()
    results_layout = dock.results_scroll.widget().layout()
    assert results_layout.indexOf(dock.results_progress) == results_layout.count() - 1
    assert results_layout.indexOf(dock.results_toolbox) < results_layout.indexOf(dock.results_progress)
    assert dock.wave_results_progress is dock.results_progress
    # The Results Run forms fit their toolbox viewports; scrolling, when the
    # whole dock is short, belongs to the surrounding Results-tab scroll area.
    dock.resize(430, 800); dock.show()
    dock.workflow_tabs.setCurrentWidget(dock.results_scroll); dock.results_toolbox.setCurrentIndex(0)
    QgsApplication.processEvents()
    assert all(scroll.verticalScrollBar().maximum() == 0 for scroll in dock.results_toolbox.findChildren(QScrollArea) if scroll.isVisible())
    assert dock.results_toolbox.itemText(4) == "Gauge Histories"
    assert dock.rheology_zones is not None
    # Regression: Lac_Lachat's valid 300-year configuration has two cohesive
    # altitude zones. Loading it must retain the blank fourth field on the
    # base zone so the normal parser can validate the case again.
    cfg300 = Path(__file__).resolve().parents[2] / "avac-main" / "src" / "AVAC" / "AVAC_configuration300.yaml"
    dock._set_controlled_parameters(controlled_values(load_complete_configuration(cfg300)))
    assert dock._controlled_parameters()["rheology.mu"] == [0.3, 0.225]
    assert dock._controlled_parameters()["rheology.z_breaks"] == [1680.0]
    # The rheology action creates an actual categorical QGIS raster from the
    # selected DEM.  The lower bound itself belongs to the higher zone,
    # exactly as the AVAC solver applies the altitude-zone configuration.
    with tempfile.TemporaryDirectory() as directory:
        from osgeo import gdal
        rheology_root = Path(directory)
        rheology_dem_path = rheology_root / "rheology_dem.tif"
        dataset = gdal.GetDriverByName("GTiff").Create(str(rheology_dem_path), 3, 2, 1, gdal.GDT_Float32)
        dataset.SetGeoTransform((0., 1., 0., 2., 0., -1.))
        dataset.SetProjection(QgsCoordinateReferenceSystem("EPSG:2056").toWkt())
        dataset.GetRasterBand(1).WriteArray(np.array([[1600., 1680., 1700.], [1600., 1700., 1600.]], dtype=np.float32))
        dataset = None
        rheology_dem = QgsRasterLayer(str(rheology_dem_path), "rheology DEM")
        assert rheology_dem.isValid()
        QgsProject.instance().addMapLayer(rheology_dem)
        dock.workspace_root.setText(str(rheology_root / "workspace"))
        dock.dem_layer.setLayer(rheology_dem)
        dock.show_rheology_visualization()
        zone_layer = next(
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsRasterLayer) and layer.customProperty("avac/rheology_zone_preview")
        )
        assert zone_layer.isValid() and zone_layer.customProperty("avac/rheology_zone_count") == 2
        labels = [label for label, _color in zone_layer.renderer().legendSymbologyItems()]
        assert any("Zone 1" in label and "z < 1680 m" in label for label in labels)
        assert any("Zone 2" in label and "z ≥ 1680 m" in label for label in labels)
        output = gdal.Open(str(rheology_root / "workspace" / "qgis_previews" / "avac_rheology_zones.tif"))
        assert np.array_equal(output.GetRasterBand(1).ReadAsArray(), np.array([[1, 2, 2], [1, 2, 1]], dtype=np.uint16))
        output = None
    assert dock.temporal_grid.itemData(0) == 1 and dock.temporal_grid.count() == 1
    assert dock.load_summary_button.text() == "Load Map"
    assert dock.load_temporal_button.text() == "Load Time Series"
    assert dock.export_frames_button.text().startswith("Export Time Series Frames")
    dock.avac_cpu_cores.setValue(1)
    dock.run_environment_check()
    assert dock.report is not None
    assert dock.report.environment["OMP_NUM_THREADS"] == "1"
    print("AVAC QGIS dock smoke test passed")
    dock.shutdown()
    dock.deleteLater()
    QgsApplication.quit()


def _run_smoke() -> None:
    """Ensure a failed assertion is visible to the command-line test runner."""
    print("Starting AVAC QGIS dock smoke test", flush=True)
    try:
        verify()
    except BaseException:  # noqa: BLE001 - a smoke failure must end QGIS cleanly
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    os._exit(0)


_run_smoke()
