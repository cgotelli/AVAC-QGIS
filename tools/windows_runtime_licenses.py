"""Copy offline, hash-pinned notices for the selected Windows runtime DLLs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

DEFAULT_BUNDLE = Path(__file__).with_suffix("")


def copy_runtime_licenses(
    destination: Path, libraries: list[Path], bundle: Path = DEFAULT_BUNDLE,
) -> None:
    """Fail closed if a new DLL/toolchain is paired with old license evidence.

    Alternative build toolchains may supply a reviewed bundle with the same
    schema. No network access or end-user dependency installation is used.
    """
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Invalid Windows runtime license bundle")
    supplied = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in libraries}
    if len(supplied) != len(libraries) or supplied != manifest.get("libraries"):
        raise ValueError("Runtime DLLs differ from the reviewed license bundle; review and update its hashes/notices")
    verified: list[Path] = []
    seen: set[str] = set()
    for entry in manifest["files"]:
        name = entry.get("path")
        if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name or ":" in name:
            raise ValueError("Unsafe runtime license filename")
        if name.casefold() in seen or name == "WINDOWS_RUNTIME_SOURCES.json":
            raise ValueError("Duplicate runtime license filename")
        seen.add(name.casefold())
        source = bundle / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Runtime license hash mismatch: {name}")
        verified.append(source)
    if not verified:
        raise ValueError("Runtime license bundle is empty")
    destination.mkdir(parents=True, exist_ok=True)
    for source in verified:
        shutil.copy2(source, destination / source.name)
    shutil.copy2(manifest_path, destination / "WINDOWS_RUNTIME_SOURCES.json")
