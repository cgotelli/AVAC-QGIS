"""Development-artifact validation and atomic installation regression."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

# Keep this release check executable directly from a source checkout as well
# as through the test runner, matching the Wave runtime companion check.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import avac_qgis.core.runtime as runtime_module
from avac_qgis.core.runtime import (
    RuntimeValidationError,
    install_runtime_archive,
    platform_key,
    runtime_architecture,
    runtime_manifest_sha256,
    validate_runtime,
)


def _minimal_runtime_archive(
    directory: Path,
    version: str,
    marker: bytes,
) -> tuple[Path, Path, str]:
    """Create a small, fully valid runtime archive for promotion tests."""
    target_platform = platform_key()
    runtime = directory / "bundle" / target_platform
    files = {
        "bin/xgeoclaw.exe": b"solver-" + marker,
        "lib/native-library.dll": b"library-" + marker,
        "backend/AVAC/setrun.py": b"backend-" + marker,
        "clawpack/clawpack/__init__.py": b"clawpack-" + marker,
        "clawpack/clawpack/data.py": b"clawpack-data-" + marker,
    }
    hashes: dict[str, str] = {}
    for relative, content in files.items():
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    manifest = {
        "format": runtime_module.RUNTIME_FORMAT,
        "platform": target_platform,
        "architecture": runtime_architecture(target_platform),
        "runtime_version": version,
        "solver": {
            "path": "bin/xgeoclaw.exe",
            "sha256": hashes["bin/xgeoclaw.exe"],
        },
        "native_libraries": [
            {
                "path": "lib/native-library.dll",
                "sha256": hashes["lib/native-library.dll"],
            }
        ],
        "backend": [
            {
                "path": "backend/AVAC/setrun.py",
                "sha256": hashes["backend/AVAC/setrun.py"],
            }
        ],
        "clawpack": {
            "root": "clawpack",
            "source_sha256": hashes["clawpack/clawpack/__init__.py"],
            "files": [
                {"path": relative, "sha256": hashes[relative]}
                for relative in sorted(hashes)
                if relative.startswith("clawpack/")
            ],
        },
    }
    (runtime / "runtime-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    archive = directory / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(runtime, arcname=target_platform)
    return archive, runtime, runtime_manifest_sha256(manifest)


def test_atomic_runtime_promotion_retries_transient_locks(
    tmp_path: Path, monkeypatch,
) -> None:
    """A short-lived scanner lock must not turn first use into manual setup."""
    source = tmp_path / "staged"
    destination = tmp_path / "installed"
    source.mkdir()
    (source / "runtime-manifest.json").write_text("{}\n", encoding="utf-8")

    real_replace = runtime_module.os.replace
    attempts = 0
    delays: list[float] = []

    def intermittently_locked(source_path, destination_path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise PermissionError(13, "simulated scanner lock", str(source_path))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(runtime_module.os, "replace", intermittently_locked)
    monkeypatch.setattr(runtime_module.time, "sleep", delays.append)

    runtime_module._replace_path(source, destination)

    assert attempts == 4
    assert delays == [0.05, 0.10, 0.20]
    assert not source.exists()
    assert (destination / "runtime-manifest.json").is_file()


def test_concurrent_exact_runtime_promotion_converges(
    tmp_path: Path, monkeypatch,
) -> None:
    """A process that loses an install race must reuse the exact winner."""
    version = "concurrent-test"
    archive, _, identity = _minimal_runtime_archive(
        tmp_path / "expected", version, b"expected"
    )
    destination_root = tmp_path / "installed"
    real_replace = runtime_module._replace_path
    simulated_race = False

    def lose_promotion(source: Path, destination: Path) -> None:
        nonlocal simulated_race
        is_staged_promotion = (
            source.name == platform_key()
            and source.parent.name.startswith(".avac-runtime-stage-")
        )
        if is_staged_promotion and not simulated_race:
            simulated_race = True
            shutil.copytree(source, destination)
            raise PermissionError(13, "simulated concurrent install", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(runtime_module, "_replace_path", lose_promotion)
    installed = install_runtime_archive(
        archive, version, destination_root=destination_root
    )

    assert simulated_race
    assert runtime_manifest_sha256(
        validate_runtime(installed, expected_version=version)
    ) == identity


def test_concurrent_different_runtime_is_not_accepted(
    tmp_path: Path, monkeypatch,
) -> None:
    """Same-version artifacts with a different manifest cannot win the race."""
    version = "concurrent-test"
    archive, _, expected_identity = _minimal_runtime_archive(
        tmp_path / "expected", version, b"expected"
    )
    _, other_runtime, other_identity = _minimal_runtime_archive(
        tmp_path / "other", version, b"other"
    )
    destination_root = tmp_path / "installed"
    real_replace = runtime_module._replace_path
    simulated_race = False

    def lose_to_different_runtime(source: Path, destination: Path) -> None:
        nonlocal simulated_race
        is_staged_promotion = (
            source.name == platform_key()
            and source.parent.name.startswith(".avac-runtime-stage-")
        )
        if is_staged_promotion and not simulated_race:
            simulated_race = True
            shutil.copytree(other_runtime, destination)
            raise PermissionError(13, "simulated concurrent install", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(runtime_module, "_replace_path", lose_to_different_runtime)
    try:
        install_runtime_archive(archive, version, destination_root=destination_root)
    except PermissionError:
        pass
    else:
        raise AssertionError("A different same-version concurrent runtime was accepted")

    winner = destination_root / version / platform_key()
    assert simulated_race
    assert other_identity != expected_identity
    assert runtime_manifest_sha256(
        validate_runtime(winner, expected_version=version)
    ) == other_identity


def test_runtime_manifest_paths_cannot_escape_install_root(tmp_path: Path) -> None:
    """A valid outside file must never satisfy a manifest path traversal."""
    version = "path-test"
    _, runtime, _ = _minimal_runtime_archive(tmp_path, version, b"inside")
    outside = runtime.parent / "outside.exe"
    outside.write_bytes(b"outside-solver")
    manifest_path = runtime / "runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["solver"] = {
        "path": "../outside.exe",
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        validate_runtime(runtime, expected_version=version)
    except RuntimeValidationError as exc:
        assert "escapes its root" in str(exc)
    else:
        raise AssertionError("Runtime validation accepted a path outside its root")


def test_all_manifested_clawpack_files_are_validated(tmp_path: Path) -> None:
    """Corruption outside Clawpack's package marker must be self-healed too."""
    version = "clawpack-integrity-test"
    _, runtime, _ = _minimal_runtime_archive(tmp_path, version, b"clean")
    (runtime / "clawpack" / "clawpack" / "data.py").write_bytes(b"corrupt")

    try:
        validate_runtime(runtime, expected_version=version)
    except RuntimeValidationError as exc:
        assert "hash mismatch" in str(exc)
        assert "clawpack/clawpack/data.py" in str(exc)
    else:
        raise AssertionError("Runtime validation missed a corrupt Clawpack file")


