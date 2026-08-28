"""Generate the UI screenshots embedded in the AVAC4QGIS reference guide.

Run with the Python environment shipped by QGIS.  On macOS the repository
release process uses::

    PYTHONHOME=/Applications/QGIS.app/Contents/Frameworks \
    QT_QPA_PLATFORM=offscreen \
    PYTHONPATH="$(pwd):/Applications/QGIS.app/Contents/Resources/python" \
    /Applications/QGIS.app/Contents/MacOS/python3.12 \
    docs/generate_ui_screenshots.py

The screenshots intentionally use empty selectors: they document controls,
not a private user case or a machine-specific path.
"""

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication

from avac_qgis.gui.dock import AvacDockWidget


OUTPUT = Path(__file__).resolve().parent / "images"


def _capture(widget, name: str) -> None:
    QgsApplication.processEvents()
    image = widget.grab()
    path = OUTPUT / name
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write UI screenshot: {path}")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    application = QgsApplication([], False)
    application.initQgis()
    dock = AvacDockWidget()
    try:
        # A documentation-width dock keeps long status labels and every normal
        # control visible without a horizontal scroll bar.  LaTeX scales the
        # resulting image to the A4 text width.
        dock.resize(1180, 900)
        dock.show()
        QgsApplication.processEvents()
        _capture(dock, "ui_overview.png")

        dock.workflow_tabs.setCurrentWidget(dock.inputs_scroll)
        for index, name in enumerate((
            "ui_avac_parameters_inputs.png",
            "ui_avac_parameters_release.png",
            "ui_avac_parameters_rheology.png",
            "ui_avac_parameters_numerical.png",
        )):
            dock.parameter_toolbox.setCurrentIndex(index)
            _capture(dock.workflow_tabs, name)

        dock.workflow_tabs.setCurrentWidget(dock.run_scroll)
        _capture(dock.workflow_tabs, "ui_avac_run.png")

        dock.wave_extension_toggle.setChecked(True)
        dock.workflow_tabs.setCurrentWidget(dock.wave_setup_scroll)
        for index, name in enumerate((
            "ui_wave_parameters_source.png",
            "ui_wave_parameters_lake.png",
            "ui_wave_parameters_model.png",
        )):
            dock.wave_parameter_toolbox.setCurrentIndex(index)
            _capture(dock.workflow_tabs, name)

        dock.workflow_tabs.setCurrentWidget(dock.wave_run_scroll)
        _capture(dock.workflow_tabs, "ui_wave_run.png")

        dock.workflow_tabs.setCurrentWidget(dock.results_scroll)
        for index, name in enumerate((
            "ui_results_runs.png",
            "ui_results_summary.png",
            "ui_results_time_series.png",
            "ui_results_profile.png",
            "ui_results_gauges.png",
            "ui_results_lake_volume.png",
        )):
            dock.results_toolbox.setCurrentIndex(index)
            _capture(dock.workflow_tabs, name)
    finally:
        dock.shutdown()
        dock.close()
        dock.deleteLater()
        application.exitQgis()


if __name__ == "__main__":
    main()
