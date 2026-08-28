#!/usr/bin/env python3
"""Create the installable Windows AMD64 AVAC4QGIS QGIS-plugin ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "avac_qgis"
TARGET = "windows-amd64"
FORBIDDEN = ("/Users/", "Desktop/AVAC-QGIS", "Downloads/Lac_Clusaz", "anaconda", "conda", "/opt/homebrew/")
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
    fields = dict(line.split("=", 1) for line in (PLUGIN / "metadata.txt").read_text(encoding="utf-8").splitlines() if "=" in line)
    version = fields.get("version", "").strip()
    if not version or version.endswith("-dev"):
        raise ValueError("metadata.txt must contain a non-development release version")
    return version


def runtime_manifest(archive: Path, version: str) -> dict:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if any(member.name.startswith("/") or ".." in Path(member.name).parts for member in members):
            raise ValueError("runtime archive contains an unsafe path")
        member = next((item for item in members if item.name == f"{TARGET}/runtime-manifest.json"), None)
        if member is None:
            raise ValueError(f"runtime archive lacks {TARGET}/runtime-manifest.json")
        payload = json.load(bundle.extractfile(member))
    if payload.get("format") != 1 or payload.get("platform") != TARGET or payload.get("architecture") != "amd64":
        raise ValueError("runtime archive is not a format-1 Windows AMD64 artifact")
    if payload.get("runtime_version") != version:
        raise ValueError(f"runtime version mismatch: expected {version}, found {payload.get('runtime_version')}")
    return payload


def assert_no_forbidden(root: Path) -> None:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".dll", ".exe", ".pyd", ".tar", ".gz", ".zip"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(token in text for token in FORBIDDEN):
            hits.append(str(path.relative_to(root)))
    if hits:
        raise ValueError("forbidden developer paths found in release staging: " + ", ".join(hits[:10]))


def copy_plugin(
    staging: Path,
    runtime_archive: Path,
    runtime_version: str,
    runtime_manifest_payload: dict,
    wave_archive: Path,
    wave_version: str,
    wave_manifest_payload: dict,
) -> Path:
    destination = staging / "avac_qgis"
    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in EXCLUDED_DIRS or Path(name).suffix in EXCLUDED_SUFFIXES or name == ".DS_Store"}
    shutil.copytree(PLUGIN, destination, ignore=ignore)
    for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, destination / name)
    if (ROOT / "docs" / "AVAC_QGIS_UI_REFERENCE.pdf").is_file():
        documentation = destination / "documentation"; documentation.mkdir(exist_ok=True)
        shutil.copy2(ROOT / "docs" / "AVAC_QGIS_UI_REFERENCE.pdf", documentation / "AVAC_QGIS_UI_REFERENCE.pdf")
    resources = destination / "resources"
    for pattern in ("avac-runtime-*.tar.gz", "wave-runtime-*.tar.gz", "runtime-release*.json", "wave-runtime-release*.json"):
        for stale in resources.glob(pattern): stale.unlink()
    avac_name = f"avac-runtime-{TARGET}-{runtime_version}.tar.gz"
    wave_name = f"wave-runtime-{TARGET}-{wave_version}.tar.gz"
    shutil.copy2(runtime_archive, resources / avac_name)
    shutil.copy2(wave_archive, resources / wave_name)
    (resources / "runtime-release.json").write_text(json.dumps({"runtimes": {TARGET: {
        "runtime_version": runtime_version,
        "platform": TARGET,
        "archive": avac_name,
        "runtime_manifest_sha256": manifest_digest(runtime_manifest_payload),
    }}}, indent=2) + "\n", encoding="utf-8")
    (resources / "wave-runtime-release.json").write_text(json.dumps({"runtimes": {TARGET: {
        "runtime_version": wave_version,
        "platform": TARGET,
        "archive": wave_name,
        "runtime_manifest_sha256": manifest_digest(wave_manifest_payload),
    }}}, indent=2) + "\n", encoding="utf-8")
    metadata = (destination / "metadata.txt").read_text(encoding="utf-8")
    metadata = metadata.replace("description=AVAC avalanche simulation integration for QGIS with managed native runtimes.", "description=AVAC avalanche simulation integration for QGIS (Windows AMD64).")
    metadata = metadata.replace("about=Prepare, run, and analyse AVAC avalanche simulations in QGIS using a bundled platform-specific runtime. Includes an opt-in Lake-Wave setup workflow. Tested with QGIS 3.44 LTS.", "about=Prepare, run, and analyse AVAC avalanche simulations in QGIS using the bundled Windows AMD64 runtime. Includes an opt-in Lake-Wave setup workflow. Tested with QGIS 3.44 LTS on Windows.")
    (destination / "metadata.txt").write_text(metadata, encoding="utf-8")
    readme = (destination / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("Install the ZIP matching your operating system. Each platform package has been tested with **QGIS 3.44 LTS** and contains its own managed runtime.", "This package is for **64-bit Windows (AMD64)** on both AMD and Intel processors, and has been tested with **QGIS 3.44 LTS**.")
    readme = readme.replace("The managed runtime installs in the operating system's application-data area and is reused by later runs.", "The managed runtime installs under the Windows application-data area and is reused by later runs.")
    (destination / "README.md").write_text(readme, encoding="utf-8")
    return destination


def write_zip(plugin_root: Path, output: Path) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(plugin_root.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(plugin_root.parent).as_posix()
                bundle.write(path, arcname)
                contents.append({"path": arcname, "bytes": path.stat().st_size, "sha256": digest(path)})
    return contents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--wave-runtime-archive", type=Path, required=True)
    parser.add_argument("--wave-runtime-version", required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "releases" / metadata_version() / TARGET)
    args = parser.parse_args()
    version = metadata_version(); archive = args.runtime_archive.resolve(); wave_archive = args.wave_runtime_archive.resolve()
    if not archive.is_file() or not wave_archive.is_file(): raise SystemExit("runtime archive not found")
    manifest = runtime_manifest(archive, args.runtime_version); wave_manifest = runtime_manifest(wave_archive, args.wave_runtime_version)
    dist = args.dist.resolve(); dist.mkdir(parents=True, exist_ok=True)
    filename = f"avac_qgis-{version}-{TARGET}.zip"; output = dist / filename
    if output.exists(): raise SystemExit(f"refusing to overwrite existing package: {output}")
    with tempfile.TemporaryDirectory(prefix="avac-qgis-windows-package-") as temporary:
        staged = copy_plugin(
            Path(temporary), archive, args.runtime_version, manifest,
            wave_archive, args.wave_runtime_version, wave_manifest,
        )
        assert_no_forbidden(staged); contents = write_zip(staged, output)
    package_hash = digest(output)
    (dist / f"{filename}.sha256").write_text(f"{package_hash}  {filename}\n", encoding="utf-8")
    (dist / "PACKAGE_CONTENTS.json").write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
    release = {"plugin_version": version, "minimum_qgis": "3.40", "runtime_version": args.runtime_version, "runtime_format": manifest["format"], "runtime_manifest_sha256": manifest_digest(manifest), "supported_os": "Windows", "supported_architecture": "AMD64", "supported_platform": TARGET, "tested_qgis": "3.44 LTS", "clawpack_version": manifest["clawpack"]["version"], "solver_sha256": manifest["solver"]["sha256"], "runtime_archive_sha256": digest(archive), "wave_runtime_version": args.wave_runtime_version, "wave_runtime_manifest_sha256": manifest_digest(wave_manifest), "wave_clawpack_version": wave_manifest["clawpack"]["version"], "wave_solver_sha256": wave_manifest["solver"]["sha256"], "wave_runtime_archive_sha256": digest(wave_archive), "plugin_zip_sha256": package_hash, "build_timestamp_utc": datetime.now(timezone.utc).isoformat()}
    (dist / "RELEASE_MANIFEST.json").write_text(json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"package: {output}\nsha256: {package_hash}\nfiles: {len(contents)}\nbytes: {output.stat().st_size}")


if __name__ == "__main__":
    main()
