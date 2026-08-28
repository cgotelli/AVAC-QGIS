#!/usr/bin/env python3
"""Build the AVAC and WAVE Windows AMD64 solver executables.

Clawpack's generic Makefile asks Python to consolidate a very large source
list.  On Windows that list can exceed the command-line limit before the
Fortran compiler is reached.  This helper performs the same consolidation in
Python and passes the resulting lists directly to mingw32-make.

The script builds developer artifacts only.  Use build_windows_runtime.py and
build_windows_plugin_package.py to turn the executables into an installable
plugin package.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAWPACK = ROOT / "avac-main" / "clawpack-v5.14.0"
TARGETS = {
    "AVAC": {
        "directory": ROOT / "avac-main" / "src" / "AVAC",
        "makefile": "Makefile.windows",
    },
    "WAVE": {
        "directory": ROOT / "avac-main" / "src" / "WAVE",
        "makefile": "Makefile.windows",
    },
}


def _variable_blocks(path: Path) -> dict[str, list[str]]:
    """Return whitespace-separated values from make variable assignments."""
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, list[str]] = {}
    active_name: str | None = None
    active_lines: list[str] = []

    def finish() -> None:
        nonlocal active_name, active_lines
        if active_name is not None:
            text = " ".join(active_lines).replace("\\", " ")
            values.setdefault(active_name, []).extend(text.split())
        active_name = None
        active_lines = []

    assignment = re.compile(r"^(COMMON_MODULES|COMMON_SOURCES|MODULES|SOURCES|EXCLUDE_MODULES|EXCLUDE_SOURCES)\s*(?:\+?=)\s*(.*)$")
    for line in lines:
        match = assignment.match(line)
        if match:
            finish()
            active_name = match.group(1)
            active_lines = [match.group(2)]
            continue
        if active_name is not None and (not line.strip() or line[:1].isspace()):
            active_lines.append(line)
            continue
        finish()
    finish()
    return values


def _expand(value: str, *, clawpack: Path, project: Path) -> Path:
    replacements = {
        "$(CLAW)": clawpack,
        "$(AMRLIB)": clawpack / "amrclaw" / "src" / "2d",
        "$(GEOLIB)": clawpack / "geoclaw" / "src" / "2d" / "shallow",
    }
    for token, replacement in replacements.items():
        value = value.replace(token, replacement.as_posix())
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project / candidate
    return candidate.resolve()


def _stem(path: Path) -> str:
    return path.stem.lower()


def _consolidated_sources(directory: Path, *, real_world_topo: bool) -> tuple[list[Path], list[Path]]:
    custom = _variable_blocks(directory / "Makefile")
    common = _variable_blocks(CLAWPACK / "geoclaw" / "src" / "2d" / "shallow" / "Makefile.geoclaw")

    def paths(values: list[str]) -> list[Path]:
        return [_expand(value, clawpack=CLAWPACK, project=directory) for value in values]

    custom_sources = paths(custom.get("SOURCES", []))
    custom_modules = paths(custom.get("MODULES", []))
    if directory.name == "AVAC":
        # qinit.f90 belongs to the synthetic-topography branch.  The release
        # solver uses the real-world branch, matching the Makefile default.
        custom_sources = [path for path in custom_sources if not real_world_topo or path.name != "qinit.f90"]
        custom_modules = [path for path in custom_modules if real_world_topo or path.name != "qinit_module.f90"]
    excluded_sources = paths(custom.get("EXCLUDE_SOURCES", []))
    excluded_modules = paths(custom.get("EXCLUDE_MODULES", []))
    common_sources = paths(common.get("COMMON_SOURCES", []))
    common_modules = paths(common.get("COMMON_MODULES", []))

    def unique(values: list[Path]) -> list[Path]:
        seen: set[str] = set()
        result: list[Path] = []
        for path in values:
            if _stem(path) not in seen:
                result.append(path)
                seen.add(_stem(path))
        return result

    def consolidate(custom_values: list[Path], common_values: list[Path], excluded: list[Path]) -> list[Path]:
        custom_values = unique(custom_values)
        excluded_stems = {_stem(path) for path in [*custom_values, *excluded]}
        return [*custom_values, *(path for path in unique(common_values) if _stem(path) not in excluded_stems)]

    return (
        consolidate(custom_sources, common_sources, excluded_sources),
        consolidate(custom_modules, common_modules, excluded_modules),
    )


def _find_shell(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "sh.exe",
        shutil.which("sh"),
        shutil.which("bash"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _make_command(make: str, target: dict[str, Path], sources: list[Path], modules: list[Path], *, shell: str | None, real_world_topo: bool) -> list[str]:
    command = [make, "-B", "-f", target["makefile"], "EXE=xgeoclaw.exe", "AVAC_WINDOWS_BUILD=1", f"REAL_WORLD_TOPO={int(real_world_topo)}"]
    command.extend([f"SOURCES={' '.join(path.as_posix() for path in sources)}"])
    command.extend([f"MODULES={' '.join(path.as_posix() for path in modules)}"])
    if shell:
        command.append(f"SHELL={Path(shell).as_posix()}")
    # These checks are already performed by this script.  Avoid invoking the
    # long check_src.py command from make, which is the Windows failure mode.
    command.extend(["SOURCE_CONFLICTS=", "MODULES_CONFLICTS="])
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", default="mingw32-make", help="make executable (default: mingw32-make)")
    parser.add_argument("--fc", default="gfortran", help="Fortran compiler (default: gfortran)")
    parser.add_argument("--python", default=shutil.which("python") or "python", help="Python executable used by make")
    parser.add_argument("--shell", help="POSIX shell used by make; auto-detected when omitted")
    parser.add_argument("--target", choices=["AVAC", "WAVE", "all"], default="all")
    parser.add_argument("--real-world-topo", type=int, choices=[0, 1], default=1, help="AVAC topography branch (default: 1)")
    parser.add_argument("--strip", action=argparse.BooleanOptionalAction, default=True, help="strip release executables (default: enabled)")
    args = parser.parse_args()

    make = shutil.which(args.make) or args.make
    fc = shutil.which(args.fc) or args.fc
    python = shutil.which(args.python) or args.python
    if not Path(make).is_file() and shutil.which(make) is None:
        raise SystemExit(f"make executable not found: {args.make}")
    if not Path(fc).is_file() and shutil.which(fc) is None:
        raise SystemExit(f"Fortran compiler not found: {args.fc}")
    if not Path(python).is_file() and shutil.which(python) is None:
        raise SystemExit(f"Python executable not found: {args.python}")
    strip = shutil.which("strip")
    if args.strip and strip is None:
        raise SystemExit("strip.exe not found; install the MinGW binutils or pass --no-strip.")

    shell = _find_shell(args.shell)
    if os.name == "nt" and shell is None:
        raise SystemExit("Git Bash sh.exe is required to build the Windows solver sources.")
    selected = list(TARGETS) if args.target == "all" else [args.target]
    environment = os.environ.copy()
    environment.update({
        "CLAW": CLAWPACK.as_posix(),
        "CLAW_PYTHON": Path(python).as_posix(),
        "FC": Path(fc).as_posix(),
        "CLAW_FC": Path(fc).as_posix(),
    })
    if shell:
        environment["SHELL"] = Path(shell).as_posix()
        shell_path = Path(shell).resolve()
        shell_directories = [str(shell_path.parent), str(shell_path.parent.parent)]
        environment["PATH"] = os.pathsep.join([*shell_directories, environment.get("PATH", "")])

    for name in selected:
        target = TARGETS[name]
        sources, modules = _consolidated_sources(target["directory"], real_world_topo=bool(args.real_world_topo))
        command = _make_command(make, target, sources, modules, shell=shell, real_world_topo=bool(args.real_world_topo))
        print(f"Building {name}: {target['directory'] / 'xgeoclaw.exe'}")
        subprocess.run(command, cwd=target["directory"], env=environment, check=True)
        executable = target["directory"] / "xgeoclaw.exe"
        if not executable.is_file():
            raise SystemExit(f"make completed without producing {executable}")
        if args.strip:
            subprocess.run([strip, "--strip-all", str(executable)], check=True)
        print(f"Built {executable} ({executable.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
