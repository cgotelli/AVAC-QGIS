"""Small notebook-facing API shared by every published validation case."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

from IPython.display import Image, display


VALIDATION_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationCase:
    """A validation case with safe helpers for execution and presentation."""

    family: str
    name: str
    path: Path

    def run(self, script: str | Path, *arguments: object, cwd: Path | None = None) -> None:
        target = Path(script)
        if not target.is_absolute():
            target = self.path / target
        command = [sys.executable, str(target), *(str(value) for value in arguments)]
        print("Running:", " ".join(command))
        subprocess.run(command, cwd=cwd or self.path, check=True)

    def json(self, relative_path: str | Path) -> dict[str, Any]:
        return json.loads((self.path / relative_path).read_text(encoding="utf-8"))

    def show(self, *relative_paths: str | Path) -> None:
        for relative_path in relative_paths:
            path = self.path / relative_path
            if not path.is_file():
                raise FileNotFoundError(f"Expected validation figure was not created: {path}")
            display(Image(filename=str(path)))


def validation_case(family: str, name: str) -> ValidationCase:
    path = VALIDATION_ROOT / family / name
    if not path.is_dir():
        raise FileNotFoundError(f"Validation case does not exist: {path}")
    return ValidationCase(family=family, name=name, path=path)
