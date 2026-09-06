#!/usr/bin/env python3
"""Package a relocatable Linux x86_64 AVAC4QGIS solver runtime.

The resulting archive carries every non-glibc shared library required by the
solver.  It sets ELF RUNPATHs only on copied files, so end users need QGIS but
do not need a compiler, Clawpack, OpenMP, BLAS, LAPACK, or GNU Fortran runtime
packages installed separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


TARGET = "linux-x86_64"
EXCLUDED = {".git", ".github", "__pycache__", "build"}
EXCLUDED_SUFFIXES = {".o", ".mod", ".a", ".pyc", ".pyo"}
# glibc and the dynamic loader must come from the host distribution.  Bundling
# them is neither portable nor safe; all other discovered dependencies are
# copied into the runtime and loaded through package-local RUNPATHs.
SYSTEM_LIBRARY_PREFIXES = (
    "libc.so.", "libdl.so.", "libm.so.", "libpthread.so.", "librt.so.",
    "libresolv.so.", "libutil.so.", "libnsl.so.", "libmvec.so.", "ld-linux",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path)}


def copy_tree(source: Path, destination: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {
            name for name in names
            if name in EXCLUDED or Path(name).suffix.lower() in EXCLUDED_SUFFIXES
        }
    shutil.copytree(source, destination, ignore=ignore)


def command(*args: str) -> str:
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


def require_linux_x86_64(path: Path) -> None:
    header = command("readelf", "-h", str(path))
    if "ELF64" not in header or "Advanced Micro Devices X86-64" not in header:
        raise RuntimeError(f"Expected a Linux x86_64 ELF artifact, got: {path}")


def _is_system_library(name: str) -> bool:
    return name.startswith("linux-vdso") or name.startswith(SYSTEM_LIBRARY_PREFIXES)


def linked_libraries(path: Path) -> list[tuple[str, Path]]:
    """Return resolved, non-glibc ELF dependencies reported by ``ldd``."""
    result: list[tuple[str, Path]] = []
    for line in command("ldd", str(path)).splitlines():
        line = line.strip()
        if not line or line.startswith("linux-vdso"):
            continue
        if "=> not found" in line:
            raise RuntimeError(f"Unresolved shared library in {path}: {line}")
        match = re.match(r"([^\s]+)\s+=>\s+(/[^\s]+)", line)
        if match:
            name, resolved = match.groups()
        else:
            direct = re.match(r"(/[^\s]+)", line)
            if direct is None:
                raise RuntimeError(f"Cannot parse ldd output for {path}: {line}")
            resolved = direct.group(1)
            name = Path(resolved).name
        if not _is_system_library(name):
            candidate = Path(resolved)
            if not candidate.is_file():
                raise RuntimeError(f"ldd resolved {name} to a missing file: {candidate}")
            result.append((name, candidate))
    return result


def package_libraries(solver: Path, lib_dir: Path) -> list[Path]:
    """Recursively copy all non-system ELF dependencies to ``lib_dir``."""
    pending = [solver]
    scanned: set[Path] = set()
    copied: dict[str, Path] = {}
    while pending:
        artifact = pending.pop()
        identity = artifact.resolve()
        if identity in scanned:
            continue
        scanned.add(identity)
        for name, source in linked_libraries(artifact):
            target = lib_dir / name
            existing = copied.get(name)
            if existing is not None and existing.resolve() != source.resolve():
                raise RuntimeError(
                    f"Library name collision for {name}: {existing} and {source}"
                )
            if existing is None:
                shutil.copy2(source, target)
                target.chmod(target.stat().st_mode | 0o200)
                copied[name] = source
                pending.append(source)
    return [lib_dir / name for name in sorted(copied)]


def set_runpath(path: Path, value: str) -> None:
    subprocess.run(("patchelf", "--set-rpath", value, str(path)), check=True)
    if command("patchelf", "--print-rpath", str(path)).strip() != value:
        raise RuntimeError(f"Could not set the expected RUNPATH on {path}")


def clawpack_version(clawpack: Path) -> str:
    init = clawpack / "clawpack" / "__init__.py"
    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", init.read_text(encoding="utf-8"))
    return match.group(1) if match else "5.14.0"


def minimum_glibc_version(artifacts: list[Path]) -> str:
    """Return the newest GLIBC symbol version required by bundled ELF files."""
    versions: set[tuple[int, int]] = set()
    for artifact in artifacts:
        for major, minor in re.findall(r"GLIBC_(\d+)\.(\d+)", command("objdump", "-T", str(artifact))):
            versions.add((int(major), int(minor)))
    if not versions:
        raise RuntimeError("Could not determine a GLIBC requirement from the runtime artifacts.")
    major, minor = max(versions)
    return f"{major}.{minor}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--backend-name", choices=("AVAC", "WAVE"), required=True)
    parser.add_argument("--clawpack", type=Path, required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--license", type=Path, action="append", default=[])
    args = parser.parse_args()

    if platform.system().lower() != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise SystemExit("The Linux runtime builder must run on Linux x86_64.")
    if shutil.which("patchelf") is None:
        raise SystemExit("patchelf is required to make the Linux runtime relocatable.")
    solver, backend, clawpack, output = (
        args.solver.resolve(), args.backend.resolve(), args.clawpack.resolve(), args.output.resolve()
    )
    if not solver.is_file():
        raise SystemExit(f"Linux solver executable not found: {solver}")
    if not (backend / "setrun.py").is_file():
        raise SystemExit(f"Backend must contain setrun.py: {backend}")
    if not (clawpack / "clawpack" / "__init__.py").is_file():
        raise SystemExit(f"Clawpack source is incomplete: {clawpack}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing runtime archive: {output}")
    require_linux_x86_64(solver)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="avac-linux-runtime-") as temporary:
        root = Path(temporary) / TARGET
        bin_dir, lib_dir = root / "bin", root / "lib"
        bin_dir.mkdir(parents=True); lib_dir.mkdir()
        solver_target = bin_dir / "xgeoclaw"
        source_hash = sha256(solver)
        shutil.copy2(solver, solver_target)
        solver_target.chmod(solver_target.stat().st_mode | 0o500)
        libraries = package_libraries(solver, lib_dir)
        set_runpath(solver_target, "$ORIGIN/../lib")
        for library in libraries:
            require_linux_x86_64(library)
            set_runpath(library, "$ORIGIN")
        glibc_requirement = minimum_glibc_version([solver_target, *libraries])

        # Re-check the staged executable: every dependency outside glibc must
        # resolve to this archive's lib directory, never a build-machine path.
        for name, resolved in linked_libraries(solver_target):
            if resolved.parent.resolve() != lib_dir.resolve():
                raise RuntimeError(
                    f"Bundled solver still resolves {name} outside the runtime: {resolved}"
                )

        backend_dir = root / "backend" / args.backend_name
        claw_dir = root / "clawpack"
        licenses = root / "licenses"; licenses.mkdir()
        copy_tree(backend, backend_dir)
        copy_tree(clawpack, claw_dir)
        for license_file in args.license:
            candidate = license_file.resolve()
            if not candidate.is_file():
                raise SystemExit(f"License file not found: {candidate}")
            shutil.copy2(candidate, licenses / candidate.name)

        manifest = {
            "format": 1,
            "runtime_version": args.runtime_version,
            "platform": TARGET,
            "architecture": "x86_64",
            "minimum_glibc_version": glibc_requirement,
            "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "toolchain": {"platform": platform.platform(), "python": platform.python_version()},
            "solver": {**file_record(root, solver_target), "source_sha256": source_hash},
            "native_libraries": [file_record(root, item) for item in libraries],
            "backend": [file_record(root, item) for item in sorted(backend_dir.rglob("*")) if item.is_file()],
            "clawpack": {
                "version": clawpack_version(clawpack),
                "root": "clawpack",
                "source_sha256": sha256(claw_dir / "clawpack" / "__init__.py"),
                "files": [file_record(root, item) for item in sorted(claw_dir.rglob("*")) if item.is_file()],
            },
            "licenses": [file_record(root, item) for item in sorted(licenses.iterdir()) if item.is_file()],
        }
        (root / "runtime-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(root, arcname=TARGET)
    print(f"runtime archive: {output}\nsha256: {sha256(output)}")


if __name__ == "__main__":
    main()
