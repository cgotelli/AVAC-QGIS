#!/usr/bin/env python3
"""Create the installable macOS Apple-Silicon AVAC-QGIS QGIS-plugin ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "avac_qgis"
FORBIDDEN = ("/Users/cmgotelli/", "Desktop/AVAC-QGIS", "Downloads/Lac_Clusaz", "anaconda", "conda", "/opt/homebrew/")
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".git", ".github", "tests"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def manifest_digest(manifest: dict) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def metadata_version() -> str:
    text = (PLUGIN / "metadata.txt").read_text(encoding="utf-8")
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    version = fields.get("version", "").strip()
    if not version or version.endswith("-dev"):
        raise ValueError("metadata.txt must contain a non-development release version")
    return version


def runtime_manifest(archive: Path, version: str) -> dict:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if any(member.name.startswith("/") or ".." in Path(member.name).parts for member in members):
            raise ValueError("runtime archive contains an unsafe path")
        member = next((item for item in members if item.name == "arm64/runtime-manifest.json"), None)
        if member is None:
            raise ValueError("runtime archive lacks arm64/runtime-manifest.json")
        payload = json.load(bundle.extractfile(member))
    if payload.get("format") != 1 or payload.get("architecture") != "arm64":
        raise ValueError("runtime archive is not format-1 arm64")
    if payload.get("runtime_version") != version:
        raise ValueError(f"runtime version mismatch: expected {version}, found {payload.get('runtime_version')}")
    return payload


def assert_no_forbidden(root: Path) -> None:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".dylib", ".so"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(token in text for token in FORBIDDEN):
            hits.append(str(path.relative_to(root)))
    if hits:
        raise ValueError("forbidden developer paths found in release staging: " + ", ".join(hits[:10]))


def copy_plugin(
    staging: Path,
    runtime_archive: Path,
    runtime_version: str,
    runtime_manifest_payload: dict,
    wave_runtime_archive: Path | None = None,
    wave_runtime_version: str | None = None,
    wave_manifest_payload: dict | None = None,
) -> Path:
    destination = staging / "avac_qgis"
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in EXCLUDED_DIRS or Path(name).suffix in EXCLUDED_SUFFIXES or name == ".DS_Store"}
    shutil.copytree(PLUGIN, destination, ignore=ignore)
    shutil.copy2(ROOT / "README.md", destination / "README.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    documentation = destination / "documentation"
    documentation.mkdir()
    shutil.copy2(ROOT / "docs" / "AVAC_QGIS_UI_REFERENCE.pdf", documentation / "AVAC_QGIS_UI_REFERENCE.pdf")
    resources = destination / "resources"
    for old in resources.glob("avac-runtime-*.tar.gz"):
        old.unlink()
    for old in resources.glob("runtime-release*.json"):
        old.unlink()
    archive_name = f"avac-runtime-macos-arm64-{runtime_version}.tar.gz"
    shutil.copy2(runtime_archive, resources / archive_name)
    (resources / "runtime-release.json").write_text(
        json.dumps({
            "runtime_version": runtime_version,
            "archive": archive_name,
            "runtime_manifest_sha256": manifest_digest(runtime_manifest_payload),
        }, indent=2) + "\n", encoding="utf-8"
    )
    if wave_runtime_archive is not None and wave_runtime_version is not None:
        if wave_manifest_payload is None:
            raise ValueError("Wave runtime manifest is required when packaging a Wave runtime.")
        for old in resources.glob("wave-runtime-*.tar.gz"):
            old.unlink()
        for old in resources.glob("wave-runtime-release*.json"):
            old.unlink()
        wave_name = f"wave-runtime-macos-arm64-{wave_runtime_version}.tar.gz"
        shutil.copy2(wave_runtime_archive, resources / wave_name)
        (resources / "wave-runtime-release.json").write_text(
            json.dumps({
                "runtime_version": wave_runtime_version,
                "archive": wave_name,
                "runtime_manifest_sha256": manifest_digest(wave_manifest_payload),
            }, indent=2) + "\n", encoding="utf-8"
        )
    return destination


def write_zip(plugin_root: Path, output: Path) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(plugin_root.rglob("*")):
            if not path.is_file():
                continue
            arcname = path.relative_to(plugin_root.parent).as_posix()
            bundle.write(path, arcname)
            contents.append({"path": arcname, "bytes": path.stat().st_size, "sha256": digest(path)})
    return contents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--wave-runtime-archive", type=Path)
    parser.add_argument("--wave-runtime-version")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = metadata_version()
    archive = args.runtime_archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"runtime archive not found: {archive}")
    manifest = runtime_manifest(archive, args.runtime_version)
    if bool(args.wave_runtime_archive) != bool(args.wave_runtime_version):
        raise SystemExit("--wave-runtime-archive and --wave-runtime-version must be provided together")
    wave_archive = args.wave_runtime_archive.resolve() if args.wave_runtime_archive else None
    wave_manifest = None
    if wave_archive is not None:
        if not wave_archive.is_file():
            raise SystemExit(f"Wave runtime archive not found: {wave_archive}")
        wave_manifest = runtime_manifest(wave_archive, args.wave_runtime_version)
    dist = args.dist.resolve(); dist.mkdir(parents=True, exist_ok=True)
    filename = f"avac_qgis-{version}-macos-arm64.zip"
    output = dist / filename
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing package: {output}")
    with tempfile.TemporaryDirectory(prefix="avac-qgis-package-") as temporary:
        staged = copy_plugin(
            Path(temporary), archive, args.runtime_version, manifest,
            wave_archive, args.wave_runtime_version, wave_manifest,
        )
        assert_no_forbidden(staged)
        contents = write_zip(staged, output)
    package_hash = digest(output)
    (dist / f"{filename}.sha256").write_text(f"{package_hash}  {filename}\n", encoding="utf-8")
    (dist / "PACKAGE_CONTENTS.json").write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
    release = {
        "plugin_version": version, "runtime_version": args.runtime_version, "runtime_format": manifest["format"],
        "runtime_manifest_sha256": manifest_digest(manifest),
        "supported_os": "macOS", "supported_architecture": "arm64", "tested_qgis": "3.44 LTS",
        "clawpack_version": manifest["clawpack"]["version"],
        "solver_sha256": manifest["solver"]["sha256"],
        "solver_source_sha256": manifest["solver"]["source_sha256"],
        "runtime_archive_sha256": digest(archive), "plugin_zip_sha256": package_hash,
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    if wave_archive is not None and wave_manifest is not None:
        release.update({
            "wave_runtime_version": args.wave_runtime_version,
            "wave_runtime_manifest_sha256": manifest_digest(wave_manifest),
            "wave_clawpack_version": wave_manifest["clawpack"]["version"],
            "wave_solver_sha256": wave_manifest["solver"]["sha256"],
            "wave_solver_source_sha256": wave_manifest["solver"]["source_sha256"],
            "wave_runtime_archive_sha256": digest(wave_archive),
        })
    (dist / "RELEASE_MANIFEST.json").write_text(json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"package: {output}\nsha256: {package_hash}\nfiles: {len(contents)}\nbytes: {output.stat().st_size}")


if __name__ == "__main__":
    main()
