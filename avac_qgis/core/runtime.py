"""Validation and atomic first-use installation of AVAC native runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


RUNTIME_FORMAT = 1
RUNTIME_APP_DIRECTORY = "AVAC-QGIS"
STALE_INSTALL_PATH_AGE_SECONDS = 24 * 60 * 60


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


def _runtime_path(root: Path, relative: str) -> Path:
    """Resolve one manifest path while confining it to the runtime root."""
    if not relative or "\x00" in relative:
        raise RuntimeValidationError("Runtime manifest contains an invalid empty path.")
    portable = PurePosixPath(relative.replace("\\", "/"))
    host_path = Path(relative)
    if portable.is_absolute() or ".." in portable.parts or host_path.is_absolute() or host_path.drive:
        raise RuntimeValidationError(f"Runtime manifest path escapes its root: {relative}")
    path = (root / Path(*portable.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeValidationError(
            f"Runtime manifest path escapes its root: {relative}"
        ) from exc
    return path


def _checked_file(root: Path, relative: str, expected_hash: str) -> Path:
    path = _runtime_path(root, relative)
    if not path.is_file():
        raise RuntimeValidationError(f"Runtime required file is missing: {relative}")
    try:
        actual = _sha256(path)
    except OSError as exc:
        raise RuntimeValidationError(
            f"Runtime required file cannot be read: {relative}"
        ) from exc
    if actual != expected_hash:
        raise RuntimeValidationError(f"Runtime file hash mismatch: {relative}")
    return path


def _replace_path(source: Path, destination: Path) -> None:
    """Atomically rename a runtime directory, tolerating short-lived locks.

    Windows antivirus and indexing processes can briefly open a freshly
    extracted file without delete sharing.  ``os.replace`` then reports
    ``WinError 5`` even though the same atomic rename succeeds moments later.
    Keep the operation atomic and bounded instead of falling back to a
    partially visible copy.
    """
    delays = (0.05, 0.10, 0.20, 0.40, 0.80, 1.00, 1.00)
    for attempt in range(len(delays) + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def _cleanup_stale_install_paths(target: Path) -> None:
    """Best-effort cleanup of abandoned staging and quarantine directories."""
    now = time.time()
    cutoff = now - STALE_INSTALL_PATH_AGE_SECONDS
    for candidate in target.parent.glob(".avac-runtime-stage-*"):
        try:
            if not candidate.is_dir() or candidate.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        # Recent directories may belong to a live concurrent install; old
        # stages are safe to retry after a scanner lock has cleared.
        shutil.rmtree(candidate, ignore_errors=True)

    quarantine_prefix = f"{target.name}.corrupt-"
    for candidate in target.parent.glob(quarantine_prefix + "*"):
        # A directory rename preserves the source mtime, so quarantine age is
        # encoded in its unique name.  UUID-only names from older releases are
        # deliberately left alone because their creation time is unknowable.
        timestamp = candidate.name[len(quarantine_prefix):].split("-", 1)[0]
        try:
            created = int(timestamp) / 1_000_000_000
            stale = candidate.is_dir() and created <= cutoff
        except (OSError, ValueError):
            continue
        if stale:
            shutil.rmtree(candidate, ignore_errors=True)


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
    clawpack_files = clawpack.get("files")
    if clawpack_files is not None:
        if not isinstance(clawpack_files, list) or not clawpack_files:
            raise RuntimeValidationError("Runtime manifest has no Clawpack file records.")
        clawpack_root = _runtime_path(root, clawpack["root"])
        seen: set[str] = set()
        for entry in clawpack_files:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
                raise RuntimeValidationError("Runtime manifest contains an invalid Clawpack file record.")
            relative = entry["path"]
            if relative in seen:
                raise RuntimeValidationError(f"Runtime manifest repeats a Clawpack path: {relative}")
            seen.add(relative)
            checked = _checked_file(root, relative, entry["sha256"])
            try:
                checked.relative_to(clawpack_root)
            except ValueError as exc:
                raise RuntimeValidationError(
                    f"Runtime Clawpack file is outside its declared root: {relative}"
                ) from exc
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
    target.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_install_paths(target)
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
        if staged.is_symlink():
            raise RuntimeValidationError(
                "Runtime archive platform root must be a real directory."
            )
        staged_manifest = validate_runtime(
            staged,
            expected_version=version,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        # If another QGIS process wins a simultaneous first-use install, only
        # converge on the exact runtime that this call just validated.  When
        # callers omit an expected identity, deriving it here prevents a
        # merely same-version (but different) artifact from being accepted.
        winner_identity = (
            expected_manifest_sha256
            or runtime_manifest_sha256(staged_manifest)
        )

        def exact_concurrent_winner() -> bool:
            try:
                validate_runtime(
                    target,
                    expected_version=version,
                    expected_manifest_sha256=winner_identity,
                )
            except (RuntimeValidationError, OSError):
                return False
            return True

        corrupt: Path | None = None
        if target.exists():
            # The target may have changed since the initial check while this
            # process extracted the archive.  Do not quarantine an identical
            # runtime that another process has already finished publishing.
            if exact_concurrent_winner():
                return target
            corrupt = target.with_name(
                target.name + f".corrupt-{time.time_ns()}-{uuid.uuid4().hex}"
            )
            try:
                _replace_path(target, corrupt)
            except OSError:
                # A concurrent installer may have replaced or temporarily
                # removed the target after our initial validation.  Accept an
                # exact winner, or continue if the target is currently absent
                # and let the atomic promotion below settle the race.
                if exact_concurrent_winner():
                    return target
                if target.exists():
                    raise
                corrupt = None
        try:
            _replace_path(staged, target)
        except OSError:
            # Directory replacement on Windows fails when another process has
            # just published the same non-empty target.  That is success only
            # when every file and the complete manifest identity match.
            if exact_concurrent_winner():
                if corrupt is not None:
                    shutil.rmtree(corrupt, ignore_errors=True)
                return target
            # The prior installation was already invalid, but restore it when
            # possible so a failed repair does not leave a surprising gap.
            if corrupt is not None and corrupt.exists() and not target.exists():
                try:
                    _replace_path(corrupt, target)
                except OSError:
                    pass
            # The winner may have appeared between the first validation and
            # the rollback check above.  Re-evaluate once before surfacing the
            # original promotion failure.
            if exact_concurrent_winner():
                if corrupt is not None:
                    shutil.rmtree(corrupt, ignore_errors=True)
                return target
            raise
        if corrupt is not None:
            # Publishing the validated target is the transaction boundary.
            # A scanner may still hold the quarantined copy briefly; leaving
            # it for a later cleanup is safer than failing a successful install.
            shutil.rmtree(corrupt, ignore_errors=True)
        return target
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)
