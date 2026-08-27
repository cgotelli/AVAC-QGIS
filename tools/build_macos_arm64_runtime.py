#!/usr/bin/env python3
"""Build a relocatable AVAC arm64 runtime development artifact.

This tool is intentionally a build input, not a normal plugin execution path.
It copies a previously built AVAC solver and its *actual* macOS runtime
dependencies, rewrites only the copies, records a manifest, and produces a
first-use-installable tarball.  It does not compile AVAC and never mutates
Homebrew's libraries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


RUNTIME_LIBRARIES = (
    "libgfortran.5.dylib",
    "libgomp.1.dylib",
    "libquadmath.0.dylib",
    "libgcc_s.1.1.dylib",
)

# Direct packaged execution needs only the tested Python data writer.  The
# compiled Fortran sources/Makefile are intentionally not copied: normal runs
# never compile.  They remain development-build inputs.
BACKEND_FILES = ("setrun.py",)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command(*args: str) -> str:
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


def require_arm64(path: Path) -> None:
    description = command("file", str(path))
    if "arm64" not in description:
        raise RuntimeError(f"Expected an arm64 Mach-O artifact, got: {description.strip()}")


def copy_clawpack_source(source: Path, destination: Path) -> None:
    """Copy the version-pinned tree required by setrun/fgout readers.

    Keeping the complete source tree is deliberate for this first artifact:
    its package namespace dynamically exposes subpackages from several source
    directories, and correctness is more important than premature pruning.
    """
    # Object files are development build residue. They embed absolute source
    # paths, are not imported by the packaged Python readers, and add sizeable
    # accidental bloat to the runtime.
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.o", "*.mod", "*.a", "build", ".git", ".github")
    shutil.copytree(source, destination, ignore=ignored)


def remove_absolute_rpaths(path: Path) -> None:
    """Remove build-machine rpaths while retaining package-local/system ones."""
    output = command("otool", "-l", str(path)).splitlines()
    for index, line in enumerate(output):
        if line.strip() != "cmd LC_RPATH":
            continue
        for candidate in output[index + 1:index + 5]:
            text = candidate.strip()
            if text.startswith("path "):
                rpath = text.split(" (offset", 1)[0][5:]
                if rpath.startswith("/"):
                    subprocess.run(("install_name_tool", "-delete_rpath", rpath, str(path)), check=True)
                break


def redact_build_paths(path: Path) -> None:
    """Remove accidental build-machine paths from copied Mach-O diagnostics.

    GNU Fortran embeds source locations in run-time error strings. They are
    not needed to execute AVAC, but cannot appear in a distributable. Keep
    byte offsets intact so this does not change executable layout.
    """
    payload = path.read_bytes()
    pattern = re.compile(rb"/(?:Users|private/tmp|opt/homebrew)/[^\x00\r\n]{1,1024}")
    def replacement(match: re.Match[bytes]) -> bytes:
        return b"<build-path>".ljust(len(match.group(0)), b"\0")
    cleaned = pattern.sub(replacement, payload)
    path.write_bytes(cleaned)


def copy_backend(source: Path, destination: Path, backend_name: str) -> list[dict[str, str]]:
    missing = [name for name in BACKEND_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError("Runtime backend is missing: " + ", ".join(missing))
    destination.mkdir(parents=True)
    records = []
    for name in BACKEND_FILES:
        target = destination / name
        shutil.copy2(source / name, target)
        records.append({"path": f"backend/{backend_name}/{name}", "sha256": sha256(target)})
    return records


def write_archive(runtime: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as output:
        output.add(runtime, arcname=runtime.name)


def clawpack_version(claw_root: Path) -> str:
    for line in (claw_root / "clawpack" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].split("#", 1)[0].strip().strip("'\"")
    raise RuntimeError("Could not determine Clawpack version from clawpack/__init__.py")


def build(args: argparse.Namespace) -> tuple[Path, Path]:
    solver = args.solver.resolve()
    backend = (args.backend or solver.parent).resolve()
    claw_root = args.claw_root.resolve()
    output = args.output.resolve()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", args.backend_name):
        raise RuntimeError("Runtime backend name must be a simple directory name.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", args.archive_prefix):
        raise RuntimeError("Runtime archive prefix must be a simple filename component.")
    # Preserve the spelling passed to the linker.  ``current`` is a symlink in
    # Homebrew's GCC keg; resolving it before ``install_name_tool -change``
    # would fail to match the install name recorded in xgeoclaw.
    gcc_lib = args.gcc_lib.expanduser().absolute()
    if platform.machine() != "arm64":
        raise RuntimeError("This build tool currently produces an Apple Silicon arm64 runtime only.")
    if not solver.is_file():
        raise RuntimeError(f"Solver does not exist: {solver}")
    if not (claw_root / "clawpack" / "__init__.py").is_file():
        raise RuntimeError(f"Not a complete Clawpack source root: {claw_root}")
    require_arm64(solver)
    missing = [name for name in RUNTIME_LIBRARIES if not (gcc_lib / name).is_file()]
    if missing:
        raise RuntimeError("GCC runtime directory is missing: " + ", ".join(missing))

    runtime = output / "runtime" / args.version / "arm64"
    if runtime.exists():
        raise RuntimeError(f"Refusing to overwrite existing runtime artifact: {runtime}")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="avac-runtime-", dir=runtime.parent)) / "arm64"
    try:
        bin_dir, lib_dir = staging / "bin", staging / "lib"
        python_dir, licenses = staging / "python", staging / "licenses"
        bin_dir.mkdir(parents=True); lib_dir.mkdir(); python_dir.mkdir(); licenses.mkdir()
        copied_solver = bin_dir / "xgeoclaw"
        shutil.copy2(solver, copied_solver)
        copied_solver.chmod(copied_solver.stat().st_mode | stat.S_IWUSR)
        for name in RUNTIME_LIBRARIES:
            target = lib_dir / name
            shutil.copy2(gcc_lib / name, target)
            # Homebrew libraries can be installed read-only.  The runtime
            # builder rewrites only these staged copies, so make the owner
            # copy writable before install_name_tool updates its load paths.
            target.chmod(target.stat().st_mode | stat.S_IWUSR)
            require_arm64(target)

        # The executable must refer only to its sibling runtime library folder.
        for name in RUNTIME_LIBRARIES[:3]:
            original = str(gcc_lib / name)
            subprocess.run(("install_name_tool", "-change", original, f"@loader_path/../lib/{name}", str(copied_solver)), check=True)
        # libgfortran has two transitive @rpath requirements.  Resolve them
        # relative to the library itself, not a user's loader-path or Homebrew.
        copied_fortran = lib_dir / "libgfortran.5.dylib"
        subprocess.run(("install_name_tool", "-change", "@rpath/libquadmath.0.dylib", "@loader_path/libquadmath.0.dylib", str(copied_fortran)), check=True)
        subprocess.run(("install_name_tool", "-change", "@rpath/libgcc_s.1.1.dylib", "@loader_path/libgcc_s.1.1.dylib", str(copied_fortran)), check=True)
        for name in RUNTIME_LIBRARIES:
            subprocess.run(("install_name_tool", "-id", f"@loader_path/{name}", str(lib_dir / name)), check=True)
        remove_absolute_rpaths(copied_solver)
        # Remove compiler/debug records which can otherwise leak source-tree
        # locations into a distributable binary. Runtime code is unchanged.
        subprocess.run(("strip", "-S", str(copied_solver)), check=True)
        redact_build_paths(copied_solver)
        # ``install_name_tool`` invalidates the copied libraries' signatures.
        # Re-sign only the copied runtime artifacts before hashing/archiving so
        # macOS can load them under normal library-validation rules.
        for artifact in (copied_solver, *(lib_dir / name for name in RUNTIME_LIBRARIES)):
            subprocess.run(("codesign", "--force", "--sign", "-", str(artifact)), check=True)
            subprocess.run(("codesign", "--verify", "--strict", str(artifact)), check=True)

        copy_clawpack_source(claw_root, python_dir / "clawpack-src")
        backend_records = copy_backend(backend, staging / "backend" / args.backend_name, args.backend_name)
        for name in ("COPYING", "COPYING.LIB", "COPYING.RUNTIME"):
            candidate = args.gcc_prefix / name
            if candidate.is_file():
                shutil.copy2(candidate, licenses / f"gcc-{name}")
        shutil.copy2(claw_root / "LICENSE", licenses / "clawpack-LICENSE")

        def relative_otool(path: Path) -> str:
            return command("otool", "-L", str(path)).replace(str(staging), "<runtime>").strip()

        manifest = {
            "format": 1,
            "runtime_version": args.version,
            "architecture": "arm64",
            "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            # The archive must not disclose or depend on the builder's local
            # Homebrew prefix.  Its copied binaries use package-local loader
            # paths and all source locations are deliberately omitted.
            "toolchain": {"platform": platform.platform(), "python": sys.version.split()[0]},
            "solver": {"path": "bin/xgeoclaw", "sha256": sha256(copied_solver), "source_sha256": sha256(solver)},
            "native_libraries": [{"path": f"lib/{name}", "sha256": sha256(lib_dir / name), "otool": relative_otool(lib_dir / name)} for name in RUNTIME_LIBRARIES],
            "clawpack": {"version": clawpack_version(claw_root), "root": "python/clawpack-src", "source_sha256": sha256(claw_root / "clawpack" / "__init__.py")},
            "backend": backend_records,
            "licenses": [path.name for path in sorted(licenses.iterdir())],
        }
        (staging / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # Fail the build rather than emitting an artifact with a Homebrew loader path.
        linkage = command("otool", "-L", str(copied_solver))
        if "/opt/homebrew/" in linkage:
            raise RuntimeError("Bundled solver still contains a Homebrew loader reference:\n" + linkage)
        os.replace(staging, runtime)
    except Exception:
        shutil.rmtree(staging.parent, ignore_errors=True)
        raise
    archive = output / f"{args.archive_prefix}-runtime-macos-arm64-{args.version}.tar.gz"
    write_archive(runtime, archive)
    return runtime, archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--backend", type=Path, help="AVAC directory containing the direct runtime backend (defaults to solver parent)")
    parser.add_argument("--backend-name", default="AVAC", help="Runtime backend directory name (AVAC or Wave)")
    parser.add_argument("--archive-prefix", default="avac", help="Archive filename prefix")
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--gcc-lib", type=Path, default=Path("/opt/homebrew/opt/gcc/lib/gcc/current"))
    parser.add_argument("--gcc-prefix", type=Path, default=Path("/opt/homebrew/opt/gcc"))
    parser.add_argument("--archive-only", action="store_true", help="remove the generated expanded runtime after creating the archive")
    args = parser.parse_args()
    runtime, archive = build(args)
    print(f"runtime: {runtime}")
    print(f"archive: {archive}")
    if args.archive_only:
        shutil.rmtree(runtime.parent)
        print("expanded runtime removed; archive retained")


if __name__ == "__main__":
    main()
