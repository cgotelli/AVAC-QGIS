"""Direct execution preparation for isolated Lake-Wave cases."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import yaml

from .clawpack_logging import suppress_pyclaw_file_logging
from .runtime import RuntimeValidationError, validate_runtime
from .wave_boundaries import WaveBoundarySummary, create_boundary_conditions


def validate_wave_runtime_dependencies(runtime_root: str | Path) -> Path:
    """Validate the Python pieces WAVE uses in QGIS's embedded interpreter.

    WAVE's shoreline coupling is intentionally implemented with NumPy only.
    This check therefore proves that a normal QGIS installation can prepare a
    WAVE run without asking the user to install SciPy or any other package.
    """
    runtime_root = Path(runtime_root).resolve()
    manifest = validate_runtime(runtime_root)
    claw_source = runtime_root / str(manifest["clawpack"]["root"])
    if str(claw_source) not in sys.path:
        sys.path.insert(0, str(claw_source))
    try:
        with suppress_pyclaw_file_logging():
            from clawpack.pyclaw.solution import Solution  # noqa: F401
    except ImportError as exc:
        raise RuntimeValidationError(f"Bundled Wave Clawpack reader cannot be imported by QGIS Python: {exc}") from exc
    return claw_source


def prepare_wave_boundary_conditions(runtime_root: str | Path, wave_root: str | Path, source_avac_root: str | Path) -> WaveBoundarySummary:
    """Generate and inspect the AVAC-driven internal Wave inflow once."""
    runtime_root, wave_root, source_avac_root = Path(runtime_root).resolve(), Path(wave_root).resolve(), Path(source_avac_root).resolve()
    manifest = validate_runtime(runtime_root)
    config_path = wave_root / "impulse_configuration.yaml"
    if not config_path.is_file():
        raise RuntimeValidationError(f"Prepared Wave configuration is missing: {config_path}")
    claw_source = validate_wave_runtime_dependencies(runtime_root)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    previous = Path.cwd()
    try:
        os.chdir(wave_root)
        with suppress_pyclaw_file_logging():
            return create_boundary_conditions(source_avac_root, wave_root, claw_source, damping=float(config["computation"]["damping"]))
    finally:
        os.chdir(previous)


def prepare_wave_runtime_execution(runtime_root: str | Path, wave_root: str | Path, source_avac_root: str | Path) -> Path:
    runtime_root, wave_root, source_avac_root = Path(runtime_root).resolve(), Path(wave_root).resolve(), Path(source_avac_root).resolve()
    manifest = validate_runtime(runtime_root)
    # Runtime archive builders use the solver's canonical source directory
    # name (``WAVE``).  Keep this lookup byte-for-byte aligned with the
    # manifest record so installed packages do not depend on a case-insensitive
    # development filesystem.
    backend = runtime_root / "backend" / "WAVE" / "setrun.py"
    wave_dir = wave_root / "Wave"
    required = {
        "bundled Wave backend (backend/WAVE/setrun.py)": backend,
        "prepared Wave configuration (impulse_configuration.yaml)": wave_root / "impulse_configuration.yaml",
        "prepared lake topography (Topo/topography_lake.asc)": wave_root / "Topo" / "topography_lake.asc",
        "prepared force-dry lake mask (Topo/mask.asc)": wave_root / "Topo" / "mask.asc",
        "prepared shoreline faces (CL/shoreline_faces.txt)": wave_root / "CL" / "shoreline_faces.txt",
    }
    missing = [f"{label}: {path}" for label, path in required.items() if not path.is_file()]
    if missing:
        raise RuntimeValidationError("Wave execution preparation is incomplete. Missing " + "; ".join(missing))
    claw_source = runtime_root / str(manifest["clawpack"]["root"])
    # Regenerate coupling data when it is absent, was prepared from a
    # different completed AVAC run, or still uses the legacy base-cell source
    # convention.  Format 1 remains readable for compatibility, but it is not
    # AMR conservative and must never be reused for a new execution.
    summary_path = wave_root / "CL" / "summary_config.yaml"
    summary = yaml.safe_load(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    if (
        summary.get("mode") != "internal_shoreline"
        or int(summary.get("source_format", 0)) != 2
        or Path(str(summary.get("source_avac_run", ""))).resolve() != source_avac_root
        or not (wave_root / "CL" / "internal_inflow.data").is_file()
    ):
        prepare_wave_boundary_conditions(runtime_root, wave_root, source_avac_root)
        summary = yaml.safe_load(summary_path.read_text(encoding="utf-8"))
    if int(summary.get("active_source_cells", 0)) <= 0:
        raise RuntimeValidationError(
            "No inward-moving AVAC material crosses the initial wet lake shoreline; "
            "there is no Wave inflow to simulate."
        )
    if str(claw_source) not in sys.path:
        sys.path.insert(0, str(claw_source))
    output = wave_dir / "_output"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    previous = Path.cwd()
    previous_argv = sys.argv
    try:
        os.chdir(wave_dir)
        namespace = {"__name__": "__main__", "__file__": str(wave_dir / "setrun.py")}
        sys.argv = [str(wave_dir / "setrun.py")]
        with suppress_pyclaw_file_logging():
            exec(compile(backend.read_bytes(), str(wave_dir / "setrun.py"), "exec"), namespace)  # noqa: S102
    finally:
        sys.argv = previous_argv
        os.chdir(previous)
    data = list(wave_dir.glob("*.data"))
    if not data:
        raise RuntimeValidationError("Wave backend generated no Clawpack data files.")
    for path in data:
        shutil.copy2(path, output / path.name)
    return output
