#!/usr/bin/env python3
"""Package a pre-built Windows AMD64 AVAC4QGIS solver as a managed runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path


TARGET = "windows-amd64"
EXCLUDED = {".git", ".github", "__pycache__", "build"}
EXCLUDED_SUFFIXES = {".o", ".mod", ".a", ".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in EXCLUDED or Path(name).suffix.lower() in EXCLUDED_SUFFIXES}
    shutil.copytree(source, destination, ignore=ignore)


def file_record(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--backend-name", required=True)
    parser.add_argument("--clawpack", type=Path, required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path, action="append", default=[])
    parser.add_argument("--license", type=Path, action="append", default=[])
    args = parser.parse_args()

    solver = args.solver.resolve()
    backend = args.backend.resolve()
    clawpack = args.clawpack.resolve()
    libraries = [path.resolve() for path in args.library]
    if not solver.is_file() or solver.suffix.lower() != ".exe":
        raise SystemExit(f"Windows solver executable not found: {solver}")
    if not (backend / "setrun.py").is_file():
        raise SystemExit(f"Backend must contain setrun.py: {backend}")
    if not (clawpack / "clawpack" / "__init__.py").is_file():
        raise SystemExit(f"Clawpack source is incomplete: {clawpack}")
    if not libraries or any(not item.is_file() or item.suffix.lower() != ".dll" for item in libraries):
        raise SystemExit("Every --library must be an existing DLL.")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing runtime archive: {output}")
    with tempfile.TemporaryDirectory(prefix="avac-windows-runtime-") as temporary:
        root = Path(temporary) / TARGET
        bin_dir = root / "bin"; bin_dir.mkdir(parents=True)
        lib_dir = root / "lib"; lib_dir.mkdir()
        backend_dir = root / "backend" / args.backend_name; backend_dir.parent.mkdir(parents=True)
        claw_dir = root / "clawpack"; licenses = root / "licenses"; licenses.mkdir()
        solver_target = bin_dir / "xgeoclaw.exe"; shutil.copy2(solver, solver_target)
        for library in libraries:
            shutil.copy2(library, lib_dir / library.name)
        copy_tree(backend, backend_dir)
        copy_tree(clawpack, claw_dir)
        for license_file in args.license:
            candidate = license_file.resolve()
            if not candidate.is_file():
                raise SystemExit(f"License file not found: {candidate}")
            shutil.copy2(candidate, licenses / candidate.name)
        init_text = (clawpack / "clawpack" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", init_text)
        manifest = {
            "format": 1,
            "runtime_version": args.runtime_version,
            "platform": TARGET,
            "architecture": "amd64",
            "solver": file_record(root, solver_target),
            "native_libraries": [file_record(root, lib_dir / item.name) for item in libraries],
            "backend": [file_record(root, path) for path in sorted(backend_dir.rglob("*")) if path.is_file()],
            "clawpack": {
                "version": match.group(1) if match else "5.14.0",
                "root": "clawpack",
                "source_sha256": sha256(claw_dir / "clawpack" / "__init__.py"),
            },
        }
        (root / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(root, arcname=TARGET)
    print(f"runtime archive: {output}\nsha256: {sha256(output)}")


if __name__ == "__main__":
    main()
