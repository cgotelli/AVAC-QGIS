"""POSIX process-group isolation regression for safe AVAC cancellation."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


launcher = Path(__file__).parents[1] / "core" / "session_exec.py"
process = subprocess.Popen([sys.executable, str(launcher), "sleep 30 & wait"])
try:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and os.getpgid(process.pid) != process.pid:
        time.sleep(.02)
    assert os.getpgid(process.pid) == process.pid, (process.pid, os.getpgid(process.pid))
    tree = subprocess.check_output(["/bin/ps", "-o", "pid=,ppid=,pgid=", "-g", str(process.pid)], text=True)
    assert str(process.pid) in tree
    os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=3)
    assert process.returncode != 0
finally:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
print("POSIX isolated process-group TERM lifecycle: PASS")
