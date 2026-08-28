"""Minimal AVAC dock: environment preflight and existing-case execution."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable

import numpy as np
import yaml

from qgis.PyQt.QtCore import QDateTime, QProcess, QProcessEnvironment, QSettings, QSize, QTimer, Qt, QUrl
from qgis.PyQt.QtGui import QBrush, QColor, QDesktopServices, QFont, QImage, QLinearGradient, QPainter
from qgis.PyQt.QtWidgets import (
    QAction, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QProgressBar, QProgressDialog, QScrollArea, QSlider, QSpinBox, QStyle, QTabWidget, QToolBox, QToolButton, QVBoxLayout, QWidget, QDockWidget, QGroupBox, QFrame,
)
from qgis.core import (
    Qgis, QgsApplication, QgsColorRampShader, QgsDateTimeRange, QgsInterval, QgsMapLayerProxyModel,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer, QgsRectangle,
    QgsRasterLayerTemporalProperties, QgsRasterShader, QgsUnitTypes, QgsWkbTypes, QgsPalettedRasterRenderer,
    QgsSingleBandPseudoColorRenderer, QgsMapRendererCustomPainterJob, QgsMapSettings, QgsFeature, QgsFillSymbol, QgsVectorLayer,
)
from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint, QgsTemporalControllerWidget

from ..core.environment import (
    EnvironmentReport, available_cpu_cores, check_environment, check_packaged_environment, default_avac_directory, default_clawpack_root,
    default_claw_python, check_runtime_environment,
)
from ..core.runtime_assets import default_template_path, ensure_bundled_runtime, ensure_bundled_wave_runtime
from ..core.runtime_execution import prepare_runtime_execution, runtime_solver
from ..core.wave_execution import prepare_wave_boundary_conditions, prepare_wave_runtime_execution, validate_wave_runtime_dependencies
from ..core.export import animation_frames, animation_provenance, frame_filename, locate_ffmpeg
from ..core.configuration import apply_controlled_values, controlled_values, load_complete_configuration, validate_controlled_values, validate_grid_contract
from ..core.runner import AvacRunner, output_summary
from ..core.preprocessing import (
    configuration_for_raster, initial_snow_surface_elevation, read_avac_topography,
    raster_from_qgis_layer, rings_from_qgis_layer,
)
from ..core.tasks import InitialDepthPreviewTask, PrepareAvacLakeDepthTask, PrepareAvacRunTask, PrepareAvacResultsTask, PrepareWaveResultsTask
from ..core.wave_results import WAVE_RESULT_DIRECTORY, discover_wave_results, load_wave_frame, read_wave_gauges
from ..core.lake_polygon import connected_lake_mask, seed_cell, write_lake_polygon
from ..core.avac_lake_depth import AVAC_LAKE_DEPTH_MANIFEST, wave_source_avac_run
from ..core.run_project import read_run_metadata, validate_prepared_run
from ..core.workspace import completed_runs, create_run_root, materialize_layer_sources, validate_workspace
from ..core.wave_project import (
    PreparedWaveLake, avac_computation_domain, prepare_wave_lake,
    prepare_wave_scenario, validate_wave_source_compatibility,
)
from ..core.profiles import ProfileDataset, bilinear_sample, extract_profile, write_profile_csv
from ..core.results import EPOCH_ISO, RESULT_DIRECTORY, discover_results
from ..core.rheology import altitude_zone_ids
from ..core.simulation_time import format_simulation_seconds, simulation_seconds_for_band
from ..core.time_utils import display_local_datetime
from .profile_plot import ProfilePlotDialog, TimeSeriesPlotDialog, WaveCrossSectionDialog, write_profile_png, write_wave_cross_section_png


def _is_stale_packaged_template_path(candidate: Path, built_in: Path) -> bool:
    """Identify known obsolete defaults written by earlier plugin versions.

    A normal missing external YAML must remain visible to the user.  The two
    cases repaired here were never normal user templates: an older installed
    plugin's resource copy, and the generated ISeeSnow driver template that a
    previous validation workflow temporarily wrote into QGIS settings.
    """
    previous_packaged_default = (
        candidate.name == built_in.name
        and candidate.parent.name == "resources"
        and candidate.parent.parent.name == "avac_qgis"
    )
    candidate_parts = {part.casefold() for part in candidate.parts}
    previous_iseesnow_validation_default = (
        candidate.name.casefold() == "avac_iseesnow_template.yaml"
        and "validation-iseesnow" in candidate_parts
        and "idealizedtopo" in candidate_parts
    )
    return previous_packaged_default or previous_iseesnow_validation_default


WAVE_SNOW_DEPTH_LABEL = "WAVE — Snow Depth Outside Lake"


class AvacDockWidget(QDockWidget):
    """Dock panel for preparing and launching plugin-owned AVAC runs only."""

    SETTINGS_AVAC_DIR = "avac_qgis/avac_directory"
    SETTINGS_CLAW_ROOT = "avac_qgis/claw_root"
    SETTINGS_CLAW_PYTHON = "avac_qgis/claw_python"
    SETTINGS_WORKSPACE = "avac_qgis/working_directory"
    SETTINGS_TEMPLATE = "avac_qgis/preprocess_template"
    SETTINGS_RESULTS_RUN_ROOT = "avac_qgis/results_run_root"
    SETTINGS_FFMPEG = "avac_qgis/ffmpeg_executable"
    WAVE_SETUP_CONFIGURATION_FORMAT = "AVAC4QGIS Wave setup configuration"
    PLUGIN_CONFIGURATION_FORMAT = "AVAC4QGIS plugin configuration"
    CONFIGURATION_VERSION = 1
    # These execution choices are standardized for every prepared AVAC run.
    # They are no longer case-by-case controls in the normal user interface.
    FIXED_RUN_PARAMETERS = {
        "computation.boundary": "extrap",
        "output.delta_t": 1.0,
        "output.verbosity": 0,
        "output.output_format": "binary32",
        "animation.variable": "depth",
    }

    def __init__(self, parent=None, iface=None) -> None:
        super().__init__("AVAC4QGIS", parent)
        self.setObjectName("avacQgisDock")
        self.runner = AvacRunner(self)
        self._maximum_cpu_cores = available_cpu_cores()
        self.wave_process = QProcess(self)
        self.iface = iface
        self.report: EnvironmentReport | None = None
        self.runtime_root: Path | None = None
        self.prepared_avac_dir: Path | None = None
        self._prepared_signature: tuple | None = None
        self._preparation_task: PrepareAvacRunTask | None = None
        self._results_task: PrepareAvacResultsTask | None = None
        self._results_manifest: dict | None = None
        self._avac_lake_depth_task: PrepareAvacLakeDepthTask | None = None
        self._avac_lake_depth_manifest: dict | None = None
        self._requested_temporal = False
        self._requested_results_value: str | None = None
        self._pending_results_action: Callable[[], None] | None = None
        self._last_profile: ProfileDataset | None = None
        self._profile_selection_layer = None
        self._profile_selection_callback = None
        self._shutting_down = False
        self._wave_extension_enabled = False
        self.wave_run_root: Path | None = None
        self._wave_results_manifest: dict | None = None
        self._wave_discovery = None
        self._wave_diagnostics: dict | None = None
        self._wave_gauge_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._sampled_wave_gauge_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._sampled_result_gauge_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._sampled_result_gauge_variable: tuple[str, str, str] | None = None
        self._last_wave_profile: ProfileDataset | None = None
        self._wave_solver_solution_error = False
        self._wave_stop_requested = False
        self._wave_expected_frames = 0
        self._wave_lake_preview: PreparedWaveLake | None = None
        self._wave_lake_preview_signature: tuple | None = None
        self._lake_polygon_map_tool: QgsMapToolEmitPoint | None = None
        self._lake_polygon_previous_map_tool = None
        self._wave_progress_timer = QTimer(self)
        self._wave_progress_timer.setInterval(500)
        self._wave_progress_timer.timeout.connect(self._update_wave_progress)
        self._wave_termination_timer = QTimer(self)
        self._wave_termination_timer.setSingleShot(True)
        self._wave_termination_timer.timeout.connect(self._escalate_wave_stop)
        # QGIS temporal-band rendering varies across platform builds.  The
        # plugin-owned player selects a raster band directly and repaints the
        # map canvas, so simulation playback remains reliable on QGIS 3.44.
        self._frame_player_timer = QTimer(self)
        self._frame_player_timer.timeout.connect(self._advance_frame_player)
        self._frame_player_family: str | None = None
        self._frame_player_index = 0
        self._frame_player_times: dict[str, list[float]] = {"avac": [], "wave": []}
        self.parameter_controls: dict[str, QWidget] = {}
        # The normal UI exposes duration and requested cadence.  Keep these
        # raw schema controls off-screen so loaded legacy YAMLs can still be
        # opened and saved without changing their established schedules.
        # Normal loaded configurations are expressed through the visible
        # interval control.  Direct developer/test changes to the two hidden
        # count widgets still switch back to raw-count mode via their signals.
        self._timing_mode = "interval"
        self._preview_task: InitialDepthPreviewTask | None = None
        self._preview_kind = "depth"
        self._animation_timer: QTimer | None = None
        self._animation_process = QProcess(self)
        self._animation_process.readyReadStandardOutput.connect(self._append_animation_process_output)
        self._animation_process.readyReadStandardError.connect(self._append_animation_process_output)
        self._animation_process.finished.connect(self._on_animation_encoded)
        self._animation_frames: list[tuple[int, float]] = []
        self._animation_index = 0
        self._animation_temp_dir: Path | None = None
        self._animation_output: Path | None = None
        self._animation_previous_range = None
        self._animation_metadata: dict | None = None
        self._frame_export_cancelled = False
        self._frame_export_active = False
        self._build_ui()
        self._connect_runner()
        self.wave_process.readyReadStandardOutput.connect(self._append_wave_process_log)
        self.wave_process.readyReadStandardError.connect(self._append_wave_process_log)
        self.wave_process.errorOccurred.connect(self._on_wave_process_error)
        self.wave_process.finished.connect(self._on_wave_process_finished)

    def _build_ui(self) -> None:
        settings = QSettings()
        root = QWidget(self)
        root.setMinimumSize(0, 0)
        self.setMinimumSize(0, 0)
        layout = QVBoxLayout(root)
        self.workspace_root = QLineEdit(settings.value(self.SETTINGS_WORKSPACE, ""))
        layout.addWidget(QLabel("AVAC Working Directory"))
        layout.addWidget(self._path_row(self.workspace_root, "Select or create an AVAC data workspace"))
        # Retain legacy fields for setting compatibility only; the packaged
        # workflow no longer exposes source-build backend controls.
        self.advanced_toggle = QToolButton()
        self.advanced_settings = QWidget()
        form = QFormLayout(self.advanced_settings)
        self.avac_dir = QLineEdit(settings.value(self.SETTINGS_AVAC_DIR, str(default_avac_directory())))
        default_root = default_clawpack_root()
        default_python = default_claw_python()
        self.claw_root = QLineEdit(settings.value(self.SETTINGS_CLAW_ROOT, str(default_root or "")))
        self.claw_python = QLineEdit(settings.value(self.SETTINGS_CLAW_PYTHON, str(default_python or "")))
        self.advanced_settings.setVisible(False)
        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setObjectName("avacWorkflowTabs")
        self.inputs_scroll, inputs_page, inputs_layout = self._scrollable_tab("avacParametersScroll")
        # Inputs and scientific parameters form one setup stage. Retain the
        # alias for compatibility with older smoke tests and internal code.
        self.parameters_scroll, parameters_page, parameters_layout = self.inputs_scroll, inputs_page, inputs_layout
        self.run_scroll, run_page, run_layout = self._scrollable_tab("avacRunScroll")
        self.results_scroll, results_page, results_layout = self._scrollable_tab("avacResultsScroll")
        self.workflow_tabs.addTab(self.inputs_scroll, "AVAC Parameters")
        self.workflow_tabs.addTab(self.run_scroll, "AVAC Run")
        self.wave_extension_toggle = QCheckBox("Enable Lake-Wave Extension")
        self.wave_extension_toggle.setToolTip("Adds the optional WAVE Parameters and WAVE Run stages, plus WAVE analysis in Results. Existing AVAC runs are read-only inputs.")
        self.help_button = QToolButton()
        self.help_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))
        self.help_button.setToolTip("Open the AVAC4QGIS User Interface Guide")
        self.help_button.setText("Help")
        self.help_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.help_button.setAutoRaise(False)
        self.load_plugin_configuration_button = QPushButton("Load Case")
        self.save_plugin_configuration_button = QPushButton("Save Case")
        self.load_plugin_configuration_button.setToolTip(
            "Load the complete AVAC4QGIS case setup, including WAVE setup when enabled."
        )
        self.save_plugin_configuration_button.setToolTip(
            "Save the complete AVAC4QGIS case setup, including selected persistent QGIS layer sources."
        )
        general_controls = QHBoxLayout()
        general_controls.addWidget(self.wave_extension_toggle); general_controls.addStretch(1)
        general_controls.addWidget(self.load_plugin_configuration_button)
        general_controls.addWidget(self.save_plugin_configuration_button)
        general_controls.addWidget(self.help_button)
        layout.addLayout(general_controls)
        layout.addWidget(self.workflow_tabs, 1)

        prepare_form = QFormLayout()
        self.dem_layer = QgsMapLayerComboBox()
        self.dem_layer.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
        self.refinement_dem_layer = QgsMapLayerComboBox()
        self.refinement_dem_layer.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
        self.refinement_dem_layer.setAllowEmptyLayer(True)
        # Keep the selector and preparation support available for a future
        # refinement-workflow return, but do not expose it in the normal UI.
        self.refinement_dem_layer.setVisible(False)
        self.release_layer = QgsMapLayerComboBox()
        self.release_layer.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        default_template = default_template_path()
        self.run_root = QLineEdit()
        self.run_root.setReadOnly(True)
        self.run_root.setPlaceholderText("Created automatically during Prepare")
        saved_template = Path(str(settings.value(self.SETTINGS_TEMPLATE, str(default_template)))).expanduser()
        # A QGIS profile can retain the resource path from a previous plugin
        # installation.  Repair only the known built-in template filename;
        # never discard a user-selected YAML merely because that file is no
        # longer available.
        if (
            default_template.is_file()
            and not saved_template.is_file()
            and _is_stale_packaged_template_path(saved_template, default_template)
        ):
            saved_template = default_template
            settings.setValue(self.SETTINGS_TEMPLATE, str(default_template))
        self.configuration_template = QLineEdit(str(saved_template))
        form.addRow("Configuration template override", self._file_row(self.configuration_template, "Load a complete AVAC configuration template"))
        self.run_button = QPushButton("Run Marked Case with Make (Advanced)")
        form.addRow("Source-build execution", self.run_button)
        prepare_form.addRow("DEM raster layer", self.dem_layer)
        prepare_form.addRow("Release polygon layer", self.release_layer)
        avac_inputs_page = QWidget()
        avac_inputs_page_layout = QVBoxLayout(avac_inputs_page)
        avac_inputs_page_layout.addWidget(QLabel("Select the QGIS layers used to prepare AVAC inputs."))
        avac_inputs_page_layout.addLayout(prepare_form)
        avac_inputs_page_layout.addStretch(1)
        self.parameter_toolbox = QToolBox()
        self.parameter_toolbox.addItem(avac_inputs_page, "AVAC Inputs")
        self.parameter_toolbox.addItem(self._parameter_release_page(), "Release / initial conditions")
        self.parameter_toolbox.addItem(self._parameter_rheology_page(), "Rheology")
        self.parameter_toolbox.addItem(self._parameter_simulation_page(), "Simulation / numerical")
        inputs_layout.addWidget(self.parameter_toolbox)
        parameter_actions = QHBoxLayout()
        self.load_configuration_button = QPushButton("Load Configuration")
        self.save_configuration_button = QPushButton("Save Configuration")
        parameter_actions.addWidget(self.load_configuration_button)
        parameter_actions.addWidget(self.save_configuration_button)
        inputs_layout.addLayout(parameter_actions)
        inputs_layout.addStretch(1)

        run_layout.addWidget(QLabel("Prepare and execute the current AVAC scenario."))
        self.prepared_summary = QLabel("Prepared Simulation: none. Check Environment, Validate Inputs, then Prepare.")
        self.prepared_summary.setWordWrap(True)
        run_layout.addWidget(self.prepared_summary)
        run_form = QFormLayout()
        run_form.addRow("Active run", self.run_root)
        self.avac_cpu_cores = self._cpu_core_control()
        run_form.addRow("CPU cores", self.avac_cpu_cores)
        run_layout.addLayout(run_form)
        prepare_controls = QHBoxLayout()
        self.check_button = QPushButton("Check Environment")
        self.validate_inputs_button = QPushButton("Validate Inputs")
        self.prepare_inputs_button = QPushButton("Prepare AVAC Run")
        self.prepare_progress = QProgressBar(); self.prepare_progress.setRange(0, 100); self.prepare_progress.setValue(0); self.prepare_progress.setFormat("Not prepared")
        prepare_controls.addWidget(self.check_button)
        prepare_controls.addWidget(self.validate_inputs_button)
        prepare_controls.addWidget(self.prepare_inputs_button)
        run_layout.addLayout(prepare_controls)
        run_layout.addWidget(self.prepare_progress)
        preview_controls = QHBoxLayout()
        self.preview_initial_depth_button = QPushButton("Preview Initial Depth")
        self.preview_initial_surface_button = QPushButton("Preview Initial Snow Surface")
        preview_controls.addWidget(self.preview_initial_depth_button)
        preview_controls.addWidget(self.preview_initial_surface_button)
        run_layout.addLayout(preview_controls)

        controls = QHBoxLayout()
        self.run_prepared_button = QPushButton("Run")
        self.run_prepared_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        controls.addWidget(self.run_prepared_button)
        controls.addWidget(self.stop_button)
        run_layout.addLayout(controls)

        self.status = QLabel("Validate inputs, prepare an isolated AVAC run, then run the marked directory.")
        self.status.setWordWrap(True)
        run_layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        run_layout.addWidget(self.progress)

        self.log_toggle = QToolButton()
        self.log_toggle.setText("Show execution log")
        self.log_toggle.setCheckable(True)
        run_layout.addWidget(self.log_toggle)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMinimumHeight(140)
        run_layout.addWidget(self.log)
        run_layout.addStretch(1)

        outer_results_layout = results_layout

        self.results_status = QLabel("Choose a completed workspace run to analyze.")
        self.results_status.setWordWrap(True)
        results_layout.addWidget(self.results_status)
        run_group = QGroupBox("Results Run")
        results_form = QFormLayout(run_group)
        self.results_run_selector = QComboBox()
        self.refresh_results_runs_button = QPushButton("Refresh Runs")
        selector_row = QWidget(); selector_layout = QHBoxLayout(selector_row); selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.addWidget(self.results_run_selector, 1); selector_layout.addWidget(self.refresh_results_runs_button)
        results_form.addRow("Completed workspace run", selector_row)
        self.results_run_root = QLineEdit(settings.value(self.SETTINGS_RESULTS_RUN_ROOT, ""))
        self.open_run_directory_button = QPushButton("Open Run Directory…")
        results_form.addRow("External completed run", self.open_run_directory_button)
        self.results_summary = QLabel("No run selected."); self.results_summary.setWordWrap(True)
        results_form.addRow(self.results_summary)
        self.results_run_form = results_form
        self.wave_results_run_container = QWidget()
        self.wave_results_run_container.setVisible(False)
        results_form.addRow(self.wave_results_run_container)
        self.results_toolbox = QToolBox()
        run_group.setTitle("")
        self.results_toolbox.addItem(run_group, "Results Run")

        summary_group = QGroupBox("Summary Maps")
        summary_form = QFormLayout(summary_group)
        self.summary_map = QComboBox()
        for label, key in (("Maximum Depth", "max_depth"), ("Maximum Velocity", "max_velocity"), ("Maximum Pressure", "max_pressure"),
                           ("Arrival Time", "arrival_time"), ("Time of Maximum Depth", "time_max_depth"), ("Time of Maximum Velocity", "time_max_velocity")):
            self.summary_map.addItem(label, key)
        self.summary_grid = QComboBox(); self.summary_grid.addItem("Full AVAC domain", 1)
        self.load_summary_button = QPushButton("Load Map")
        summary_form.addRow("Summary map", self.summary_map); summary_form.addRow(self.load_summary_button)
        self.summary_form = summary_form
        summary_group.setTitle("")
        self.results_toolbox.addItem(summary_group, "Summary Maps")

        temporal_group = QGroupBox("Time Series Maps")
        temporal_form = QFormLayout(temporal_group)
        self.temporal_variable = QComboBox()
        self.temporal_variable.addItem("AVAC — Depth", "avac:depth")
        self.temporal_variable.addItem("AVAC — Velocity", "avac:velocity")
        self.temporal_variable.addItem("AVAC — Pressure", "avac:pressure")
        self.temporal_variable.addItem("AVAC — Snow Surface Elevation", "avac:snow_surface_elevation")
        temporal_form.addRow("Variable", self.temporal_variable)
        self.temporal_grid = QComboBox(); self.temporal_grid.addItem("Full AVAC domain", 1)
        self.load_temporal_button = QPushButton("Load Time Series")
        temporal_form.addRow(self.load_temporal_button)
        temporal_help = QLabel("Loads the selected AVAC variable through time. Use the built-in Frame Player to play or seek the simulation directly on the map canvas.")
        temporal_help.setWordWrap(True); temporal_form.addRow(temporal_help)
        self.avac_frame_slider = QSlider(Qt.Horizontal); self.avac_frame_slider.setEnabled(False)
        self.avac_play_button = QPushButton("Play"); self.avac_play_button.setEnabled(False)
        self.avac_pause_button = QPushButton("Pause"); self.avac_pause_button.setEnabled(False)
        self.avac_restart_button = QPushButton("Restart"); self.avac_restart_button.setEnabled(False)
        self.avac_playback_fps = QSpinBox(); self.avac_playback_fps.setRange(1, 30); self.avac_playback_fps.setValue(5); self.avac_playback_fps.setSuffix(" fps"); self.avac_playback_fps.setEnabled(False)
        self.avac_frame_status = QLabel("Load a time series to enable direct playback.")
        avac_player_row = QWidget(); avac_player_layout = QHBoxLayout(avac_player_row); avac_player_layout.setContentsMargins(0, 0, 0, 0)
        avac_player_layout.addWidget(self.avac_frame_slider, 1); avac_player_layout.addWidget(self.avac_play_button); avac_player_layout.addWidget(self.avac_pause_button); avac_player_layout.addWidget(self.avac_restart_button); avac_player_layout.addWidget(self.avac_playback_fps)
        temporal_form.addRow("Frame Player", avac_player_row); temporal_form.addRow(self.avac_frame_status)

        self.export_extent = QComboBox()
        self.export_extent.addItem("Current map canvas", "canvas")
        self.export_extent.addItem("Selected result extent", "result")
        self.export_width = QSpinBox(); self.export_width.setRange(640, 8000); self.export_width.setValue(1600); self.export_width.setSuffix(" px")
        self.export_time = QCheckBox("Simulation time"); self.export_time.setChecked(True)
        self.export_legend = QCheckBox("Legend"); self.export_legend.setChecked(True)
        self.export_scale_bar = QCheckBox("Scale bar"); self.export_scale_bar.setChecked(False)
        self.ffmpeg_executable = QLineEdit(settings.value(self.SETTINGS_FFMPEG, ""))
        temporal_form.addRow("Include", self._export_check_row())
        temporal_form.addRow("Extent", self.export_extent)
        temporal_form.addRow("Image width", self.export_width)
        export_buttons = QHBoxLayout()
        self.export_png_button = QPushButton("Export Current Map PNG")
        self.animation_variable = QComboBox()
        for label, value in (("AVAC — Depth", "avac:depth"), ("AVAC — Velocity", "avac:velocity"), ("AVAC — Pressure", "avac:pressure"),
                             ("AVAC — Snow Surface Elevation", "avac:snow_surface_elevation")):
            self.animation_variable.addItem(label, value)
        self.animation_fps = QSpinBox(); self.animation_fps.setRange(1, 60); self.animation_fps.setValue(5); self.animation_fps.setSuffix(" fps")
        self.animation_every = QSpinBox(); self.animation_every.setRange(1, 100000); self.animation_every.setValue(1); self.animation_every.setSuffix(" frame(s)")
        # Retained only for developer-level compatibility with the internal
        # encoder; MP4 has no normal Results-tab control.
        self.export_animation_button = QPushButton("Export MP4…"); self.export_animation_button.setVisible(False)
        self.export_frames_button = QPushButton("Export Time Series Frames…")
        self.cancel_export_button = QPushButton("Cancel Export"); self.cancel_export_button.setEnabled(False)
        export_buttons.addWidget(self.export_png_button); export_buttons.addWidget(self.export_frames_button)
        export_buttons.addWidget(QLabel("Export every Nth frame:")); export_buttons.addWidget(self.animation_every)
        self.animation_every.setToolTip("1 exports every available temporal frame; 2 exports frames 1, 3, 5, …")
        export_buttons.addWidget(self.cancel_export_button)
        temporal_form.addRow(export_buttons)
        temporal_group.setTitle("")
        self.temporal_form = temporal_form
        self.results_toolbox.addItem(temporal_group, "Time Series Maps")

        profile_group = QGroupBox("Profile Analysis")
        profile_form = QFormLayout(profile_group)
        self.profile_line_layer = QComboBox()
        self.refresh_profile_layers_button = QPushButton("Refresh Layers")
        self.profile_feature = QComboBox()
        self.profile_source = QComboBox()
        self.profile_source.addItem("Selected frame", "frame")
        self.profile_source.addItem("Full time series (export)", "time_series")
        self.profile_source.addItem("Historical maximum through selected frame", "maximum")
        self.profile_variable = QComboBox()
        for label, value in (("AVAC — Depth", "avac:depth"), ("AVAC — Velocity", "avac:velocity"), ("AVAC — Pressure", "avac:pressure"),
                             ("AVAC — Snow Surface Elevation", "avac:snow_surface_elevation")):
            self.profile_variable.addItem(label, value)
        self.profile_sampling = QComboBox()
        self.profile_sampling.addItem("Automatic (raster cell)", "automatic")
        self.profile_sampling.addItem("User-defined", "spacing")
        self.profile_spacing = QDoubleSpinBox()
        self.profile_spacing.setDecimals(4)
        self.profile_spacing.setRange(0.0001, 1_000_000.0)
        self.profile_spacing.setValue(2.0)
        self.profile_spacing.setSuffix(" m")
        self.profile_spacing.setEnabled(False)
        profile_layer_row = QHBoxLayout(); profile_layer_row.addWidget(self.profile_line_layer, 1); profile_layer_row.addWidget(self.refresh_profile_layers_button)
        profile_form.addRow("Profile layer", profile_layer_row)
        profile_form.addRow("Selected feature", self.profile_feature)
        profile_form.addRow("Result type", self.profile_source)
        profile_form.addRow("Variable", self.profile_variable)
        profile_form.addRow("Sampling", self.profile_sampling)
        profile_form.addRow("Sample spacing", self.profile_spacing)
        profile_buttons = QHBoxLayout()
        self.extract_profile_button = QPushButton("Extract / Plot Profile")
        self.export_profile_button = QPushButton("Export CSV")
        self.export_profile_button.setEnabled(False)
        profile_buttons.addWidget(self.extract_profile_button)
        profile_buttons.addWidget(self.export_profile_button)
        profile_form.addRow(profile_buttons)
        self.profile_status = QLabel("Select exactly one line feature in the chosen QGIS layer.")
        self.profile_status.setWordWrap(True); profile_form.addRow(self.profile_status)
        self.wave_profile_series_container = QWidget()
        wave_profile_series_layout = QHBoxLayout(self.wave_profile_series_container)
        wave_profile_series_layout.setContentsMargins(0, 0, 0, 0)
        self.wave_profile_series_format = QComboBox(); self.wave_profile_series_format.addItem("CSV", "csv"); self.wave_profile_series_format.addItem("PNG frames", "png")
        self.wave_export_profile_series_button = QPushButton("Export Profile Time Series…")
        wave_profile_series_layout.addWidget(self.wave_profile_series_format)
        wave_profile_series_layout.addWidget(self.wave_export_profile_series_button)
        self.wave_profile_series_container.setVisible(False)
        profile_form.addRow("Time-series export", self.wave_profile_series_container)
        self.profile_form = profile_form
        profile_group.setTitle("")
        self.results_toolbox.addItem(profile_group, "Profile Analysis")

        gauge_group = QGroupBox("Gauge Histories")
        gauge_form = QFormLayout(gauge_group)
        self.result_gauge_layer = QgsMapLayerComboBox()
        self.result_gauge_layer.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        self.result_gauge_layer.setAllowEmptyLayer(True)
        self.result_gauge_layer.setLayer(None)
        self.result_gauge_variable = QComboBox()
        for label, value in (("AVAC — Depth", "avac:depth"), ("AVAC — Velocity", "avac:velocity"), ("AVAC — Pressure", "avac:pressure"),
                             ("AVAC — Snow Surface Elevation", "avac:snow_surface_elevation")):
            self.result_gauge_variable.addItem(label, value)
        self.sample_result_gauge_button = QPushButton("Read Gauges from Selected Point Layer")
        self.sampled_result_gauge_selector = QComboBox()
        self.plot_sampled_result_gauge_button = QPushButton("Plot Gauge History")
        self.export_sampled_result_gauge_button = QPushButton("Export Gauge CSV")
        gauge_form.addRow("Point layer", self.result_gauge_layer)
        gauge_form.addRow("Variable", self.result_gauge_variable)
        gauge_form.addRow(self.sample_result_gauge_button)
        gauge_form.addRow("Sampled point", self.sampled_result_gauge_selector)
        gauge_buttons = QHBoxLayout(); gauge_buttons.addWidget(self.plot_sampled_result_gauge_button); gauge_buttons.addWidget(self.export_sampled_result_gauge_button)
        gauge_form.addRow(gauge_buttons)
        gauge_group.setTitle("")
        self.results_toolbox.addItem(gauge_group, "Gauge Histories")
        self._reserve_toolbox_page_height(self.results_toolbox, run_group)
        # The toolbox owns the available vertical space in Results.  Its
        # selected page must never be compressed beneath the following
        # progress bar when optional WAVE pages are added.
        results_layout.addWidget(self.results_toolbox, 1)
        self.results_progress = QProgressBar()
        self.results_progress.setRange(0, 1)
        self.results_progress.setValue(0)
        self.results_progress.setFormat("No completed results")
        outer_results_layout.addWidget(self.results_progress)
        self.workflow_tabs.addTab(self.results_scroll, "Results")
        self.setWidget(root)

        self.check_button.clicked.connect(self.run_environment_check)
        self.run_button.clicked.connect(self.run_case)
        self.run_prepared_button.clicked.connect(self.run_prepared_case)
        self.stop_button.clicked.connect(self.stop_case)
        self.validate_inputs_button.clicked.connect(self.validate_preprocessing_inputs)
        self.prepare_inputs_button.clicked.connect(self.prepare_preprocessing_inputs)
        self.load_configuration_button.clicked.connect(self.load_configuration)
        self.save_configuration_button.clicked.connect(self.save_configuration)
        self.preview_initial_depth_button.clicked.connect(self.preview_initial_depth)
        self.preview_initial_surface_button.clicked.connect(self.preview_initial_snow_surface)
        self.refresh_results_runs_button.clicked.connect(self.refresh_results_runs)
        self.results_run_selector.currentIndexChanged.connect(self._select_results_run)
        self.open_run_directory_button.clicked.connect(self.open_run_directory)
        self.load_summary_button.clicked.connect(lambda: self.prepare_selected_results(False))
        self.load_temporal_button.clicked.connect(lambda: self.prepare_selected_results(True))
        self.avac_frame_slider.valueChanged.connect(lambda index: self._set_frame_player_frame(self._selected_frame_player_family(), index))
        self.avac_play_button.clicked.connect(lambda: self._start_frame_player(self._selected_frame_player_family()))
        self.avac_pause_button.clicked.connect(self._pause_frame_player)
        self.avac_restart_button.clicked.connect(lambda: self._restart_frame_player(self._selected_frame_player_family()))
        self.avac_playback_fps.valueChanged.connect(self._update_frame_player_rate)
        self.temporal_variable.currentTextChanged.connect(self._update_temporal_button_label)
        self.profile_line_layer.currentIndexChanged.connect(lambda _index: self._refresh_profile_features())
        self.refresh_profile_layers_button.clicked.connect(self.refresh_profile_layers)
        self.profile_sampling.currentIndexChanged.connect(self._update_profile_sampling_state)
        self.profile_source.currentIndexChanged.connect(self._update_profile_mode_controls)
        self.extract_profile_button.clicked.connect(self.extract_selected_profile)
        self.export_profile_button.clicked.connect(self.export_selected_profile_csv)
        self.wave_export_profile_series_button.clicked.connect(self.export_profile_time_series)
        self.sample_result_gauge_button.clicked.connect(self.sample_result_gauges)
        self.plot_sampled_result_gauge_button.clicked.connect(self.plot_sampled_result_gauge)
        self.export_sampled_result_gauge_button.clicked.connect(self.export_sampled_result_gauge_csv)
        self.export_png_button.clicked.connect(self.export_selected_current_map_png)
        self.export_frames_button.clicked.connect(self.export_selected_temporal_frames)
        self.cancel_export_button.clicked.connect(self.cancel_export)
        self.help_button.clicked.connect(self.open_help_pdf)
        self.load_plugin_configuration_button.clicked.connect(self.load_plugin_configuration)
        self.save_plugin_configuration_button.clicked.connect(self.save_plugin_configuration)
        self.wave_extension_toggle.toggled.connect(self._set_wave_extension_enabled)
        self.log_toggle.toggled.connect(self.log.setVisible)
        self.dem_layer.layerChanged.connect(self._invalidate_prepared)
        self.refinement_dem_layer.layerChanged.connect(self._invalidate_prepared)
        self.release_layer.layerChanged.connect(self._invalidate_prepared)
        self.workspace_root.textChanged.connect(self._invalidate_prepared)
        self.configuration_template.textChanged.connect(self._invalidate_prepared)
        self.workspace_root.textChanged.connect(self.refresh_results_runs)
        self.workflow_tabs.currentChanged.connect(lambda _index: self.refresh_profile_layers() if self.workflow_tabs.currentWidget() is self.results_scroll else None)
        QgsProject.instance().layersAdded.connect(self._on_project_layers_changed)
        QgsProject.instance().layersRemoved.connect(self._on_project_layers_changed)
        self._set_results_available(False)
        self._update_profile_mode_controls()
        self.refresh_profile_layers()
        self.refresh_results_runs()
        try:
            self._set_controlled_parameters(controlled_values(load_complete_configuration(self.configuration_template.text())))
        except ValueError:
            # A missing/default path is reported when the user validates or prepares.
            self._update_rheology_controls()

    @staticmethod
    def _scrollable_tab(object_name: str) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        """Build a tab whose content adapts to the available dock height."""
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        scroll.setWidget(page)
        return scroll, page, layout

    @staticmethod
    def _reserve_toolbox_page_height(toolbox: QToolBox, page: QWidget | None = None, minimum_page_height: int = 225) -> None:
        """Reserve sufficient space for every page of a Results toolbox.

        ``QToolBox`` only displays one page at a time, but its minimum height
        must account for whichever page is selected.  In particular, the
        optional Lake Volume page is inserted after the base Results pages
        have been constructed.  Sizing only the initial Results Run page can
        compress that later page and make its contents draw over neighboring
        Results controls.
        """
        pages = [toolbox.widget(index) for index in range(toolbox.count())]
        if page is not None and page not in pages:
            pages.append(page)
        if not pages:
            return
        heights: list[int] = []
        for item in pages:
            item_height = max(minimum_page_height, item.sizeHint().height())
            item.setMinimumHeight(item_height)
            heights.append(item_height)
        header_height = max(30, toolbox.fontMetrics().height() + 12)
        toolbox.setMinimumHeight(max(heights) + toolbox.count() * header_height + 16)

    @staticmethod
    def help_pdf_path() -> Path:
        """Locate the packaged guide, with a source-tree fallback for development."""
        packaged = Path(__file__).resolve().parents[1] / "documentation" / "AVAC_QGIS_UI_REFERENCE.pdf"
        if packaged.is_file():
            return packaged
        return Path(__file__).resolve().parents[2] / "docs" / "AVAC_QGIS_UI_REFERENCE.pdf"

    def open_help_pdf(self) -> None:
        path = self.help_pdf_path()
        if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.status.setText("The AVAC4QGIS User Interface Guide PDF is unavailable in this installation.")

    def _ensure_results_tab_last(self) -> None:
        """Keep the one shared Results stage at the end of the workflow."""
        index = self.workflow_tabs.indexOf(self.results_scroll)
        if index >= 0:
            self.workflow_tabs.removeTab(index)
        self.workflow_tabs.addTab(self.results_scroll, "Results")

    @staticmethod
    def _split_result_variable(value: object) -> tuple[str, str]:
        """Decode a namespaced Results variable while accepting legacy values."""
        text = str(value or "")
        if ":" in text:
            family, variable = text.split(":", 1)
            return family, variable
        if text.startswith("wave_"):
            return "wave", text[5:]
        return "avac", text

    def _selected_temporal_family_variable(self) -> tuple[str, str]:
        return self._split_result_variable(self.temporal_variable.currentData())

    def _selected_frame_player_family(self) -> str:
        """Map Results-variable namespaces onto the two actual frame players."""
        family, _variable = self._selected_temporal_family_variable()
        # The lake-zero snow product is derived from AVAC and deliberately
        # shares AVAC's exact frame clock.  It is not a third independent
        # player merely because it has a distinct Results namespace.
        return "wave" if family == "wave" else "avac"

    def _add_unique_combo_item(self, combo: QComboBox, label: str, value: str) -> None:
        if combo.findData(value) < 0:
            combo.addItem(label, value)

    @staticmethod
    def _remove_combo_family(combo: QComboBox, family: str) -> None:
        for index in reversed(range(combo.count())):
            if str(combo.itemData(index) or "").startswith(family + ":"):
                combo.removeItem(index)

    def _sync_wave_result_controls(self, enabled: bool) -> None:
        """Expose WAVE products in the shared Results controls only when enabled."""
        if enabled:
            self._add_unique_combo_item(
                self.temporal_variable,
                WAVE_SNOW_DEPTH_LABEL,
                "avac_lake:depth",
            )
            for combo in (self.animation_variable, self.profile_variable, self.result_gauge_variable):
                self._add_unique_combo_item(combo, WAVE_SNOW_DEPTH_LABEL, "avac_lake:depth")
            for combo in (self.temporal_variable, self.animation_variable, self.profile_variable, self.result_gauge_variable):
                self._add_unique_combo_item(combo, "WAVE — Water depth", "wave:depth")
                self._add_unique_combo_item(combo, "WAVE — Water elevation", "wave:water_elevation")
                self._add_unique_combo_item(combo, "WAVE — Surface displacement", "wave:surface_displacement")
            self._add_unique_combo_item(self.summary_map, "WAVE — Maximum surface rise", "wave:maximum_surface_rise")
            self._add_unique_combo_item(self.summary_map, "WAVE — Maximum surface drawdown", "wave:maximum_surface_drawdown")
        else:
            for combo in (self.temporal_variable, self.animation_variable, self.profile_variable, self.result_gauge_variable,
                          self.summary_map):
                self._remove_combo_family(combo, "wave")
            for combo in (self.temporal_variable, self.animation_variable, self.profile_variable, self.result_gauge_variable):
                self._remove_combo_family(combo, "avac_lake")
        self.wave_results_run_container.setVisible(enabled)
        self._update_profile_mode_controls()

    def _set_wave_extension_enabled(self, enabled: bool) -> None:
        """Show optional Wave workflow tabs without changing AVAC state."""
        if enabled == self._wave_extension_enabled:
            return
        self._wave_extension_enabled = enabled
        if enabled:
            self._build_wave_tabs()
            self.refresh_wave_avac_runs()
            self.refresh_wave_results_runs()
            self._sync_wave_result_controls(True)
            if hasattr(self, "wave_diagnostics_group") and self.results_toolbox.indexOf(self.wave_diagnostics_group) < 0:
                self.results_toolbox.addItem(self.wave_diagnostics_group, "Lake Volume")
            self._reserve_toolbox_page_height(self.results_toolbox, self.results_toolbox.widget(0))
            self._ensure_results_tab_last()
            self.status.setText("Lake-Wave Extension enabled. AVAC and WAVE runs and variables are available together in Results.")
        else:
            if hasattr(self, "wave_setup_scroll"):
                for tab in (self.wave_setup_scroll, self.wave_run_scroll):
                    index = self.workflow_tabs.indexOf(tab)
                    if index >= 0:
                        self.workflow_tabs.removeTab(index)
            self._sync_wave_result_controls(False)
            if hasattr(self, "wave_diagnostics_group"):
                index = self.results_toolbox.indexOf(self.wave_diagnostics_group)
                if index >= 0:
                    self.results_toolbox.removeItem(index)
            self._reserve_toolbox_page_height(self.results_toolbox, self.results_toolbox.widget(0))
            self._ensure_results_tab_last()
            self.status.setText("Lake-Wave Extension disabled. Existing AVAC workflow is unchanged.")

    def _build_wave_tabs(self) -> None:
        if hasattr(self, "wave_setup_scroll"):
            results_index = self.workflow_tabs.indexOf(self.results_scroll)
            if results_index >= 0:
                self.workflow_tabs.removeTab(results_index)
            for tab, label in ((self.wave_setup_scroll, "WAVE Parameters"), (self.wave_run_scroll, "WAVE Run")):
                if self.workflow_tabs.indexOf(tab) < 0:
                    self.workflow_tabs.addTab(tab, label)
            self._ensure_results_tab_last()
            return
        self.wave_setup_scroll, _setup_page, setup_layout = self._scrollable_tab("waveSetupScroll")
        self.wave_run_scroll, _run_page, run_layout = self._scrollable_tab("waveRunScroll")
        self.wave_parameter_toolbox = QToolBox()

        setup_layout.addWidget(QLabel("Prepare a lake-wave scenario from a completed AVAC run. The selected AVAC run is copied by reference only and is never modified."))
        source_group = QGroupBox("AVAC Source")
        source_form = QFormLayout(source_group)
        self.wave_avac_run_selector = QComboBox()
        self.wave_refresh_runs_button = QPushButton("Refresh Completed AVAC Runs")
        source_row = QWidget(); source_row_layout = QHBoxLayout(source_row); source_row_layout.setContentsMargins(0, 0, 0, 0)
        source_row_layout.addWidget(self.wave_avac_run_selector, 1); source_row_layout.addWidget(self.wave_refresh_runs_button)
        source_form.addRow("Completed AVAC run", source_row)
        source_group.setTitle(""); self.wave_parameter_toolbox.addItem(source_group, "AVAC Source")

        lake_group = QGroupBox("Terrain and Lake Inputs")
        lake_form = QFormLayout(lake_group)
        self.wave_lake_dem = QgsMapLayerComboBox(); self.wave_lake_dem.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer); self.wave_lake_dem.setAllowEmptyLayer(True); self.wave_lake_dem.setLayer(None)
        self.wave_lake_boundary = QgsMapLayerComboBox(); self.wave_lake_boundary.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer); self.wave_lake_boundary.setAllowEmptyLayer(True); self.wave_lake_boundary.setLayer(None)
        self.wave_water_level = QDoubleSpinBox(); self.wave_water_level.setDecimals(4); self.wave_water_level.setRange(-10000.0, 10000.0); self.wave_water_level.setSuffix(" m")
        self.wave_cell_size = QDoubleSpinBox(); self.wave_cell_size.setDecimals(6); self.wave_cell_size.setRange(.01, 10000.0); self.wave_cell_size.setValue(1.0); self.wave_cell_size.setSuffix(" m")
        self.wave_lake_dem.setToolTip("Terrain/bathymetry DEM covering the completed AVAC computation domain.")
        self.wave_lake_boundary.setToolTip("Polygon of the actual water body used to initialize the lake and its shoreline coupling.")
        lake_form.addRow("Terrain/bathymetry DEM", self.wave_lake_dem)
        lake_form.addRow("Lake water-body polygon", self.wave_lake_boundary)
        lake_form.addRow("Water level", self.wave_water_level)
        self.wave_preview_water_button = QPushButton("Preview Water Level")
        self.wave_preview_water_button.setToolTip("Show water depth inside the lake polygon for the selected water-surface elevation.")
        self.wave_create_lake_polygon_button = QPushButton("Create Lake Polygon from Map Point")
        self.wave_create_lake_polygon_button.setToolTip(
            "Click a point inside the lake basin; connected DEM cells at or below the water level become a persistent polygon. "
            "No completed AVAC run is required."
        )
        lake_form.addRow(self.wave_create_lake_polygon_button)
        lake_form.addRow(self.wave_preview_water_button)
        self.wave_cell_size.setToolTip("Use the DEM resolution or a larger whole-number multiple. A coarser grid reduces Wave runtime and memory use.")
        lake_form.addRow("Wave grid cell size", self.wave_cell_size)
        lake_group.setTitle(""); self.wave_parameter_toolbox.addItem(lake_group, "Terrain and Lake Inputs")

        model_group = QGroupBox("Wave Model Settings")
        model_form = QFormLayout(model_group)
        self.wave_damping = QDoubleSpinBox(); self.wave_damping.setRange(0.0, .4); self.wave_damping.setDecimals(4); self.wave_damping.setValue(.3)
        self.wave_land_strickler = QDoubleSpinBox(); self.wave_land_strickler.setRange(.01, 1000.0); self.wave_land_strickler.setValue(10.0)
        self.wave_water_strickler = QDoubleSpinBox(); self.wave_water_strickler.setRange(.01, 1000.0); self.wave_water_strickler.setValue(30.0)
        self.wave_friction_depth = QDoubleSpinBox(); self.wave_friction_depth.setRange(.0001, 10000.0); self.wave_friction_depth.setValue(20.0); self.wave_friction_depth.setSuffix(" m")
        self.wave_dry_limit = QDoubleSpinBox(); self.wave_dry_limit.setRange(.000001, 10.0); self.wave_dry_limit.setDecimals(6); self.wave_dry_limit.setValue(.0001); self.wave_dry_limit.setSuffix(" m")
        self.wave_tolerance = QDoubleSpinBox(); self.wave_tolerance.setRange(.000001, 100.0); self.wave_tolerance.setDecimals(6); self.wave_tolerance.setValue(.2)
        self.wave_cfl_target = QDoubleSpinBox(); self.wave_cfl_target.setRange(.01, 1.0); self.wave_cfl_target.setDecimals(3); self.wave_cfl_target.setValue(.5)
        self.wave_cfl_max = QDoubleSpinBox(); self.wave_cfl_max.setRange(.01, 1.0); self.wave_cfl_max.setDecimals(3); self.wave_cfl_max.setValue(1.0)
        self.wave_limiter = QComboBox(); self.wave_limiter.addItems(["none", "minmod", "superbee", "mc", "vanleer"]); self.wave_limiter.setCurrentText("vanleer")
        model_form.addRow("Snow-to-water damping", self.wave_damping)
        model_form.addRow("Land Strickler coefficient", self.wave_land_strickler)
        model_form.addRow("Water Strickler coefficient", self.wave_water_strickler)
        model_form.addRow("Friction depth limit", self.wave_friction_depth)
        model_form.addRow("Dry-depth limit", self.wave_dry_limit)
        model_form.addRow("Wave refinement tolerance", self.wave_tolerance)
        model_form.addRow("CFL target", self.wave_cfl_target)
        model_form.addRow("CFL maximum", self.wave_cfl_max)
        model_form.addRow("Limiter", self.wave_limiter)
        model_group.setTitle(""); self.wave_parameter_toolbox.addItem(model_group, "WAVE Model Settings")

        setup_layout.addWidget(self.wave_parameter_toolbox)
        wave_configuration_actions = QHBoxLayout()
        self.load_wave_configuration_button = QPushButton("Load WAVE Configuration")
        self.save_wave_configuration_button = QPushButton("Save WAVE Configuration")
        wave_configuration_actions.addWidget(self.load_wave_configuration_button)
        wave_configuration_actions.addWidget(self.save_wave_configuration_button)
        setup_layout.addLayout(wave_configuration_actions)
        self.prepare_wave_button = QPushButton("Prepare Wave Run")
        self.wave_setup_status = QLabel("Select completed AVAC results and the lake inputs, then prepare an isolated Wave scenario.")
        self.wave_setup_status.setWordWrap(True)
        self.wave_prepare_progress = QProgressBar(); self.wave_prepare_progress.setRange(0, 100); self.wave_prepare_progress.setValue(0); self.wave_prepare_progress.setFormat("Not prepared")
        setup_layout.addWidget(self.wave_setup_status); setup_layout.addStretch(1)

        run_layout.addWidget(QLabel("Prepare and execute the current WAVE scenario in a separate workspace directory."))
        self.wave_prepared_summary = QLabel("Prepared Simulation: none. Check Environment, Validate Inputs, then Prepare.")
        self.wave_prepared_summary.setWordWrap(True)
        run_layout.addWidget(self.wave_prepared_summary)
        wave_prepare_controls = QHBoxLayout()
        self.wave_check_button = QPushButton("Check Environment")
        self.wave_validate_inputs_button = QPushButton("Validate Inputs")
        wave_prepare_controls.addWidget(self.wave_check_button)
        wave_prepare_controls.addWidget(self.wave_validate_inputs_button)
        wave_prepare_controls.addWidget(self.prepare_wave_button)
        run_layout.addLayout(wave_prepare_controls)
        run_layout.addWidget(self.wave_prepare_progress)
        self.wave_run_button = QPushButton("Run"); self.wave_run_button.setEnabled(False)
        self.wave_stop_button = QPushButton("Stop")
        self.wave_stop_button.setEnabled(False)
        self.wave_cpu_cores = self._cpu_core_control()
        self.wave_run_status = QLabel("Prepare a Wave scenario first."); self.wave_run_status.setWordWrap(True)
        self.wave_progress = QProgressBar()
        self.wave_progress.setRange(0, 1); self.wave_progress.setValue(0); self.wave_progress.setFormat("No prepared Wave simulation")
        self.wave_execution_log = QPlainTextEdit()
        self.wave_execution_log.setObjectName("waveExecutionLog")
        self.wave_execution_log.setReadOnly(True)
        self.wave_execution_log.setMaximumBlockCount(2_000)
        self.wave_execution_log.setPlaceholderText("Wave preparation and solver messages will appear here.")
        self.wave_execution_log.setMinimumHeight(140)
        self.wave_execution_log.setVisible(False)
        self.wave_log_toggle = QToolButton()
        self.wave_log_toggle.setText("Show Wave execution log")
        self.wave_log_toggle.setCheckable(True)
        wave_controls = QHBoxLayout()
        wave_controls.addWidget(self.wave_run_button)
        wave_controls.addWidget(self.wave_stop_button)
        wave_execution_form = QFormLayout()
        wave_execution_form.addRow("CPU cores", self.wave_cpu_cores)
        run_layout.addLayout(wave_controls); run_layout.addLayout(wave_execution_form); run_layout.addWidget(self.wave_run_status); run_layout.addWidget(self.wave_progress)
        run_layout.addWidget(self.wave_log_toggle); run_layout.addWidget(self.wave_execution_log); run_layout.addStretch(1)

        # WAVE uses the same Results categories and controls as AVAC.  Only
        # its run selector and WAVE-specific diagnostics are added when the
        # extension is active.
        self.wave_results_status = self.results_status
        self.wave_results_progress = self.results_progress
        wave_run_form = QFormLayout(self.wave_results_run_container)
        wave_run_form.setContentsMargins(0, 0, 0, 0)
        self.wave_results_run_selector = QComboBox(); self.wave_refresh_results_button = QPushButton("Refresh Runs")
        wave_selector_row = QWidget(); wave_selector_layout = QHBoxLayout(wave_selector_row); wave_selector_layout.setContentsMargins(0, 0, 0, 0)
        wave_selector_layout.addWidget(self.wave_results_run_selector, 1); wave_selector_layout.addWidget(self.wave_refresh_results_button)
        self.wave_results_run_root = QLineEdit(); self.wave_open_run_directory_button = QPushButton("Open Wave Scenario Directory…")
        self.wave_results_summary = QLabel("No Wave scenario selected."); self.wave_results_summary.setWordWrap(True)
        wave_run_form.addRow("Completed WAVE scenario", wave_selector_row)
        wave_run_form.addRow("External WAVE scenario", self.wave_open_run_directory_button)
        wave_run_form.addRow(self.wave_results_summary)
        self.wave_results_map = self.summary_map
        self.wave_results_variable = self.temporal_variable
        self.wave_load_map_button = self.load_summary_button
        self.wave_load_temporal_button = self.load_temporal_button
        self.wave_frame_slider = self.avac_frame_slider
        self.wave_play_button = self.avac_play_button
        self.wave_pause_button = self.avac_pause_button
        self.wave_restart_button = self.avac_restart_button
        self.wave_playback_fps = self.avac_playback_fps
        self.wave_frame_status = self.avac_frame_status
        self.wave_export_extent = self.export_extent
        self.wave_export_width = self.export_width
        self.wave_export_time = self.export_time
        self.wave_export_legend = self.export_legend
        self.wave_export_scale_bar = self.export_scale_bar
        self.wave_export_every = self.animation_every
        self.wave_export_current_button = self.export_png_button
        self.wave_export_frames_button = self.export_frames_button
        self.wave_cancel_export_button = self.cancel_export_button
        self.wave_profile_line_layer = self.profile_line_layer
        self.wave_profile_source = self.profile_source
        self.wave_extract_profile_button = self.extract_profile_button
        self.wave_export_profile_button = self.export_profile_button
        self.wave_result_gauge_layer = self.result_gauge_layer
        self.wave_sample_gauge_button = self.sample_result_gauge_button
        self.wave_sampled_gauge_selector = self.sampled_result_gauge_selector
        self.wave_plot_sampled_gauge_button = self.plot_sampled_result_gauge_button
        self.wave_export_sampled_gauge_button = self.export_sampled_result_gauge_button

        self.wave_diagnostics_group = QGroupBox("Lake Volume")
        diagnostics_form = QFormLayout(self.wave_diagnostics_group)
        self.wave_diagnostics_summary = QLabel("Load Wave results to calculate lake-water volume history."); self.wave_diagnostics_summary.setWordWrap(True)
        self.wave_plot_volume_button = QPushButton("Plot Lake Volume History"); self.wave_export_volume_button = QPushButton("Export Lake Volume CSV")
        diagnostics_form.addRow(self.wave_diagnostics_summary); diagnostics_form.addRow(self.wave_plot_volume_button); diagnostics_form.addRow(self.wave_export_volume_button)
        self.wave_diagnostics_group.setTitle("")

        self.wave_refresh_runs_button.clicked.connect(self.refresh_wave_avac_runs)
        self.load_wave_configuration_button.clicked.connect(self.load_wave_configuration)
        self.save_wave_configuration_button.clicked.connect(self.save_wave_configuration)
        self.wave_refresh_results_button.clicked.connect(self.refresh_wave_results_runs)
        self.wave_results_run_selector.currentIndexChanged.connect(self._select_wave_results_run)
        self.wave_open_run_directory_button.clicked.connect(self.open_wave_results_directory)
        self.wave_check_button.clicked.connect(self.check_wave_environment)
        self.wave_validate_inputs_button.clicked.connect(self.validate_wave_inputs)
        self.prepare_wave_button.clicked.connect(self.prepare_wave_scenario)
        self.wave_run_button.clicked.connect(self.run_wave_simulation)
        self.wave_stop_button.clicked.connect(self.stop_wave_simulation)
        self.wave_log_toggle.toggled.connect(self.wave_execution_log.setVisible)
        self.wave_plot_volume_button.clicked.connect(self.plot_wave_volume)
        self.wave_export_volume_button.clicked.connect(lambda: self.export_wave_diagnostic_csv("volume_csv", "lake_volume_history.csv"))
        self.wave_create_lake_polygon_button.clicked.connect(self.start_wave_lake_polygon_capture)
        self.wave_preview_water_button.clicked.connect(self.preview_wave_water_level)
        self.wave_lake_dem.layerChanged.connect(self._set_wave_cell_size_from_dem)
        self.wave_lake_dem.layerChanged.connect(self._invalidate_wave_water_preview)
        self.wave_lake_boundary.layerChanged.connect(self._invalidate_wave_water_preview)
        self.wave_avac_run_selector.currentIndexChanged.connect(self._invalidate_wave_water_preview)
        self.workspace_root.textChanged.connect(self._invalidate_wave_water_preview)
        for control in (
            self.wave_water_level, self.wave_cell_size, self.wave_dry_limit,
        ):
            control.valueChanged.connect(self._invalidate_wave_water_preview)
        results_index = self.workflow_tabs.indexOf(self.results_scroll)
        if results_index >= 0:
            self.workflow_tabs.removeTab(results_index)
        for tab, label in ((self.wave_setup_scroll, "WAVE Parameters"), (self.wave_run_scroll, "WAVE Run")):
            self.workflow_tabs.addTab(tab, label)
        self._ensure_results_tab_last()

    def _set_wave_cell_size_from_dem(self, layer) -> None:
        """Make native DEM resolution the convenient default, not a limit."""
        if layer is None or not layer.isValid():
            return
        try:
            x_res, y_res = float(layer.rasterUnitsPerPixelX()), float(layer.rasterUnitsPerPixelY())
            if x_res > 0 and np.isclose(x_res, y_res, rtol=0.0, atol=max(x_res, y_res, 1.0) * 1e-8):
                self.wave_cell_size.setValue(x_res)
        except Exception:  # Layer metadata can be incomplete for some providers.
            pass

    def start_wave_lake_polygon_capture(self) -> None:
        """Arm one map click that seeds a water-level lake polygon."""
        terrain = self.wave_lake_dem.currentLayer() if hasattr(self, "wave_lake_dem") else None
        if terrain is None or not terrain.isValid() or not terrain.crs().isValid():
            self.wave_setup_status.setText("Choose a valid terrain/bathymetry DEM before creating the lake polygon.")
            return
        if self.iface is None or self.iface.mapCanvas() is None:
            self.wave_setup_status.setText("The QGIS map canvas is unavailable; the lake seed point cannot be captured.")
            return
        canvas = self.iface.mapCanvas()
        self._lake_polygon_previous_map_tool = canvas.mapTool()
        self._lake_polygon_map_tool = QgsMapToolEmitPoint(canvas)
        self._lake_polygon_map_tool.canvasClicked.connect(self._create_wave_lake_polygon_from_point)
        canvas.setMapTool(self._lake_polygon_map_tool)
        self.wave_setup_status.setText(
            f"Click inside the lake basin on the map. Connected DEM cells at or below "
            f"{self.wave_water_level.value():g} m will define the lake polygon."
        )

    def _finish_wave_lake_polygon_capture(self) -> None:
        """Restore the map tool that was active before lake-point capture."""
        if self.iface is None or self.iface.mapCanvas() is None or self._lake_polygon_map_tool is None:
            self._lake_polygon_map_tool = None
            self._lake_polygon_previous_map_tool = None
            return
        canvas = self.iface.mapCanvas()
        try:
            self._lake_polygon_map_tool.canvasClicked.disconnect(self._create_wave_lake_polygon_from_point)
        except (TypeError, RuntimeError):
            pass
        if self._lake_polygon_previous_map_tool is not None:
            canvas.setMapTool(self._lake_polygon_previous_map_tool)
        else:
            canvas.unsetMapTool(self._lake_polygon_map_tool)
        self._lake_polygon_map_tool = None
        self._lake_polygon_previous_map_tool = None

    def _create_wave_lake_polygon_from_point(self, point, mouse_button) -> None:
        """Create and select the connected water-level polygon at one click."""
        if mouse_button == Qt.MouseButton.RightButton:
            self._finish_wave_lake_polygon_capture()
            self.wave_setup_status.setText("Lake-polygon point selection cancelled.")
            return
        try:
            terrain = self.wave_lake_dem.currentLayer()
            if terrain is None or not terrain.isValid():
                raise ValueError("Terrain/bathymetry DEM is no longer available.")
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            selected = QgsPointXY(point)
            if canvas_crs != terrain.crs():
                selected = QgsCoordinateTransform(
                    canvas_crs, terrain.crs(), QgsProject.instance().transformContext()
                ).transform(selected)
            # Lake delineation is an input-building operation, not a result
            # operation.  It therefore uses only the selected terrain, water
            # level, and map point.  The expanding native-resolution window
            # avoids materializing a very large source DEM while still
            # proving that the connected contour closes inside that DEM.
            raster, mask = self._lake_raster_window_from_point(
                terrain, selected.x(), selected.y(),
            )
            destination_root = validate_workspace(self.workspace_root.text()) / "derived_inputs"
            destination_root.mkdir(exist_ok=True)
            level_name = f"{self.wave_water_level.value():.3f}".replace("-", "minus_").replace(".", "_")
            destination = destination_root / f"lake_at_{level_name}_m.gpkg"
            suffix = 1
            while destination.exists():
                suffix += 1
                destination = destination_root / f"lake_at_{level_name}_m_{suffix:02d}.gpkg"
            write_lake_polygon(
                destination, raster, mask, water_level=self.wave_water_level.value(),
                seed_x=selected.x(), seed_y=selected.y(),
            )
            layer = QgsVectorLayer(str(destination), f"Lake at {self.wave_water_level.value():g} m", "ogr")
            if not layer.isValid():
                raise ValueError(f"QGIS could not load the derived lake polygon: {destination}")
            layer.renderer().setSymbol(QgsFillSymbol.createSimple({
                "color": "0,120,255,45", "outline_color": "0,80,200,255", "outline_width": "0.7",
            }))
            layer.setCustomProperty("avac/derived_lake_polygon", True)
            layer.setCustomProperty("avac/water_level", float(self.wave_water_level.value()))
            QgsProject.instance().addMapLayer(layer)
            self.wave_lake_boundary.setLayer(layer)
            self._invalidate_wave_water_preview()
            self.wave_setup_status.setText(
                f"Created lake polygon from {int(np.count_nonzero(mask))} connected DEM cells: {destination}. "
                "Preview Water Level to inspect the exact WAVE-grid initial state."
            )
        except Exception as exc:  # noqa: BLE001 - map/provider/GDAL failures are user-facing
            self.wave_setup_status.setText(f"Lake polygon creation failed: {exc}")
        finally:
            self._finish_wave_lake_polygon_capture()

    def _lake_raster_window_from_point(self, terrain, x: float, y: float):
        """Read the smallest DEM window that fully encloses a seeded lake."""
        source_extent = terrain.extent()
        columns, rows = int(terrain.width()), int(terrain.height())
        if columns <= 0 or rows <= 0:
            raise ValueError("Terrain/bathymetry DEM has no raster cells.")
        cell_x = float(source_extent.width()) / columns
        cell_y = float(source_extent.height()) / rows
        tolerance = max(abs(cell_x), abs(cell_y), 1.0) * 1e-8
        if cell_x <= 0.0 or cell_y <= 0.0 or not np.isclose(
            cell_x, cell_y, rtol=0.0, atol=tolerance,
        ):
            raise ValueError("Terrain/bathymetry DEM must have positive square cells.")
        x, y = float(x), float(y)
        xmin, ymin = float(source_extent.xMinimum()), float(source_extent.yMinimum())
        xmax, ymax = float(source_extent.xMaximum()), float(source_extent.yMaximum())
        if not (xmin <= x < xmax and ymin <= y < ymax):
            raise ValueError("The selected point is outside the terrain DEM.")
        seed_column = min(columns - 1, max(0, int(np.floor((x - xmin) / cell_x))))
        seed_row = min(rows - 1, max(0, int(np.floor((y - ymin) / cell_y))))

        half_cells = 256
        while True:
            left = max(0, seed_column - half_cells)
            right = min(columns, seed_column + half_cells + 1)
            bottom = max(0, seed_row - half_cells)
            top = min(rows, seed_row + half_cells + 1)
            window = QgsRectangle(
                xmin + left * cell_x, ymin + bottom * cell_y,
                xmin + right * cell_x, ymin + top * cell_y,
            )
            raster = raster_from_qgis_layer(terrain, extent=window)
            seed = seed_cell(raster, x, y)
            mask = connected_lake_mask(
                raster.z, seed, self.wave_water_level.value(), require_closed=False,
            )
            touches = (
                bool(mask[:, 0].any()), bool(mask[:, -1].any()),
                bool(mask[0, :].any()), bool(mask[-1, :].any()),
            )
            source_edges = (left == 0, right == columns, bottom == 0, top == rows)
            if any(touch and source_edge for touch, source_edge in zip(touches, source_edges)):
                raise ValueError(
                    "The connected water body reaches the terrain DEM edge, so its contour is not closed. "
                    "Use a terrain DEM that fully encloses the water body, or lower the water level."
                )
            if not any(touches):
                return raster, mask
            if left == 0 and right == columns and bottom == 0 and top == rows:
                raise ValueError("The connected water body does not form a closed contour inside the terrain DEM.")
            half_cells *= 2

    def _validated_wave_domain(self) -> dict[str, float]:
        """Validate the completed AVAC domain against the selected WAVE grid."""
        terrain = self.wave_lake_dem.currentLayer() if hasattr(self, "wave_lake_dem") else None
        if terrain is None or not terrain.isValid():
            raise ValueError("Choose a valid terrain/bathymetry DEM.")
        domain = self._wave_domain()
        source_x = float(terrain.rasterUnitsPerPixelX())
        source_y = float(terrain.rasterUnitsPerPixelY())
        cell_size = float(self.wave_cell_size.value())
        tolerance = max(source_x, source_y, cell_size, 1.0) * 1e-8
        if source_x <= 0.0 or source_y <= 0.0 or not np.isclose(source_x, source_y, rtol=0.0, atol=tolerance):
            raise ValueError("Terrain/bathymetry DEM must have positive square cells.")
        ratio = cell_size / source_x
        if round(ratio) < 1 or not np.isclose(ratio, round(ratio), rtol=0.0, atol=1e-8):
            raise ValueError(
                f"Wave grid cell size ({cell_size:g} m) must equal the DEM resolution ({source_x:g} m) "
                "or be a whole-number multiple of it."
            )
        for axis in ("x", "y"):
            cells = (domain[f"{axis}max"] - domain[f"{axis}min"]) / cell_size
            if cells < 2 or not np.isclose(cells, round(cells), rtol=0.0, atol=1e-8):
                raise ValueError(
                    f"The completed AVAC {axis.upper()} span is not divisible into at least two "
                    f"{cell_size:g} m WAVE cells. Choose a compatible coarser cell size."
                )
        extent = terrain.extent()
        if (
            domain["xmin"] < extent.xMinimum() - tolerance or domain["xmax"] > extent.xMaximum() + tolerance
            or domain["ymin"] < extent.yMinimum() - tolerance or domain["ymax"] > extent.yMaximum() + tolerance
        ):
            raise ValueError("Terrain/bathymetry DEM must fully cover the completed AVAC computation domain.")
        return domain

    @staticmethod
    def _remove_wave_preview_layers(property_name: str) -> None:
        for layer_id, layer in list(QgsProject.instance().mapLayers().items()):
            if layer.customProperty(property_name):
                QgsProject.instance().removeMapLayer(layer_id)

    def _workspace_preview_raster(self, filename: str) -> Path:
        """Return a reusable preview raster path inside the Working Directory."""
        preview_dir = validate_workspace(self.workspace_root.text()) / "qgis_previews"
        preview_dir.mkdir(exist_ok=True)
        return preview_dir / filename

    def _wave_setup_terrain(self, terrain, domain: dict[str, float], cell_size: float):
        """Read only the native DEM window needed for GeoClaw terrain."""
        source_x = float(terrain.rasterUnitsPerPixelX())
        source_y = float(terrain.rasterUnitsPerPixelY())
        if source_x <= 0.0 or source_y <= 0.0 or not np.isclose(source_x, source_y, rtol=0.0, atol=max(source_x, source_y, 1.0) * 1e-8):
            raise ValueError("Terrain/bathymetry DEM must have positive square cells.")
        ratio = float(cell_size) / source_x
        if round(ratio) < 1 or not np.isclose(ratio, round(ratio), rtol=0.0, atol=1e-8):
            raise ValueError(
                f"Wave grid cell size ({cell_size:g} m) must equal the DEM resolution ({source_x:g} m) or be a whole-number multiple of it."
            )
        read_extent = QgsRectangle(domain["xmin"] - cell_size, domain["ymin"] - cell_size,
                                    domain["xmax"] + cell_size, domain["ymax"] + cell_size)
        return raster_from_qgis_layer(terrain, extent=read_extent)

    def _invalidate_wave_water_preview(self, *_args) -> None:
        """Discard solver-grid data whenever an input used to create it changes."""
        self._wave_lake_preview = None
        self._wave_lake_preview_signature = None

    def _wave_water_preview_input_signature(self) -> tuple:
        """Return an exact-enough identity for safely reusing a lake preview."""
        terrain = self.wave_lake_dem.currentLayer()
        boundary = self.wave_lake_boundary.currentLayer()
        if terrain is None or boundary is None or not terrain.isValid() or not boundary.isValid():
            raise ValueError("Choose both a terrain/bathymetry DEM and a lake water-body polygon.")
        geometry_digest = hashlib.sha256()
        for feature in boundary.getFeatures():
            geometry_digest.update(str(feature.id()).encode("ascii", errors="replace"))
            geometry_digest.update(bytes(feature.geometry().asWkb()))
        extent = terrain.extent()
        return (
            str(Path(self.workspace_root.text()).expanduser()),
            terrain.id(), terrain.source(), terrain.width(), terrain.height(), terrain.bandCount(),
            extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum(),
            boundary.id(), boundary.source(), boundary.featureCount(), geometry_digest.hexdigest(),
            *(self._wave_domain()[key] for key in ("xmin", "xmax", "ymin", "ymax")),
            self.wave_cell_size.value(), self.wave_water_level.value(), self.wave_dry_limit.value(),
        )

    def _render_wave_water_preview(self, prepared: PreparedWaveLake) -> tuple[int, float]:
        """Write and display the reusable solver-grid initial-water raster."""
        depth = prepared.initial_depth
        if not np.isfinite(depth).any():
            raise ValueError("The selected water level creates no wet cells inside the lake polygon.")
        from osgeo import gdal, osr
        raster = prepared.raster
        path = self._workspace_preview_raster("wave_water_level_preview.tif")
        dataset = gdal.GetDriverByName("GTiff").Create(
            str(path), raster.x.size, raster.y.size, 1, gdal.GDT_Float32,
            options=["COMPRESS=DEFLATE"],
        )
        if dataset is None:
            raise ValueError(f"Could not create the Wave water-level preview raster: {path}")
        reference = osr.SpatialReference(); reference.SetFromUserInput(raster.crs_authid)
        dataset.SetProjection(reference.ExportToWkt())
        dx = float(np.median(np.diff(raster.x))) if raster.x.size > 1 else prepared.cell_size
        dy = float(np.median(np.diff(raster.y))) if raster.y.size > 1 else prepared.cell_size
        dataset.SetGeoTransform((raster.x[0] - dx / 2, dx, 0, raster.y[-1] + dy / 2, 0, -dy))
        band = dataset.GetRasterBand(1); band.SetNoDataValue(-9999.0)
        band.WriteArray(np.flipud(np.where(np.isfinite(depth), depth, -9999.0).astype(np.float32)))
        dataset = None
        self._remove_wave_preview_layers("avac/wave_water_preview")
        maximum = float(np.nanmax(depth))
        layer = self._add_raster(path, "Wave Water-Level Preview", maximum, "m")
        layer.setCustomProperty("avac/wave_water_preview", True)
        return int(np.count_nonzero(np.isfinite(depth))), maximum

    def _compute_wave_water_preview(self) -> PreparedWaveLake:
        """Create, display and cache the exact lake state consumed by Prepare."""
        terrain = self.wave_lake_dem.currentLayer()
        boundary = self.wave_lake_boundary.currentLayer()
        domain = self._validated_wave_domain()
        signature = self._wave_water_preview_input_signature()
        lake_rings = rings_from_qgis_layer(boundary, terrain.crs())
        native_raster = self._wave_setup_terrain(terrain, domain, self.wave_cell_size.value())
        prepared = prepare_wave_lake(
            native_raster, lake_rings, water_level=self.wave_water_level.value(),
            cell_size=self.wave_cell_size.value(), domain=domain,
            dry_tolerance=self.wave_dry_limit.value(),
        )
        wet_cells, maximum = self._render_wave_water_preview(prepared)
        if self.wave_lake_dem.currentLayer() is not terrain:
            self.wave_lake_dem.setLayer(terrain)
        if self._wave_water_preview_input_signature() != signature:
            raise ValueError("Wave inputs changed while the water-level preview was being created; preview again.")
        # Cache only after every calculation and display step succeeds.
        self._wave_lake_preview = prepared
        self._wave_lake_preview_signature = signature
        self.wave_setup_status.setText(
            f"Water-level preview: {wet_cells} wet cells; maximum depth {maximum:g} m. "
            "This prepared lake state will be reused by Prepare Wave Run."
        )
        return prepared

    def preview_wave_water_level(self) -> None:
        """Display and cache the exact solver-grid water depth implied by setup."""
        try:
            self._compute_wave_water_preview()
        except Exception as exc:  # noqa: BLE001 - user-facing selection validation
            self._invalidate_wave_water_preview()
            self.wave_setup_status.setText(f"Water-level preview failed: {exc}")

    def _wave_domain(self) -> dict[str, float]:
        run = self.wave_avac_run_selector.currentData() if hasattr(self, "wave_avac_run_selector") else None
        if not run:
            raise ValueError("Choose a completed AVAC run.")
        return avac_computation_domain(run)

    def _wave_parameters(self) -> dict[str, float | str]:
        return {"damping": self.wave_damping.value(), "land_strickler": self.wave_land_strickler.value(),
                "water_strickler": self.wave_water_strickler.value(), "friction_depth_limit": self.wave_friction_depth.value(),
                "dry_limit": self.wave_dry_limit.value(), "wave_tolerance_flag": self.wave_tolerance.value(),
                "cfl_target": self.wave_cfl_target.value(), "cfl_max": self.wave_cfl_max.value(), "limiter": self.wave_limiter.currentText()}

    def _wave_gauges(self) -> list[dict[str, float | str]]:
        """Legacy solver-gauge hook; ordinary gauges are sampled post-run.

        Wave Setup no longer exposes a gauge layer because a user should be
        able to add visualization points after a successful computation.  Do
        not inspect the hidden combo box: QGIS may select an arbitrary vector
        layer when project layers change, which must never block preparation.
        """
        return []

    def refresh_wave_avac_runs(self) -> None:
        if not hasattr(self, "wave_avac_run_selector"):
            return
        previous = self.wave_avac_run_selector.currentData()
        self.wave_avac_run_selector.blockSignals(True)
        self.wave_avac_run_selector.clear()
        try:
            for run in completed_runs(self.workspace_root.text()):
                metadata = read_run_metadata(run)
                self.wave_avac_run_selector.addItem(
                    f"{run.name} — {display_local_datetime(metadata.get('updated_at', ''))}", str(run),
                )
        except Exception as exc:  # noqa: BLE001
            self.wave_setup_status.setText(f"Completed AVAC runs are unavailable: {exc}")
        index = self.wave_avac_run_selector.findData(previous)
        self.wave_avac_run_selector.setCurrentIndex(index if index >= 0 else 0)
        self.wave_avac_run_selector.blockSignals(False)

    def refresh_wave_results_runs(self) -> None:
        """List previously completed Wave scenarios in the current workspace."""
        if not hasattr(self, "wave_results_run_selector"):
            return
        previous = self.wave_results_run_root.text().strip()
        self.wave_results_run_selector.blockSignals(True); self.wave_results_run_selector.clear()
        try:
            root = validate_workspace(self.workspace_root.text()) / "wave_runs"
            runs = sorted((item for item in root.iterdir() if item.is_dir()
                           and (item / ".avac_qgis_wave_run.json").is_file()
                           and any((item / "Wave" / "_output").glob("fgout0001.t*"))), reverse=True) if root.is_dir() else []
            for run in runs:
                marker = json.loads((run / ".avac_qgis_wave_run.json").read_text(encoding="utf-8"))
                stamp = display_local_datetime(marker.get("updated_at", marker.get("created_at", "")))
                self.wave_results_run_selector.addItem(f"{run.name} — {stamp}", str(run))
            if runs:
                index = next((i for i in range(self.wave_results_run_selector.count())
                              if self.wave_results_run_selector.itemData(i) == previous), 0)
                self.wave_results_run_selector.setCurrentIndex(index)
                self._select_wave_results_run(index)
            else:
                self.wave_results_summary.setText("No completed Wave scenarios in the current AVAC Working Directory.")
        except Exception as exc:  # noqa: BLE001
            self.wave_results_summary.setText(f"Wave scenarios unavailable: {exc}")
        finally:
            self.wave_results_run_selector.blockSignals(False)

    def _select_wave_results_run(self, index: int) -> None:
        path = self.wave_results_run_selector.itemData(index)
        if not path:
            return
        self.wave_run_root = Path(str(path))
        self.wave_results_run_root.setText(str(path)); self._wave_results_manifest = None; self._wave_diagnostics = None; self._wave_discovery = None
        self._avac_lake_depth_manifest = None
        self.wave_results_summary.setText(f"Scenario: {self.wave_run_root.name}\nStatus: Wave output available")
        self.summary_map.setEnabled(True); self.load_summary_button.setEnabled(True); self.load_temporal_button.setEnabled(True)
        self.wave_results_status.setText("Wave scenario selected. Load a Summary Map or Time Series Map.")

    def open_wave_results_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open completed AVAC4QGIS Wave scenario", self.wave_results_run_root.text())
        if not selected:
            return
        root = Path(selected)
        if not (root / ".avac_qgis_wave_run.json").is_file():
            self.wave_results_status.setText("Selected directory is not an AVAC4QGIS Wave scenario.")
            return
        self.wave_run_root = root; self.wave_results_run_root.setText(str(root)); self._wave_results_manifest = None; self._wave_diagnostics = None; self._wave_discovery = None
        self._avac_lake_depth_manifest = None
        self.wave_results_summary.setText(f"External scenario: {root.name}\nStatus: selected")
        self.summary_map.setEnabled(True); self.load_summary_button.setEnabled(True); self.load_temporal_button.setEnabled(True)
        self.wave_results_status.setText("External Wave scenario selected. Load a Summary Map or Time Series Map.")

    def check_wave_environment(self) -> None:
        """Check the packaged WAVE runtime and writable workspace."""
        try:
            workspace = validate_workspace(self.workspace_root.text())
            self.wave_runtime_root = ensure_bundled_wave_runtime()
            solver = runtime_solver(self.wave_runtime_root)
            if not solver.is_file():
                raise ValueError(f"Bundled WAVE solver is missing: {solver}")
            validate_wave_runtime_dependencies(self.wave_runtime_root)
            self.wave_run_status.setText("Environment ready. Validate inputs, then Prepare Wave Run.")
            self.wave_progress.setRange(0, 1); self.wave_progress.setValue(0); self.wave_progress.setFormat("Ready")
            self._append_wave_log(
                f"WAVE environment ready.\nWorkspace: {workspace}\nRuntime: {self.wave_runtime_root}\n"
                f"Solver: {solver}\nPython coupling: bundled (no SciPy installation required)\n"
                f"OMP_NUM_THREADS: {self.wave_cpu_cores.value()}"
            )
        except Exception as exc:  # noqa: BLE001 - complete user-facing preflight
            self.wave_run_status.setText(f"Environment check blocked: {exc}")
            self.wave_progress.setRange(0, 1); self.wave_progress.setValue(0); self.wave_progress.setFormat("Blocked")
            self._append_wave_log(f"WAVE environment check failed: {type(exc).__name__}: {exc}")

    def validate_wave_inputs(self) -> None:
        """Validate WAVE selections without creating or modifying a scenario."""
        try:
            validate_workspace(self.workspace_root.text())
            avac_run = self.wave_avac_run_selector.currentData()
            terrain = self.wave_lake_dem.currentLayer()
            lake = self.wave_lake_boundary.currentLayer()
            if not avac_run:
                raise ValueError("Choose a completed AVAC run.")
            if terrain is None or not terrain.isValid() or not terrain.crs().isValid():
                raise ValueError("Choose a valid terrain/bathymetry DEM with a defined CRS.")
            if lake is None or not lake.isValid() or lake.geometryType() != QgsWkbTypes.PolygonGeometry:
                raise ValueError("Choose a valid lake water-body polygon layer.")
            domain = self._validated_wave_domain()
            validate_wave_source_compatibility(avac_run, terrain.crs().authid(), domain)
            rings = rings_from_qgis_layer(lake, terrain.crs())
            if not rings:
                raise ValueError("The lake water-body polygon contains no usable geometry.")
            signature = self._wave_water_preview_input_signature()
            preview_ready = self._wave_lake_preview is not None and self._wave_lake_preview_signature == signature
            suffix = " The current water-level preview is ready and will be reused." if preview_ready else " Preview Water Level will be calculated once during preparation and then reused."
            self.wave_run_status.setText("WAVE inputs valid." + suffix)
            self._append_wave_log(
                f"WAVE inputs valid. AVAC source: {avac_run}; terrain: {terrain.name()}; "
                f"lake polygons: {len(rings)}; cell size: {self.wave_cell_size.value():g} m."
            )
        except Exception as exc:  # noqa: BLE001 - complete user-facing validation
            self.wave_run_status.setText(f"WAVE input validation failed: {exc}")
            self._append_wave_log(f"WAVE input validation failed: {type(exc).__name__}: {exc}")

    def prepare_wave_scenario(self) -> None:
        """Create a self-contained Wave case without modifying AVAC output."""
        avac_run = self.wave_avac_run_selector.currentData() if hasattr(self, "wave_avac_run_selector") else None
        if not avac_run:
            self.wave_setup_status.setText("Choose a completed AVAC run before preparing Wave inputs.")
            return
        if self.wave_lake_dem.currentLayer() is None or self.wave_lake_boundary.currentLayer() is None:
            self.wave_setup_status.setText("Choose both a lake/bathymetry DEM and a lake boundary polygon.")
            return
        self.wave_prepare_progress.setValue(5); self.wave_prepare_progress.setFormat("Preparing Wave run: %p%")
        QgsApplication.processEvents()
        try:
            domain = self._validated_wave_domain()
            wave_cell = self.wave_cell_size.value()
            terrain_layer = self.wave_lake_dem.currentLayer()
            validate_wave_source_compatibility(avac_run, terrain_layer.crs().authid(), domain)
            signature = self._wave_water_preview_input_signature()
            reuse_preview = (
                self._wave_lake_preview is not None
                and self._wave_lake_preview_signature == signature
            )
            if reuse_preview:
                prepared_lake = self._wave_lake_preview
                self.wave_setup_status.setText("Reusing the validated water-level preview for Wave preparation.")
            else:
                self.wave_setup_status.setText(
                    "Creating the required water-level preview. Its solver-grid lake state will be reused for Wave preparation."
                )
                QgsApplication.processEvents()
                prepared_lake = self._compute_wave_water_preview()
            self.wave_prepare_progress.setValue(25); QgsApplication.processEvents()
            wave_root = prepare_wave_scenario(
                self.workspace_root.text(), avac_run, prepared_lake.raster, (),
                water_level=self.wave_water_level.value(), cell_size=wave_cell,
                domain=domain, parameters=self._wave_parameters(), gauges=self._wave_gauges(),
                prepared_lake=prepared_lake,
            )
            self.wave_prepare_progress.setValue(55); QgsApplication.processEvents()
        except Exception as exc:  # noqa: BLE001 - user-facing preparation validation
            self.wave_setup_status.setText(f"Wave preparation failed: {exc}")
            self.wave_prepare_progress.setValue(0); self.wave_prepare_progress.setFormat("Preparation failed")
            self._append_wave_log(f"Scenario preparation failed: {type(exc).__name__}: {exc}")
            self.wave_run_button.setEnabled(False)
            return
        self.wave_run_root = wave_root
        self.wave_results_run_root.setText(str(wave_root))
        self.wave_prepared_summary.setText(f"Prepared Simulation\nScenario: {wave_root.name}; AVAC source: {Path(str(avac_run)).name}")
        try:
            self.wave_runtime_root = ensure_bundled_wave_runtime()
            self.wave_prepare_progress.setValue(70); QgsApplication.processEvents()
        except Exception as exc:  # noqa: BLE001
            self.wave_setup_status.setText(f"Wave scenario prepared: {wave_root}\nThe AVAC source was read-only.\nWave runtime unavailable: {exc}")
            self.wave_prepare_progress.setValue(0); self.wave_prepare_progress.setFormat("Preparation failed")
            self._append_wave_log(f"Wave runtime installation failed: {type(exc).__name__}: {exc}")
            self.wave_run_button.setEnabled(False)
            return
        try:
            boundary = prepare_wave_boundary_conditions(self.wave_runtime_root, wave_root, avac_run)
            self.wave_prepare_progress.setValue(100); self.wave_prepare_progress.setFormat("Prepared")
        except Exception as exc:  # noqa: BLE001
            self.wave_setup_status.setText(f"Wave preparation failed while creating the AVAC shoreline inflow: {exc}")
            self.wave_prepare_progress.setValue(0); self.wave_prepare_progress.setFormat("Preparation failed")
            self._append_wave_log(f"Shoreline-inflow preparation failed: {type(exc).__name__}: {exc}")
            self.wave_run_button.setEnabled(False)
            return
        wave_configuration = yaml.safe_load(
            (wave_root / "impulse_configuration.yaml").read_text(encoding="utf-8")
        )
        wave_timing = wave_configuration["computation"]
        self._append_wave_log(
            f"Scenario prepared: {wave_root}\nWave runtime: {self.wave_runtime_root}\n"
            f"Wave duration/output intervals inherited from AVAC: "
            f"{float(wave_timing['t_max']):g} s / {int(wave_timing['nb_simul'])}.\n"
            f"Wet shoreline faces: {boundary.shoreline_faces}; active source cells: {boundary.active_source_cells}; "
            f"active AVAC shoreline samples: {boundary.active_samples}; estimated injected water volume: "
            f"{boundary.injected_water_volume_m3:.3f} m³; injected water momentum (X, Y): "
            f"({boundary.injected_water_momentum_x_kg_m_s:.3f}, "
            f"{boundary.injected_water_momentum_y_kg_m_s:.3f}) kg·m/s; samples outside AVAC coverage zeroed: "
            f"{boundary.outside_avac_coverage_zeroed}."
        )
        if boundary.active_samples == 0:
            self.wave_setup_status.setText("No Wave inflow detected: the completed AVAC simulation has no inward-moving snow crossing the initial wet lake shoreline.")
            self.wave_run_status.setText("Wave Run is unavailable because the completed AVAC simulation does not reach the wet lake shoreline.")
            self.wave_progress.setRange(0, 1); self.wave_progress.setValue(0); self.wave_progress.setFormat("Lake not reached")
            self.wave_run_button.setEnabled(False)
            return
        self.wave_setup_status.setText(f"Wave scenario prepared: {wave_root}\nThe AVAC source was read-only.")
        self.wave_run_status.setText("Ready. Verified internal shoreline inflow was prepared from the read-only AVAC output; Run will launch the separate Wave solver.")
        self.wave_progress.setRange(0, 1); self.wave_progress.setValue(0); self.wave_progress.setFormat("Ready")
        self.wave_run_button.setEnabled(True)

    def run_wave_simulation(self) -> None:
        if self.wave_process.state() != QProcess.ProcessState.NotRunning:
            return
        if self.wave_run_root is None or not self.wave_avac_run_selector.currentData():
            self.wave_run_status.setText("Prepare a Wave scenario first.")
            return
        try:
            runtime = getattr(self, "wave_runtime_root", None) or ensure_bundled_wave_runtime()
            output = prepare_wave_runtime_execution(runtime, self.wave_run_root, self.wave_avac_run_selector.currentData())
        except Exception as exc:  # noqa: BLE001
            self.wave_run_status.setText(f"Wave execution preparation failed: {exc}")
            self._append_wave_log(f"Execution preparation failed: {type(exc).__name__}: {exc}")
            return
        self._wave_stop_requested = False
        self.wave_run_button.setEnabled(False)
        self.wave_stop_button.setEnabled(True)
        self.wave_run_status.setText("Wave simulation running in its isolated Wave directory…")
        configuration = yaml.safe_load((self.wave_run_root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
        self._wave_expected_frames = int(configuration["computation"]["nb_simul"]) + 1
        self.wave_progress.setRange(0, self._wave_expected_frames)
        self.wave_progress.setValue(0)
        self.wave_progress.setFormat(f"Wave frames 0 / {self._wave_expected_frames}")
        environment = QProcessEnvironment.systemEnvironment()
        # Wave is a separate QProcess and must receive the same isolated DLL
        # search path as AVAC.  Otherwise a QGIS/OS copy of libgfortran or
        # libgomp can be loaded ahead of the bundled matching libraries,
        # which can corrupt the solver heap on Windows.
        for key in ("CLAW", "CLAW_PYTHON", "FC", "PYTHONPATH"):
            environment.remove(key)
        runtime_path = Path(runtime).expanduser().resolve()
        existing_path = environment.value("PATH")
        runtime_library_path = os.pathsep.join((str(runtime_path / "bin"), str(runtime_path / "lib")))
        environment.insert("PATH", runtime_library_path + (os.pathsep + existing_path if existing_path else ""))
        environment.insert("OMP_NUM_THREADS", str(self.wave_cpu_cores.value()))
        self.wave_process.setProcessEnvironment(environment)
        self.wave_process.setWorkingDirectory(str(output))
        self.wave_process.setProgram(str(runtime_solver(runtime)))
        self.wave_process.setArguments([])
        self._wave_solver_solution_error = False
        self.wave_cpu_cores.setEnabled(False)
        self._append_wave_log(f"Launching WAVE solver with OMP_NUM_THREADS={self.wave_cpu_cores.value()}.")
        self.wave_process.start()
        self._wave_progress_timer.start()

    def stop_wave_simulation(self) -> None:
        """Request a clean stop, then force-stop only this Wave QProcess if needed."""
        if self.wave_process.state() == QProcess.ProcessState.NotRunning:
            return
        self._wave_stop_requested = True
        self.wave_stop_button.setEnabled(False)
        self.wave_run_status.setText("Stopping Wave simulation…")
        self._append_wave_log("Stop requested for the direct Wave solver process.")
        self.wave_process.terminate()
        self._wave_termination_timer.start(3000)

    def prepare_wave_results(self, requested_temporal: bool | None = None) -> None:
        if self.wave_run_root is None:
            self.wave_results_status.setText("Prepare and complete a Wave scenario before loading results.")
            self._cancel_pending_results_action()
            return
        try:
            runtime = ensure_bundled_wave_runtime()
            if requested_temporal is None:
                requested_temporal = self.sender() is self.wave_load_temporal_button
            _family, selected_variable = self._split_result_variable(self._requested_result_value(bool(requested_temporal)))
            variable = selected_variable if requested_temporal else "surface_displacement"
            task = PrepareWaveResultsTask(self.wave_run_root, runtime, variable)
            self._wave_results_task = task
            self._wave_requested_temporal = requested_temporal
            task.taskCompleted.connect(self._on_wave_results_completed)
            task.taskTerminated.connect(self._on_wave_results_terminated)
            self.wave_load_map_button.setEnabled(False); self.wave_load_temporal_button.setEnabled(False)
            self.wave_results_progress.setRange(0, 0); self.wave_results_progress.setFormat("Preparing Wave results")
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:  # noqa: BLE001
            self.wave_results_status.setText(f"Wave results cannot be loaded: {exc}")
            self._cancel_pending_results_action()

    def _on_wave_results_completed(self) -> None:
        task = getattr(self, "_wave_results_task", None)
        self.wave_load_map_button.setEnabled(True); self.wave_load_temporal_button.setEnabled(True)
        if task is None or task.discovery is None or task.manifest is None:
            self._on_wave_results_terminated(); return
        root, manifest = task.discovery.root / WAVE_RESULT_DIRECTORY, task.manifest
        self._wave_results_manifest, self._wave_diagnostics, self._wave_discovery = manifest, task.diagnostics, task.discovery
        self._set_results_available(True)
        # Ordinary gauges are selected after a run and sampled from the
        # result rasters.  Keep raw solver-gauge reading as backend support
        # only; there is no second, competing Results category.
        self._wave_gauge_data = read_wave_gauges(task.discovery)
        self.wave_diagnostics_summary.setText("Lake-water volume history is available.")
        self.wave_results_progress.setRange(0, 1); self.wave_results_progress.setValue(1); self.wave_results_progress.setFormat("Wave results ready")
        if self._wave_requested_temporal:
            _family, variable = self._split_result_variable(self._requested_result_value(True)); product = manifest["temporal"].get(variable)
            if product is None:
                raise ValueError("Requested Wave time series was not materialized.")
            previous = QgsProject.instance().timeSettings().temporalRange()
            layer = self._add_raster(
                root / product["path"],
                f"WAVE {self.temporal_variable.currentText().split('—')[-1].strip()} (Temporal) — {task.discovery.root.name}",
                product["range"], product["unit"],
                transparent_zero=variable == "surface_displacement",
            )
            properties = layer.temporalProperties(); properties.setIsActive(True); properties.setMode(QgsRasterLayerTemporalProperties.FixedRangePerBand); properties.setIntervalHandlingMethod(Qgis.TemporalIntervalMatchMethod.MatchUsingWholeRange)
            times = [float(value) for value in manifest["simulation_time_seconds"]]
            ranges = self._temporal_band_ranges(self._temporal_origin(manifest), times)
            properties.setFixedRangePerBand(ranges); layer.setCustomProperty("avac/temporal_variable", "wave_" + variable)
            layer.setCustomProperty("avac/wave_root", str(task.discovery.root))
            layer.setCustomProperty("avac/temporal_origin_iso", manifest.get("temporal_origin_iso", EPOCH_ISO))
            layer.setCustomProperty("avac/simulation_times_seconds", times)
            self._register_frame_player("wave", layer, times)
            self._show_temporal_layer(layer)
            self._append_wave_log(f"WAVE Frame Player ready: {len(times)} frames; direct raster-band display is active.")
        else:
            _family, key = self._split_result_variable(self._requested_result_value(False)); product = manifest["static"][key]
            self._add_raster(root / product["path"], f"WAVE {self.summary_map.currentText().split('—')[-1].strip()} — {task.discovery.root.name}", product["range"], product["unit"])
        self.wave_results_status.setText(f"Wave results loaded from {root}.")
        self._finish_pending_results_action()

    def _on_wave_results_terminated(self) -> None:
        task = getattr(self, "_wave_results_task", None)
        self.wave_load_map_button.setEnabled(True); self.wave_load_temporal_button.setEnabled(True)
        self.wave_results_progress.setRange(0, 1); self.wave_results_progress.setValue(0); self.wave_results_progress.setFormat("Wave result preparation failed")
        detail = task.error if task and task.error else "cancelled"
        self.wave_results_status.setText(f"Wave result preparation failed: {detail}")
        self._append_wave_log(f"Wave result preparation failed: {detail}")
        self._cancel_pending_results_action()
        if self.wave_run_root is not None:
            self._append_wave_log(f"Detailed traceback: {self.wave_run_root / WAVE_RESULT_DIRECTORY / 'result_loading_error.log'}")

    def _active_wave_temporal_layer(self, variable: str | None = None):
        """Return the loaded WAVE series for the selected scenario and variable."""
        expected = f"wave_{variable}" if variable else None
        root = str(self.wave_run_root.resolve()) if self.wave_run_root is not None else ""
        candidates = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsRasterLayer):
                continue
            layer_variable = str(layer.customProperty("avac/temporal_variable", ""))
            if not layer_variable.startswith("wave_") or (expected and layer_variable != expected):
                continue
            layer_root = str(layer.customProperty("avac/wave_root", ""))
            if root and layer_root and str(Path(layer_root).resolve()) != root:
                continue
            candidates.append(layer)
        return candidates[0] if candidates else None

    def _wave_profile_geometry(self, result_crs: QgsCoordinateReferenceSystem) -> tuple[np.ndarray, str]:
        return self._profile_geometry_in_result_crs(result_crs)

    def plot_wave_profile(self) -> None:
        try:
            family, variable, dataset, points, band, time = self._build_profile_dataset()
            if family != "wave":
                raise ValueError("The selected profile variable is not a WAVE result.")
            self._last_wave_profile = dataset
            if self._profile_mode() != "maximum":
                distance, ground, surface = self._wave_cross_section(points, band)
                title = f"WAVE {variable.replace('_', ' ').title()} Profile — {dataset.profile_name} at {format_simulation_seconds(time)}"
            else:
                discovery = self._wave_discovery
                if discovery is None:
                    discovery = discover_wave_results(self.wave_run_root, ensure_bundled_wave_runtime())
                    self._wave_discovery = discovery
                _t, fx, fy, initial_depth, bed, _hu, _hv = load_wave_frame(discovery, discovery.frames[0].frame_id)
                terrain = extract_profile(points, fx, fy, bed, "surface_displacement", "Wave bed")
                baseline = extract_profile(points, fx, fy, bed + initial_depth, "surface_displacement", "Initial water surface")
                if variable == "depth":
                    surface = terrain.values + dataset.values
                elif variable == "water_elevation":
                    surface = dataset.values
                else:
                    surface = baseline.values + dataset.values
                distance, ground = terrain.distance_m, terrain.values
                title = (
                    f"WAVE Historical Maximum {variable.replace('_', ' ').title()} — "
                    f"{dataset.profile_name} through {format_simulation_seconds(time)}"
                )
            dialog = WaveCrossSectionDialog(distance, ground, surface, title, self)
            dialog.exec()
        except Exception as exc: self.wave_results_status.setText(f"Wave profile failed: {exc}")

    def _wave_cross_section(self, points: np.ndarray, band: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Sample bed and free surface for a notebook-style Wave cross-section."""
        discovery = self._wave_discovery
        if discovery is None:
            if self.wave_run_root is None: raise ValueError("No Wave scenario is selected.")
            discovery = discover_wave_results(self.wave_run_root, ensure_bundled_wave_runtime())
            self._wave_discovery = discovery
        if band < 1 or band > len(discovery.frames): raise ValueError("Requested Wave profile frame is unavailable.")
        _time, x, y, depth, bed, _hu, _hv = load_wave_frame(discovery, discovery.frames[band - 1].frame_id)
        ground_data = extract_profile(points, x, y, bed, "surface_displacement", "Wave bed")
        surface_data = extract_profile(points, x, y, bed + depth, "surface_displacement", "Wave water surface")
        return ground_data.distance_m, ground_data.values, surface_data.values

    def _avac_profile_cross_section(
        self,
        family: str,
        variable: str,
        dataset: ProfileDataset,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Return terrain and snow surface for elevation-compatible AVAC profiles.

        Depth and snow-surface elevation have the same vertical datum as the
        prepared AVAC terrain, so they can use the notebook-style terrain
        cross section. Velocity and pressure retain their own-unit line plot;
        drawing either against terrain elevation would be physically false.
        """
        if variable not in {"depth", "snow_surface_elevation"}:
            return None
        if family == "avac":
            if not self._results_manifest:
                raise ValueError("AVAC results are not available.")
            avac_root = Path(str(self._results_manifest["source_run"]))
        elif family == "avac_lake":
            if self.wave_run_root is None:
                raise ValueError("The linked AVAC run is unavailable.")
            avac_root = wave_source_avac_run(self.wave_run_root)
        else:
            return None
        topography = avac_root / "Topo" / "topography.asc"
        if not topography.is_file():
            raise ValueError(f"Prepared AVAC terrain is unavailable: {topography}")
        terrain = read_avac_topography(topography)
        ground = bilinear_sample(terrain.x, terrain.y, terrain.z, dataset.x, dataset.y)
        values = np.asarray(dataset.values, dtype=float)
        if variable == "depth":
            surface = np.where(np.isfinite(ground) & np.isfinite(values), ground + np.maximum(values, 0.0), np.nan)
        else:
            surface = values
        return np.asarray(dataset.distance_m, dtype=float), ground, surface

    def export_wave_profile_csv(self) -> None:
        self.export_selected_profile_csv()

    def export_wave_profile_time_series_csv(self) -> None:
        self.export_profile_time_series()

    def _selected_wave_gauge(self) -> tuple[str, np.ndarray, np.ndarray]:
        name = str(self.wave_gauge_selector.currentData() or "")
        if name not in self._wave_gauge_data: raise ValueError("No recorded Wave gauge history is available. Configure gauges before preparing and running Wave.")
        times, values = self._wave_gauge_data[name]; return name, times, values

    def plot_wave_gauge(self) -> None:
        try:
            name, times, values = self._selected_wave_gauge(); TimeSeriesPlotDialog(times, values, f"Wave Gauge — {name}", "Water depth", "m", self).exec()
        except Exception as exc: self.wave_results_status.setText(f"Wave gauge plot failed: {exc}")

    def export_wave_gauge_csv(self) -> None:
        try:
            name, times, values = self._selected_wave_gauge(); selected, _ = QFileDialog.getSaveFileName(self, "Export Wave gauge CSV", f"{name}.csv", "CSV (*.csv)")
            if selected:
                with Path(selected).with_suffix(".csv").open("w", encoding="utf-8") as handle:
                    handle.write("simulation_time_s,water_depth_m\n"); handle.writelines(f"{time:.12g},{value:.12g}\n" for time, value in zip(times, values))
                self.wave_results_status.setText(f"Exported Wave gauge CSV: {selected}")
        except Exception as exc: self.wave_results_status.setText(f"Wave gauge CSV export failed: {exc}")

    def sample_wave_result_gauges(self) -> None:
        """Sample loaded temporal rasters at arbitrary post-run point features."""
        try:
            if not self._wave_results_manifest: raise ValueError("Load a Wave time series before sampling result gauges.")
            layer = self.wave_result_gauge_layer.currentLayer()
            temporal = self._active_wave_temporal_layer()
            if layer is None or not layer.isValid() or layer.geometryType() != QgsWkbTypes.PointGeometry:
                raise ValueError("Select a point layer for result-gauge sampling.")
            if temporal is None: raise ValueError("Load a Wave time series before sampling result gauges.")
            variable = str(temporal.customProperty("avac/temporal_variable"))[5:]
            product = self._wave_results_manifest["temporal"].get(variable)
            path = self.wave_run_root / WAVE_RESULT_DIRECTORY / product["path"]
            x, y, _values = self._raster_band_axes(path, 1)
            transform = QgsCoordinateTransform(layer.crs(), temporal.crs(), QgsProject.instance()) if layer.crs() != temporal.crs() else None
            points: list[tuple[str, float, float]] = []
            for feature in layer.getFeatures():
                geometry = QgsGeometry(feature.geometry())
                if geometry.isNull() or geometry.isEmpty(): continue
                if transform is not None and geometry.transform(transform) != 0: raise ValueError("QGIS could not transform a result gauge into the Wave result CRS.")
                point = geometry.asMultiPoint()[0] if geometry.isMultipart() else geometry.asPoint()
                points.append((self._feature_label(feature), point.x(), point.y()))
            if not points: raise ValueError("The selected point layer has no usable point features.")
            times = np.asarray(self._wave_results_manifest["simulation_time_seconds"], float)
            data = {name: np.empty(times.size, float) for name, _px, _py in points}
            for band in range(1, times.size + 1):
                _x, _y, values = self._raster_band_axes(path, band)
                for name, px, py in points: data[name][band - 1] = bilinear_sample(x, y, values, np.array([px]), np.array([py]))[0]
            self._sampled_wave_gauge_data = {name: (times, values) for name, values in data.items()}
            self.wave_sampled_gauge_selector.clear()
            for name in self._sampled_wave_gauge_data: self.wave_sampled_gauge_selector.addItem(name, name)
            self.wave_results_status.setText(f"Sampled {len(data)} result gauge(s) from the loaded Wave time series.")
        except Exception as exc: self.wave_results_status.setText(f"Result-gauge sampling failed: {exc}")

    def _selected_sampled_wave_gauge(self) -> tuple[str, np.ndarray, np.ndarray]:
        name = str(self.wave_sampled_gauge_selector.currentData() or "")
        if name not in self._sampled_wave_gauge_data: raise ValueError("Sample a point layer from Wave results first.")
        times, values = self._sampled_wave_gauge_data[name]; return name, times, values

    def plot_sampled_wave_gauge(self) -> None:
        try:
            name, times, values = self._selected_sampled_wave_gauge(); TimeSeriesPlotDialog(times, values, f"Wave Result Gauge — {name}", "Water depth" if str(self._active_wave_temporal_layer().customProperty("avac/temporal_variable"))[5:] == "depth" else "Water-surface displacement", "m", self).exec()
        except Exception as exc: self.wave_results_status.setText(f"Sampled-gauge plot failed: {exc}")

    def export_sampled_wave_gauge_csv(self) -> None:
        try:
            name, times, values = self._selected_sampled_wave_gauge(); selected, _ = QFileDialog.getSaveFileName(self, "Export sampled Wave gauge CSV", f"{name}.csv", "CSV (*.csv)")
            if selected:
                label = "water_depth_m" if str(self._active_wave_temporal_layer().customProperty("avac/temporal_variable"))[5:] == "depth" else "surface_displacement_m"
                with Path(selected).with_suffix(".csv").open("w", encoding="utf-8") as handle:
                    handle.write(f"simulation_time_s,{label}\n"); handle.writelines(f"{time:.12g},{value:.12g}\n" for time, value in zip(times, values))
                self.wave_results_status.setText(f"Exported sampled Wave gauge CSV: {selected}")
        except Exception as exc: self.wave_results_status.setText(f"Sampled-gauge CSV export failed: {exc}")

    def _selected_gauge_temporal_product(self) -> tuple[str, str, QgsRasterLayer, Path, dict, list[float]]:
        family, variable = self._split_result_variable(self.result_gauge_variable.currentData())
        if family == "wave":
            if not self._wave_results_manifest or self.wave_run_root is None:
                raise ValueError("Load the selected WAVE time series before sampling gauges.")
            layer = self._active_wave_temporal_layer(variable)
            product = self._wave_results_manifest["temporal"].get(variable)
            if layer is None or product is None:
                raise ValueError(f"Load WAVE {variable.replace('_', ' ')} before sampling gauges.")
            path = self.wave_run_root / WAVE_RESULT_DIRECTORY / str(product["path"])
            times = [float(value) for value in self._wave_results_manifest["simulation_time_seconds"]]
        elif family == "avac_lake":
            if not self._avac_lake_depth_manifest or self.wave_run_root is None:
                raise ValueError(f"Load {WAVE_SNOW_DEPTH_LABEL} before sampling gauges.")
            layer = self._active_avac_lake_depth_layer()
            product = self._avac_lake_depth_manifest.get("temporal", {}).get("depth")
            if layer is None or not isinstance(product, dict):
                raise ValueError(f"Load {WAVE_SNOW_DEPTH_LABEL} before sampling gauges.")
            path = self.wave_run_root / WAVE_RESULT_DIRECTORY / str(product["path"])
            times = [float(value) for value in self._avac_lake_depth_manifest["simulation_time_seconds"]]
        else:
            if not self._results_manifest:
                raise ValueError("Load the selected AVAC time series before sampling gauges.")
            layer = self._active_avac_temporal_layer(variable)
            if layer is None:
                raise ValueError(f"Load AVAC {variable.replace('_', ' ')} before sampling gauges.")
            grid = int(layer.customProperty("avac/fgout_grid", 1))
            product = self._results_manifest["temporal"].get(f"fgout{grid:04d}_{variable}")
            if product is None:
                raise ValueError(f"AVAC {variable.replace('_', ' ')} is not cached.")
            path = Path(self._results_manifest["source_run"]) / RESULT_DIRECTORY / str(product["path"])
            times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
        return family, variable, layer, path, product, times

    def sample_result_gauges(self) -> None:
        """Sample any selected AVAC or WAVE variable at post-run point features."""
        try:
            points_layer = self.result_gauge_layer.currentLayer()
            if points_layer is None or not points_layer.isValid() or points_layer.geometryType() != QgsWkbTypes.PointGeometry:
                raise ValueError("Select a valid QGIS point layer for result-gauge sampling.")
            selected_value = self.result_gauge_variable.currentData()
            if not self._ensure_temporal_result_loaded(selected_value, self.sample_result_gauges):
                return
            family, variable, temporal, path, product, times_list = self._selected_gauge_temporal_product()
            x, y, _values = self._raster_band_axes(path, 1)
            transform = QgsCoordinateTransform(points_layer.crs(), temporal.crs(), QgsProject.instance()) if points_layer.crs() != temporal.crs() else None
            points: list[tuple[str, float, float]] = []
            for feature in points_layer.getFeatures():
                geometry = QgsGeometry(feature.geometry())
                if geometry.isNull() or geometry.isEmpty():
                    continue
                if transform is not None and geometry.transform(transform) != 0:
                    raise ValueError("QGIS could not transform a gauge point into the result CRS.")
                point = geometry.asMultiPoint()[0] if geometry.isMultipart() else geometry.asPoint()
                points.append((self._feature_label(feature), point.x(), point.y()))
            if not points:
                raise ValueError("The selected point layer has no usable point features.")
            times = np.asarray(times_list, dtype=float)
            data = {name: np.empty(times.size, dtype=float) for name, _px, _py in points}
            for band in range(1, times.size + 1):
                _x, _y, values = self._raster_band_axes(path, band)
                for name, px, py in points:
                    data[name][band - 1] = bilinear_sample(x, y, values, np.array([px]), np.array([py]))[0]
            self._sampled_result_gauge_data = {name: (times, values) for name, values in data.items()}
            self._sampled_result_gauge_variable = (family, variable, str(product.get("unit", "")))
            # Retain compatibility for code that consumed the previous WAVE-only state.
            self._sampled_wave_gauge_data = dict(self._sampled_result_gauge_data) if family == "wave" else {}
            self.sampled_result_gauge_selector.clear()
            for name in self._sampled_result_gauge_data:
                self.sampled_result_gauge_selector.addItem(name, name)
            self.results_status.setText(f"Sampled {len(data)} gauge point(s) from {family.upper()} {variable.replace('_', ' ')}.")
        except Exception as exc:  # noqa: BLE001 - point/layer/result validation
            self.results_status.setText(f"Result-gauge sampling failed: {exc}")

    def _selected_result_gauge(self) -> tuple[str, np.ndarray, np.ndarray, str, str, str]:
        name = str(self.sampled_result_gauge_selector.currentData() or "")
        if name not in self._sampled_result_gauge_data or self._sampled_result_gauge_variable is None:
            raise ValueError("Read gauges from a point layer first.")
        family, variable, unit = self._sampled_result_gauge_variable
        times, values = self._sampled_result_gauge_data[name]
        return name, times, values, family, variable, unit

    def plot_sampled_result_gauge(self) -> None:
        try:
            name, times, values, family, variable, unit = self._selected_result_gauge()
            TimeSeriesPlotDialog(times, values, f"{family.upper()} Gauge — {name}", variable.replace("_", " ").title(), unit, self).exec()
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Gauge plot failed: {exc}")

    def export_sampled_result_gauge_csv(self) -> None:
        try:
            name, times, values, family, variable, unit = self._selected_result_gauge()
            selected, _ = QFileDialog.getSaveFileName(self, "Export result gauge CSV", f"{family}_{variable}_{name}.csv", "CSV (*.csv)")
            if not selected:
                return
            column = f"{variable}_{unit}".strip("_").replace("³", "3").replace("/", "_per_")
            path = Path(selected).with_suffix(".csv")
            with path.open("w", encoding="utf-8") as handle:
                handle.write(f"simulation_time_s,{column}\n")
                handle.writelines(f"{time:.12g},{value:.12g}\n" for time, value in zip(times, values))
            self.results_status.setText(f"Exported gauge CSV: {path}")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Gauge CSV export failed: {exc}")

    def _wave_diagnostic_series(self, key: str) -> tuple[np.ndarray, np.ndarray, str, str]:
        if not self._wave_diagnostics or not self._wave_diagnostics.get(key): raise ValueError("Load Wave results before using diagnostics.")
        path = Path(self._wave_diagnostics[key]); raw = np.genfromtxt(path, delimiter=",", names=True)
        value_column = raw.dtype.names[1]; return np.atleast_1d(raw["simulation_time_s"]), np.atleast_1d(raw[value_column]), value_column, str(path)

    def plot_wave_volume(self) -> None:
        try:
            times, values, _name, _path = self._wave_diagnostic_series("volume_csv"); TimeSeriesPlotDialog(times, values, "Wave Lake Water Volume", "Lake water volume", "m³", self).exec()
        except Exception as exc: self.wave_results_status.setText(f"Lake-volume plot failed: {exc}")

    def export_wave_diagnostic_csv(self, key: str, default: str) -> None:
        try:
            _times, _values, _name, path = self._wave_diagnostic_series(key); selected, _ = QFileDialog.getSaveFileName(self, "Export Wave diagnostic CSV", default, "CSV (*.csv)")
            if selected: shutil.copyfile(path, Path(selected).with_suffix(".csv")); self.wave_results_status.setText(f"Exported Wave diagnostic CSV: {selected}")
        except Exception as exc: self.wave_results_status.setText(f"Wave diagnostic CSV export failed: {exc}")

    def _escalate_wave_stop(self) -> None:
        if self._wave_stop_requested and self.wave_process.state() != QProcess.ProcessState.NotRunning:
            self._append_wave_log("Wave solver did not stop within 3 seconds; force-stopping it.")
            self.wave_process.kill()

    def _update_wave_progress(self) -> None:
        if self.wave_run_root is None or self._wave_expected_frames <= 0:
            return
        count = len(list((self.wave_run_root / "Wave" / "_output").glob("fort.q[0-9]*")))
        self.wave_progress.setValue(min(count, self._wave_expected_frames))
        self.wave_progress.setFormat(f"Wave frames {count} / {self._wave_expected_frames}")

    def _append_wave_log(self, message: str) -> None:
        """Keep Wave diagnostics in the Wave tab as well as the AVAC run log."""
        text = message.rstrip()
        if not text:
            return
        if "SOLUTION ERROR" in text or "NaN" in text:
            self._wave_solver_solution_error = True
        if hasattr(self, "wave_execution_log"):
            self.wave_execution_log.appendPlainText(text)
        self.log.appendPlainText("[Wave] " + text)

    def _append_wave_process_log(self) -> None:
        output = bytes(self.wave_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        output += bytes(self.wave_process.readAllStandardError()).decode("utf-8", errors="replace")
        if output:
            self._append_wave_log(output)

    def _on_wave_process_error(self, _error: QProcess.ProcessError) -> None:
        self._append_wave_log(f"Wave solver process error: {self.wave_process.errorString()}")

    def _on_wave_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._wave_progress_timer.stop()
        self._wave_termination_timer.stop()
        self._update_wave_progress()
        stopped = self._wave_stop_requested
        succeeded = not stopped and exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit and not self._wave_solver_solution_error
        self.wave_run_button.setEnabled(self.wave_run_root is not None)
        self.wave_stop_button.setEnabled(False)
        self.wave_cpu_cores.setEnabled(True)
        if stopped:
            self.wave_run_status.setText("Wave simulation stopped. You may run the prepared Wave scenario again.")
            self._append_wave_log("Wave solver stopped by user request.")
        elif succeeded:
            self.wave_run_status.setText("Wave simulation completed. Wave results are available in the isolated scenario directory.")
            self._append_wave_log("Wave solver completed successfully.")
        else:
            self.wave_run_status.setText(f"Wave simulation failed (exit code {exit_code}; numerical solution error detected). See execution log.")
            self._append_wave_log(f"Wave solver failed (exit code {exit_code}; numerical solution error detected).")
        if succeeded:
            self.wave_progress.setValue(self._wave_expected_frames)
            self.wave_progress.setFormat(f"Completed: {self._wave_expected_frames} Wave frames")
        if succeeded:
            self.refresh_wave_results_runs()
            self.wave_results_status.setText("Wave simulation completed. Choose a WAVE product in Results, then load its Summary Map or Time Series Map.")

    def _parameter_control(self, path: str, widget: QWidget) -> QWidget:
        self.parameter_controls[path] = widget
        signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentTextChanged", None) or getattr(widget, "toggled", None)
        if signal is not None:
            signal.connect(self._invalidate_prepared)
        return widget

    def _parameter_release_page(self) -> QWidget:
        page, form = QWidget(), None
        form = QFormLayout(page)
        for path, label, minimum, maximum, value, suffix in (
            ("release.d0", "Release depth", 0.0, 10.0, 1.6, " m"),
            ("release.theta_cr", "Critical slope", 0.0, 60.0, 30.0, " °"),
            ("release.gradient_hypso", "Hypsometric gradient", 0.0, 0.2, 0.03, ""),
            ("release.z_ref", "Reference elevation", 0.0, 9000.0, 1300.0, " m"),
            ("release.nu", "Slope correction ν", 0.0, 1.0, 0.2, ""),
        ):
            control = QDoubleSpinBox(); control.setDecimals(6); control.setRange(minimum, maximum); control.setValue(value); control.setSuffix(suffix)
            form.addRow(label, self._parameter_control(path, control))
        return_period = QSpinBox(); return_period.setRange(1, 10_000_000); return_period.setValue(100)
        form.addRow("Return period [years]", self._parameter_control("release.period_return", return_period))
        for path, label in (("release.correction_slope", "Apply slope correction"), ("release.correction_elevation", "Apply elevation correction")):
            control = QCheckBox(label); control.setChecked(True); form.addRow(self._parameter_control(path, control))
        return page

    def _parameter_rheology_page(self) -> QWidget:
        page, form = QWidget(), QFormLayout()
        model = QComboBox(); model.addItems(["Voellmy", "Coulomb", "cohesive_Voellmy"]); form.addRow("Model", self._parameter_control("rheology.model", model))
        for path, label, minimum, maximum, value, suffix in (
            ("rheology.rho", "Density", 100.0, 1200.0, 300.0, " kg/m³"),
            ("rheology.mu", "μ", 0.05, 0.5, 0.25, ""),
            ("rheology.xi", "ξ", 100.0, 20000.0, 1100.0, " m/s²"),
            ("rheology.C", "Cohesion", 0.0, 100000.0, 0.0, " Pa"),
        ):
            control = QDoubleSpinBox(); control.setDecimals(6); control.setRange(minimum, maximum); control.setValue(value); control.setSuffix(suffix)
            form.addRow(label, self._parameter_control(path, control))
        self.rheology_zones = QPlainTextEdit()
        self.rheology_zones.setPlaceholderText("Uniform rheology (leave empty), or one zone per line:\nμ, ξ, cohesion (Pa), lower elevation (m)\n0.30, 600, 100,\n0.225, 1200, 0, 1680")
        self.rheology_zones.setFixedHeight(96)
        self.rheology_zones.textChanged.connect(self._invalidate_prepared)
        form.addRow("Altitude zones", self.rheology_zones)
        self.rheology_visualize_button = QPushButton("Visualize Rheology Zones")
        self.rheology_visualize_button.setToolTip("Create a categorical DEM raster showing the active altitude-dependent rheology zones.")
        self.rheology_visualize_button.clicked.connect(self.show_rheology_visualization)
        form.addRow(self.rheology_visualize_button)
        page.setLayout(form); model.currentTextChanged.connect(self._update_rheology_controls); return page

    def _parameter_simulation_page(self) -> QWidget:
        page, form = QWidget(), QFormLayout()
        for path, label, minimum, maximum, value, suffix in (
            ("computation.t_max", "Simulation duration", 1, 100000, 150, " s"),
            ("computation.refinement", "AMR refinement levels", 1, 6, 1, ""),
        ):
            control = QSpinBox(); control.setRange(minimum, maximum); control.setValue(value); control.setSuffix(suffix); form.addRow(label, self._parameter_control(path, control))
        self.parameter_controls["computation.t_max"].valueChanged.connect(self._use_interval_timing)
        self.output_interval_control = QDoubleSpinBox(); self.output_interval_control.setDecimals(6); self.output_interval_control.setRange(.000001, 100000.0); self.output_interval_control.setValue(1.0); self.output_interval_control.setSuffix(" s")
        self.output_interval_control.valueChanged.connect(self._use_interval_timing)
        form.addRow("Output interval", self.output_interval_control)
        # Retained as non-visible controls for complete-schema compatibility
        # and the explicit advanced/test API.  They are not normal user
        # controls; duration/cadence is the normal workflow.
        for path, value in (("computation.nb_simul", 150), ("animation.n_out", 151)):
            control = QSpinBox(); control.setRange(1, 1_000_000); control.setValue(value)
            self._parameter_control(path, control)
            control.valueChanged.connect(self._use_raw_timing)
        for path, label, minimum, maximum, value in (("computation.cfl_target", "CFL target", 0.1, 1.0, 0.5), ("computation.cfl_max", "CFL maximum", 0.1, 1.0, 1.0)):
            control = QDoubleSpinBox(); control.setRange(minimum, maximum); control.setSingleStep(.05); control.setValue(value); form.addRow(label, self._parameter_control(path, control))
        computational_cell = QDoubleSpinBox(); computational_cell.setDecimals(6); computational_cell.setRange(.01, 10000.0); computational_cell.setValue(1.0); computational_cell.setSuffix(" m")
        form.addRow("Computational cell size", self._parameter_control("computation.cell_size", computational_cell))
        limiter = QComboBox(); limiter.addItems(["none", "minmod", "superbee", "mc", "vanleer"]); limiter.setCurrentText("superbee")
        form.addRow("Limiter", self._parameter_control("computation.limiter", limiter))
        page.setLayout(form); return page

    def _controlled_parameters(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for path, control in self.parameter_controls.items():
            if isinstance(control, QDoubleSpinBox): values[path] = float(control.value())
            elif isinstance(control, QSpinBox): values[path] = int(control.value())
            elif isinstance(control, QCheckBox): values[path] = bool(control.isChecked())
            elif isinstance(control, QComboBox): values[path] = control.currentText()
        zones = self._parse_rheology_zones()
        if zones:
            values["rheology.mu"] = [zone[0] for zone in zones]
            values["rheology.xi"] = [zone[1] for zone in zones]
            values["rheology.C"] = [zone[2] for zone in zones]
            values["rheology.z_breaks"] = [zone[3] for zone in zones[1:]]
        else:
            values["rheology.z_breaks"] = []
        if self._timing_mode == "interval":
            duration = float(values["computation.t_max"])
            interval = float(self.output_interval_control.value())
            # ``num_output_times`` counts intervals after t=0, whereas FGout
            # ``nout`` counts frames including t=0 and t_max.  One extra
            # FGout frame therefore gives both products the same exact clock.
            interval_count = max(1, int(np.ceil(duration / interval)))
            values["computation.nb_simul"] = interval_count
            values["animation.n_out"] = interval_count + 1
        # Keep output products standardized even when a loaded template or a
        # legacy saved configuration contained different values.
        values.update(self.FIXED_RUN_PARAMETERS)
        return values

    def _set_controlled_parameters(self, values: dict[str, object]) -> None:
        for path, value in values.items():
            control = self.parameter_controls.get(path)
            if control is None: continue
            blocked = control.blockSignals(True)
            if isinstance(control, QDoubleSpinBox):
                control.setValue(float(value[0] if isinstance(value, list) else value))
            elif isinstance(control, QSpinBox): control.setValue(int(value))
            elif isinstance(control, QCheckBox): control.setChecked(bool(value))
            elif isinstance(control, QComboBox): control.setCurrentText(str(value))
            control.blockSignals(blocked)
        self._update_rheology_controls()
        mu = values.get("rheology.mu", self.parameter_controls["rheology.mu"].value())
        xi = values.get("rheology.xi", self.parameter_controls["rheology.xi"].value())
        cohesion = values.get("rheology.C", self.parameter_controls["rheology.C"].value())
        z_breaks = list(values.get("rheology.z_breaks") or [])
        if isinstance(mu, list):
            lines = []
            for index, (mu_value, xi_value, c_value) in enumerate(zip(mu, xi, cohesion if isinstance(cohesion, list) else [cohesion] * len(mu))):
                # Keep the empty fourth column for the first zone.  The
                # parser deliberately uses that blank field to distinguish
                # the base zone from later altitude-bound zones; omitting the
                # trailing comma made valid multi-zone templates fail their
                # next input validation.
                lower = "" if index == 0 else f"{z_breaks[index - 1]:g}"
                lines.append(f"{float(mu_value):g}, {float(xi_value):g}, {float(c_value):g}, {lower}")
            blocked = self.rheology_zones.blockSignals(True)
            self.rheology_zones.setPlainText("\n".join(lines))
            self.rheology_zones.blockSignals(blocked)
        else:
            blocked = self.rheology_zones.blockSignals(True)
            self.rheology_zones.clear()
            self.rheology_zones.blockSignals(blocked)
        duration = float(values.get("computation.t_max", self.parameter_controls["computation.t_max"].value()))
        count = int(values.get("computation.nb_simul", max(1, int(values.get("animation.n_out", 2)) - 1)))
        if hasattr(self, "output_interval_control"):
            # Solver output count is the number of intervals after t=0.
            blocked = self.output_interval_control.blockSignals(True)
            self.output_interval_control.setValue(duration / max(1, count))
            self.output_interval_control.blockSignals(blocked)
        self._timing_mode = "raw"

    def _use_interval_timing(self, *_args) -> None:
        self._timing_mode = "interval"
        self._invalidate_prepared()

    def _use_raw_timing(self, *_args) -> None:
        self._timing_mode = "raw"

    def _update_rheology_controls(self, *_args) -> None:
        model = self.parameter_controls["rheology.model"].currentText()
        # ξ is used by both Voellmy variants; cohesion only by the cohesive
        # branch.  Zone entries remain available to make model changes
        # explicit rather than silently dropping a loaded configuration.
        self.parameter_controls["rheology.xi"].setEnabled(model in {"Voellmy", "cohesive_Voellmy"})
        self.parameter_controls["rheology.C"].setEnabled(model == "cohesive_Voellmy")

    def _parse_rheology_zones(self) -> list[tuple[float, float, float, float | None]]:
        """Read compact, ordered altitude-zone rows without a new file format."""
        text = self.rheology_zones.toPlainText().strip()
        if not text:
            return []
        zones: list[tuple[float, float, float, float | None]] = []
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            columns = [item.strip() for item in line.split(",")]
            if len(columns) != 4:
                raise ValueError(f"Altitude zone {line_number} must contain μ, ξ, cohesion, and lower elevation.")
            try:
                lower = None if not columns[3] else float(columns[3])
                zones.append((float(columns[0]), float(columns[1]), float(columns[2]), lower))
            except ValueError as exc:
                raise ValueError(f"Altitude zone {line_number} has a non-numeric value.") from exc
        if not zones or zones[0][3] is not None or any(zone[3] is None for zone in zones[1:]):
            raise ValueError("The first altitude zone must have a blank lower elevation; every later zone needs one.")
        lower_bounds = [zone[3] for zone in zones[1:]]
        if any(left >= right for left, right in zip(lower_bounds, lower_bounds[1:])):
            raise ValueError("Altitude-zone lower elevations must be strictly ascending.")
        return zones

    @staticmethod
    def _rheology_zone_label(index: int, zones: list[tuple[float, float, float, float | None]], model: str) -> str:
        """Build a categorical QGIS legend label from the solver's zone definition."""
        zone = zones[index]
        if len(zones) == 1:
            elevation_range = "all elevations"
        elif index == 0:
            elevation_range = f"z < {float(zones[1][3]):g} m"
        elif index == len(zones) - 1:
            elevation_range = f"z ≥ {float(zone[3]):g} m"
        else:
            elevation_range = f"{float(zone[3]):g} m ≤ z < {float(zones[index + 1][3]):g} m"
        values = [f"μ {zone[0]:g}"]
        if model != "Coulomb":
            values.append(f"ξ {zone[1]:g} m/s²")
        if model == "cohesive_Voellmy":
            values.append(f"C {zone[2]:g} Pa")
        return f"Zone {index + 1} — {elevation_range} ({'; '.join(values)})"

    @classmethod
    def _style_rheology_zone_raster(cls, layer: QgsRasterLayer, zones: list[tuple[float, float, float, float | None]], model: str) -> None:
        """Apply an exact categorical renderer: one color per solver zone."""
        palette = ("#3b7ddd", "#35a853", "#f4c430", "#f28e2b", "#d84a3a", "#9b59b6", "#17a2a4", "#795548")
        classes = [
            QgsPalettedRasterRenderer.Class(index + 1, QColor(palette[index % len(palette)]), cls._rheology_zone_label(index, zones, model))
            for index in range(len(zones))
        ]
        layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes))
        layer.setCustomProperty("avac/rheology_zone_preview", True)
        layer.setCustomProperty("avac/rheology_zone_count", len(zones))
        layer.setCustomProperty("avac/rheology_model", model)

    def show_rheology_visualization(self) -> None:
        """Create a categorical raster of the active DEM's solver rheology zones."""
        try:
            dem = self.dem_layer.currentLayer()
            if dem is None or not dem.isValid():
                raise ValueError("Select a valid DEM in AVAC Inputs before visualizing rheology zones.")
            if not dem.crs().isValid():
                raise ValueError("The selected DEM must have a valid CRS.")
            zones = self._parse_rheology_zones()
            if not zones:
                zones = [
                    (
                        float(self.parameter_controls["rheology.mu"].value()),
                        float(self.parameter_controls["rheology.xi"].value()),
                        float(self.parameter_controls["rheology.C"].value()),
                        None,
                    )
                ]
            self.rheology_visualize_button.setEnabled(False)
            self.status.setText("Creating rheology-zone raster from the selected DEM…")
            QgsApplication.processEvents()
            from osgeo import gdal, osr

            width, height = int(dem.width()), int(dem.height())
            if width <= 0 or height <= 0:
                raise ValueError("The selected DEM has no raster cells.")
            provider = dem.dataProvider()
            nodata = provider.sourceNoDataValue(1) if provider.sourceHasNoDataValue(1) else None
            extent = dem.extent()
            pixel_x, pixel_y = extent.width() / width, extent.height() / height
            if pixel_x <= 0.0 or pixel_y <= 0.0:
                raise ValueError("The selected DEM has an invalid extent.")
            path = self._workspace_preview_raster("avac_rheology_zones.tif")
            self._remove_wave_preview_layers("avac/rheology_zone_preview")
            dataset = gdal.GetDriverByName("GTiff").Create(
                str(path), width, height, 1, gdal.GDT_UInt16,
                options=["COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES", "BIGTIFF=IF_SAFER"],
            )
            if dataset is None:
                raise ValueError(f"Could not create the rheology-zone raster: {path}")
            try:
                reference = osr.SpatialReference(); reference.SetFromUserInput(dem.crs().authid())
                dataset.SetProjection(reference.ExportToWkt())
                dataset.SetGeoTransform((extent.xMinimum(), pixel_x, 0.0, extent.yMaximum(), 0.0, -pixel_y))
                output_band = dataset.GetRasterBand(1); output_band.SetNoDataValue(0)
                lower_bounds = [float(zone[3]) for zone in zones[1:]]
                dtype_by_qgis_type = {
                    Qgis.DataType.Byte: np.uint8, Qgis.DataType.UInt16: np.uint16, Qgis.DataType.Int16: np.int16,
                    Qgis.DataType.UInt32: np.uint32, Qgis.DataType.Int32: np.int32, Qgis.DataType.Float32: np.float32,
                    Qgis.DataType.Float64: np.float64,
                }
                chunk_rows = max(1, min(256, 2_000_000 // max(width, 1)))
                zone_counts = np.zeros(len(zones), dtype=np.int64)
                for row_start in range(0, height, chunk_rows):
                    rows = min(chunk_rows, height - row_start)
                    block_extent = QgsRectangle(
                        extent.xMinimum(), extent.yMaximum() - (row_start + rows) * pixel_y,
                        extent.xMaximum(), extent.yMaximum() - row_start * pixel_y,
                    )
                    block = provider.block(1, block_extent, width, rows)
                    dtype = dtype_by_qgis_type.get(block.dataType())
                    raw = bytes(block.data())
                    if dtype is not None and len(raw) == width * rows * np.dtype(dtype).itemsize:
                        elevation = np.frombuffer(raw, dtype=dtype).astype(float, copy=True).reshape((rows, width))
                    else:
                        elevation = np.fromiter(
                            (block.value(row, column) for row in range(rows) for column in range(width)),
                            dtype=float, count=width * rows,
                        ).reshape((rows, width))
                    if nodata is not None and np.isfinite(nodata):
                        elevation[np.isclose(elevation, nodata)] = np.nan
                    zone_ids = altitude_zone_ids(elevation, lower_bounds)
                    output_band.WriteArray(zone_ids, 0, row_start)
                    zone_counts += np.bincount(zone_ids.ravel(), minlength=len(zones) + 1)[1:]
                    if row_start % (chunk_rows * 8) == 0:
                        QgsApplication.processEvents()
                output_band.FlushCache(); dataset.FlushCache()
            finally:
                dataset = None
            layer = QgsRasterLayer(str(path), f"AVAC Rheology Zones — {dem.name()}")
            if not layer.isValid():
                raise ValueError(f"QGIS could not load the rheology-zone raster: {path}")
            model = self.parameter_controls["rheology.model"].currentText()
            self._style_rheology_zone_raster(layer, zones, model)
            QgsProject.instance().addMapLayer(layer)
            self._show_temporal_layer(layer)
            counts = ", ".join(f"Z{index + 1}: {count:,}" for index, count in enumerate(zone_counts))
            self.status.setText(f"Rheology-zone raster created: {path.name}. {counts} DEM cells.")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Rheology visualization failed: {exc}")
        finally:
            self.rheology_visualize_button.setEnabled(True)

    def load_configuration(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Load complete AVAC configuration", self.configuration_template.text(), "YAML (*.yaml *.yml)")
        if not selected: return
        try:
            self._set_controlled_parameters(controlled_values(load_complete_configuration(selected)))
            self.configuration_template.setText(selected)
            self.status.setText(f"Loaded complete AVAC configuration: {selected}")
        except ValueError as exc:
            self.status.setText(f"Configuration load failed: {exc}")

    def save_configuration(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(self, "Save complete AVAC configuration", "AVAC_configuration.yaml", "YAML (*.yaml)")
        if not selected: return
        try:
            template = load_complete_configuration(self._current_configuration_template())
            issues = validate_controlled_values(self._controlled_parameters())
            issues += validate_grid_contract(apply_controlled_values(template, self._controlled_parameters()))
            if issues: raise ValueError(" ".join(issues))
            payload = apply_controlled_values(template, self._controlled_parameters())
            Path(selected).with_suffix(".yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            self.status.setText(f"Saved complete AVAC configuration: {Path(selected).with_suffix('.yaml')}")
        except (OSError, ValueError) as exc:
            self.status.setText(f"Configuration save failed: {exc}")

    @classmethod
    def _read_plugin_configuration(cls, path: str | Path, expected_format: str) -> dict:
        """Read one of the plugin-owned YAML configuration formats."""
        try:
            payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Cannot read configuration: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be a YAML mapping.")
        if payload.get("format") != expected_format:
            raise ValueError(
                f"This is not a {expected_format} file. "
                "Use the matching Load Configuration button."
            )
        try:
            version = int(payload.get("version"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Configuration has no readable format version.") from exc
        if version != cls.CONFIGURATION_VERSION:
            raise ValueError(
                f"Configuration version {version} is unsupported; expected version {cls.CONFIGURATION_VERSION}."
            )
        return payload

    @staticmethod
    def _saved_layer_reference(layer, label: str) -> dict | None:
        """Describe a persistent QGIS layer so a plugin setup can reopen it."""
        if layer is None:
            return None
        provider = str(layer.providerType() or "")
        source = str(layer.source() or "")
        if provider.lower() == "memory" or source.startswith("/vsimem/"):
            raise ValueError(
                f"{label} uses a temporary in-memory layer and cannot be restored after QGIS closes. "
                "Save that layer to a file first."
            )
        if not provider or not source:
            raise ValueError(f"{label} has no persistent QGIS data source to save.")
        kind = "raster" if isinstance(layer, QgsRasterLayer) else "vector" if isinstance(layer, QgsVectorLayer) else "other"
        if kind == "other":
            raise ValueError(f"{label} is not a raster or vector layer.")
        reference = {
            "layer_id": layer.id(),
            "name": layer.name(),
            "source": source,
            "provider": provider,
            "kind": kind,
        }
        crs = layer.crs()
        if crs.isValid():
            authid = str(crs.authid() or "").strip()
            if authid:
                reference["crs_authid"] = authid
            else:
                # A laboratory/local Cartesian CRS can be valid in QGIS even
                # when it has no EPSG authority. Preserve its WKT so reloading
                # a Case never invents a geographic reference.
                wkt = str(crs.toWkt() or "").strip()
                if wkt:
                    reference["crs_wkt"] = wkt
        return reference

    @staticmethod
    def _configuration_mapping(value, label: str) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"Configuration field '{label}' must be a mapping.")
        return value

    def _restore_saved_layer(self, reference, expected_type, label: str):
        """Find a saved layer in the project or reopen it from its provider URI."""
        if reference is None:
            return None
        reference = self._configuration_mapping(reference, label)
        saved_kind = str(reference.get("kind", ""))
        expected_kind = "raster" if expected_type is QgsRasterLayer else "vector"
        if saved_kind != expected_kind:
            raise ValueError(f"Saved {label} is a {saved_kind or 'unknown'} layer, not a {expected_kind} layer.")
        source = str(reference.get("source", "")).strip()
        provider = str(reference.get("provider", "")).strip()
        name = str(reference.get("name", label)).strip() or label
        if not source or not provider:
            raise ValueError(f"Saved {label} has no usable QGIS source URI.")
        def apply_saved_crs(layer):
            saved_authid = str(reference.get("crs_authid", "")).strip()
            saved_wkt = str(reference.get("crs_wkt", "")).strip()
            if not saved_authid and not saved_wkt:
                return layer
            crs = QgsCoordinateReferenceSystem(saved_authid) if saved_authid else QgsCoordinateReferenceSystem()
            if saved_wkt and not saved_authid and not crs.createFromWkt(saved_wkt):
                raise ValueError(f"Saved {label} has an unreadable local CRS WKT.")
            if not crs.isValid():
                raise ValueError(f"Saved {label} has an invalid CRS.")
            if layer.crs() != crs:
                layer.setCrs(crs)
            return layer

        project = QgsProject.instance()
        saved_id = str(reference.get("layer_id", ""))
        current = project.mapLayer(saved_id) if saved_id else None
        if isinstance(current, expected_type):
            return apply_saved_crs(current)
        for candidate in project.mapLayers().values():
            if (isinstance(candidate, expected_type) and candidate.providerType() == provider
                    and candidate.source() == source):
                return apply_saved_crs(candidate)
        layer = expected_type(source, name, provider)
        if not layer.isValid():
            raise ValueError(f"QGIS could not reopen {label}: {source}")
        apply_saved_crs(layer)
        project.addMapLayer(layer)
        return layer

    @staticmethod
    def _set_configuration_spin(control, value, label: str) -> None:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Configuration value '{label}' must be numeric.") from exc
        if not math.isfinite(number) or number < control.minimum() or number > control.maximum():
            raise ValueError(
                f"Configuration value '{label}' must be between {control.minimum():g} and {control.maximum():g}."
            )
        control.setValue(number)

    @staticmethod
    def _set_configuration_combo_text(control: QComboBox, value, label: str) -> None:
        index = control.findText(str(value))
        if index < 0:
            raise ValueError(f"Configuration value '{label}' is not available: {value!r}.")
        control.setCurrentIndex(index)

    @staticmethod
    def _set_configuration_combo_data(control: QComboBox, value, label: str) -> None:
        index = control.findData(value)
        if index < 0:
            raise ValueError(f"Configuration value '{label}' is not available: {value!r}.")
        control.setCurrentIndex(index)

    def _wave_setup_state(self) -> dict:
        """Return every user-configurable WAVE Parameters value, not solver output."""
        if not hasattr(self, "wave_setup_scroll"):
            raise ValueError("Enable the Lake-Wave Extension before saving a WAVE configuration.")
        return {
            "avac_source_run": str(self.wave_avac_run_selector.currentData() or ""),
            "terrain": self._saved_layer_reference(self.wave_lake_dem.currentLayer(), "Terrain/bathymetry DEM"),
            "lake_polygon": self._saved_layer_reference(self.wave_lake_boundary.currentLayer(), "Lake water-body polygon"),
            "water_level": float(self.wave_water_level.value()),
            "cell_size": float(self.wave_cell_size.value()),
            "model": dict(self._wave_parameters()),
        }

    def _apply_wave_setup_state(self, state) -> list[str]:
        """Apply a saved WAVE setup and return non-fatal AVAC-source warnings."""
        state = self._configuration_mapping(state, "wave.setup")
        model = self._configuration_mapping(state.get("model"), "wave.setup.model")
        required_model = ("damping", "land_strickler", "water_strickler", "friction_depth_limit", "dry_limit",
                          "wave_tolerance_flag", "cfl_target", "cfl_max", "limiter")
        missing = [key for key in required_model if key not in model]
        if missing:
            raise ValueError("WAVE setup is missing model values: " + ", ".join(missing))
        terrain = self._restore_saved_layer(state.get("terrain"), QgsRasterLayer, "Terrain/bathymetry DEM")
        lake = self._restore_saved_layer(state.get("lake_polygon"), QgsVectorLayer, "Lake water-body polygon")
        self.wave_lake_dem.setLayer(terrain)
        self.wave_lake_boundary.setLayer(lake)
        self._set_configuration_spin(self.wave_water_level, state.get("water_level"), "wave.setup.water_level")
        self._set_configuration_spin(self.wave_cell_size, state.get("cell_size"), "wave.setup.cell_size")
        self._set_configuration_spin(self.wave_damping, model["damping"], "wave.setup.model.damping")
        self._set_configuration_spin(self.wave_land_strickler, model["land_strickler"], "wave.setup.model.land_strickler")
        self._set_configuration_spin(self.wave_water_strickler, model["water_strickler"], "wave.setup.model.water_strickler")
        self._set_configuration_spin(self.wave_friction_depth, model["friction_depth_limit"], "wave.setup.model.friction_depth_limit")
        self._set_configuration_spin(self.wave_dry_limit, model["dry_limit"], "wave.setup.model.dry_limit")
        self._set_configuration_spin(self.wave_tolerance, model["wave_tolerance_flag"], "wave.setup.model.wave_tolerance_flag")
        self._set_configuration_spin(self.wave_cfl_target, model["cfl_target"], "wave.setup.model.cfl_target")
        self._set_configuration_spin(self.wave_cfl_max, model["cfl_max"], "wave.setup.model.cfl_max")
        self._set_configuration_combo_text(self.wave_limiter, model["limiter"], "wave.setup.model.limiter")
        self._invalidate_wave_water_preview()

        requested_run = str(state.get("avac_source_run", "")).strip()
        self.refresh_wave_avac_runs()
        if requested_run:
            index = self.wave_avac_run_selector.findData(requested_run)
            if index >= 0:
                self.wave_avac_run_selector.setCurrentIndex(index)
                return []
            return [
                "The saved completed AVAC source run is not available in the current AVAC Working Directory. "
                "Select a completed run before preparing WAVE."
            ]
        return []

    def save_wave_configuration(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save WAVE setup configuration", "WAVE_configuration.yaml", "YAML (*.yaml *.yml)"
        )
        if not selected:
            return
        try:
            payload = {
                "format": self.WAVE_SETUP_CONFIGURATION_FORMAT,
                "version": self.CONFIGURATION_VERSION,
                "setup": self._wave_setup_state(),
            }
            destination = Path(selected).with_suffix(".yaml")
            destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            self.wave_setup_status.setText(f"Saved WAVE setup configuration: {destination}")
        except (OSError, ValueError) as exc:
            self.wave_setup_status.setText(f"WAVE configuration save failed: {exc}")

    def load_wave_configuration(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Load WAVE setup configuration", self.workspace_root.text(), "YAML (*.yaml *.yml)"
        )
        if not selected:
            return
        try:
            payload = self._read_plugin_configuration(selected, self.WAVE_SETUP_CONFIGURATION_FORMAT)
            warnings = self._apply_wave_setup_state(payload.get("setup"))
            suffix = " " + " ".join(warnings) if warnings else ""
            self.wave_setup_status.setText(f"Loaded WAVE setup configuration: {selected}.{suffix}")
        except (OSError, TypeError, ValueError) as exc:
            self.wave_setup_status.setText(f"WAVE configuration load failed: {exc}")

    def _plugin_configuration_state(self) -> dict:
        """Return the reopenable GUI setup, deliberately excluding run/result state."""
        wave_enabled = bool(self.wave_extension_toggle.isChecked())
        return {
            "format": self.PLUGIN_CONFIGURATION_FORMAT,
            "version": self.CONFIGURATION_VERSION,
            "working_directory": self.workspace_root.text().strip(),
            "avac": {
                "configuration_template": self.configuration_template.text().strip(),
                "parameters": self._controlled_parameters(),
                "inputs": {
                    "dem": self._saved_layer_reference(self.dem_layer.currentLayer(), "AVAC DEM raster layer"),
                    "release": self._saved_layer_reference(self.release_layer.currentLayer(), "AVAC release polygon layer"),
                },
            },
            "wave": {
                "enabled": wave_enabled,
                "setup": self._wave_setup_state() if wave_enabled else None,
            },
        }

    def save_plugin_configuration(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save complete AVAC4QGIS configuration", "AVAC4QGIS_configuration.yaml", "YAML (*.yaml *.yml)"
        )
        if not selected:
            return
        try:
            destination = Path(selected).with_suffix(".yaml")
            destination.write_text(yaml.safe_dump(self._plugin_configuration_state(), sort_keys=False), encoding="utf-8")
            self.status.setText(f"Saved complete AVAC4QGIS configuration: {destination}")
        except (OSError, ValueError) as exc:
            self.status.setText(f"Complete configuration save failed: {exc}")

    def load_plugin_configuration(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Load complete AVAC4QGIS configuration", self.workspace_root.text(), "YAML (*.yaml *.yml)"
        )
        if not selected:
            return
        try:
            payload = self._read_plugin_configuration(selected, self.PLUGIN_CONFIGURATION_FORMAT)
            avac = self._configuration_mapping(payload.get("avac"), "avac")
            inputs = self._configuration_mapping(avac.get("inputs"), "avac.inputs")
            parameters = self._configuration_mapping(avac.get("parameters"), "avac.parameters")
            wave = self._configuration_mapping(payload.get("wave"), "wave")
            template = str(avac.get("configuration_template", "")).strip()
            if not template:
                raise ValueError("Complete configuration has no AVAC configuration template path.")
            self.workspace_root.setText(str(payload.get("working_directory", "")).strip())
            self.configuration_template.setText(template)
            self._set_controlled_parameters(parameters)
            self.dem_layer.setLayer(self._restore_saved_layer(inputs.get("dem"), QgsRasterLayer, "AVAC DEM raster layer"))
            self.release_layer.setLayer(self._restore_saved_layer(inputs.get("release"), QgsVectorLayer, "AVAC release polygon layer"))
            self.prepared_avac_dir = None
            self._prepared_signature = None
            self.run_prepared_button.setEnabled(False)
            self.run_root.clear()

            enabled = wave.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("Complete configuration field 'wave.enabled' must be true or false.")
            warnings: list[str] = []
            self.wave_extension_toggle.setChecked(enabled)
            if enabled:
                warnings = self._apply_wave_setup_state(wave.get("setup"))
            # Selecting a workspace can refresh the Results-run summaries.
            # Keep their compact toolbox pages tall enough for the refreshed
            # labels, rather than introducing an inner scrollbar.
            self._reserve_toolbox_page_height(self.results_toolbox, self.results_toolbox.widget(0))
            suffix = " " + " ".join(warnings) if warnings else ""
            self.status.setText(f"Loaded complete AVAC4QGIS configuration: {selected}.{suffix}")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self.status.setText(f"Complete configuration load failed: {exc}")

    def preview_initial_depth(self) -> None:
        """Create a QGIS layer from the exact depth field that preparation writes."""
        self._start_initial_preview("depth")

    def preview_initial_snow_surface(self) -> None:
        """Show the exact t=0 surface elevation initialized by AVAC."""
        self._start_initial_preview("snow_surface")

    def _start_initial_preview(self, kind: str) -> None:
        """Compute one release initialization and publish the requested view."""
        try:
            dem = self.dem_layer.currentLayer()
            raster = raster_from_qgis_layer(dem)
            rings = rings_from_qgis_layer(self.release_layer.currentLayer(), dem.crs())
            task = InitialDepthPreviewTask(raster, rings, self._preprocessing_release())
            self._preview_kind = kind
            self._preview_task = task
            task.taskCompleted.connect(self._on_preview_completed)
            task.taskTerminated.connect(self._on_preview_terminated)
            self.preview_initial_depth_button.setEnabled(False)
            self.preview_initial_surface_button.setEnabled(False)
            label = "initial snow-surface" if kind == "snow_surface" else "initial-depth"
            self.status.setText(f"Computing AVAC {label} preview in the background…")
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"AVAC initialization preview failed: {exc}")

    def _on_preview_completed(self) -> None:
        task = self._preview_task
        self.preview_initial_depth_button.setEnabled(True)
        self.preview_initial_surface_button.setEnabled(True)
        if task is None or task.depth is None:
            self._on_preview_terminated(); return
        try:
            from osgeo import gdal, osr
            raster = task.raster
            surface = self._preview_kind == "snow_surface"
            values = initial_snow_surface_elevation(raster, task.depth) if surface else task.depth
            path = self._workspace_preview_raster(
                "avac_initial_snow_surface_elevation.tif" if surface else "avac_initial_depth_preview.tif"
            )
            dataset = gdal.GetDriverByName("GTiff").Create(str(path), raster.x.size, raster.y.size, 1, gdal.GDT_Float32, options=["COMPRESS=DEFLATE"])
            reference = osr.SpatialReference(); reference.SetFromUserInput(raster.crs_authid)
            dataset.SetProjection(reference.ExportToWkt())
            dx, dy = float(np.median(np.diff(raster.x))), float(np.median(np.diff(raster.y)))
            dataset.SetGeoTransform((raster.x[0] - dx / 2, dx, 0, raster.y[-1] + dy / 2, 0, -dy))
            band = dataset.GetRasterBand(1)
            band.SetNoDataValue(-9999.0)
            band.WriteArray(np.flipud(np.where(np.isfinite(values), values, -9999.0).astype(np.float32)))
            dataset = None
            property_name = "avac/initial_snow_surface_preview" if surface else "avac/initial_depth_preview"
            for layer_id, layer in list(QgsProject.instance().mapLayers().items()):
                if layer.customProperty(property_name):
                    QgsProject.instance().removeMapLayer(layer_id)
            if surface:
                limits = [float(np.nanmin(values)), float(np.nanmax(values))]
                layer = self._add_raster(path, "AVAC Initial Snow Surface Elevation", limits, "m")
                layer.setCustomProperty(property_name, True)
                layer.setCustomProperty("avac/snow_surface_definition", "selected DEM + AVAC mobile initial depth")
                self.status.setText(
                    "Initial snow surface loaded: selected DEM + AVAC mobile release depth. "
                    "No stationary winter snowpack is added outside the release polygons."
                )
            else:
                layer = self._add_raster(path, "AVAC Initial Depth Preview", float(np.nanmax(task.depth)), "m")
                layer.setCustomProperty(property_name, True)
                self.status.setText(f"Initial-depth preview: {int(np.count_nonzero(task.depth))} nonzero cells; max {np.nanmax(task.depth):g} m.")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"AVAC initialization preview layer failed: {exc}")

    def _on_preview_terminated(self) -> None:
        self.preview_initial_depth_button.setEnabled(True)
        self.preview_initial_surface_button.setEnabled(True)
        detail = str(self._preview_task.error) if self._preview_task and self._preview_task.error else "Preview was cancelled or failed."
        self.status.setText(f"AVAC initialization preview failed: {detail}")

    def _update_temporal_button_label(self, label: str) -> None:
        """Keep one stable action label for the shared solver/variable selector."""
        del label
        self.load_temporal_button.setText("Load Time Series")

    def _export_check_row(self) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.export_time)
        layout.addWidget(self.export_legend)
        layout.addWidget(self.export_scale_bar)
        layout.addStretch(1)
        return row

    def _path_row(self, field: QLineEdit, title: str) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("…")
        browse.setToolTip(title)
        browse.setMaximumWidth(32)
        browse.clicked.connect(lambda: self._choose_directory(field, title))
        layout.addWidget(field, 1)
        layout.addWidget(browse)
        return row

    @staticmethod
    def _choose_directory(field: QLineEdit, title: str) -> None:
        selected = QFileDialog.getExistingDirectory(None, title, field.text().strip())
        if selected:
            field.setText(selected)

    @staticmethod
    def _file_row(field: QLineEdit, title: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("…")
        browse.setToolTip(title)
        browse.setMaximumWidth(32)

        def choose() -> None:
            selected, _ = QFileDialog.getOpenFileName(None, title, field.text().strip())
            if selected:
                field.setText(selected)

        browse.clicked.connect(choose)
        layout.addWidget(field, 1)
        layout.addWidget(browse)
        return row

    def _cpu_core_control(self) -> QSpinBox:
        """Create a per-solver OpenMP thread-count selector."""
        control = QSpinBox()
        control.setRange(1, self._maximum_cpu_cores)
        control.setValue(self._maximum_cpu_cores)
        control.setSuffix(" cores")
        control.setToolTip(
            "Number of logical CPU cores used by this solver (OMP_NUM_THREADS). "
            "The default is the maximum available on this computer."
        )
        return control

    def _connect_runner(self) -> None:
        self.runner.started.connect(self._on_started)
        self.runner.stdout.connect(self._append_log)
        self.runner.stderr.connect(self._append_log)
        self.runner.finished.connect(self._on_finished)
        self.runner.progress.connect(self._on_progress)

    def _set_results_available(self, available: bool) -> None:
        """Gate postprocessing actions without blocking direct completed-run reopen."""
        analysis_available = bool(available or self._wave_results_manifest)
        self.load_temporal_button.setEnabled(analysis_available)
        for control in (
            self.summary_map, self.load_summary_button, self.export_png_button, self.export_frames_button,
            self.animation_every,
            self.extract_profile_button, self.profile_source, self.profile_variable, self.profile_sampling,
            self.profile_spacing, self.profile_line_layer, self.refresh_profile_layers_button,
            self.result_gauge_layer, self.result_gauge_variable, self.sample_result_gauge_button,
            self.sampled_result_gauge_selector, self.plot_sampled_result_gauge_button,
            self.export_sampled_result_gauge_button,
            self.wave_profile_series_format, self.wave_export_profile_series_button,
        ):
            control.setEnabled(analysis_available)

    def _current_configuration_template(self) -> Path:
        """Return the configured YAML, repairing only stale built-in paths.

        Complete case files are deliberately not replaced: a missing external
        YAML must remain a clear user-facing error.  The packaged default is
        different because QGIS settings routinely preserve its old plugin
        install location across an upgrade.
        """
        current = Path(self.configuration_template.text()).expanduser()
        built_in = default_template_path()
        if (
            built_in.is_file()
            and not current.is_file()
            and _is_stale_packaged_template_path(current, built_in)
        ):
            self.configuration_template.setText(str(built_in))
            QSettings().setValue(self.SETTINGS_TEMPLATE, str(built_in))
            return built_in
        return current

    def run_environment_check(self) -> None:
        # Normal operation checks the runtime rather than external development
        # tools.  The source-build check remains available through the explicit
        # Advanced action below.
        self.report = check_packaged_environment(
            self.workspace_root.text(), self._current_configuration_template(), self.avac_cpu_cores.value()
        )
        self.runtime_root = self.report.runtime_root
        self.log.setPlainText(self.report.as_text())
        self.status.setText("Environment ready. Validate inputs, then Prepare AVAC Run." if self.report.ready else "Environment check blocked; see log.")
        QSettings().setValue(self.SETTINGS_AVAC_DIR, self.avac_dir.text().strip())
        QSettings().setValue(self.SETTINGS_CLAW_ROOT, self.claw_root.text().strip())
        QSettings().setValue(self.SETTINGS_CLAW_PYTHON, self.claw_python.text().strip())
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Ready" if self.report.ready else "Blocked")

    def _preprocessing_release(self) -> dict[str, object]:
        """Return only the release values controlled through the normal UI."""
        return {path.split(".", 1)[1]: value for path, value in self._controlled_parameters().items() if path.startswith("release.")}

    def validate_preprocessing_inputs(self) -> None:
        try:
            raster = raster_from_qgis_layer(self.dem_layer.currentLayer())
            rings = rings_from_qgis_layer(self.release_layer.currentLayer(), self.dem_layer.currentLayer().crs())
            template = self._current_configuration_template()
            if not template.is_file():
                raise ValueError(f"Complete AVAC YAML template not found: {template}")
            configuration = configuration_for_raster(
                apply_controlled_values(load_complete_configuration(template), self._controlled_parameters()), raster,
            )
            issues = validate_controlled_values(self._controlled_parameters())
            issues += validate_grid_contract(configuration, float(raster.metadata["cellsize"]))
            if issues:
                raise ValueError(" ".join(issues))
            self.status.setText("Inputs valid. Preparation will derive the AVAC domain from the selected DEM and use its CRS.")
            self.log.setPlainText(
                f"DEM: {raster.metadata['ncols']} x {raster.metadata['nrows']}; "
                f"cell size {raster.metadata['cellsize']}; CRS {raster.crs_authid}; band {raster.band}\n"
                f"NoData: {raster.metadata['nodata_value']}; release polygons: {len(rings)}\n"
                f"AVAC domain: {configuration['dem_extent']['xmin']:g} to {configuration['dem_extent']['xmax']:g}, "
                f"{configuration['dem_extent']['ymin']:g} to {configuration['dem_extent']['ymax']:g}\n"
                "Release geometries are explicitly transformed to the DEM CRS only when their CRS differs."
            )
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Input validation failed: {exc}")
            self.log.setPlainText(str(exc))

    def _preparation_signature(self) -> tuple:
        dem = self.dem_layer.currentLayer()
        fine_dem = self.refinement_dem_layer.currentLayer()
        release = self.release_layer.currentLayer()
        return (
            dem.id() if dem else None, fine_dem.id() if fine_dem else None, release.id() if release else None,
            self.workspace_root.text().strip(), self.configuration_template.text().strip(),
            json.dumps(self._controlled_parameters(), sort_keys=True),
        )

    def _invalidate_prepared(self, *_args) -> None:
        if self.prepared_avac_dir is not None:
            self.prepared_avac_dir = None
            self._prepared_signature = None
            self.run_prepared_button.setEnabled(False)
            self.status.setText("Inputs changed; prepared run is stale. Prepare AVAC Run again.")

    def prepare_preprocessing_inputs(self) -> None:
        try:
            # Use the exact same normal packaged preflight as Check
            # Environment, rather than maintaining a second requirement list.
            self.report = check_packaged_environment(
                self.workspace_root.text(), self._current_configuration_template(), self.avac_cpu_cores.value()
            )
            if not self.report.ready:
                raise ValueError("Environment check blocked preparation: " + "; ".join(self.report.errors))
            workspace = self.report.avac_dir
            dem = self.dem_layer.currentLayer()
            raster = raster_from_qgis_layer(dem)
            fine_layer = self.refinement_dem_layer.currentLayer()
            fine_raster = raster_from_qgis_layer(fine_layer) if fine_layer else None
            rings = rings_from_qgis_layer(self.release_layer.currentLayer(), dem.crs())
            template = self._current_configuration_template()
            if not template.is_file():
                raise ValueError("Complete AVAC YAML template is unavailable; repair the plugin installation.")
            parameters = self._controlled_parameters()
            issues = validate_controlled_values(parameters)
            configuration = configuration_for_raster(
                apply_controlled_values(load_complete_configuration(template), parameters), raster,
            )
            issues += validate_grid_contract(configuration, float(raster.metadata["cellsize"]))
            if issues:
                raise ValueError(" ".join(issues))
            self.runtime_root = ensure_bundled_runtime()
            backend = self.runtime_root / "backend" / "AVAC"
            if not backend.is_dir():
                raise ValueError("Bundled AVAC runtime is unavailable; repair the plugin installation.")
            run_id, run_root = create_run_root(workspace)
            release_crs = self.release_layer.currentLayer().crs()
            release_crs_id = str(release_crs.authid() or release_crs.toWkt() or "").strip()
            inputs = materialize_layer_sources(
                run_root, dem.source(), self.release_layer.currentLayer().source(), raster.crs_authid,
                release_crs_id,
            )
            metadata = {
                "plugin": "AVAC QGIS", "source_dem": dem.source(), "dem_crs": raster.crs_authid,
                "release_layer": self.release_layer.currentLayer().source(), "runtime": str(self.runtime_root),
                "template": str(template.resolve()), "execution_mode": "bundled_runtime",
                "selected_release_overrides": self._preprocessing_release(), "selected_parameters": self._controlled_parameters(),
                "workspace_root": str(workspace), "run_id": run_id, "materialized_inputs": inputs,
            }
            task = PrepareAvacRunTask(run_root, backend, raster, rings, template, self._preprocessing_release(), metadata, parameters, fine_raster, bundled_runtime=True)
            self._preparation_task = task
            task.progressChanged.connect(self._on_preparation_progress)
            task.taskCompleted.connect(self._on_preparation_completed)
            task.taskTerminated.connect(self._on_preparation_terminated)
            self.prepare_inputs_button.setEnabled(False)
            self.run_prepared_button.setEnabled(False)
            self.prepare_progress.setRange(0, 100)
            self.prepare_progress.setValue(0)
            self.prepare_progress.setFormat("Preparing AVAC run: %p%")
            self.status.setText("Preparing isolated AVAC run in the background…")
            QgsApplication.taskManager().addTask(task)
            settings = QSettings()
            settings.setValue(self.SETTINGS_WORKSPACE, str(workspace))
            settings.setValue(self.SETTINGS_TEMPLATE, self.configuration_template.text().strip())
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Input preparation failed: {exc}")
            self.log.setPlainText(str(exc))

    def _on_preparation_progress(self, value: float) -> None:
        self.prepare_progress.setValue(int(value))

    def _on_preparation_completed(self) -> None:
        task = self._preparation_task
        self.prepare_inputs_button.setEnabled(True)
        if task is None or task.prepared is None:
            self._on_preparation_terminated()
            return
        prepared = task.prepared
        try:
            if self.runtime_root is None:
                self.runtime_root = ensure_bundled_runtime()
            output = prepare_runtime_execution(self.runtime_root, prepared.avac_dir)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Runtime data staging failed: {exc}")
            self.log.setPlainText(str(exc))
            return
        self.prepared_avac_dir = prepared.avac_dir
        self._prepared_signature = self._preparation_signature()
        self.run_root.setText(str(prepared.run_root))
        self.results_run_root.setText(str(prepared.run_root))
        self.run_prepared_button.setEnabled(True)
        self.prepare_progress.setValue(100)
        self.prepare_progress.setFormat("Prepared")
        self.status.setText("Prepared / Ready. Run will use the bundled managed runtime.")
        configuration = yaml.safe_load(prepared.configuration_path.read_text(encoding="utf-8"))
        release, computation, rheology = configuration["release"], configuration["computation"], configuration["rheology"]
        interval = float(computation["t_max"]) / max(1, int(computation["nb_simul"]))
        def value_text(value) -> str:
            return ", ".join(f"{float(item):g}" for item in value) if isinstance(value, list) else f"{float(value):g}"
        xi = f"; xi {value_text(rheology['xi'])}" if rheology.get("model") in {"Voellmy", "cohesive_Voellmy"} else ""
        self.prepared_summary.setText(
            f"Prepared Simulation\nRun ID: {prepared.run_root.name}; Return period: {release.get('period_return')} years; "
            f"Duration: {computation['t_max']:g} s; Output interval: {interval:g} s; Cell size: {computation['cell_size']:g} m\n"
            f"Rheology: {rheology['model']}; Density: {rheology['rho']:g} kg/m³; d0: {release['d0']:g} m; "
            f"mu: {value_text(rheology['mu'])}{xi}"
        )
        self.log.setPlainText(
            f"Prepared run: {prepared.run_root}\n{prepared.topo_path}\n{prepared.init_path}\n{prepared.configuration_path}\n"
            f"Release cells: {int(prepared.mask.sum())}; depth min/max/sum: "
            f"{prepared.depth.min():.12g} / {prepared.depth.max():.12g} / {prepared.depth.sum():.12g}\n"
            f"Runtime staged: {self.runtime_root}\nOutput working directory: {output}"
        )

    def _on_preparation_terminated(self) -> None:
        task = self._preparation_task
        self.prepare_inputs_button.setEnabled(True)
        self.prepare_progress.setValue(0)
        self.prepare_progress.setFormat("Preparation failed")
        detail = str(task.error) if task and task.error else "Preparation was cancelled or failed."
        self.status.setText(f"Input preparation failed: {detail}")
        self.log.setPlainText(detail)

    def run_prepared_case(self) -> None:
        if self.prepared_avac_dir is None or self._prepared_signature != self._preparation_signature():
            self._invalidate_prepared()
            return
        try:
            validate_prepared_run(self.prepared_avac_dir)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.run_prepared_button.setEnabled(False)
            return
        try:
            self.runtime_root = ensure_bundled_runtime()
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Bundled runtime unavailable: {exc}")
            self.log.setPlainText(str(exc))
            return
        self.report = check_runtime_environment(self.prepared_avac_dir, self.avac_cpu_cores.value())
        self.log.setPlainText(self.report.as_text())
        if not self.report.ready:
            self.status.setText("Prepared run is blocked by environment validation; see log.")
            return
        self.log.appendPlainText(f"\nLaunching bundled solver: {runtime_solver(self.runtime_root)}")
        self.runner.start_runtime(self.report, self.runtime_root, require_prepared_run=True)

    def run_case(self) -> None:
        self.run_environment_check()
        if self.report is None or not self.report.ready:
            return
        try:
            # This advanced entry point exists only for reopening a previously
            # prepared run after QGIS restarts.  It has the same marker guard
            # as the normal Prepare -> Run Prepared workflow.
            validate_prepared_run(self.report.avac_dir)
            self.log.appendPlainText("\nLaunching marked prepared run: /bin/sh -lc 'make clean && make .output'")
            self.runner.start(self.report, require_prepared_run=True)
        except (RuntimeError, ValueError) as exc:
            self.status.setText(str(exc))

    def stop_case(self) -> None:
        self.runner.stop()
        self.status.setText("Stop requested for the direct QProcess; child processes may remain.")

    def _on_started(self) -> None:
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.avac_cpu_cores.setEnabled(False)
        if self.report and self.report.expected_fort_frames:
            self.progress.setRange(0, self.report.expected_fort_frames)
            self.progress.setValue(0)
            self.progress.setFormat("%v / %m fort.t frames")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("Running")
        self.status.setText("AVAC is running; QGIS remains responsive.")

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text.rstrip("\n"))

    def _on_progress(self, written: int, expected: int) -> None:
        self.progress.setRange(0, expected)
        self.progress.setValue(written)
        self.progress.setFormat("%v / %m fort.t frames")

    def _on_finished(self, exit_code: int, normal_exit: bool) -> None:
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.avac_cpu_cores.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if exit_code == 0 and normal_exit else 0)
        if exit_code == 0 and normal_exit:
            self.status.setText("AVAC completed successfully. Raw output was checked; see log.")
            self.progress.setFormat("Completed")
            active_avac = self.prepared_avac_dir or Path(self.avac_dir.text()).resolve()
            self.log.appendPlainText("\n" + output_summary(active_avac))
            self.results_run_root.setText(str(active_avac.parent))
            self.refresh_results_runs()
            self.results_status.setText("Run completed. Open / Load Completed Run is now available in Results.")
            self.results_progress.setRange(0, 1); self.results_progress.setValue(1); self.results_progress.setFormat("Completed run available")
        else:
            self.status.setText(f"AVAC failed (exit code {exit_code}). See log.")
            self.progress.setFormat("Failed")
            self.results_status.setText("No completed AVAC results available for this failed or cancelled run.")
            self._set_results_available(False)

    def _requested_result_value(self, temporal: bool) -> str:
        """Keep an asynchronous task tied to the variable that started it."""
        if self._requested_results_value:
            return self._requested_results_value
        value = self.temporal_variable.currentData() if temporal else self.summary_map.currentData()
        return str(value or "")

    def _result_temporal_layer(self, value: object):
        family, variable = self._split_result_variable(value)
        if family == "wave":
            return self._active_wave_temporal_layer(variable)
        if family == "avac_lake":
            return self._active_avac_lake_depth_layer() if variable == "depth" else None
        return self._active_avac_temporal_layer(variable)

    def _finish_pending_results_action(self) -> None:
        """Resume a Results command after its required temporal layer loads."""
        action = self._pending_results_action
        self._pending_results_action = None
        self._requested_results_value = None
        if action is None:
            return

        def resume() -> None:
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - present a normal Results error after background loading
                self.results_status.setText(f"Results action failed after loading: {exc}")
                self.log.appendPlainText(str(exc))

        QTimer.singleShot(0, resume)

    def _cancel_pending_results_action(self) -> None:
        self._pending_results_action = None
        self._requested_results_value = None

    def _ensure_temporal_result_loaded(self, value: object, continuation: Callable[[], None]) -> bool:
        """Load a selected product on demand, then resume one Results command."""
        if self._result_temporal_layer(value) is not None:
            return True
        family, variable = self._split_result_variable(value)
        self.results_status.setText(f"Loading {family.upper()} {variable.replace('_', ' ')} time series before continuing…")
        self.prepare_selected_results(True, value=str(value), after_loaded=continuation)
        return False

    def prepare_selected_results(
        self,
        temporal: bool,
        *,
        value: str | None = None,
        after_loaded: Callable[[], None] | None = None,
    ) -> None:
        """Dispatch one shared Results action to the selected solver product."""
        selected_value = str(value or (self.temporal_variable.currentData() if temporal else self.summary_map.currentData()) or "")
        self._requested_results_value = selected_value
        self._pending_results_action = after_loaded
        family, _variable = self._split_result_variable(selected_value)
        if family == "wave":
            self.prepare_wave_results(temporal)
        elif family == "avac_lake":
            if not temporal:
                self.results_status.setText(f"{WAVE_SNOW_DEPTH_LABEL} is a time-series product; use Load Time Series.")
                self._cancel_pending_results_action()
            else:
                self.prepare_avac_lake_depth_results()
        else:
            self.prepare_results(temporal)

    def prepare_avac_lake_depth_results(self) -> None:
        """Create the AVAC depth series with the prepared WAVE lake set to zero."""
        try:
            avac_root = Path(self.results_run_root.text()).expanduser().resolve()
            if self.wave_run_root is None:
                raise ValueError("Select the completed WAVE scenario associated with this AVAC run first.")
            if wave_source_avac_run(self.wave_run_root) != avac_root:
                raise ValueError("Select the WAVE scenario prepared from the selected AVAC completed run.")
            task = PrepareAvacLakeDepthTask(avac_root, self.wave_run_root, int(self.temporal_grid.currentData()))
            self._avac_lake_depth_task = task
            task.progressChanged.connect(self._on_results_progress)
            task.taskCompleted.connect(self._on_avac_lake_depth_completed)
            task.taskTerminated.connect(self._on_avac_lake_depth_terminated)
            self.load_summary_button.setEnabled(False)
            self.load_temporal_button.setEnabled(False)
            self.results_progress.setRange(0, 100)
            self.results_progress.setValue(0)
            self.results_progress.setFormat("Preparing WAVE snow depth: %p%")
            self.results_status.setText("Preparing WAVE Snow Depth Outside Lake from the AVAC depth time series…")
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"WAVE Snow Depth Outside Lake cannot be loaded: {exc}")
            self.log.appendPlainText(str(exc))
            self._cancel_pending_results_action()

    def _on_avac_lake_depth_completed(self) -> None:
        task = self._avac_lake_depth_task
        self.load_summary_button.setEnabled(True)
        self.load_temporal_button.setEnabled(True)
        if task is None or task.discovery is None or task.manifest is None:
            self._on_avac_lake_depth_terminated()
            return
        self._avac_lake_depth_manifest = task.manifest
        self._set_results_available(True)
        self.results_progress.setValue(100)
        self.results_progress.setFormat("WAVE snow depth ready")
        self._load_avac_lake_depth_temporal(task.discovery, task.manifest)
        zeroed = task.manifest["temporal"]["depth"].get("zeroed_avac_cells", 0)
        self.results_status.setText(
            f"WAVE Snow Depth Outside Lake ready: {len(task.discovery.frames)} frames; "
            f"{zeroed} AVAC grid cell(s) in the prepared lake area set to zero."
        )
        self.log.appendPlainText(
            f"Derived WAVE Snow Depth Outside Lake product: {self.wave_run_root / WAVE_RESULT_DIRECTORY / AVAC_LAKE_DEPTH_MANIFEST}"
        )
        self._finish_pending_results_action()

    def _on_avac_lake_depth_terminated(self) -> None:
        task = self._avac_lake_depth_task
        self.load_summary_button.setEnabled(True)
        self.load_temporal_button.setEnabled(True)
        detail = str(task.error) if task and task.error else "WAVE Snow Depth Outside Lake preparation was cancelled or failed."
        self.results_progress.setFormat("WAVE snow depth preparation failed")
        self.results_status.setText(f"WAVE Snow Depth Outside Lake preparation failed: {detail}")
        self.log.appendPlainText(detail)
        self._cancel_pending_results_action()

    def prepare_results(self, requested_temporal: bool | None = None) -> None:
        """Discover/reuse result products for a completed run in a QgsTask."""
        try:
            self._requested_temporal = (self.sender() is self.load_temporal_button) if requested_temporal is None else bool(requested_temporal)
            root = Path(self.results_run_root.text()).expanduser().resolve()
            # Discover early for a concise user error; conversion remains off-thread.
            grid = int(self.temporal_grid.currentData()) if self._requested_temporal else int(self.summary_grid.currentData())
            discovery = discover_results(root, grid)
            _family, variable = self._split_result_variable(self._requested_result_value(self._requested_temporal))
            selected_temporal = (variable,) if self._requested_temporal else ()
            task = PrepareAvacResultsTask(root, selected_temporal, grid)
            self._results_task = task
            task.progressChanged.connect(self._on_results_progress)
            task.taskCompleted.connect(self._on_results_completed)
            task.taskTerminated.connect(self._on_results_terminated)
            self.load_summary_button.setEnabled(False)
            self.load_temporal_button.setEnabled(False)
            self.results_progress.setRange(0, 100)
            self.results_progress.setValue(0)
            self.results_progress.setFormat("Preparing results: %p%")
            label = self.temporal_variable.currentText().lower() if self._requested_temporal else self.summary_map.currentText().lower()
            self.results_status.setText(f"Preparing {label} for {len(discovery.frames)} discovered frames in the background…")
            QgsApplication.taskManager().addTask(task)
            QSettings().setValue(self.SETTINGS_RESULTS_RUN_ROOT, str(root))
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Results cannot be loaded: {exc}")
            self.log.appendPlainText(str(exc))
            self._cancel_pending_results_action()

    def refresh_results_runs(self, *_args) -> None:
        self.refresh_profile_layers()
        try:
            runs = completed_runs(self.workspace_root.text())
            previous = self.results_run_root.text().strip()
            self.results_run_selector.blockSignals(True); self.results_run_selector.clear()
            for run in runs:
                metadata = read_run_metadata(run)
                parameters = metadata.get("selected_parameters", metadata.get("controlled_parameters", {}))
                parameters = parameters if isinstance(parameters, dict) else {}
                return_period = parameters.get("release.period_return", "?")
                completed = display_local_datetime(metadata.get("updated_at", ""))
                benchmark = str(metadata.get("benchmark", "")).strip()
                case_name = str(metadata.get("case", "")).strip()
                if benchmark:
                    label = f"{benchmark} — {case_name or run.name} — completed {completed}"
                else:
                    label = f"{run.name} — {completed} — {return_period} years"
                self.results_run_selector.addItem(label, str(run))
            self.results_run_selector.blockSignals(False)
            if runs:
                index = next((i for i in range(self.results_run_selector.count()) if self.results_run_selector.itemData(i) == previous), 0)
                self.results_run_selector.setCurrentIndex(index); self._select_results_run(index)
            else:
                self.results_summary.setText("No completed runs in the current AVAC Working Directory.")
        except Exception as exc:  # noqa: BLE001
            self.results_summary.setText(f"Workspace runs unavailable: {exc}")

    def _select_results_run(self, index: int) -> None:
        path = self.results_run_selector.itemData(index)
        if not path:
            return
        self.results_run_root.setText(str(path))
        self._results_manifest = None; self._avac_lake_depth_manifest = None; self._last_profile = None; self._set_results_available(True)
        try:
            metadata = read_run_metadata(path)
            params = metadata.get("selected_parameters", metadata.get("controlled_parameters", {}))
            params = params if isinstance(params, dict) else {}
            benchmark = str(metadata.get("benchmark", "")).strip()
            case_name = str(metadata.get("case", "")).strip()
            if "computation.t_max" not in params or "release.period_return" not in params:
                configuration_path = Path(path) / str(metadata.get("avac_directory", "AVAC")) / "AVAC_configuration.yaml"
                try:
                    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8")) or {}
                    if isinstance(configuration, dict):
                        computation = configuration.get("computation", {})
                        release = configuration.get("release", {})
                        if isinstance(computation, dict):
                            params.setdefault("computation.t_max", computation.get("t_max"))
                        if isinstance(release, dict):
                            params.setdefault("release.period_return", release.get("period_return"))
                except (OSError, TypeError, ValueError, yaml.YAMLError):
                    pass
            run_label = f"{benchmark} — {case_name}" if benchmark else Path(path).name
            benchmark_line = f"\nBenchmark: {benchmark}" if benchmark else ""
            self.results_summary.setText(
                f"Run: {run_label}\nStatus: Completed{benchmark_line}\n"
                f"Return period: {params.get('release.period_return', 'unknown')} years\n"
                f"Simulation: {params.get('computation.t_max', 'unknown')} s"
            )
            self.results_status.setText("Run selected. Load a Summary Map or Time Series Map.")
        except ValueError as exc:
            self.results_summary.setText(str(exc))

    def open_run_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open completed AVAC-QGIS run directory", self.results_run_root.text())
        if selected:
            self.results_run_root.setText(selected)
            self._results_manifest = None; self._avac_lake_depth_manifest = None; self._set_results_available(True)
            self.results_status.setText("External run selected. Load a Summary Map or Time Series Map.")

    def _on_results_progress(self, value: float) -> None:
        self.results_progress.setValue(int(value))

    def _on_results_completed(self) -> None:
        task = self._results_task
        self.load_summary_button.setEnabled(True)
        self.load_temporal_button.setEnabled(True)
        if task is None or task.discovery is None or task.manifest is None:
            self._on_results_terminated()
            return
        self._results_manifest = task.manifest
        self._set_results_available(True)
        self.results_progress.setValue(100)
        self.results_progress.setFormat("Results ready")
        self.results_status.setText(
            f"Results ready: {len(task.discovery.frames)} frames, "
            f"simulation time {format_simulation_seconds(task.discovery.frames[0].time_seconds)}–{format_simulation_seconds(task.discovery.frames[-1].time_seconds)}."
        )
        self.log.appendPlainText(f"\nDerived GIS products: {task.discovery.run_root / RESULT_DIRECTORY}")
        for index in range(self.summary_map.count()):
            key = str(self.summary_map.itemData(index))
            if key.startswith("wave:"):
                continue
            static_key = key if task.discovery.fgmax_grid == 1 else f"fgmax{task.discovery.fgmax_grid:04d}_{key}"
            self.summary_map.model().item(index).setEnabled(static_key in task.manifest["static"])
        if self._requested_temporal:
            _family, variable = self._split_result_variable(self._requested_result_value(True))
            self._load_temporal_variable(task.discovery, task.manifest, variable)
        else:
            self._load_selected_static(task.discovery, task.manifest)
        self._finish_pending_results_action()

    def _on_results_terminated(self) -> None:
        task = self._results_task
        self.load_summary_button.setEnabled(True)
        self.load_temporal_button.setEnabled(True)
        detail = str(task.error) if task and task.error else "Result preparation was cancelled or failed."
        self.results_status.setText(f"Result preparation failed: {detail}")
        self.log.appendPlainText(detail)
        self._cancel_pending_results_action()

    @staticmethod
    def _style_raster(
        layer: QgsRasterLayer,
        limits,
        unit: str,
        *,
        event_time: bool = False,
        transparent_zero: bool = False,
    ) -> None:
        """Apply explicit physical renderer limits; never provider byte defaults."""
        minimum, maximum = (float(limits[0]), float(limits[1])) if isinstance(limits, (tuple, list)) else (0.0, float(limits))
        maximum = max(maximum, minimum + 1e-9)
        shader = QgsRasterShader()
        ramp = QgsColorRampShader()
        ramp.setColorRampType(QgsColorRampShader.Interpolated)
        ramp.setClassificationMode(Qgis.ShaderClassificationMethod.Continuous)
        ramp.setMinimumValue(minimum)
        ramp.setMaximumValue(maximum)
        if event_time:
            mid = minimum + (maximum - minimum) * .5
            items = [QgsColorRampShader.ColorRampItem(minimum, QColor(65, 105, 225), f"{minimum:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(mid, QColor(255, 215, 0), f"{mid:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(maximum, QColor(220, 30, 30), f"{maximum:g} {unit}")]
        elif minimum < 0.0:
            items = [QgsColorRampShader.ColorRampItem(minimum, QColor(65, 105, 225), f"{minimum:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(
                         0.0,
                         QColor(245, 245, 245, 0 if transparent_zero else 255),
                         f"0 {unit}",
                     ),
                     QgsColorRampShader.ColorRampItem(maximum, QColor(220, 30, 30), f"{maximum:g} {unit}")]
        else:
            span = maximum - minimum
            items = [QgsColorRampShader.ColorRampItem(minimum, QColor(0, 0, 0, 0), f"{minimum:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(minimum + span * .2, QColor(65, 105, 225), f"{minimum + span * .2:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(minimum + span * .6, QColor(255, 215, 0), f"{minimum + span * .6:g} {unit}"),
                     QgsColorRampShader.ColorRampItem(maximum, QColor(220, 30, 30), f"{maximum:g} {unit}")]
        ramp.setColorRampItemList(items)
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        # Explicit classification limits are required by QGIS's continuous
        # color-ramp legend node.  Without them a diverging multiband WAVE
        # displacement renderer can draw the ramp but omit its numeric values,
        # even though the shader items themselves are valid.
        renderer.setClassificationMin(minimum)
        renderer.setClassificationMax(maximum)
        layer.setRenderer(renderer)
        layer.setCustomProperty("avac/unit", unit)
        layer.setCustomProperty("avac/display_minimum", minimum)
        layer.setCustomProperty("avac/display_maximum", maximum)

    def _add_raster(
        self,
        path: Path,
        name: str,
        limits,
        unit: str,
        *,
        event_time: bool = False,
        transparent_zero: bool = False,
    ) -> QgsRasterLayer:
        layer = QgsRasterLayer(str(path), name)
        if not layer.isValid():
            raise ValueError(f"QGIS could not load derived raster: {path}")
        self._style_raster(
            layer, limits, unit,
            event_time=event_time,
            transparent_zero=transparent_zero,
        )
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _show_temporal_layer(self, layer: QgsRasterLayer) -> None:
        """Make an initialized temporal raster immediately visible in QGIS.

        AVAC and WAVE layers deliberately remain together: they now share a
        temporal origin, and the export layout creates a separate legend for
        every visible temporal layer.
        """
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if tree_layer is not None:
            tree_layer.setItemVisibilityChecked(True)
        layer.triggerRepaint()
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
            QgsApplication.processEvents()

    def _load_selected_static(self, discovery, manifest: dict) -> None:
        root = discovery.run_root / RESULT_DIRECTORY
        key = str(self.summary_map.currentData())
        static_key = key if discovery.fgmax_grid == 1 else f"fgmax{discovery.fgmax_grid:04d}_{key}"
        product = manifest["static"].get(static_key)
        if not product:
            raise ValueError(f"Selected summary map is unavailable for this run: {self.summary_map.currentText()}")
        titles = {"max_depth": "Maximum Depth", "max_velocity": "Maximum Velocity", "max_pressure": "Maximum Pressure",
                  "time_max_depth": "Time of Maximum Depth", "time_max_velocity": "Time of Maximum Velocity", "arrival_time": "Arrival Time"}
        self._add_raster(root / product["path"], f"AVAC {titles[key]} — {discovery.run_root.name}", product["range"], str(product["unit"]), event_time=bool(product.get("event_time")))

    def _load_temporal_variable(self, discovery, manifest: dict, variable: str) -> None:
        product = manifest["temporal"].get(f"fgout{discovery.fgout_grid:04d}_{variable}")
        if not product:
            raise ValueError(f"No cached temporal {variable} product is available.")
        previous_range = QgsProject.instance().timeSettings().temporalRange()
        title = f"AVAC {variable.replace('_', ' ').title()} (Temporal)"
        layer = self._add_raster(
            discovery.run_root / RESULT_DIRECTORY / product["path"], f"{title} — {discovery.run_root.name}", product["range"], product["unit"],
        )
        properties = layer.temporalProperties()
        properties.setIsActive(True)
        properties.setMode(QgsRasterLayerTemporalProperties.FixedRangePerBand)
        properties.setIntervalHandlingMethod(Qgis.TemporalIntervalMatchMethod.MatchUsingWholeRange)
        epoch = self._temporal_origin(manifest)
        times = [float(value) for value in manifest["simulation_time_seconds"]]
        ranges = self._temporal_band_ranges(epoch, times)
        properties.setFixedRangePerBand(ranges)
        layer.setCustomProperty("avac/temporal_axis", "Simulation time [s] (internal QGIS temporal-band mapping)")
        layer.setCustomProperty("avac/temporal_origin_iso", manifest.get("temporal_origin_iso", EPOCH_ISO))
        layer.setCustomProperty("avac/simulation_times_seconds", times)
        layer.setCustomProperty("avac/temporal_variable", variable)
        layer.setCustomProperty("avac/fgout_grid", discovery.fgout_grid)
        self._register_frame_player("avac", layer, times)
        self._show_temporal_layer(layer)
        self.log.appendPlainText(
            f"AVAC Frame Player ready: {len(times)} frames; direct raster-band display is active."
        )

    def _load_avac_lake_depth_temporal(self, discovery, manifest: dict) -> None:
        """Load the lake-zero AVAC depth series on AVAC's shared frame clock."""
        if self.wave_run_root is None:
            raise ValueError("The linked WAVE scenario is no longer selected.")
        product = manifest.get("temporal", {}).get("depth")
        if not isinstance(product, dict):
            raise ValueError("The WAVE Snow Depth Outside Lake product is unavailable.")
        layer = self._add_raster(
            self.wave_run_root / WAVE_RESULT_DIRECTORY / str(product["path"]),
            f"{WAVE_SNOW_DEPTH_LABEL} (Temporal) — {discovery.run_root.name}",
            product["range"], str(product["unit"]),
        )
        properties = layer.temporalProperties()
        properties.setIsActive(True)
        properties.setMode(QgsRasterLayerTemporalProperties.FixedRangePerBand)
        properties.setIntervalHandlingMethod(Qgis.TemporalIntervalMatchMethod.MatchUsingWholeRange)
        times = [float(value) for value in manifest["simulation_time_seconds"]]
        properties.setFixedRangePerBand(self._temporal_band_ranges(self._temporal_origin(manifest), times))
        layer.setCustomProperty("avac/temporal_axis", "Simulation time [s] (internal QGIS temporal-band mapping)")
        layer.setCustomProperty("avac/temporal_origin_iso", manifest.get("temporal_origin_iso", EPOCH_ISO))
        layer.setCustomProperty("avac/simulation_times_seconds", times)
        layer.setCustomProperty("avac/temporal_variable", "lake_depth")
        layer.setCustomProperty("avac/result_family", "avac_lake")
        layer.setCustomProperty("avac/display_label", "WAVE Snow Depth Outside Lake")
        layer.setCustomProperty("avac/fgout_grid", discovery.fgout_grid)
        layer.setCustomProperty("avac/wave_root", str(self.wave_run_root))
        # A newly selected lake-zero series represents the alternative,
        # so hide only the matching original depth layer.  It remains loaded
        # and can be made visible again in QGIS for comparison.
        for candidate in QgsProject.instance().mapLayers().values():
            if not isinstance(candidate, QgsRasterLayer):
                continue
            if str(candidate.customProperty("avac/temporal_variable", "")) != "depth":
                continue
            if str(candidate.customProperty("avac/result_family", "avac")) != "avac":
                continue
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(candidate.id())
            if tree_layer is not None:
                tree_layer.setItemVisibilityChecked(False)
        self._register_frame_player("avac", layer, times)
        self._show_temporal_layer(layer)
        self.log.appendPlainText(
            f"WAVE Snow Depth Outside Lake Frame Player ready: {len(times)} frames; "
            "the AVAC simulation-time axis is used unchanged."
        )

    @staticmethod
    def _layer_simulation_times(layer: QgsRasterLayer) -> list[float]:
        """Read the explicit simulation-time axis stored with a raster layer."""
        value = layer.customProperty("avac/simulation_times_seconds", [])
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                value = []
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return []

    @staticmethod
    def _frame_player_family_for_layer(layer: QgsRasterLayer) -> str | None:
        variable = str(layer.customProperty("avac/temporal_variable", ""))
        if not variable:
            return None
        return "wave" if variable.startswith("wave_") else "avac"

    def _frame_player_widgets(self, family: str):
        if family == "wave":
            return (
                self.wave_frame_slider, self.wave_play_button, self.wave_pause_button,
                self.wave_restart_button, self.wave_playback_fps, self.wave_frame_status,
            )
        return (
            self.avac_frame_slider, self.avac_play_button, self.avac_pause_button,
            self.avac_restart_button, self.avac_playback_fps, self.avac_frame_status,
        )

    def _frame_player_layers(self) -> list[QgsRasterLayer]:
        """Return visible, still-live AVAC/WAVE multiband time-series rasters."""
        project = QgsProject.instance()
        layers: list[QgsRasterLayer] = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
                continue
            if self._frame_player_family_for_layer(layer) is None:
                continue
            if not self._layer_simulation_times(layer):
                continue
            tree_layer = project.layerTreeRoot().findLayer(layer.id())
            if tree_layer is None or tree_layer.isVisible():
                layers.append(layer)
        return layers

    def _directly_display_temporal_band(self, layer: QgsRasterLayer, band: int, times: list[float]) -> None:
        """Select a multiband raster frame without QGIS temporal filtering."""
        band = min(max(int(band), 1), min(layer.bandCount(), len(times)))
        renderer = layer.renderer()
        if not isinstance(renderer, QgsSingleBandPseudoColorRenderer):
            raise ValueError(f"Temporal raster renderer is unsupported: {renderer.__class__.__name__ if renderer else 'none'}")
        # Deactivate QGIS filtering before repainting.  It otherwise replaces
        # the explicit input band in a version-dependent render-pipeline step.
        layer.temporalProperties().setIsActive(False)
        renderer.setInputBand(band)
        # ``renderer`` is owned by the QgsRasterLayer.  Reassigning that same
        # wrapped C++ object with ``setRenderer`` can invalidate QGIS's raster
        # pipe on macOS while a QgsTask completion signal is being delivered
        # (QGIS 3.44.12 then crashes in QgsRasterPipe::set).  Mutating the
        # existing renderer and explicitly repainting is the supported safe
        # path and retains the selected band.
        layer.setCustomProperty("avac/frame_player_band", band)
        layer.setCustomProperty("avac/frame_player_time_seconds", times[band - 1])
        layer.triggerRepaint()

    def _register_frame_player(self, family: str, layer: QgsRasterLayer, times: list[float]) -> None:
        """Make one newly loaded temporal raster controllable in the dock."""
        times = [float(value) for value in times]
        if not times or layer.bandCount() != len(times):
            raise ValueError("The loaded time series does not have one raster band per simulation frame.")
        self._frame_player_times[family] = times
        slider, play, pause, restart, fps, status = self._frame_player_widgets(family)
        slider.blockSignals(True)
        slider.setRange(0, len(times) - 1)
        slider.setValue(0)
        slider.blockSignals(False)
        for control in (slider, play, pause, restart, fps):
            control.setEnabled(True)
        status.setText(f"Frame 1 / {len(times)} — simulation time {format_simulation_seconds(times[0])}")
        self._set_frame_player_frame(family, 0)

    def _set_frame_player_frame(self, family: str, index: int) -> None:
        """Display a requested AVAC/WAVE frame and synchronize loaded layers."""
        times = self._frame_player_times.get(family, [])
        if not times:
            return
        index = min(max(int(index), 0), len(times) - 1)
        target_time = times[index]
        self._frame_player_index = index
        self._frame_player_family = family
        for layer in self._frame_player_layers():
            layer_times = self._layer_simulation_times(layer)
            if not layer_times:
                continue
            # AVAC and WAVE use the same source run clock.  Nearest-time
            # matching also handles a reduced Wave output cadence safely.
            band = min(range(len(layer_times)), key=lambda item: abs(layer_times[item] - target_time)) + 1
            self._directly_display_temporal_band(layer, band, layer_times)
        slider, _play, _pause, _restart, _fps, status = self._frame_player_widgets(family)
        slider.blockSignals(True); slider.setValue(index); slider.blockSignals(False)
        status.setText(f"Frame {index + 1} / {len(times)} — simulation time {format_simulation_seconds(target_time)}")
        # Preserve one authoritative timestamp for exports and profile labels
        # without relying on it to select the displayed raster band.
        primary = next((item for item in self._frame_player_layers()
                        if self._frame_player_family_for_layer(item) == family), None)
        if primary is not None:
            origin_text = str(primary.customProperty("avac/temporal_origin_iso", EPOCH_ISO))
            origin = QDateTime.fromString(origin_text, Qt.ISODate)
            if origin.isValid():
                ranges = self._temporal_band_ranges(origin, times)
                QgsProject.instance().timeSettings().setTemporalRange(ranges[index + 1])
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
        QgsApplication.processEvents()

    def _start_frame_player(self, family: str) -> None:
        if not self._frame_player_times.get(family):
            return
        self._frame_player_family = family
        _slider, _play, _pause, _restart, fps, _status = self._frame_player_widgets(family)
        self._frame_player_timer.start(max(1, round(1000 / fps.value())))

    def _pause_frame_player(self) -> None:
        self._frame_player_timer.stop()

    def _restart_frame_player(self, family: str) -> None:
        self._pause_frame_player()
        self._set_frame_player_frame(family, 0)

    def _update_frame_player_rate(self, _value: int) -> None:
        if self._frame_player_timer.isActive() and self._frame_player_family:
            self._start_frame_player(self._frame_player_family)

    def _advance_frame_player(self) -> None:
        family = self._frame_player_family
        times = self._frame_player_times.get(family or "", [])
        if not family or not times:
            self._pause_frame_player()
            return
        next_index = self._frame_player_index + 1
        if next_index >= len(times):
            self._pause_frame_player()
            return
        self._set_frame_player_frame(family, next_index)

    @staticmethod
    def _temporal_origin(manifest: dict) -> QDateTime:
        """Return the meaningful run origin used only for QGIS navigation."""
        value = str(manifest.get("temporal_origin_iso") or manifest.get("temporal_axis_epoch") or EPOCH_ISO)
        origin = QDateTime.fromString(value, Qt.ISODate)
        if not origin.isValid():
            raise ValueError(f"Temporal result has an invalid civil-time origin: {value}")
        return origin

    @staticmethod
    def _temporal_band_ranges(epoch: QDateTime, times: list[float]) -> dict[int, QgsDateTimeRange]:
        """Map each instantaneous AVAC state to a non-overlapping QGIS range."""
        if not times:
            raise ValueError("AVAC temporal result has no frame times.")
        ranges: dict[int, QgsDateTimeRange] = {}
        for band, start_seconds in enumerate(times, 1):
            final_step = max(0.001, start_seconds - times[band - 2] if band > 1 else 0.001)
            end_seconds = times[band] if band < len(times) else start_seconds + final_step
            ranges[band] = QgsDateTimeRange(
                epoch.addMSecs(round(start_seconds * 1000)), epoch.addMSecs(round(end_seconds * 1000)), True, False,
            )
        return ranges

    @staticmethod
    def _range_band(ranges: dict[int, QgsDateTimeRange], value) -> int | None:
        """Return a band only for an exact controller frame, never broad overlap."""
        return next((band for band, interval in ranges.items() if interval == value), None)

    def _temporal_controller(self):
        """Return QGIS's navigation object and the canvas controller it drives."""
        if not self.iface:
            return None, None, None
        canvas = self.iface.mapCanvas()
        canvas_controller = canvas.temporalController() if canvas is not None else None
        widget = self.iface.mainWindow().findChild(QgsTemporalControllerWidget)
        # Some QGIS 3.44 builds do not expose the application's controller
        # widget through QObject.findChild(), although the map canvas still
        # owns the complete QgsTemporalNavigationObject.  Prefer the visible
        # widget when available and otherwise use that same canvas object.
        navigation = widget.temporalController() if widget is not None else canvas_controller
        if navigation is not None and not hasattr(navigation, "setNavigationMode"):
            navigation = None
        return navigation, canvas_controller, widget

    def _show_temporal_controller(self) -> None:
        """Open QGIS's native controller so a loaded series is immediately playable."""
        if not self.iface or self.iface.mainWindow().findChild(QgsTemporalControllerWidget) is not None:
            return
        action = self.iface.mainWindow().findChild(QAction, "mActionTemporalController")
        if action is None:
            action = next(
                (
                    candidate
                    for candidate in self.iface.mainWindow().findChildren(QAction)
                    if candidate.text().replace("&", "") == "Temporal Controller"
                ),
                None,
            )
        if action is not None and not action.isChecked():
            action.trigger()
            QgsApplication.processEvents()

    @staticmethod
    def _format_temporal_range(value) -> str:
        if value is None:
            return "<none>"
        begin, end = value.begin(), value.end()
        return (
            f"[{begin.toString(Qt.ISODateWithMs)} ({begin.toMSecsSinceEpoch()} ms), "
            f"{end.toString(Qt.ISODateWithMs)} ({end.toMSecsSinceEpoch()} ms), "
            f"included={value.includeBeginning()}/{value.includeEnd()}]"
        )

    def _configure_temporal_controller(self, ranges: dict[int, QgsDateTimeRange], previous_range) -> None:
        """Configure the actual canvas controller from the manifest time axis."""
        target_band = self._range_band(ranges, previous_range) or 1
        target_range = ranges[target_band]
        self._show_temporal_controller()
        controller, _canvas_controller, _widget = self._temporal_controller()
        if controller is not None:
            controller.setNavigationMode(Qgis.TemporalNavigationMode.Animated)
            controller.setTemporalRangeCumulative(False)
            starts = [interval.begin().toMSecsSinceEpoch() for interval in ranges.values()]
            steps = [right - left for left, right in zip(starts, starts[1:])]
            # Use the manifest's exact regular cadence whenever it is exactly
            # representable in QDateTime milliseconds.  The end of the last
            # display interval is required to expose all N instantaneous
            # states as N non-cumulative frames.
            if steps and len(set(steps)) == 1:
                controller.setAvailableTemporalRanges([])
                controller.setTemporalExtents(QgsDateTimeRange(ranges[1].begin(), ranges[max(ranges)].end(), True, False))
                controller.setFrameDuration(QgsInterval(steps[0] / 1000.0, Qgis.TemporalUnit.Seconds))
            else:
                # QGIS 3.44's IrregularStep implementation returns the exact
                # available range for each frame.  Retain it only when the
                # authoritative manifest really is not a fixed ms schedule.
                controller.setTemporalExtents(QgsDateTimeRange(ranges[1].begin(), ranges[max(ranges)].begin(), True, True))
                controller.setAvailableTemporalRanges(list(ranges.values()))
                controller.setFrameDuration(QgsInterval(1, Qgis.TemporalUnit.IrregularStep))
            controller.setCurrentFrameNumber(target_band - 1)
        # Project time settings remain the fallback for headless tests and are
        # synchronized by the controller in the normal QGIS dock.
        QgsProject.instance().timeSettings().setTemporalRange(target_range)

    def _log_temporal_runtime_state(self, layer: QgsRasterLayer, times: list[float], ranges: dict[int, QgsDateTimeRange]) -> None:
        """Log the live QGIS temporal wiring after a time-series layer loads.

        These diagnostics deliberately use controller-generated ranges, not
        the ranges constructed above, so a QGIS-version behaviour change is
        visible in the execution log.
        """
        props = layer.temporalProperties()
        lines = ["Temporal runtime diagnostic (QGIS live objects):"]
        for band in range(1, min(10, layer.bandCount()) + 1):
            interval = props.fixedRangePerBand().get(band)
            lines.append(
                f"  band={band} avac_t={times[band - 1]:.12g}s "
                f"range={self._format_temporal_range(interval)}"
            )
        controller, canvas_controller, widget = self._temporal_controller()
        if controller is None:
            lines.append("  canvas temporal controller: unavailable")
        else:
            widget_controller = widget.temporalController() if widget is not None else None
            lines.append(
                "  controller="
                f"navigation_present={controller is not None}; widget_present={widget is not None}; "
                f"widget_matches_canvas={widget_controller == canvas_controller if widget_controller is not None else False}; "
                f"mode={controller.navigationMode()}; cumulative={controller.temporalRangeCumulative()}; "
                f"extent={self._format_temporal_range(controller.temporalExtents())}; "
                f"frame_duration={controller.frameDuration().seconds():.12g}s "
                f"unit={controller.frameDuration().originalUnit()}; "
                f"total_frames={controller.totalFrameCount()}; current_frame={controller.currentFrameNumber()}; "
                f"available_ranges={len(controller.availableTemporalRanges())}"
            )
            for frame in range(min(10, controller.totalFrameCount())):
                frame_range = controller.dateTimeRangeForFrameNumber(frame)
                resolved = props.bandForTemporalRange(layer, frame_range)
                filtered = list(props.filteredBandsForTemporalRange(layer, frame_range))
                lines.append(
                    f"  controller_frame={frame} range={self._format_temporal_range(frame_range)} "
                    f"bandFor={resolved} filtered={filtered}"
                )
        renderer = layer.renderer()
        renderer_bands = []
        if renderer is not None and hasattr(renderer, "usesBands"):
            renderer_bands = list(renderer.usesBands())
        lines.append(
            f"  renderer={renderer.__class__.__name__ if renderer is not None else '<none>'} "
            f"usesBands={renderer_bands}; QGIS render-pipe temporal selection is evaluated at render time."
        )
        self.log.appendPlainText("\n".join(lines))

    def _temporal_band_and_time(self, variable: str) -> tuple[int, float, dict]:
        if not self._results_manifest:
            raise ValueError("Load AVAC temporal results before exporting them.")
        layer = self._active_avac_temporal_layer(variable)
        grid = int(layer.customProperty("avac/fgout_grid", 1)) if layer is not None else 1
        product = self._results_manifest["temporal"].get(f"fgout{grid:04d}_{variable}")
        if not product:
            raise ValueError(f"Temporal {variable} is not cached; load it through Results first.")
        times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
        active_range = QgsProject.instance().timeSettings().temporalRange()
        band = 0
        if layer is not None:
            try:
                band = int(layer.customProperty("avac/frame_player_band", 0) or 0)
            except (TypeError, ValueError):
                band = 0
        if layer is not None and self._usable_temporal_range(active_range):
            band = band or layer.temporalProperties().bandForTemporalRange(layer, active_range)
        band = min(max(int(band or 1), 1), len(times))
        return band, simulation_seconds_for_band(times, band), product

    @staticmethod
    def _usable_temporal_range(value) -> bool:
        """QGIS-3.44-safe check for a controller range without isValid()."""
        if value is None or value.isEmpty():
            return False
        begin, end = value.begin(), value.end()
        return begin.isValid() and end.isValid()

    def _set_temporal_band(self, band: int) -> None:
        """Set the AVAC export frame through the direct player renderer."""
        if not self._results_manifest:
            return
        times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
        if self._frame_player_times.get("avac") == times:
            # Keep every visible AVAC/WAVE direct-rendered layer at the same
            # simulation instant before a combined-map export.
            self._set_frame_player_frame("avac", band - 1)
            return
        layer = self._active_avac_temporal_layer()
        if layer is not None:
            self._directly_display_temporal_band(layer, band, times)
        ranges = self._temporal_band_ranges(self._temporal_origin(self._results_manifest), times)
        QgsProject.instance().timeSettings().setTemporalRange(ranges[band])

    def _export_layer(self, temporal_variable: str | None = None) -> tuple[QgsRasterLayer, str, str, float | None, dict]:
        """Identify the displayed AVAC product; never infer a band from frame number."""
        if not self._results_manifest:
            raise ValueError("Load AVAC Results before exporting a map.")
        if temporal_variable is not None:
            layer = self._active_avac_temporal_layer(temporal_variable)
            if layer is None or layer.customProperty("avac/temporal_variable") != temporal_variable:
                raise ValueError(
                    f"Load Temporal {temporal_variable.replace('_', ' ').title()} before exporting its animation."
                )
            _band, time_seconds, product = self._temporal_band_and_time(temporal_variable)
            return layer, temporal_variable, str(product["unit"]), time_seconds, product
        layer = self._active_avac_temporal_layer()
        if layer is not None:
            variable = str(layer.customProperty("avac/temporal_variable"))
            _band, time_seconds, product = self._temporal_band_and_time(variable)
            return layer, variable, str(product["unit"]), time_seconds, product
        result_dir = Path(self._results_manifest["source_run"]) / RESULT_DIRECTORY
        for candidate in QgsProject.instance().mapLayers().values():
            if not isinstance(candidate, QgsRasterLayer):
                continue
            source = Path(candidate.source().split("|", 1)[0])
            for key, product in self._results_manifest["static"].items():
                if source == result_dir / str(product["path"]):
                    return candidate, key.replace("_", " "), str(product["unit"]), None, product
        raise ValueError("Select/load an AVAC static raster or temporal layer before exporting.")

    def _export_extent_for(self, layer: QgsRasterLayer, extent_mode: str | None = None):
        if (extent_mode or self.export_extent.currentData()) == "canvas" and self.iface is not None:
            return self.iface.mapCanvas().extent()
        return layer.extent()

    def _export_legend_layers(self, primary: QgsRasterLayer) -> list[QgsRasterLayer]:
        """Return each currently visible temporal raster for a PNG legend.

        A user can load AVAC and WAVE depth at once.  Their ranges and color
        ramps are independently styled, so one generic legend would be
        misleading.  Keep the requested product first and add every other
        temporal raster that is both visible and active at the current QGIS
        time.  Static exports retain one legend for the requested raster.
        """
        project = QgsProject.instance()
        canvas_layers = list(self.iface.mapCanvas().layers()) if self.iface is not None else list(project.mapLayers().values())
        active_range = project.timeSettings().temporalRange()
        candidates = [primary] + [candidate for candidate in canvas_layers if candidate.id() != primary.id()]
        result: list[QgsRasterLayer] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, QgsRasterLayer) or candidate.id() in seen:
                continue
            is_primary = candidate.id() == primary.id()
            tree_layer = project.layerTreeRoot().findLayer(candidate.id())
            if not is_primary and tree_layer is not None and not tree_layer.isVisible():
                continue
            temporal_variable = str(candidate.customProperty("avac/temporal_variable", ""))
            if not is_primary and not temporal_variable:
                continue
            if temporal_variable:
                properties = candidate.temporalProperties()
                try:
                    explicit_band = int(candidate.customProperty("avac/frame_player_band", 0) or 0)
                except (TypeError, ValueError):
                    explicit_band = 0
                if explicit_band:
                    pass
                elif not properties.isActive():
                    continue
                elif self._usable_temporal_range(active_range) and not properties.bandForTemporalRange(candidate, active_range):
                    continue
            seen.add(candidate.id())
            result.append(candidate)
        return result or [primary]

    @staticmethod
    def _legend_title(layer: QgsRasterLayer, fallback_variable: str) -> str:
        """Name a legend without hiding whether its depth is AVAC or WAVE."""
        explicit = str(layer.customProperty("avac/display_label", "")).strip()
        if explicit:
            return explicit
        variable = str(layer.customProperty("avac/temporal_variable", "")) or fallback_variable
        family = ""
        if variable.startswith("wave_"):
            family, variable = "WAVE", variable[5:]
        elif layer.customProperty("avac/temporal_variable"):
            family = "AVAC"
        display_name = "Depth" if "depth" in variable.lower() else variable.replace("_", " ").title()
        return f"{family} {display_name}".strip()

    def _render_export_png(
        self,
        target: Path,
        layer: QgsRasterLayer,
        variable: str,
        unit: str,
        simulation_time: float | None,
        *,
        product_label: str = "AVAC",
        width: int | None = None,
        extent_mode: str | None = None,
        include_time: bool | None = None,
        include_legend: bool | None = None,
        include_scale_bar: bool | None = None,
    ) -> None:
        """Render with QGIS's raster renderer, never a second AVAC/Matplotlib renderer."""
        if self.iface is None:
            raise ValueError("QGIS map canvas is unavailable for map export.")
        target.parent.mkdir(parents=True, exist_ok=True)
        extent = self._export_extent_for(layer, extent_mode)
        map_width = width or self.export_width.value()
        include_time = self.export_time.isChecked() if include_time is None else include_time
        include_legend = self.export_legend.isChecked() if include_legend is None else include_legend
        include_scale_bar = self.export_scale_bar.isChecked() if include_scale_bar is None else include_scale_bar
        map_height = max(1, round(map_width * extent.height() / extent.width()))
        visible_temporal_layers = self._export_legend_layers(layer)
        legend_layers = visible_temporal_layers if include_legend else []
        legend_width = 240 * len(legend_layers)
        image = QImage(map_width + legend_width, map_height + 48, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("white"))
        settings = QgsMapSettings()
        canvas_layers = list(self.iface.mapCanvas().layers())
        # A newly opened/headless QGIS canvas may not yet have synchronized its
        # layer set.  The requested AVAC product must always be rendered.
        layers = visible_temporal_layers + [candidate for candidate in canvas_layers if candidate.id() not in {item.id() for item in visible_temporal_layers}]
        settings.setLayers(layers)
        settings.setDestinationCrs(layer.crs())
        settings.setExtent(extent)
        settings.setOutputSize(QSize(map_width, map_height))
        settings.setBackgroundColor(QColor("white"))
        # Custom painter jobs do not implicitly inherit the project's Temporal
        # Controller range.  Without this, every exported PNG uses band 1.
        settings.setIsTemporal(True)
        settings.setTemporalRange(QgsProject.instance().timeSettings().temporalRange())
        painter = QPainter(image)
        painter.translate(0, 48)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start(); job.waitForFinished()
        painter.resetTransform()
        painter.setPen(QColor("black")); painter.setFont(QFont("Sans Serif", 12))
        title = f"{product_label} {variable.title()} [{unit}]"
        if simulation_time is not None and include_time:
            title += f" — Simulation time: {format_simulation_seconds(simulation_time)}"
        painter.drawText(12, 28, title)
        for index, legend_layer in enumerate(legend_layers):
            legend_variable = str(legend_layer.customProperty("avac/temporal_variable", "")) or variable
            self._paint_raster_legend(
                painter, legend_layer, map_width + 16 + 240 * index, 64,
                str(legend_layer.customProperty("avac/unit", unit)), self._legend_title(legend_layer, variable),
            )
        if include_scale_bar:
            self._paint_scale_bar(painter, extent, map_width, map_height, layer.crs())
        painter.end()
        if not image.save(str(target), "PNG"):
            raise RuntimeError(f"QGIS could not export PNG: {target}")

    @staticmethod
    def _paint_raster_legend(painter: QPainter, layer: QgsRasterLayer, x: int, y: int, unit: str, title: str) -> None:
        """Draw the active layer's own QGIS color ramp as a continuous bar."""
        painter.setPen(QColor("black")); painter.setFont(QFont("Sans Serif", 10)); painter.drawText(x, y, title)
        items = []
        try:
            items = layer.renderer().shader().rasterShaderFunction().colorRampItemList()
        except Exception:  # noqa: BLE001
            pass
        if not items:
            return
        items = sorted(items, key=lambda item: item.value)
        minimum, maximum = items[0].value, items[-1].value
        bar_top, bar_height, bar_width = y + 16, 180, 22
        gradient = QLinearGradient(x, bar_top, x, bar_top + bar_height)
        if maximum <= minimum:
            gradient.setColorAt(0.0, items[-1].color); gradient.setColorAt(1.0, items[-1].color)
        else:
            for item in items:
                position = 1.0 - (item.value - minimum) / (maximum - minimum)
                gradient.setColorAt(position, item.color)
        painter.fillRect(x, bar_top, bar_width, bar_height, QBrush(gradient))
        painter.drawRect(x, bar_top, bar_width, bar_height)
        for item in items:
            position = 1.0 if maximum <= minimum else 1.0 - (item.value - minimum) / (maximum - minimum)
            label_y = bar_top + round(position * bar_height)
            painter.drawLine(x + bar_width, label_y, x + bar_width + 4, label_y)
            label = str(item.label or "").strip()
            if not any(character.isdigit() for character in label):
                label = f"{item.value:.6g} {unit}".strip()
            painter.drawText(x + bar_width + 8, label_y + 4, label)

    @staticmethod
    def _paint_scale_bar(
        painter: QPainter,
        extent: QgsRectangle,
        map_width: int,
        map_height: int,
        crs: QgsCoordinateReferenceSystem,
    ) -> None:
        """Paint a compact, map-unit-aware scale bar inside the map frame."""
        if extent.width() <= 0.0 or map_width <= 0:
            return
        target = extent.width() * 0.2
        exponent = 10.0 ** np.floor(np.log10(target))
        length = max(value for value in (exponent, 2.0 * exponent, 5.0 * exponent, 10.0 * exponent) if value <= target * (1.0 + 1.e-12))
        pixels = max(1, round(length / extent.width() * map_width))
        unit = QgsUnitTypes.toAbbreviatedString(crs.mapUnits()) or "map units"
        display_length = length
        if unit.lower() in {"m", "metres", "meters"} and length >= 1000.0:
            display_length, unit = length / 1000.0, "km"
        label = f"{display_length:g} {unit}".strip()
        x, baseline = 20, 48 + map_height - 18
        painter.fillRect(x - 8, baseline - 30, pixels + 16, 42, QColor(255, 255, 255, 220))
        half = max(1, pixels // 2)
        painter.fillRect(x, baseline, half, 8, QColor("black"))
        painter.fillRect(x + half, baseline, pixels - half, 8, QColor("white"))
        painter.setPen(QColor("black")); painter.drawRect(x, baseline, pixels, 8)
        painter.setFont(QFont("Sans Serif", 10)); painter.drawText(x, baseline - 6, label)

    def export_selected_current_map_png(self) -> None:
        selected_value = self.temporal_variable.currentData()
        if not self._ensure_temporal_result_loaded(selected_value, self.export_selected_current_map_png):
            return
        family, _variable = self._split_result_variable(selected_value)
        if family == "wave":
            self.export_wave_current_map_png()
        elif family == "avac_lake":
            self.export_avac_lake_depth_current_map_png()
        else:
            self.export_current_map_png()

    def export_selected_temporal_frames(self) -> None:
        selected_value = self.temporal_variable.currentData()
        if not self._ensure_temporal_result_loaded(selected_value, self.export_selected_temporal_frames):
            return
        family, _variable = self._split_result_variable(selected_value)
        if family == "wave":
            self.export_wave_temporal_frames()
        elif family == "avac_lake":
            self.export_avac_lake_depth_temporal_frames()
        else:
            self.export_temporal_frames()

    def _avac_lake_depth_export_layer(self) -> tuple[QgsRasterLayer, str, str, float, dict]:
        if not self._avac_lake_depth_manifest:
            raise ValueError("Load WAVE Snow Depth Outside Lake before exporting it.")
        layer = self._active_avac_lake_depth_layer()
        product = self._avac_lake_depth_manifest.get("temporal", {}).get("depth")
        if layer is None or not isinstance(product, dict):
            raise ValueError("The loaded WAVE Snow Depth Outside Lake layer is unavailable for the selected WAVE scenario.")
        times = [float(value) for value in self._avac_lake_depth_manifest["simulation_time_seconds"]]
        try:
            band = int(layer.customProperty("avac/frame_player_band", 0) or 0)
        except (TypeError, ValueError):
            band = 0
        band = band or layer.temporalProperties().bandForTemporalRange(layer, QgsProject.instance().timeSettings().temporalRange()) or 1
        band = min(max(int(band), 1), len(times))
        return layer, "Snow Depth Outside Lake", str(product["unit"]), times[band - 1], product

    def export_avac_lake_depth_current_map_png(self) -> None:
        try:
            layer, variable, unit, time_seconds, _product = self._avac_lake_depth_export_layer()
            suffix = format_simulation_seconds(time_seconds).replace(" ", "")
            selected, _ = QFileDialog.getSaveFileName(
                self, "Export WAVE Snow Depth Outside Lake map PNG",
                f"wave_snow_depth_outside_lake_t{suffix}.png", "PNG image (*.png)",
            )
            if not selected:
                return
            self._render_export_png(Path(selected).with_suffix(".png"), layer, variable, unit, time_seconds, product_label="WAVE")
            self.results_status.setText(f"Exported QGIS-rendered WAVE Snow Depth Outside Lake map: {selected}")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"WAVE Snow Depth Outside Lake PNG export failed: {exc}")
            self.log.appendPlainText(str(exc))

    def export_avac_lake_depth_temporal_frames(self) -> None:
        """Export the lake-zero AVAC depth series on the shared simulation clock."""
        previous_range = None
        try:
            layer, variable, unit, _time, product = self._avac_lake_depth_export_layer()
            selected = QFileDialog.getExistingDirectory(self, "Export WAVE Snow Depth Outside Lake PNG frames")
            if not selected:
                return
            directory = Path(selected)
            times = [float(value) for value in self._avac_lake_depth_manifest["simulation_time_seconds"]]
            frames = animation_frames(times, self.animation_every.value())
            previous_range = QgsProject.instance().timeSettings().temporalRange()
            dialog = self._begin_frame_export("Exporting WAVE snow-depth PNG frames", len(frames), self.results_progress, self.cancel_export_button)
            for index, (band, time_seconds) in enumerate(frames, 1):
                self._set_frame_player_frame("avac", band - 1)
                self._render_export_png(
                    directory / frame_filename("wave_snow_depth_outside_lake", band, time_seconds),
                    layer, variable, unit, time_seconds, product_label="WAVE",
                )
                if self._frame_export_step(dialog, index):
                    break
            if self._frame_export_cancelled:
                self.results_status.setText("WAVE Snow Depth Outside Lake PNG frame export cancelled.")
                return
            extent = self._export_extent_for(layer)
            provenance = animation_provenance(
                self._avac_lake_depth_manifest["source_avac_run"], variable, frames, 0,
                (extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum()), product["range"],
            )
            provenance.pop("frames_per_second", None)
            provenance.update({
                "format": "AVAC4QGIS WAVE Snow Depth Outside Lake PNG frames v1",
                "prepared_lake_area": "zero depth", "unit": unit,
                "frame_step": self.animation_every.value(), "image_width_px": self.export_width.value(),
                "include_legend": self.export_legend.isChecked(),
                "include_scale_bar": self.export_scale_bar.isChecked(),
                "filenames": [frame_filename("wave_snow_depth_outside_lake", band, time) for band, time in frames],
            })
            (directory / "frames.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
            self.results_progress.setFormat("WAVE snow-depth PNG frames exported")
            self.results_status.setText(f"Exported {len(frames)} WAVE Snow Depth Outside Lake PNG time-series frames to {directory}.")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"WAVE Snow Depth Outside Lake PNG frame export failed: {exc}")
            self.log.appendPlainText(str(exc))
        finally:
            if "dialog" in locals():
                self._finish_frame_export(dialog, self.results_progress, self.cancel_export_button)
            if previous_range is not None:
                QgsProject.instance().timeSettings().setTemporalRange(previous_range)

    def export_current_map_png(self) -> None:
        try:
            layer, variable, unit, time_seconds, _product = self._export_layer()
            suffix = f"_t{format_simulation_seconds(time_seconds).replace(' ', '')}" if time_seconds is not None else ""
            default = f"avac_{variable.replace(' ', '_')}{suffix}.png"
            selected, _ = QFileDialog.getSaveFileName(self, "Export AVAC map PNG", default, "PNG image (*.png)")
            if not selected:
                return
            output = Path(selected).with_suffix(".png")
            self._render_export_png(output, layer, variable, unit, time_seconds)
            self.results_status.setText(f"Exported QGIS-rendered AVAC map: {output}")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Map PNG export failed: {exc}")
            self.log.appendPlainText(str(exc))

    def export_temporal_frames(self) -> None:
        """Export a complete PNG sequence without requiring ffmpeg."""
        previous_range = None
        try:
            _family, variable = self._selected_temporal_family_variable()
            layer, _name, unit, _time, product = self._export_layer(variable)
            selected = QFileDialog.getExistingDirectory(self, "Export AVAC time series PNG frames")
            if not selected:
                return
            directory = Path(selected)
            times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
            frames = animation_frames(times, self.animation_every.value())
            previous_range = QgsProject.instance().timeSettings().temporalRange()
            dialog = self._begin_frame_export("Exporting AVAC PNG frames", len(frames), self.results_progress, self.cancel_export_button)
            for index, (band, time_seconds) in enumerate(frames, 1):
                self._set_temporal_band(band)
                self._render_export_png(directory / frame_filename(variable, band, time_seconds), layer, variable, unit, time_seconds)
                if self._frame_export_step(dialog, index): break
            if self._frame_export_cancelled:
                self.results_status.setText("AVAC PNG frame export cancelled.")
                return
            extent = self._export_extent_for(layer)
            provenance = animation_provenance(self._results_manifest["source_run"], variable, frames, 0,
                                              (extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum()), product["range"])
            provenance.pop("frames_per_second", None)
            provenance.update({"format": "AVAC-QGIS time series PNG frames v1", "unit": unit,
                               "frame_step": self.animation_every.value(), "image_width_px": self.export_width.value(),
                               "include_legend": self.export_legend.isChecked(),
                               "include_scale_bar": self.export_scale_bar.isChecked(),
                               "filenames": [frame_filename(variable, band, time) for band, time in frames]})
            (directory / "frames.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
            self.results_progress.setFormat("PNG frames exported")
            self.results_status.setText(f"Exported {len(frames)} AVAC PNG time-series frames to {directory}.")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"PNG frame export failed: {exc}")
            self.log.appendPlainText(str(exc))
        finally:
            if 'dialog' in locals(): self._finish_frame_export(dialog, self.results_progress, self.cancel_export_button)
            if previous_range is not None:
                QgsProject.instance().timeSettings().setTemporalRange(previous_range)

    def _begin_frame_export(self, label: str, total: int, progress_bar: QProgressBar, cancel_button: QPushButton) -> QProgressDialog:
        self._frame_export_cancelled = False
        self._frame_export_active = True
        progress_bar.setRange(0, total); progress_bar.setValue(0); progress_bar.setFormat(label + ": %v / %m")
        cancel_button.setEnabled(True)
        dialog = QProgressDialog(label, "Cancel", 0, total, self)
        dialog.setWindowModality(Qt.WindowModal); dialog.setAutoClose(False); dialog.setAutoReset(False); dialog.show()
        return dialog

    def _frame_export_step(self, dialog: QProgressDialog, value: int) -> bool:
        dialog.setValue(value)
        self.results_progress.setValue(value)
        QgsApplication.processEvents()
        self._frame_export_cancelled = self._frame_export_cancelled or dialog.wasCanceled()
        return self._frame_export_cancelled

    def cancel_frame_export(self) -> None:
        self._frame_export_cancelled = True

    def _finish_frame_export(self, dialog: QProgressDialog, progress_bar: QProgressBar, cancel_button: QPushButton) -> None:
        dialog.close(); dialog.deleteLater(); cancel_button.setEnabled(False); self._frame_export_active = False
        if self._frame_export_cancelled: progress_bar.setFormat("PNG export cancelled")

    def _wave_export_layer(self) -> tuple[QgsRasterLayer, str, str, float | None]:
        if not self._wave_results_manifest or self.wave_run_root is None:
            raise ValueError("Load Wave results before exporting a map.")
        _family, requested_variable = self._selected_temporal_family_variable()
        layer = self._active_wave_temporal_layer(requested_variable) or self._active_wave_temporal_layer()
        if layer is not None:
            variable = str(layer.customProperty("avac/temporal_variable"))[5:]
            times = [float(value) for value in self._wave_results_manifest["simulation_time_seconds"]]
            try:
                band = int(layer.customProperty("avac/frame_player_band", 0) or 0)
            except (TypeError, ValueError):
                band = 0
            band = band or layer.temporalProperties().bandForTemporalRange(layer, QgsProject.instance().timeSettings().temporalRange()) or 1
            return layer, variable, str(self._wave_results_manifest["temporal"][variable]["unit"]), times[min(max(int(band), 1), len(times)) - 1]
        result_dir = self.wave_run_root / WAVE_RESULT_DIRECTORY
        for candidate in QgsProject.instance().mapLayers().values():
            if not isinstance(candidate, QgsRasterLayer): continue
            source = Path(candidate.source().split("|", 1)[0])
            for key, product in self._wave_results_manifest["static"].items():
                if source == result_dir / str(product["path"]): return candidate, key.replace("_", " "), str(product["unit"]), None
        raise ValueError("Load a Wave summary map or time series before exporting.")

    def _set_wave_temporal_band(self, band: int) -> None:
        """Set the WAVE export frame through the direct player renderer."""
        if not self._wave_results_manifest:
            return
        times = [float(value) for value in self._wave_results_manifest["simulation_time_seconds"]]
        if self._frame_player_times.get("wave") == times:
            # As above, exports include all visible time-series layers at one
            # shared physical simulation time.
            self._set_frame_player_frame("wave", band - 1)
            return
        layer = self._active_wave_temporal_layer()
        if layer is not None:
            self._directly_display_temporal_band(layer, band, times)
        ranges = self._temporal_band_ranges(self._temporal_origin(self._wave_results_manifest), times)
        QgsProject.instance().timeSettings().setTemporalRange(ranges[band])

    def export_wave_current_map_png(self) -> None:
        try:
            layer, variable, unit, time_seconds = self._wave_export_layer()
            selected, _ = QFileDialog.getSaveFileName(self, "Export Wave map PNG", f"wave_{variable.replace(' ', '_')}.png", "PNG image (*.png)")
            if selected:
                self._render_export_png(
                    Path(selected).with_suffix(".png"), layer, variable, unit, time_seconds,
                    product_label="Wave", width=self.wave_export_width.value(),
                    extent_mode=str(self.wave_export_extent.currentData()),
                    include_time=self.wave_export_time.isChecked(),
                    include_legend=self.wave_export_legend.isChecked(),
                    include_scale_bar=self.wave_export_scale_bar.isChecked(),
                )
                self.wave_results_status.setText(f"Exported QGIS-rendered Wave map: {selected}")
        except Exception as exc:
            self.wave_results_status.setText(f"Wave PNG export failed: {exc}")

    def export_wave_temporal_frames(self) -> None:
        """Write QGIS-rendered PNG frames for the loaded Wave time-series layer."""
        previous_range = None
        try:
            if not self._wave_results_manifest:
                raise ValueError("Load a Wave time series before exporting PNG frames.")
            _family, variable = self._selected_temporal_family_variable()
            layer = self._active_wave_temporal_layer(variable)
            if layer is None:
                raise ValueError(f"Load the WAVE {self.wave_results_variable.currentText()} time series before exporting PNG frames.")
            product = self._wave_results_manifest["temporal"].get(variable)
            if not product: raise ValueError("The loaded Wave time series is not available for export.")
            selected = QFileDialog.getExistingDirectory(self, "Export Wave PNG frames")
            if not selected: return
            directory, times = Path(selected), [float(value) for value in self._wave_results_manifest["simulation_time_seconds"]]
            frames = animation_frames(times, self.wave_export_every.value())
            previous_range = QgsProject.instance().timeSettings().temporalRange()
            dialog = self._begin_frame_export("Exporting Wave PNG frames", len(frames), self.wave_results_progress, self.wave_cancel_export_button)
            filenames = []
            for index, (band, time_seconds) in enumerate(frames, 1):
                self._set_wave_temporal_band(band)
                filename = frame_filename(f"wave_{variable}", band, time_seconds); filenames.append(filename)
                self._render_export_png(
                    directory / filename, layer, variable, str(product["unit"]), time_seconds,
                    product_label="Wave", width=self.wave_export_width.value(),
                    extent_mode=str(self.wave_export_extent.currentData()),
                    include_time=self.wave_export_time.isChecked(),
                    include_legend=self.wave_export_legend.isChecked(),
                    include_scale_bar=self.wave_export_scale_bar.isChecked(),
                )
                if self._frame_export_step(dialog, index): break
            if self._frame_export_cancelled:
                self.wave_results_status.setText("Wave PNG frame export cancelled.")
                return
            (directory / "wave_frames.json").write_text(json.dumps({
                "format": "AVAC4QGIS Wave PNG frames v1", "variable": variable, "unit": product["unit"],
                "simulation_time_seconds": [time for _band, time in frames],
                "frame_step": self.wave_export_every.value(), "image_width_px": self.wave_export_width.value(),
                "include_legend": self.wave_export_legend.isChecked(),
                "include_scale_bar": self.wave_export_scale_bar.isChecked(),
                "filenames": filenames,
            }, indent=2) + "\n", encoding="utf-8")
            self.wave_results_status.setText(f"Exported {len(frames)} Wave PNG frames to {directory}.")
        except Exception as exc:
            self.wave_results_status.setText(f"Wave PNG export failed: {exc}")
        finally:
            if 'dialog' in locals(): self._finish_frame_export(dialog, self.wave_results_progress, self.wave_cancel_export_button)
            if previous_range is not None: QgsProject.instance().timeSettings().setTemporalRange(previous_range)

    def export_temporal_animation(self) -> None:
        try:
            _family, variable = self._selected_temporal_family_variable()
            layer, _name, unit, _time, product = self._export_layer(variable)
            ffmpeg = locate_ffmpeg(self.ffmpeg_executable.text().strip())
            if ffmpeg is None:
                raise ValueError("ffmpeg was not found. Select an external ffmpeg executable; PNG export remains available.")
            times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
            self._animation_frames = animation_frames(times, self.animation_every.value())
            selected, _ = QFileDialog.getSaveFileName(self, "Export AVAC temporal animation", f"avac_{variable}_animation.mp4", "MP4 video (*.mp4)")
            if not selected:
                return
            self._animation_output = Path(selected).with_suffix(".mp4")
            self._animation_temp_dir = Path(tempfile.mkdtemp(prefix="avac_qgis_animation_"))
            self._animation_previous_range = QgsProject.instance().timeSettings().temporalRange()
            self._animation_index = 0
            extent = self._export_extent_for(layer)
            self._animation_metadata = animation_provenance(
                self._results_manifest["source_run"], variable, self._animation_frames, self.animation_fps.value(),
                (extent.xMinimum(), extent.xMaximum(), extent.yMinimum(), extent.yMaximum()), product["range"],
            )
            self._animation_metadata["unit"] = unit
            self._animation_metadata["frame_step"] = self.animation_every.value()
            self.ffmpeg_executable.setText(str(ffmpeg))
            QSettings().setValue(self.SETTINGS_FFMPEG, str(ffmpeg))
            self.export_animation_button.setEnabled(False); self.cancel_export_button.setEnabled(True)
            self.status.setText(f"Rendering animation frame 1 / {len(self._animation_frames)}…")
            QTimer.singleShot(0, self._render_next_animation_frame)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Animation export failed: {exc}")
            self.log.appendPlainText(str(exc))

    def _render_next_animation_frame(self) -> None:
        if self._animation_temp_dir is None or self._animation_output is None:
            return
        try:
            if self._animation_index >= len(self._animation_frames):
                self._encode_animation()
                return
            band, time_seconds = self._animation_frames[self._animation_index]
            _family, variable = self._selected_temporal_family_variable()
            layer, _name, unit, _unused_time, _product = self._export_layer(variable)
            self._set_temporal_band(band)
            frame = self._animation_temp_dir / f"frame_{self._animation_index + 1:05d}.png"
            self._render_export_png(frame, layer, variable, unit, time_seconds)
            self._animation_index += 1
            self.progress.setRange(0, len(self._animation_frames)); self.progress.setValue(self._animation_index)
            self.progress.setFormat(f"Rendering animation: %v / %m")
            self.status.setText(f"Rendering animation frame {self._animation_index} / {len(self._animation_frames)} (simulation time {format_simulation_seconds(time_seconds)})…")
            QTimer.singleShot(0, self._render_next_animation_frame)
        except Exception as exc:  # noqa: BLE001
            self._finish_animation(False, f"Animation rendering failed: {exc}")

    def _encode_animation(self) -> None:
        assert self._animation_temp_dir is not None and self._animation_output is not None
        ffmpeg = locate_ffmpeg(self.ffmpeg_executable.text().strip())
        if ffmpeg is None:
            self._finish_animation(False, "ffmpeg disappeared before encoding.")
            return
        self.status.setText("Encoding AVAC animation with ffmpeg…")
        self.progress.setFormat("Encoding animation")
        self._animation_process.setWorkingDirectory(str(self._animation_temp_dir))
        # H.264/yuv420p requires even dimensions; QGIS layout page pixels may be odd.
        self._animation_process.start(str(ffmpeg), ["-y", "-framerate", str(self.animation_fps.value()), "-start_number", "1", "-i", "frame_%05d.png", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self._animation_output)])

    def _append_animation_process_output(self) -> None:
        text = bytes(self._animation_process.readAllStandardOutput()).decode(errors="replace")
        text += bytes(self._animation_process.readAllStandardError()).decode(errors="replace")
        if text:
            self.log.appendPlainText(text.rstrip())

    def _on_animation_encoded(self, exit_code: int, normal_exit: bool) -> None:
        self._append_animation_process_output()
        # PyQt exposes NormalExit as enum value 0 on some QGIS builds; do not
        # treat its boolean value as a failure when ffmpeg returned zero.
        if exit_code == 0 and self._animation_output and self._animation_output.is_file():
            sidecar = self._animation_output.with_suffix(".json")
            sidecar.write_text(json.dumps(self._animation_metadata, indent=2) + "\n", encoding="utf-8")
            self._finish_animation(True, f"Exported AVAC animation: {self._animation_output}")
        else:
            self._finish_animation(False, f"ffmpeg failed (exit code {exit_code}).")

    def cancel_export(self) -> None:
        if self._frame_export_active:
            self.cancel_frame_export()
            return
        if self._animation_process.state() != QProcess.ProcessState.NotRunning:
            self._animation_process.kill()
        self._finish_animation(False, "Animation export cancelled.")

    def _finish_animation(self, success: bool, message: str) -> None:
        if self._animation_previous_range is not None:
            QgsProject.instance().timeSettings().setTemporalRange(self._animation_previous_range)
        if self._animation_temp_dir is not None:
            shutil.rmtree(self._animation_temp_dir, ignore_errors=True)
        self._animation_temp_dir = None; self._animation_output = None; self._animation_frames = []
        self.export_animation_button.setEnabled(True); self.cancel_export_button.setEnabled(False)
        self.progress.setRange(0, 1); self.progress.setValue(1 if success else 0); self.progress.setFormat("Exported" if success else "Export failed/cancelled")
        self.status.setText(message)

    def _selected_profile_layer(self):
        layer_id = self.profile_line_layer.currentData()
        return QgsProject.instance().mapLayer(str(layer_id)) if layer_id else None

    def refresh_profile_layers(self) -> None:
        """List ordinary project LineString/MultiLineString layers."""
        if self._shutting_down:
            return
        selected_id = self.profile_line_layer.currentData()
        self.profile_line_layer.blockSignals(True)
        self.profile_line_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if hasattr(layer, "geometryType") and layer.isValid() and layer.geometryType() == QgsWkbTypes.LineGeometry:
                self.profile_line_layer.addItem(layer.name(), layer.id())
        index = self.profile_line_layer.findData(selected_id)
        if index < 0 and self.profile_line_layer.count() == 1:
            index = 0
        self.profile_line_layer.setCurrentIndex(index)
        self.profile_line_layer.blockSignals(False)
        self._connect_profile_selection_signal()
        self._refresh_profile_features()

    def _on_project_layers_changed(self, *_args) -> None:
        """Refresh profile choices while this dock remains live."""
        if not self._shutting_down:
            self.refresh_profile_layers()

    def _connect_profile_selection_signal(self) -> None:
        layer = self._selected_profile_layer()
        if layer is self._profile_selection_layer:
            return
        if self._profile_selection_layer is not None:
            try:
                self._profile_selection_layer.selectionChanged.disconnect(self._profile_selection_callback)
            except (TypeError, RuntimeError):
                pass
        self._profile_selection_layer = layer
        self._profile_selection_callback = None
        if layer is not None:
            self._profile_selection_callback = lambda *_args: self._refresh_profile_features()
            layer.selectionChanged.connect(self._profile_selection_callback)

    @staticmethod
    def _usable_line_features(layer):
        """Return valid line *features*, independent of QGIS selection state."""
        if layer is None or not layer.isValid() or layer.geometryType() != QgsWkbTypes.LineGeometry:
            return []
        return [feature for feature in layer.getFeatures()
                if not feature.geometry().isNull() and not feature.geometry().isEmpty()
                and feature.geometry().type() == QgsWkbTypes.LineGeometry]

    @staticmethod
    def _feature_label(feature) -> str:
        label = f"Feature {feature.id()}"
        for field in feature.fields():
            value = feature[field.name()]
            if value not in (None, ""):
                return f"{label} — {value}"
        return label

    def _refresh_profile_features(self, layer=None) -> None:
        """Resolve a sole feature automatically; otherwise reflect selection."""
        layer = layer or self._selected_profile_layer()
        self._connect_profile_selection_signal()
        self.profile_feature.clear()
        if layer is None or not layer.isValid() or layer.geometryType() != QgsWkbTypes.LineGeometry:
            self.profile_feature.addItem("Select a QGIS line layer", None)
            self.profile_status.setText("Select a Profile layer containing a line feature.")
            return
        features = self._usable_line_features(layer)
        count = len(features)
        if count == 0:
            self.profile_feature.addItem("No usable line features", None)
            self.profile_status.setText(f'Profile layer: {layer.name()}\nNo usable line features were found.')
            return
        if count == 1:
            feature = features[0]
            self.profile_feature.addItem(self._feature_label(feature) + " — automatic", int(feature.id()))
            self.profile_status.setText(f"Profile layer: {layer.name()}\n1 line feature — will be used automatically.")
            return
        usable_ids = {feature.id() for feature in features}
        selected = [feature for feature in layer.selectedFeatures() if feature.id() in usable_ids]
        if len(selected) == 1:
            feature = selected[0]
            self.profile_feature.addItem(self._feature_label(feature), int(feature.id()))
            self.profile_status.setText(f"Profile layer: {layer.name()}\n{count} line features — selected {self._feature_label(feature)}.")
        elif len(selected) == 0:
            self.profile_feature.addItem("Select one feature in QGIS", None)
            self.profile_status.setText(f'Profile layer: {layer.name()}\n{count} line features — select one feature in QGIS.')
        else:
            self.profile_feature.addItem("Select only one feature in QGIS", None)
            self.profile_status.setText(f'Select only one feature in "{layer.name()}" before extracting a profile.')

    def _update_profile_sampling_state(self, _index: int) -> None:
        self.profile_spacing.setEnabled(self.profile_sampling.currentData() == "spacing")

    def _active_avac_temporal_layer(self, variable: str | None = None):
        return next(
            (layer for layer in QgsProject.instance().mapLayers().values()
             if isinstance(layer, QgsRasterLayer)
             and layer.customProperty("avac/temporal_variable")
             and str(layer.customProperty("avac/result_family", "avac")) == "avac"
             and not str(layer.customProperty("avac/temporal_variable")).startswith("wave_")
             and (variable is None or str(layer.customProperty("avac/temporal_variable")) == variable)),
            None,
        )

    def _active_avac_lake_depth_layer(self):
        """Return the selected-scenario AVAC depth product with lake cells zeroed."""
        root = str(self.wave_run_root.resolve()) if self.wave_run_root is not None else ""
        return next(
            (layer for layer in QgsProject.instance().mapLayers().values()
             if isinstance(layer, QgsRasterLayer)
             and str(layer.customProperty("avac/result_family", "")) == "avac_lake"
             and str(layer.customProperty("avac/temporal_variable", "")) == "lake_depth"
             and (not root or str(Path(str(layer.customProperty("avac/wave_root", ""))).resolve()) == root)),
            None,
        )

    def _update_profile_mode_controls(self, _index: int | None = None) -> None:
        """Show the series-export controls only for an explicit profile history."""
        is_time_series = self.profile_source.currentData() == "time_series"
        self.wave_profile_series_container.setVisible(is_time_series)
        if is_time_series:
            self.profile_status.setText(
                "Select a line and variable, then export one CSV or PNG profile for every simulation frame. "
                "Extract / Plot Profile previews the selected frame."
            )

    def _profile_mode(self) -> str:
        """Return the explicit temporal interpretation selected for a profile."""
        mode = str(self.profile_source.currentData() or "frame")
        return mode if mode in {"frame", "time_series", "maximum"} else "frame"

    @staticmethod
    def _raster_band_axes(path: Path, band_number: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Read a materialized AVAC GeoTIFF band as south-to-north axes/array."""
        from osgeo import gdal
        dataset = gdal.Open(str(path))
        if dataset is None or band_number < 1 or band_number > dataset.RasterCount:
            raise ValueError(f"Cannot read AVAC result band {band_number}: {path}")
        band = dataset.GetRasterBand(band_number)
        values = np.asarray(band.ReadAsArray(), dtype=float)
        nodata = band.GetNoDataValue()
        if nodata is not None:
            values[np.isclose(values, float(nodata))] = np.nan
        transform = dataset.GetGeoTransform()
        x = transform[0] + (np.arange(dataset.RasterXSize) + 0.5) * transform[1]
        y = transform[3] + (np.arange(dataset.RasterYSize) + 0.5) * transform[5]
        dataset = None
        if y[0] > y[-1]:
            y, values = y[::-1], np.flipud(values)
        if x[0] > x[-1]:
            x, values = x[::-1], np.fliplr(values)
        return x, y, values

    def _profile_geometry_in_result_crs(self, result_crs: QgsCoordinateReferenceSystem) -> tuple[np.ndarray, str]:
        layer = self._selected_profile_layer()
        self._refresh_profile_features(layer)
        feature_id = self.profile_feature.currentData()
        if layer is None or feature_id is None:
            layer_name = layer.name() if layer is not None else "the selected Profile layer"
            features = self._usable_line_features(layer)
            selected = [feature for feature in (layer.selectedFeatures() if layer is not None else [])
                        if feature.id() in {item.id() for item in features}]
            if len(features) > 1 and not selected:
                raise ValueError(f'The layer "{layer_name}" contains {len(features)} line features. Select one feature in QGIS before extracting the profile.')
            if len(features) > 1 and len(selected) > 1:
                raise ValueError(f'Select only one feature in "{layer_name}" before extracting the profile.')
            raise ValueError(f'Select a usable line feature in "{layer_name}" before extracting a profile.')
        if not layer.crs().isValid() or not result_crs.isValid():
            raise ValueError("Both the profile layer and AVAC result require valid CRS definitions.")
        feature = layer.getFeature(int(feature_id))
        geometry = feature.geometry()
        if geometry.isNull() or geometry.isEmpty() or geometry.type() != QgsWkbTypes.LineGeometry:
            raise ValueError("The selected feature is not a valid line geometry.")
        geometry = QgsGeometry(geometry)
        if layer.crs() != result_crs:
            transform = QgsCoordinateTransform(layer.crs(), result_crs, QgsProject.instance())
            if geometry.transform(transform) != 0:
                raise ValueError("QGIS could not transform the selected profile into the AVAC result CRS.")
        if geometry.isMultipart():
            geometry = geometry.mergeLines()
            if geometry.isMultipart():
                raise ValueError("Selected MultiLineString is disconnected; select one connected line profile.")
        points = geometry.asPolyline()
        if len(points) < 2:
            raise ValueError("The selected profile has fewer than two line vertices.")
        return np.array([(point.x(), point.y()) for point in points], dtype=float), self.profile_feature.currentText()

    def _profile_temporal_product(self) -> tuple[str, str, Path, int, float, dict, QgsRasterLayer, list[float]]:
        """Resolve one loaded result series for a profile without using a static surrogate."""
        family, variable = self._split_result_variable(self.profile_variable.currentData())
        if family == "wave":
            if not self._wave_results_manifest or self.wave_run_root is None:
                raise ValueError("WAVE results are not available.")
            layer = self._active_wave_temporal_layer(variable)
            product = self._wave_results_manifest["temporal"].get(variable)
            if layer is None or not isinstance(product, dict):
                raise ValueError(f"WAVE {variable.replace('_', ' ')} time series is not loaded.")
            times = [float(value) for value in self._wave_results_manifest["simulation_time_seconds"]]
            try:
                band = int(layer.customProperty("avac/frame_player_band", 0) or 0)
            except (TypeError, ValueError):
                band = 0
            band = band or layer.temporalProperties().bandForTemporalRange(layer, QgsProject.instance().timeSettings().temporalRange()) or 1
            band = min(max(int(band), 1), len(times))
            return family, variable, self.wave_run_root / WAVE_RESULT_DIRECTORY / str(product["path"]), band, times[band - 1], product, layer, times
        if family == "avac_lake":
            if not self._avac_lake_depth_manifest or self.wave_run_root is None:
                raise ValueError(f"{WAVE_SNOW_DEPTH_LABEL} is not available.")
            layer = self._active_avac_lake_depth_layer()
            product = self._avac_lake_depth_manifest.get("temporal", {}).get("depth")
            if layer is None or not isinstance(product, dict):
                raise ValueError(f"{WAVE_SNOW_DEPTH_LABEL} time series is not loaded.")
            times = [float(value) for value in self._avac_lake_depth_manifest["simulation_time_seconds"]]
            try:
                band = int(layer.customProperty("avac/frame_player_band", 0) or 0)
            except (TypeError, ValueError):
                band = 0
            band = band or layer.temporalProperties().bandForTemporalRange(layer, QgsProject.instance().timeSettings().temporalRange()) or 1
            band = min(max(int(band), 1), len(times))
            return family, variable, self.wave_run_root / WAVE_RESULT_DIRECTORY / str(product["path"]), band, times[band - 1], product, layer, times
        if not self._results_manifest:
            raise ValueError("AVAC results are not available.")
        layer = self._active_avac_temporal_layer(variable)
        if layer is None:
            raise ValueError(f"AVAC {variable.replace('_', ' ')} time series is not loaded.")
        grid = int(layer.customProperty("avac/fgout_grid", 1))
        product = self._results_manifest["temporal"].get(f"fgout{grid:04d}_{variable}")
        if not isinstance(product, dict):
            raise ValueError(f"AVAC {variable.replace('_', ' ')} is not cached.")
        band, time_seconds, _unused = self._temporal_band_and_time(variable)
        times = [float(value) for value in self._results_manifest["simulation_time_seconds"]]
        return family, variable, Path(self._results_manifest["source_run"]) / RESULT_DIRECTORY / str(product["path"]), band, time_seconds, product, layer, times

    def _profile_coordinates(self, result_layer: QgsRasterLayer) -> tuple[np.ndarray, str, float | None]:
        result_crs = result_layer.crs()
        if QgsUnitTypes.toAbbreviatedString(result_crs.mapUnits()).lower() not in {"m", "metres", "meters"}:
            raise ValueError("The result CRS is not metric; profile distance cannot be labelled meters.")
        coords, profile_name = self._profile_geometry_in_result_crs(result_crs)
        spacing = self.profile_spacing.value() if self.profile_sampling.currentData() == "spacing" else None
        return coords, profile_name, spacing

    def _historical_maximum_profile(
        self,
        coords: np.ndarray,
        path: Path,
        last_band: int,
        variable: str,
        profile_name: str,
        spacing: float | None,
        time_seconds: float,
    ) -> ProfileDataset:
        """Sample the maximum of each profile point through the selected frame."""
        x, y, values = self._raster_band_axes(path, 1)
        first = extract_profile(coords, x, y, values, variable, "historical maximum", spacing=spacing, profile_name=profile_name)
        maximum = np.asarray(first.values, dtype=float)
        for band in range(2, last_band + 1):
            bx, by, values = self._raster_band_axes(path, band)
            samples = bilinear_sample(bx, by, values, first.x, first.y)
            maximum = np.fmax(maximum, samples)
        return ProfileDataset(
            first.distance_m, first.x, first.y, maximum, variable,
            "historical maximum through selected frame", time_seconds, profile_name,
        )

    def _build_profile_dataset(self) -> tuple[str, str, ProfileDataset, np.ndarray, int, float]:
        """Create the selected-frame or cumulative-maximum profile dataset."""
        family, variable, path, band, time_seconds, _product, layer, _times = self._profile_temporal_product()
        coords, profile_name, spacing = self._profile_coordinates(layer)
        if self._profile_mode() == "maximum":
            dataset = self._historical_maximum_profile(coords, path, band, variable, profile_name, spacing, time_seconds)
        else:
            x, y, values = self._raster_band_axes(path, band)
            source = "selected frame" if self._profile_mode() == "frame" else "time-series selected-frame preview"
            dataset = extract_profile(
                coords, x, y, values, variable, source, spacing=spacing,
                simulation_time_s=time_seconds, profile_name=profile_name,
            )
        return family, variable, dataset, coords, band, time_seconds

    def extract_profile(self) -> None:
        """Extract an AVAC-family profile after its selected series is available."""
        try:
            family, variable, dataset, _coords, _band, time_seconds = self._build_profile_dataset()
            if family == "wave":
                self.plot_wave_profile()
                return
            self._last_profile = dataset
            self.export_profile_button.setEnabled(True)
            outside = int(np.count_nonzero(~np.isfinite(dataset.values)))
            actual = f" through {format_simulation_seconds(time_seconds)}" if self._profile_mode() == "maximum" else f" at {format_simulation_seconds(time_seconds)}"
            self.status.setText(
                f"Profile extracted: {dataset.values.size} samples, {dataset.distance_m[-1]:g} m{actual}; "
                f"{outside} outside/NoData sample(s)."
            )
            self.profile_status.setText(self.status.text())
            cross_section = self._avac_profile_cross_section(family, variable, dataset)
            if cross_section is None:
                dialog = ProfilePlotDialog(dataset, self)
            else:
                distance, ground, surface = cross_section
                title = f"AVAC {variable.replace('_', ' ').title()} Profile — {dataset.profile_name}"
                if self._profile_mode() == "maximum":
                    title += f" through {format_simulation_seconds(time_seconds)}"
                else:
                    title += f" at {format_simulation_seconds(time_seconds)}"
                dialog = WaveCrossSectionDialog(distance, ground, surface, title, self)
            dialog.setAttribute(Qt.WA_DeleteOnClose)
            dialog.show()
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Profile extraction failed: {exc}")
            self.profile_status.setText(self.status.text())
            self.log.appendPlainText(str(exc))

    def extract_selected_profile(self) -> None:
        value = self.profile_variable.currentData()
        if not self._ensure_temporal_result_loaded(value, self.extract_selected_profile):
            return
        family, _variable = self._split_result_variable(value)
        if family == "wave":
            self.plot_wave_profile()
            self.export_profile_button.setEnabled(self._last_wave_profile is not None)
        else:
            self.extract_profile()

    def export_selected_profile_csv(self) -> None:
        value = self.profile_variable.currentData()
        if not self._ensure_temporal_result_loaded(value, self.export_selected_profile_csv):
            return
        try:
            family, variable, dataset, _coords, _band, _time = self._build_profile_dataset()
            if family == "wave":
                self._last_wave_profile = dataset
            else:
                self._last_profile = dataset
            selected, _ = QFileDialog.getSaveFileName(
                self, "Export profile CSV", f"{family}_{variable}_profile.csv", "CSV (*.csv)",
            )
            if not selected:
                return
            path = write_profile_csv(selected, dataset)
            self.results_status.setText(f"Exported profile CSV: {path}")
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Profile CSV export failed: {exc}")
            self.log.appendPlainText(str(exc))

    def export_profile_time_series(self) -> None:
        """Export one profile sample set for every AVAC or WAVE output frame."""
        value = self.profile_variable.currentData()
        if not self._ensure_temporal_result_loaded(value, self.export_profile_time_series):
            return
        progress = None
        try:
            family, variable, path, _band, _time, product, layer, times = self._profile_temporal_product()
            coords, profile_name, spacing = self._profile_coordinates(layer)
            x, y, first_values = self._raster_band_axes(path, 1)
            positions = extract_profile(coords, x, y, first_values, variable, "time series", spacing=spacing, profile_name=profile_name)
            export_format = str(self.wave_profile_series_format.currentData())
            if export_format == "csv":
                selected, _ = QFileDialog.getSaveFileName(
                    self, "Export profile time series CSV", f"{family}_{variable}_profile_time_series.csv", "CSV (*.csv)",
                )
                if not selected:
                    return
                column = f"{variable}_{str(product.get('unit', ''))}".strip("_").replace("³", "3").replace("/", "_per_")
                with Path(selected).with_suffix(".csv").open("w", encoding="utf-8") as handle:
                    handle.write(f"simulation_time_s,distance_m,x,y,{column}\n")
                    for band, time_seconds in enumerate(times, 1):
                        bx, by, values = self._raster_band_axes(path, band)
                        samples = bilinear_sample(bx, by, values, positions.x, positions.y)
                        handle.writelines(
                            f"{time_seconds:.12g},{distance:.12g},{px:.12g},{py:.12g},{sample:.12g}\n"
                            for distance, px, py, sample in zip(positions.distance_m, positions.x, positions.y, samples)
                        )
                self.results_status.setText(f"Exported {len(times)} profile frames to {Path(selected).with_suffix('.csv')}.")
                return
            selected = QFileDialog.getExistingDirectory(self, "Export profile PNG frames")
            if not selected:
                return
            directory = Path(selected)
            progress_bar, cancel_button = (
                (self.wave_results_progress, self.wave_cancel_export_button) if family == "wave"
                else (self.results_progress, self.cancel_export_button)
            )
            width = self.wave_export_width.value() if family == "wave" else self.export_width.value()
            progress = self._begin_frame_export("Exporting profile PNG frames", len(times), progress_bar, cancel_button)
            for index, time_seconds in enumerate(times, 1):
                bx, by, values = self._raster_band_axes(path, index)
                samples = bilinear_sample(bx, by, values, positions.x, positions.y)
                frame = ProfileDataset(
                    positions.distance_m, positions.x, positions.y, samples, variable,
                    "time-series frame", time_seconds, profile_name,
                )
                if family == "wave":
                    distance, ground, surface = self._wave_cross_section(coords, index)
                    write_wave_cross_section_png(
                        directory / f"wave_{variable}_profile_{index:04d}.png", distance, ground, surface,
                        f"WAVE {variable.replace('_', ' ').title()} Profile — {profile_name} at {format_simulation_seconds(time_seconds)}", width,
                    )
                else:
                    cross_section = self._avac_profile_cross_section(family, variable, frame)
                    if cross_section is None:
                        write_profile_png(directory / f"{family}_{variable}_profile_{index:04d}.png", frame, width)
                    else:
                        distance, ground, surface = cross_section
                        write_wave_cross_section_png(
                            directory / f"{family}_{variable}_profile_{index:04d}.png", distance, ground, surface,
                            f"AVAC {variable.replace('_', ' ').title()} Profile — {profile_name} at {format_simulation_seconds(time_seconds)}", width,
                        )
                if self._frame_export_step(progress, index):
                    break
            self.results_status.setText(
                "Profile PNG export cancelled." if self._frame_export_cancelled
                else f"Exported {len(times)} profile PNG frames to {directory}."
            )
        except Exception as exc:  # noqa: BLE001
            self.results_status.setText(f"Profile time-series export failed: {exc}")
            self.log.appendPlainText(str(exc))
        finally:
            if progress is not None:
                progress_bar, cancel_button = (
                    (self.wave_results_progress, self.wave_cancel_export_button) if self._split_result_variable(value)[0] == "wave"
                    else (self.results_progress, self.cancel_export_button)
                )
                self._finish_frame_export(progress, progress_bar, cancel_button)

    def shutdown(self) -> None:
        """Called by plugin unload; avoids retaining an active QProcess."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._finish_wave_lake_polygon_capture()
        self._frame_player_timer.stop()
        project = QgsProject.instance()
        for signal in (project.layersAdded, project.layersRemoved):
            try:
                signal.disconnect(self._on_project_layers_changed)
            except (TypeError, RuntimeError):
                pass
        if self._profile_selection_layer is not None and self._profile_selection_callback is not None:
            try:
                self._profile_selection_layer.selectionChanged.disconnect(self._profile_selection_callback)
            except (TypeError, RuntimeError):
                pass
        self._profile_selection_layer = None
        self._profile_selection_callback = None
        if self._animation_temp_dir is not None:
            self.cancel_export()
        if self.runner.is_running:
            self.runner.stop()
        if self.wave_process.state() != QProcess.ProcessState.NotRunning:
            self.stop_wave_simulation()
