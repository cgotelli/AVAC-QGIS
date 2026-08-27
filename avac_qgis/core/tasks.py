"""QGIS background tasks for CPU/I/O-heavy AVAC preparation."""

from __future__ import annotations

from qgis.core import QgsTask
from pathlib import Path
import traceback

from .preprocessing import PreparationCancelled
from .run_project import prepare_isolated_run, prepare_isolated_runtime_run
from .results import discover_results, materialize_results
from .avac_lake_depth import materialize_avac_lake_depth
from .wave_results import discover_wave_results, materialize_wave_diagnostics, materialize_wave_results
from .preprocessing import initial_depth_from_release, release_mask_from_rings


class PrepareAvacRunTask(QgsTask):
    """Materialize solver and science inputs without blocking the QGIS UI."""

    def __init__(self, run_root, backend, raster, rings, template, release, metadata, controlled_values=None, fine_raster=None, *, bundled_runtime=False) -> None:
        super().__init__("Prepare AVAC run", QgsTask.Flag.CanCancel)
        self._args = (run_root, backend, raster, rings, template, release, metadata, controlled_values, fine_raster)
        self.prepared = None
        self.error: Exception | None = None
        self.bundled_runtime = bundled_runtime

    def run(self) -> bool:
        try:
            prepare = prepare_isolated_runtime_run if self.bundled_runtime else prepare_isolated_run
            self.prepared = prepare(*self._args, progress=self._progress, cancelled=self.isCanceled)
            return True
        except PreparationCancelled:
            return False
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            return False

    def _progress(self, value: int) -> None:
        if self.isCanceled():
            raise PreparationCancelled("AVAC input preparation cancelled.")
        self.setProgress(value)


class PrepareAvacResultsTask(QgsTask):
    """Convert immutable AVAC output to cached QGIS products off the UI thread."""

    def __init__(self, run_root, temporal_variables: tuple[str, ...] = (), fgout_grid: int = 1) -> None:
        label = "Prepare AVAC temporal " + "/".join(temporal_variables) if temporal_variables else "Prepare AVAC static results"
        super().__init__(label, QgsTask.Flag.CanCancel)
        self.run_root = run_root
        self.temporal_variables = temporal_variables
        self.fgout_grid = fgout_grid
        self.discovery = None
        self.manifest = None
        self.error: Exception | None = None

    def run(self) -> bool:
        try:
            if self.isCanceled():
                return False
            self.setProgress(1)
            self.discovery = discover_results(self.run_root, self.fgout_grid)
            self.manifest = materialize_results(self.discovery, self.temporal_variables, progress=self._progress, cancelled=self.isCanceled)
            return True
        except InterruptedError:
            return False
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            return False

    def _progress(self, value: int) -> None:
        if self.isCanceled():
            raise InterruptedError("AVAC result preparation cancelled.")
        self.setProgress(value)


class PrepareAvacLakeDepthTask(QgsTask):
    """Create the non-destructive WAVE Snow Depth Outside Lake product."""

    def __init__(self, avac_root, wave_root, fgout_grid: int = 1) -> None:
        super().__init__("Prepare WAVE Snow Depth Outside Lake", QgsTask.Flag.CanCancel)
        self.avac_root, self.wave_root, self.fgout_grid = avac_root, wave_root, fgout_grid
        self.discovery = self.manifest = None
        self.error: Exception | None = None

    def run(self) -> bool:
        try:
            self.discovery, self.manifest = materialize_avac_lake_depth(
                self.avac_root, self.wave_root, fgout_grid=self.fgout_grid,
                progress=self._progress, cancelled=self.isCanceled,
            )
            return True
        except InterruptedError:
            return False
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            return False

    def _progress(self, value: int) -> None:
        if self.isCanceled():
            raise InterruptedError("WAVE Snow Depth Outside Lake preparation cancelled.")
        self.setProgress(value)


class PrepareWaveResultsTask(QgsTask):
    """Materialize Wave maps/time series without blocking QGIS."""
    def __init__(self, root, runtime, variable: str) -> None:
        super().__init__("Prepare Wave results", QgsTask.Flag.CanCancel)
        self.root, self.runtime, self.variable = root, runtime, variable
        self.discovery = self.manifest = self.diagnostics = None
        self.error: Exception | None = None

    def run(self) -> bool:
        try:
            self.discovery = discover_wave_results(self.root, self.runtime)
            self.manifest = materialize_wave_results(self.discovery, self.variable)
            self.diagnostics = materialize_wave_diagnostics(self.discovery)
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            try:
                root = Path(self.root) / "qgis_wave_results"
                root.mkdir(exist_ok=True)
                (root / "result_loading_error.log").write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
            return False


class InitialDepthPreviewTask(QgsTask):
    """Compute the exact AVAC initial depth without blocking QGIS."""

    def __init__(self, raster, rings, release) -> None:
        super().__init__("Preview AVAC initial depth", QgsTask.Flag.CanCancel)
        self.raster, self.rings, self.release = raster, rings, release
        self.mask = None
        self.depth = None
        self.error: Exception | None = None

    def run(self) -> bool:
        try:
            if self.isCanceled():
                return False
            self.setProgress(10)
            self.mask = release_mask_from_rings(self.rings, self.raster.x, self.raster.y)
            if self.isCanceled():
                return False
            self.setProgress(55)
            self.depth = initial_depth_from_release(self.raster, self.mask, self.release)
            if self.isCanceled():
                return False
            self.setProgress(100)
            return True
        except Exception as exc:
            self.error = exc
            return False
