"""Drive the installed AVAC plugin through a normal QGIS profile for a real run.

Run with QGIS's graphical executable and ``--code``.  The target case must be
an isolated copy: the plugin deliberately uses ``make clean`` before running.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.utils import loadPlugin, plugins, startPlugin


CASE = Path(os.environ["AVAC_QGIS_TEST_CASE"])
CLAW = Path(os.environ["AVAC_QGIS_TEST_CLAW"])
PYTHON = Path(os.environ["AVAC_QGIS_TEST_PYTHON"])
progress_samples: list[tuple[int, int]] = []


def fail(message: str) -> None:
    print(f"QGIS_PROFILE_RUN_FAILURE: {message}", flush=True)
    QCoreApplication.quit()


def finish(exit_code: int, normal_exit: bool) -> None:
    print(f"QGIS_AVAC_EXIT_CODE={exit_code}", flush=True)
    print(f"QGIS_AVAC_NORMAL_EXIT={normal_exit}", flush=True)
    print(f"QGIS_PROGRESS_SAMPLES={progress_samples}", flush=True)
    print(f"QGIS_OUTPUT_SUMMARY_BEGIN\n{plugin.dock.log.toPlainText()}\nQGIS_OUTPUT_SUMMARY_END", flush=True)
    QCoreApplication.quit()


def run() -> None:
    # This enables the package in the real default profile.  The following
    # load/start calls are QGIS's normal plugin-manager loading path, not a
    # direct import from the source tree.
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    if "avac_qgis" not in plugins:
        if not loadPlugin("avac_qgis"):
            fail("QGIS could not discover avac_qgis in the default profile")
            return
        startPlugin("avac_qgis")
    global plugin
    plugin = plugins.get("avac_qgis")
    if plugin is None:
        fail("plugin did not initialise through the normal QGIS lifecycle")
        return
    plugin.show_dock()
    if plugin.dock is None:
        fail("plugin did not create its dock after its normal AVAC action was invoked")
        return
    dock = plugin.dock
    dock.avac_dir.setText(str(CASE))
    dock.claw_root.setText(str(CLAW))
    dock.claw_python.setText(str(PYTHON))
    dock.run_environment_check()
    print(f"QGIS_PROFILE_READY={dock.report.ready if dock.report else False}", flush=True)
    print(f"QGIS_PROFILE_ENVIRONMENT=\n{dock.log.toPlainText()}", flush=True)
    if dock.report is None or not dock.report.ready:
        fail("environment check rejected the isolated regression case")
        return
    dock.runner.progress.connect(lambda current, total: progress_samples.append((current, total)))
    dock.runner.finished.connect(finish)
    dock.run_button.click()


QTimer.singleShot(1000, run)
