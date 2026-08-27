"""Cancel a real short AVAC run and inspect only its owned POSIX group."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from qgis.PyQt.QtCore import QCoreApplication, QTimer

from avac_qgis.core.environment import check_environment
from avac_qgis.core.runner import AvacRunner


ROOT = Path(os.environ["AVAC_QGIS_CANCEL_RUN_ROOT"])
CLAW = Path("/Users/cmgotelli/Downloads/Lac_Clusaz/clawpack-v5.14.0")
PYTHON = Path("/Users/cmgotelli/anaconda3/envs/lac-clusaz-notebooks/bin/python")
runner = AvacRunner()
poller = QTimer()
tree_before = ""


def fail(message: str) -> None:
    print(f"QGIS_CANCEL_FAILURE={message}", flush=True)
    QCoreApplication.quit()


def poll() -> None:
    global tree_before
    pgid = runner.process_group_id or int(runner.process.processId() or 0)
    if not pgid:
        return
    listing = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="], text=True)
    owned = "\n".join(line for line in listing.splitlines() if len(line.split(None, 3)) >= 3 and line.split(None, 3)[2] == str(pgid))
    # Do not match the linker command, which mentions its output name before
    # the solver exists.  Require a live executable whose command starts with
    # this run's own xgeoclaw path.
    solver = str(ROOT / "AVAC" / "xgeoclaw")
    if any(line.split(None, 3)[3].startswith(solver) for line in owned.splitlines() if len(line.split(None, 3)) == 4):
        tree_before = owned
        runner.stop()
        poller.stop()


def finished(code: int, normal: bool) -> None:
    QTimer.singleShot(500, verify)


def verify() -> None:
    pgid = last_pgid
    listing = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="], text=True)
    owned = [line for line in listing.splitlines() if len(line.split(None, 3)) >= 3 and line.split(None, 3)[2] == str(pgid)]
    marker = json.loads((ROOT / ".avac_qgis_run.json").read_text())
    if not tree_before or owned or marker.get("status") != "cancelled":
        fail(f"tree_before={tree_before!r} owned_after={owned!r} status={marker.get('status')}"); return
    print(f"QGIS_CANCEL=True pgid={pgid} tree_before={tree_before.replace(chr(10), ' | ')} status=cancelled owned_after=0", flush=True)
    QCoreApplication.quit()


def start() -> None:
    global last_pgid
    report = check_environment(ROOT / "AVAC", CLAW, PYTHON)
    if not report.ready:
        fail(report.as_text()); return
    runner.started.connect(lambda: globals().__setitem__("last_pgid", int(runner.process.processId())))
    runner.finished.connect(finished)
    runner.start(report, require_prepared_run=True)
    poller.setInterval(250); poller.timeout.connect(poll); poller.start()
    QTimer.singleShot(180000, lambda: fail("timed out before xgeoclaw cancellation"))


QTimer.singleShot(0, start)