def test_failed_repair_promotion_restores_prior_runtime(
    tmp_path: Path, monkeypatch,
) -> None:
    """A failed atomic repair must restore the quarantined prior directory."""
    version = "rollback-test"
    old_archive, _, _ = _minimal_runtime_archive(
        tmp_path / "old", version, b"old"
    )
    new_archive, _, _ = _minimal_runtime_archive(
        tmp_path / "new", version, b"new"
    )
    destination_root = tmp_path / "installed"
    installed = install_runtime_archive(
        old_archive, version, destination_root=destination_root
    )
    solver = installed / "bin" / "xgeoclaw.exe"
    solver.write_bytes(solver.read_bytes() + b"-corrupt")
    prior_solver = solver.read_bytes()
    real_replace = runtime_module._replace_path

    def fail_staged_promotion(source: Path, destination: Path) -> None:
        is_staged_promotion = (
            source.name == platform_key()
            and source.parent.name.startswith(".avac-runtime-stage-")
        )
        if is_staged_promotion:
            raise PermissionError(13, "simulated promotion failure", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(runtime_module, "_replace_path", fail_staged_promotion)
    try:
        install_runtime_archive(
            new_archive, version, destination_root=destination_root
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("A forced runtime repair promotion unexpectedly succeeded")

    assert installed.is_dir()
    assert solver.read_bytes() == prior_solver
    assert not list(installed.parent.glob(platform_key() + ".corrupt-*"))


def test_later_install_cleans_abandoned_runtime_directories(tmp_path: Path) -> None:
    """Old lock leftovers are retried without touching recent live stages."""
    version = "cleanup-test"
    archive, _, _ = _minimal_runtime_archive(tmp_path / "archive", version, b"clean")
    destination_root = tmp_path / "installed"
    installed = install_runtime_archive(
        archive, version, destination_root=destination_root
    )
    stale_stage = installed.parent / ".avac-runtime-stage-abandoned"
    now_ns = runtime_module.time.time_ns()
    old_ns = now_ns - (
        runtime_module.STALE_INSTALL_PATH_AGE_SECONDS + 1
    ) * 1_000_000_000
    stale_corrupt = installed.parent / (
        platform_key() + f".corrupt-{old_ns}-abandoned"
    )
    recent_stage = installed.parent / ".avac-runtime-stage-active"
    recent_corrupt = installed.parent / (
        platform_key() + f".corrupt-{now_ns}-active"
    )
    for directory in (
        stale_stage, stale_corrupt, recent_stage, recent_corrupt,
    ):
        directory.mkdir()
    old = (
        runtime_module.time.time()
        - runtime_module.STALE_INSTALL_PATH_AGE_SECONDS
        - 1
    )
    os.utime(stale_stage, (old, old))
    os.utime(stale_corrupt, (old, old))
    # Rename preserves the source mtime on Windows.  A freshly created
    # quarantine with an old inherited mtime must still be treated as live.
    os.utime(recent_corrupt, (old, old))

    assert install_runtime_archive(
        archive, version, destination_root=destination_root
    ) == installed
    assert not stale_stage.exists()
    assert not stale_corrupt.exists()
    assert recent_stage.is_dir()
    assert recent_corrupt.is_dir()


def main() -> None:
    archive = Path(os.environ["AVAC_QGIS_RUNTIME_ARCHIVE"])
    version = os.environ["AVAC_QGIS_RUNTIME_VERSION"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        installed = install_runtime_archive(archive, version, destination_root=root)
        manifest = validate_runtime(installed, expected_version=version)
        target = platform_key()
        assert installed == (root / version / target).resolve()
        # Early arm64 archives predate the explicit platform field and remain
        # supported by validate_runtime for installed-package compatibility.
        declared_platform = manifest.get("platform")
        if declared_platform is None:
            assert target == "macos-arm64"
        else:
            assert declared_platform == target
        assert manifest["architecture"] == runtime_architecture(target)
        identity = runtime_manifest_sha256(manifest)
        assert validate_runtime(
            installed,
            expected_version=version,
            expected_manifest_sha256=identity,
        ) == manifest
        try:
            validate_runtime(
                installed,
                expected_version=version,
                expected_manifest_sha256="0" * 64,
            )
        except RuntimeValidationError as exc:
            assert "differs from the runtime bundled" in str(exc)
        else:
            raise AssertionError("A valid but stale same-version runtime was accepted")
        # The test installation is explicitly isolated under ``root``.  Do
        # not make its result depend on whether a real first-use installation
        # already exists in Application Support.
        solver = installed / manifest["solver"]["path"]
        solver.write_bytes(solver.read_bytes() + b"corrupt")
        try:
            validate_runtime(installed, expected_version=version)
        except RuntimeValidationError as exc:
            assert "hash mismatch" in str(exc)
        else:
            raise AssertionError("Corrupt solver was accepted")
        repaired = install_runtime_archive(archive, version, destination_root=root)
        assert validate_runtime(repaired, expected_version=version)["runtime_version"] == version
    print("runtime identity validation, corrupt-runtime replacement, and staged install: PASS")


if __name__ == "__main__":
    main()
