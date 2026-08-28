"""Validation and atomic first-use installation of AVAC native runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any


RUNTIME_FORMAT = 1
RUNTIME_APP_DIRECTORY = "AVAC-QGIS"


class RuntimeValidationError(ValueError):
    """A runtime cannot safely be used or installed."""


def platform_key(*, system: str | None = None, machine: str | None = None) -> str:
    """Return the managed-runtime target for this QGIS host."""
    host_system = (system or platform.system()).strip().lower()
    host_machine = (machine or platform.machine()).strip().lower()
    if host_system == "darwin" and host_machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if host_system == "linux" and host_machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    if host_system == "windows" and host_machine in {"x86_64", "amd64"}:
        return "windows-amd64"
    raise RuntimeValidationError(
        f"AVAC4QGIS has no managed runtime target for {platform.system()} {platform.machine()}."
    )


def runtime_architecture(key: str | None = None) -> str:
    return (key or platform_key()).rsplit("-", 1)[-1]


def runtime_install_root() -> Path:
    try:
        from qgis.PyQt.QtCore import QStandardPaths
        location = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
        if location:
            return Path(location).expanduser() / RUNTIME_APP_DIRECTORY / "runtime"
    except ImportError:
        pass
    host = platform.system().lower()
    if host == "linux":
        return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))).expanduser() / RUNTIME_APP_DIRECTORY / "runtime"
    if host == "windows":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))).expanduser() / RUNTIME_APP_DIRECTORY / "runtime"
    return Path.home() / "Library" / "Application Support" / RUNTIME_APP_DIRECTORY / "runtime"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads((path / "runtime-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeValidationError(f"Runtime manifest is missing or invalid: {path / 'runtime-manifest.json'}") from exc
    if not isinstance(payload, dict):
        raise RuntimeValidationError("Runtime manifest must be a JSON object.")
    return payload


def runtime_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Return a stable identity for one complete runtime manifest."""
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checked_file(root: Path, relative: str, expected_hash: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise RuntimeValidationError(f"Runtime required file is missing: {relative}")
    actual = _sha256(path)
    if actual != expected_hash:
        raise RuntimeValidationError(f"Runtime file hash mismatch: {relative}")
    return path


def validate_runtime(
    root: str | Path,
    *,
    expected_version: str | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate every executable/library/backend hash before a runtime is used."""
    root = Path(root).expanduser().resolve()
    manifest = _manifest(root)
    if manifest.get("format") != RUNTIME_FORMAT:
        raise RuntimeValidationError(f"Unsupported runtime manifest format: {manifest.get('format')!r}")
    target = platform_key()
    manifest_platform = manifest.get("platform")
    if manifest_platform is None and manifest.get("architecture") == "arm64":
        manifest_platform = "macos-arm64"
    if manifest_platform != target or manifest.get("architecture") != runtime_architecture(target):
        raise RuntimeValidationError(
            f"This AVAC4QGIS package does not include a runtime for {target}. "
            f"Found {manifest_platform or 'an unlabelled runtime'} instead."
        )
    if expected_version is not None and manifest.get("runtime_version") != expected_version:
        raise RuntimeValidationError(f"Runtime version mismatch: expected {expected_version}, found {manifest.get('runtime_version')}")
    if expected_manifest_sha256 is not None and runtime_manifest_sha256(manifest) != expected_manifest_sha256.lower():
        raise RuntimeValidationError(
            "Installed runtime manifest differs from the runtime bundled with this plugin."
        )
    solver = manifest.get("solver")
    if not isinstance(solver, dict) or not isinstance(solver.get("path"), str) or not isinstance(solver.get("sha256"), str):
        raise RuntimeValidationError("Runtime manifest has no valid solver record.")
    _checked_file(root, solver["path"], solver["sha256"])
    libraries = manifest.get("native_libraries")
    if not isinstance(libraries, list) or not libraries:
        raise RuntimeValidationError("Runtime manifest has no native-library records.")
    for library in libraries:
        if not isinstance(library, dict) or not isinstance(library.get("path"), str) or not isinstance(library.get("sha256"), str):
            raise RuntimeValidationError("Runtime manifest contains an invalid native-library record.")
        _checked_file(root, library["path"], library["sha256"])
    backend = manifest.get("backend")
    if not isinstance(backend, list) or not backend:
        raise RuntimeValidationError("Runtime manifest has no backend records.")
    for entry in backend:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise RuntimeValidationError("Runtime manifest contains an invalid backend record.")
        _checked_file(root, entry["path"], entry["sha256"])
    clawpack = manifest.get("clawpack")
    if not isinstance(clawpack, dict) or not isinstance(clawpack.get("root"), str) or not isinstance(clawpack.get("source_sha256"), str):
        raise RuntimeValidationError("Runtime manifest has no valid Clawpack record.")
    _checked_file(root, f"{clawpack['root']}/clawpack/__init__.py", clawpack["source_sha256"])
    return manifest


def installed_runtime(
    version: str,
    *,
    destination_root: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> Path | None:
    """Return a validated installed runtime from the requested product area.

    Optional components can share a manifest version number while providing a
    different backend.  ``destination_root`` keeps those components from
    accidentally reusing the main AVAC runtime solely because their version
    strings happen to match.
    """
    destination = Path(destination_root).expanduser().resolve() if destination_root else runtime_install_root()
    candidate = destination / version / platform_key()
    try:
        validate_runtime(
            candidate,
            expected_version=version,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except RuntimeValidationError:
        return None
    return candidate


def install_runtime_archive(
    archive: str | Path,
    version: str,
    *,
    destination_root: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> Path:
    """Atomically install a validated artifact; never publish a partial runtime."""
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file():
        raise RuntimeValidationError(f"Bundled AVAC runtime archive is missing: {archive}")
    destination = Path(destination_root).expanduser().resolve() if destination_root else runtime_install_root()
    target_platform = platform_key()
    target = destination / version / target_platform
    if target.exists():
        try:
            validate_runtime(
                target,
                expected_version=version,
                expected_manifest_sha256=expected_manifest_sha256,
            )
            return target
        except RuntimeValidationError:
            # A corrupt prior install is replaced only after a new staged copy
            # has been completely extracted and validated.
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".avac-runtime-stage-", dir=target.parent))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if any(member.name.startswith("/") or ".." in Path(member.name).parts for member in members):
                raise RuntimeValidationError("Runtime archive contains an unsafe path.")
            bundle.extractall(staging_parent, filter="data")
        staged = staging_parent / target_platform
        # Retain existing macOS development archives while new archives use
        # their full platform target as the top-level member.
        if not staged.is_dir() and target_platform == "macos-arm64":
            staged = staging_parent / "arm64"
        validate_runtime(
            staged,
            expected_version=version,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if target.exists():
            corrupt = target.with_name(target.name + ".corrupt")
            if corrupt.exists():
                shutil.rmtree(corrupt)
            os.replace(target, corrupt)
            shutil.rmtree(corrupt)
        os.replace(staged, target)
        return target
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)
