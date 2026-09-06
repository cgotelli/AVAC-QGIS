#!/usr/bin/env python3
"""Change only a validated Windows runtime's version; never rebuild its solver."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reversion_archive(source: Path, target: Path, expected_version: str, version: str) -> dict:
    """Preserve every member payload except runtime-manifest.json byte-for-byte."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid release version")
    if target.exists():
        raise ValueError(f"Refusing to overwrite runtime archive: {target}")
    old_bytes = source.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(old_bytes), mode="r:gz") as old:
        entries = old.getmembers()
        names: set[str] = set()
        payloads: dict[str, bytes] = {}
        for entry in entries:
            parts = PurePosixPath(entry.name).parts
            if (not parts or parts[0] != "windows-amd64" or ".." in parts
                    or "\\" in entry.name or ":" in entry.name
                    or entry.name.casefold() in names or not (entry.isfile() or entry.isdir())):
                raise ValueError(f"Unsafe or duplicate runtime member: {entry.name}")
            names.add(entry.name.casefold())
            if entry.isfile():
                payloads[entry.name] = old.extractfile(entry).read()
    manifest_name = "windows-amd64/runtime-manifest.json"
    original_manifest = json.loads(payloads[manifest_name])
    if (original_manifest.get("format") != 1
            or original_manifest.get("platform") != "windows-amd64"
            or original_manifest.get("architecture") != "amd64"
            or original_manifest.get("runtime_version") != expected_version):
        raise ValueError("Runtime identity does not match the requested source")
    records = [original_manifest["solver"], *original_manifest["native_libraries"],
               *original_manifest["backend"], *original_manifest["clawpack"]["files"],
               *original_manifest["licenses"]]
    declared = {"windows-amd64/" + record["path"] for record in records}
    if len(declared) != len(records) or set(payloads) != declared | {manifest_name}:
        raise ValueError("Runtime file manifest is incomplete or contains duplicate records")
    for record in records:
        if digest(payloads["windows-amd64/" + record["path"]]) != record["sha256"]:
            raise ValueError(f"Runtime member hash mismatch: {record['path']}")
    manifest = copy.deepcopy(original_manifest)
    manifest["runtime_version"] = version
    changed_manifest = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as new:
        for member in entries:
            entry = copy.copy(member)
            if member.isfile():
                data = changed_manifest if member.name == manifest_name else payloads[member.name]
                entry.size = len(data)
                new.addfile(entry, io.BytesIO(data))
            else:
                new.addfile(entry)
    with tarfile.open(target, "r:gz") as check:
        actual = {m.name: check.extractfile(m).read() for m in check.getmembers() if m.isfile()}
    changes = [name for name in payloads if payloads[name] != actual[name]]
    if set(actual) != set(payloads) or changes != [manifest_name]:
        raise ValueError("Reversion unexpectedly changed runtime payload")
    restored = dict(manifest, runtime_version=expected_version)
    assert restored == original_manifest
    return {
        "source_version": expected_version, "runtime_version": version,
        "source_archive_sha256": digest(old_bytes),
        "archive_sha256": digest(target.read_bytes()),
        "source_manifest_sha256": digest(json.dumps(original_manifest, sort_keys=True, separators=(",", ":")).encode()),
        "runtime_manifest_sha256": digest(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()),
        "solver_sha256": manifest["solver"]["sha256"],
        "unchanged_manifested_files": len(records),
        "changed_files": changes,
        "changed_manifest_fields": ["runtime_version"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(json.dumps(reversion_archive(args.source, args.output, args.expected_version, args.version), indent=2))


if __name__ == "__main__":
    main()
