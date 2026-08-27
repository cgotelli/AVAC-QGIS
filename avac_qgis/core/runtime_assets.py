"""Resolution of plugin-owned AVAC runtime assets.

The installed-product layout is intentionally explicit even though this source
checkout still uses ``avac-main`` as its development fixture.  Packaging will
place a versioned backend beneath ``resources/backend``; normal UI code never
needs to expose that path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .runtime import install_runtime_archive, installed_runtime, platform_key, runtime_install_root


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = PLUGIN_ROOT / "resources"
DEFAULT_TEMPLATE = RESOURCES / "AVAC_configuration100.yaml"
_DEVELOPMENT_RUNTIME_VERSION = "0.5.1"
_RELEASE_DESCRIPTOR = RESOURCES / "runtime-release.json"


def _runtime_release() -> tuple[str, Path]:
    """Resolve release metadata without making a checkout depend on it.

    The packaging builder adds the descriptor and release archive to its
    staging tree.  A development checkout deliberately continues to use the
    accepted development artifact until a release has been assembled.
    """
    target = platform_key()
    if _RELEASE_DESCRIPTOR.is_file():
        try:
            payload = json.loads(_RELEASE_DESCRIPTOR.read_text(encoding="utf-8"))
            record = payload.get("runtimes", {}).get(target) if isinstance(payload.get("runtimes"), dict) else payload
            version = str(record["runtime_version"])
            archive_name = str(record["archive"])
            declared_platform = str(record.get("platform", target))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"Invalid packaged runtime descriptor: {_RELEASE_DESCRIPTOR}") from exc
        if declared_platform != target:
            raise RuntimeError(f"This AVAC4QGIS package does not include a runtime for {target}.")
        if Path(archive_name).name != archive_name:
            raise RuntimeError("Packaged runtime descriptor contains an unsafe archive name.")
        return version, RESOURCES / archive_name
    return _DEVELOPMENT_RUNTIME_VERSION, RESOURCES / f"avac-runtime-{target}-{_DEVELOPMENT_RUNTIME_VERSION}.tar.gz"


RUNTIME_VERSION, RUNTIME_ARCHIVE = _runtime_release()


def bundled_backend_directory() -> Path:
    """Return the packaged solver directory, or the development fixture."""
    override = os.environ.get("AVAC_QGIS_AVAC_DIRECTORY", "").strip()
    candidates = (
        Path(override).expanduser() if override else None,
        RESOURCES / "backend" / "AVAC",
        PLUGIN_ROOT.parents[0] / "avac-main" / "Lac_Clusaz" / "AVAC",
    )
    usable = [path for path in candidates if path is not None]
    return next((path for path in usable if (path / "Makefile").is_file()), usable[0])


def default_template_path() -> Path:
    """Return the normal-user template without requiring a user path choice."""
    if DEFAULT_TEMPLATE.is_file():
        return DEFAULT_TEMPLATE
    # Development-only fallback until the backend is packaged.
    return bundled_backend_directory() / "AVAC_configuration100.yaml"


def bundled_runtime_archive() -> Path:
    """Return the plugin-owned artifact for this exact platform."""
    if not RUNTIME_ARCHIVE.is_file():
        raise RuntimeError(f"Bundled AVAC runtime is missing from this plugin installation: {RUNTIME_ARCHIVE}")
    return RUNTIME_ARCHIVE


def ensure_bundled_runtime() -> Path:
    """Reuse a validated installed runtime or atomically install the plugin asset."""
    runtime = installed_runtime(RUNTIME_VERSION)
    return runtime or install_runtime_archive(bundled_runtime_archive(), RUNTIME_VERSION)


# WAVE is a separate executable and is intentionally installed beside—not in
# place of—the validated AVAC runtime.
_WAVE_RELEASE_DESCRIPTOR = RESOURCES / "wave-runtime-release.json"


def _wave_runtime_release() -> tuple[str, Path]:
    try:
        payload = json.loads(_WAVE_RELEASE_DESCRIPTOR.read_text(encoding="utf-8"))
        target = platform_key()
        record = payload.get("runtimes", {}).get(target) if isinstance(payload.get("runtimes"), dict) else payload
        version, archive = str(record["runtime_version"]), str(record["archive"])
        declared_platform = str(record.get("platform", target))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Bundled Wave runtime descriptor is missing or invalid.") from exc
    if Path(archive).name != archive:
        raise RuntimeError("Bundled Wave runtime descriptor contains an unsafe archive name.")
    if declared_platform != target:
        raise RuntimeError(f"This AVAC4QGIS package does not include a Wave runtime for {target}.")
    return version, RESOURCES / archive


def ensure_bundled_wave_runtime() -> Path:
    """Install/use the independent optional Wave runtime only when requested.

    Wave's 0.1.0 artifact and an older AVAC artifact both use ``0.1.0`` as
    their manifest version.  Use a separate product area so a valid AVAC
    runtime can never be mistaken for the Wave backend.
    """
    version, archive = _wave_runtime_release()
    if not archive.is_file():
        raise RuntimeError(f"Bundled Wave runtime is missing from this plugin installation: {archive}")
    destination = runtime_install_root() / "wave"
    runtime = installed_runtime(version, destination_root=destination)
    return runtime or install_runtime_archive(archive, version, destination_root=destination)
