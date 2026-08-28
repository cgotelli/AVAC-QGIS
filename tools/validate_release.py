#!/usr/bin/env python3
"""Validate a release assembled by a platform package builder."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--package", type=Path, help="validate this ZIP when dist retains prior releases")
    parser.add_argument("--platform", default="macos-arm64", help="release target suffix, e.g. windows-amd64")
    args = parser.parse_args()
    dist = args.dist.resolve()
    manifest = json.loads((dist / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    package = args.package.resolve() if args.package else None
    if package is None:
        packages = list(dist.glob(f"avac_qgis-*-{args.platform}.zip"))
        if len(packages) != 1:
            raise SystemExit("expected exactly one release ZIP (or pass --package)")
        package = packages[0]
    if not package.is_file():
        raise SystemExit(f"release ZIP not found: {package}")
    if sha256(package) != manifest.get("plugin_zip_sha256"):
        raise SystemExit("plugin ZIP hash differs from release manifest")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if not names or any(not name.startswith("avac_qgis/") for name in names):
            raise SystemExit("ZIP does not have one avac_qgis/ root")
        required = {"avac_qgis/__init__.py", "avac_qgis/plugin.py", "avac_qgis/metadata.txt", "avac_qgis/resources/AVAC_configuration100.yaml", "avac_qgis/resources/runtime-release.json", "avac_qgis/resources/wave-runtime-release.json"}
        if not required.issubset(names):
            raise SystemExit("ZIP is missing mandatory plugin resources")
        bad = [name for name in names if "/tests/" in name or "__pycache__" in name or name.endswith((".pyc", ".DS_Store"))]
        if bad:
            raise SystemExit("development artifacts in ZIP: " + ", ".join(bad[:5]))
        for descriptor_name, release_key in (
            ("avac_qgis/resources/runtime-release.json", "runtime_manifest_sha256"),
            ("avac_qgis/resources/wave-runtime-release.json", "wave_runtime_manifest_sha256"),
        ):
            descriptor = json.loads(archive.read(descriptor_name))
            runtimes = descriptor.get("runtimes")
            record = runtimes.get(args.platform) if isinstance(runtimes, dict) else descriptor
            fingerprint = record.get("runtime_manifest_sha256") if isinstance(record, dict) else None
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                raise SystemExit(f"{descriptor_name} has no runtime manifest identity")
            if fingerprint != manifest.get(release_key):
                raise SystemExit(f"{descriptor_name} differs from release manifest")
    print(f"release validation: PASS ({package.name})")


if __name__ == "__main__":
    main()
