"""Isolated, marked AVAC run-directory materialization and protection."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from .preprocessing import AvacRaster, PreparedInputs, PreparationCancelled, prepare_inputs
from .time_utils import local_now_iso


RUN_MARKER = ".avac_qgis_run.json"
RUN_FORMAT = 1
# This is deliberately the complete Makefile dependency surface for an AVAC
# build.  It excludes generated data, objects, executables and old outputs.
SOLVER_MANIFEST = (
    "Makefile", "config.mk", "setrun.py", "src2.f90", "setprob.f90", "b4step2.f90",
    "rpn2_geoclaw.f", "rheology_module.f90", "qinit_module.f90", "qinit.f90",
)
# Packaged execution evaluates the verified runtime backend in memory.  No
# Python source is copied into normal user workspaces.
RUNTIME_RUN_MANIFEST: tuple[str, ...] = ()


def _marker_path(run_root: Path) -> Path:
    return run_root / RUN_MARKER


def read_run_metadata(run_root: str | Path) -> dict[str, Any]:
    path = _marker_path(Path(run_root))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Not a plugin-prepared AVAC run directory: {path}") from exc


def write_run_metadata(run_root: str | Path, payload: dict[str, Any]) -> None:
    path = _marker_path(Path(run_root))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_prepared_run(avac_dir: str | Path, *, require_ready: bool = True) -> dict[str, Any]:
    """Guard the destructive Make workflow with the plugin-owned run marker."""
    avac_dir = Path(avac_dir).resolve()
    run_root = avac_dir.parent
    metadata = read_run_metadata(run_root)
    if metadata.get("format") != RUN_FORMAT or metadata.get("avac_directory") != "AVAC":
        raise ValueError("Run marker is incompatible with this plugin version.")
    valid_states = {"prepared", "running", "completed", "failed", "cancelled"}
    if not require_ready:
        valid_states.add("materializing")
    if metadata.get("status") not in valid_states:
        raise ValueError("Run marker has no valid prepared state.")
    if avac_dir != run_root / "AVAC" or (require_ready and not (run_root / "Topo" / "topography.asc").is_file()):
        raise ValueError("Prepared run structure is incomplete; refusing to invoke make clean.")
    return metadata


def update_run_status(avac_dir: str | Path, status: str, **fields: Any) -> None:
    avac_dir = Path(avac_dir).resolve()
    payload = validate_prepared_run(avac_dir, require_ready=False)
    payload.update(fields)
    payload["status"] = status
    payload["updated_at"] = local_now_iso()
    write_run_metadata(avac_dir.parent, payload)


def materialize_solver_tree(run_root: str | Path, backend_avac_dir: str | Path, metadata: dict[str, Any]) -> Path:
    """Copy only solver-build sources into an empty run root, never a binary/output."""
    run_root, backend = Path(run_root).expanduser().resolve(), Path(backend_avac_dir).expanduser().resolve()
    if run_root.exists() and any(path.name != "inputs" for path in run_root.iterdir()):
        raise ValueError(f"Run directory must be empty except for materialized inputs: {run_root}")
    missing = [name for name in SOLVER_MANIFEST if not (backend / name).is_file()]
    if missing:
        raise ValueError("Verified AVAC backend is missing required solver files: " + ", ".join(missing))
    avac_dir = run_root / "AVAC"
    topo_dir = run_root / "Topo"
    avac_dir.mkdir(parents=True, exist_ok=False)
    topo_dir.mkdir()
    for name in SOLVER_MANIFEST:
        shutil.copy2(backend / name, avac_dir / name)
    now = local_now_iso()
    payload = {
        "format": RUN_FORMAT,
        "status": "materializing",
        "created_at": now,
        "updated_at": now,
        "temporal_origin_iso": now,
        "avac_directory": "AVAC",
        "topo_directory": "Topo",
        "solver_manifest": list(SOLVER_MANIFEST),
        **metadata,
    }
    write_run_metadata(run_root, payload)
    return avac_dir


def materialize_runtime_tree(run_root: str | Path, runtime_backend: str | Path, metadata: dict[str, Any]) -> Path:
    """Create the minimal no-Make run tree from a validated runtime backend."""
    run_root, backend = Path(run_root).expanduser().resolve(), Path(runtime_backend).expanduser().resolve()
    if run_root.exists() and any(path.name != "inputs" for path in run_root.iterdir()):
        raise ValueError(f"Run directory must be empty except for materialized inputs: {run_root}")
    if not (backend / "setrun.py").is_file():
        raise ValueError("Verified runtime backend is missing setrun.py.")
    avac_dir, topo_dir = run_root / "AVAC", run_root / "Topo"
    avac_dir.mkdir(parents=True, exist_ok=False); topo_dir.mkdir()
    now = local_now_iso()
    write_run_metadata(run_root, {"format": RUN_FORMAT, "status": "materializing", "created_at": now, "updated_at": now,
                                  "temporal_origin_iso": now,
                                  "avac_directory": "AVAC", "topo_directory": "Topo", "solver_manifest": list(RUNTIME_RUN_MANIFEST),
                                  "execution_mode": "bundled_runtime", **metadata})
    return avac_dir


def prepare_isolated_runtime_run(run_root: str | Path, runtime_backend: str | Path, raster: AvacRaster, rings, template: str | Path,
                                 release: dict[str, Any], metadata: dict[str, Any], controlled_values: dict[str, Any] | None = None,
                                 fine_raster: AvacRaster | None = None,
                                 progress: Callable[[int], None] | None = None, cancelled: Callable[[], bool] | None = None) -> PreparedInputs:
    """Prepare scientific inputs for direct packaged execution without sources/Make."""
    run_root = Path(run_root).expanduser().resolve()
    if progress: progress(5)
    avac_dir = materialize_runtime_tree(run_root, runtime_backend, metadata)
    try:
        prepared = prepare_inputs(run_root, raster, rings, Path(template), release, controlled_values, fine_raster=fine_raster, allow_existing_run=True, progress=progress, cancelled=cancelled)
    except PreparationCancelled:
        update_run_status(avac_dir, "cancelled", preparation_error="Scientific input preparation cancelled"); raise
    except Exception:
        update_run_status(avac_dir, "failed", preparation_error="Scientific input preparation failed"); raise
    update_run_status(avac_dir, "prepared", configuration_template=str(Path(template).resolve()), release_parameters=release,
                      controlled_parameters=controlled_values or {})
    if progress: progress(100)
    return prepared


def prepare_isolated_run(
    run_root: str | Path,
    backend_avac_dir: str | Path,
    raster: AvacRaster,
    rings,
    template: str | Path,
    release: dict[str, Any],
    metadata: dict[str, Any],
    controlled_values: dict[str, Any] | None = None,
    fine_raster: AvacRaster | None = None,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PreparedInputs:
    """Build a marked solver tree, then materialize equivalent scientific inputs."""
    run_root = Path(run_root).expanduser().resolve()
    if progress:
        progress(5)
    materialize_solver_tree(run_root, backend_avac_dir, metadata)
    try:
        if progress:
            progress(15)
        prepared = prepare_inputs(
            run_root, raster, rings, Path(template), release, controlled_values, fine_raster=fine_raster, allow_existing_run=True,
            progress=progress, cancelled=cancelled,
        )
    except PreparationCancelled:
        update_run_status(run_root / "AVAC", "cancelled", preparation_error="Scientific input preparation cancelled")
        raise
    except Exception:
        update_run_status(run_root / "AVAC", "failed", preparation_error="Scientific input preparation failed")
        raise
    update_run_status(run_root / "AVAC", "prepared", configuration_template=str(Path(template).resolve()), release_parameters=release, controlled_parameters=controlled_values or {})
    if progress:
        progress(100)
    return prepared
