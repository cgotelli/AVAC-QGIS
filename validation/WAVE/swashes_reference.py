"""Access the unmodified SWASHES 1.05.01 analytical generators."""

from __future__ import annotations

from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
SWASHES_ROOT = ROOT / "vendor" / "SWASHES-1.05.01"
SWASHES = SWASHES_ROOT / "bin" / "swashes"


def executable() -> Path:
    """Build and return the pinned analytical generator on first use."""
    if SWASHES.is_file():
        return SWASHES
    make = shutil.which("make")
    compiler = os.environ.get("CXX") or next(
        (
            path
            for name in ("g++-15", "g++-14", "g++-13", "g++-12", "g++", "clang++", "c++")
            if (path := shutil.which(name)) is not None
        ),
        None,
    )
    if make is None or compiler is None:
        raise RuntimeError(
            "Generating SWASHES references requires GNU Make and a C++ compiler."
        )
    (SWASHES_ROOT / "bin").mkdir(exist_ok=True)
    subprocess.run([make, f"CPP={compiler}", "swashes"], cwd=SWASHES_ROOT, check=True)
    if not SWASHES.is_file():
        raise RuntimeError(f"SWASHES build did not create {SWASHES}")
    return SWASHES


def solution(dimension: float, kind: int, domain: int, choice: int,
             nx: int, ny: int | None = None) -> tuple[np.ndarray, str]:
    """Return the numeric SWASHES output and its complete authoritative text."""
    program = executable()
    args = [str(program), str(dimension), str(kind), str(domain),
            str(choice), str(nx)]
    if ny is not None:
        args.append(str(ny))
    result = subprocess.run(args, cwd=SWASHES_ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"SWASHES failed:\n{result.stderr}")
    numeric = "\n".join(
        line for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    data = np.loadtxt(StringIO(numeric), ndmin=2)
    return data, result.stdout


def save_reference(directory: Path, data: np.ndarray, text: str,
                   header: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.savetxt(directory / "swashes_reference.csv", data, delimiter=",",
               header=header, comments="")
    (directory / "swashes_reference.txt").write_text(text, encoding="utf-8")
