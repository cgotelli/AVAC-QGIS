"""Asynchronous QProcess wrapper for the existing AVAC Makefile workflow."""

from __future__ import annotations

from pathlib import Path
import os
import signal
import sys

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from .environment import EnvironmentReport
from .run_project import update_run_status, validate_prepared_run
from .runtime_execution import runtime_solver


class AvacRunner(QObject):
    """Run `make clean && make .output` without blocking the QGIS GUI thread."""

    started = pyqtSignal()
    stdout = pyqtSignal(str)
    stderr = pyqtSignal(str)
    finished = pyqtSignal(int, bool)
    progress = pyqtSignal(int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.started.connect(self.started)
        self.process.finished.connect(self._finished)
        self._output_dir: Path | None = None
        self._run_avac_dir: Path | None = None
        self._expected_frames: int | None = None
        self._prepared_run = False
        self._stop_requested = False
        self._process_group_id: int | None = None
        self._direct_runtime = False
        self._termination_timer = QTimer(self)
        self._termination_timer.setSingleShot(True)
        self._termination_timer.timeout.connect(self._escalate_stop)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._emit_progress)

    @property
    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(self, report: EnvironmentReport, *, require_prepared_run: bool = False) -> None:
        if not report.ready:
            raise RuntimeError("AVAC preflight failed; run Environment Check and resolve all failures first.")
        if require_prepared_run:
            validate_prepared_run(report.avac_dir)
            update_run_status(report.avac_dir, "running")
        self._prepared_run = require_prepared_run
        self._stop_requested = False
        environment = QProcessEnvironment()
        for key, value in report.environment.items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(report.avac_dir))
        self._output_dir = report.avac_dir / "_output"
        self._run_avac_dir = report.avac_dir
        self._expected_frames = report.expected_fort_frames
        # session_exec calls os.setsid() and execs the shell, making the
        # QProcess child PID the unique leader of this AVAC run's process group.
        python = report.environment.get("CLAW_PYTHON") or sys.executable
        launcher = Path(__file__).with_name("session_exec.py")
        self.process.setProgram(python)
        self.process.setArguments([str(launcher), "make clean && make .output"])
        self.process.start()
        self._progress_timer.start()

    def start_runtime(self, report: EnvironmentReport, runtime_root: str | Path, *, require_prepared_run: bool = False) -> None:
        """Launch the precompiled solver directly after runtime data staging.

        No Make, compiler, Clawpack checkout or external Python process is
        involved.  The QProcess owns xgeoclaw directly, so cancellation never
        needs a broad process search or a Make process group.
        """
        if require_prepared_run:
            validate_prepared_run(report.avac_dir)
            update_run_status(report.avac_dir, "running")
        output = report.avac_dir / "_output"
        if not output.is_dir() or not any(output.glob("*.data")):
            raise RuntimeError("Bundled runtime data are not staged in _output; prepare runtime execution first.")
        environment = QProcessEnvironment.systemEnvironment()
        for key in ("CLAW", "CLAW_PYTHON", "FC", "PYTHONPATH"):
            environment.remove(key)
        environment.insert("OMP_NUM_THREADS", report.environment.get("OMP_NUM_THREADS", "8"))
        # The managed Windows runtime keeps its DLLs outside the executable
        # directory.  Prepend both locations so the Windows loader can resolve
        # the bundled compiler and numerical-library dependencies without any
        # machine-wide installation.
        runtime_path = Path(runtime_root).expanduser().resolve()
        existing_path = environment.value("PATH")
        runtime_library_path = os.pathsep.join((str(runtime_path / "bin"), str(runtime_path / "lib")))
        environment.insert("PATH", runtime_library_path + (os.pathsep + existing_path if existing_path else ""))
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(output))
        self._output_dir = output
        self._run_avac_dir = report.avac_dir
        self._expected_frames = report.expected_fort_frames
        self._prepared_run = require_prepared_run
        self._stop_requested = False
        self._process_group_id = None
        self._direct_runtime = True
        self.process.setProgram(str(runtime_solver(runtime_root)))
        self.process.setArguments([])
        self.process.start()
        self._progress_timer.start()

    def stop(self) -> None:
        """TERM then KILL only the dedicated POSIX process group for this run."""
        if self.is_running:
            self._stop_requested = True
            if self._direct_runtime:
                self.process.terminate()
                self._termination_timer.start(3000)
                return
            self._process_group_id = int(self.process.processId())
            self._signal_group(signal.SIGTERM)
            # Let make/xgeoclaw close files cleanly; never block the GUI.
            self._termination_timer.start(3000)

    @property
    def process_group_id(self) -> int | None:
        return self._process_group_id

    def _signal_group(self, signum: signal.Signals) -> None:
        if self._process_group_id is None:
            return
        try:
            os.killpg(self._process_group_id, signum)
        except ProcessLookupError:
            pass
        except OSError as exc:
            self.stderr.emit(f"Could not signal AVAC process group {self._process_group_id}: {exc}\n")

    def _escalate_stop(self) -> None:
        if self.is_running and self._stop_requested:
            if self._direct_runtime:
                self.process.kill()
            else:
                self._signal_group(signal.SIGKILL)

    def _read_stdout(self) -> None:
        self.stdout.emit(bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace"))

    def _read_stderr(self) -> None:
        self.stderr.emit(bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace"))

    def _finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._progress_timer.stop()
        self._termination_timer.stop()
        self._emit_progress()
        if self._prepared_run:
            status = "cancelled" if self._stop_requested else ("completed" if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit else "failed")
            try:
                update_run_status(self._run_avac_dir or Path(self.process.workingDirectory()), status, exit_code=exit_code)
            except ValueError as exc:
                self.stderr.emit(f"Could not update prepared-run status: {exc}\n")
            self._prepared_run = False
            self._stop_requested = False
        self._process_group_id = None
        self._direct_runtime = False
        self._run_avac_dir = None
        self.finished.emit(exit_code, exit_status == QProcess.ExitStatus.NormalExit)

    def _emit_progress(self) -> None:
        if self._output_dir is None or self._expected_frames is None:
            return
        written = len(list(self._output_dir.glob("fort.t*"))) if self._output_dir.is_dir() else 0
        self.progress.emit(min(written, self._expected_frames), self._expected_frames)


def output_summary(avac_dir: str | Path) -> str:
    """Inspect raw AVAC output only; no result conversion or QGIS loading."""
    output = Path(avac_dir) / "_output"
    if not output.is_dir():
        return f"Run ended but _output was not found: {output}"
    fort_t = sorted(output.glob("fort.t*"))
    fort_q = sorted(output.glob("fort.q*"))
    fgout_t = sorted(output.glob("fgout0001.t*"))
    fgout_fields = sorted(output.glob("fgout0001.b*")) + sorted(output.glob("fgout0001.a*"))
    fgmax = output / "fgmax0001.txt"
    final_time = "unknown"
    if fort_t:
        try:
            final_time = fort_t[-1].read_text(encoding="utf-8", errors="ignore").splitlines()[0].split()[0]
        except (IndexError, OSError):
            pass
    return "\n".join(
        [
            f"Output directory: {output}",
            f"fort.t frames: {len(fort_t)}", f"fort.q frames: {len(fort_q)}",
            f"fgout0001.t frames: {len(fgout_t)}", f"fgout field files: {len(fgout_fields)}",
            f"fgmax0001.txt: {'present' if fgmax.is_file() else 'missing'}", f"Final fort.t time: {final_time}",
        ]
    )
