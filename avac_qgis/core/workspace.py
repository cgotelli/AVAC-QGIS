"""Data-only AVAC workspace management for normal packaged runs."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from .runtime import runtime_install_root
from .runtime_assets import PLUGIN_ROOT
from .time_utils import local_run_stamp


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_workspace(path: str | Path) -> Path:
    """Create/check a user data workspace without permitting code locations."""
    text = str(path).strip()
    if not text:
        raise ValueError("Select an AVAC Working Directory before preparing a run.")
    root = Path(text).expanduser().resolve()
    forbidden = (PLUGIN_ROOT.resolve(), runtime_install_root().resolve())
    if any(root == item or _inside(root, item) or _inside(item, root) for item in forbidden):
        raise ValueError("AVAC Working Directory must be separate from the plugin installation and managed runtime.")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
        raise ValueError(f"AVAC Working Directory is not writable: {root}")
    (root / "runs").mkdir(exist_ok=True)
    return root


def create_run_root(workspace: str | Path) -> tuple[str, Path]:
    root = validate_workspace(workspace)
    run_id = "run_" + local_run_stamp()
    candidate = root / "runs" / run_id
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / "runs" / f"{run_id}_{suffix:02d}"
    return candidate.name, candidate


def _local_path(source: str) -> Path:
    path = Path(source.split("|", 1)[0]).expanduser()
    if not path.is_file():
        raise ValueError(f"Selected input cannot be materialized as a local dataset: {source}")
    return path.resolve()


def _copy_record(source: Path, destination: Path) -> dict[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {"source_path": str(source), "materialized_path": str(destination), "source_sha256": _sha256(source), "materialized_sha256": _sha256(destination)}


def materialize_layer_sources(run_root: str | Path, dem_source: str, release_source: str, dem_crs: str, release_crs: str) -> dict[str, Any]:
    """Copy local DEM plus complete Shapefile sidecars into a run's inputs.

    Normal QGIS layers may originate anywhere.  The solver never uses these
    originals after preparation: it consumes AVAC-formatted inputs generated
    beneath this run.  Shapefiles are copied as a complete same-stem dataset.
    Other local single-file providers are copied as their selected file.
    """
    root = Path(run_root).resolve() / "inputs"
    dem = _local_path(dem_source)
    release = _local_path(release_source)
    dem_record = _copy_record(dem, root / "dem" / dem.name)
    dem_record["crs"] = dem_crs
    release_dir = root / "release"
    if release.suffix.lower() == ".shp":
        components = sorted(path for path in release.parent.glob(release.stem + ".*") if path.is_file())
        required = {".shp", ".shx", ".dbf"}
        suffixes = {path.suffix.lower() for path in components}
        if not required.issubset(suffixes):
            raise ValueError("Selected Shapefile is incomplete; .shp, .shx and .dbf are required for workspace materialization.")
    else:
        components = [release]
    records = [_copy_record(component, release_dir / component.name) for component in components]
    return {"dem": dem_record, "release": {"crs": release_crs, "components": records}}


def completed_runs(workspace: str | Path) -> list[Path]:
    """Return completed marked runs in a normal or imported-case workspace.

    Normal AVAC4QGIS workspaces keep generated runs in ``runs/<run-id>``.
    A completed imported case may instead have one immutable, marked ``Run``
    directory at its root (as used by the ISeeSnow validation records).  Read
    that single compatibility location only when it carries a valid completed
    plugin marker; ordinary unmarked folders named ``Run`` are ignored.
    """
    root = validate_workspace(workspace)
    from .run_project import read_run_metadata

    candidates = [candidate for candidate in sorted((root / "runs").iterdir(), reverse=True) if candidate.is_dir()]
    imported = root / "Run"
    if imported.is_dir() and imported not in candidates:
        candidates.append(imported)

    result: list[Path] = []
    for candidate in candidates:
        try:
            if read_run_metadata(candidate).get("status") == "completed":
                result.append(candidate)
        except ValueError:
            continue
    return result
