"""No-Make execution preparation using a validated bundled AVAC runtime."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .clawpack_logging import suppress_pyclaw_file_logging
from .runtime import RuntimeValidationError, validate_runtime


def prepare_runtime_execution(runtime_root: str | Path, avac_dir: str | Path) -> Path:
    """Use QGIS Python + bundled Clawpack to write `.data`, then stage output.

    ``xgeoclaw`` follows Clawpack's established ``runclaw`` contract: it reads
    data files from its current working directory.  The prepared AVAC/Topo
    inputs remain in their normal locations and the two generated data files
    with absolute input paths preserve those references.
    """
    runtime_root, avac_dir = Path(runtime_root).expanduser().resolve(), Path(avac_dir).expanduser().resolve()
    manifest = validate_runtime(runtime_root)
    backend = runtime_root / "backend" / "AVAC" / "setrun.py"
    has_qinit = any((avac_dir / name).is_file() for name in ("init.avacbin", "init.xyz"))
    if not (avac_dir / "AVAC_configuration.yaml").is_file() or not (avac_dir.parent / "Topo" / "topography.asc").is_file() or not has_qinit:
        raise RuntimeValidationError("Prepared AVAC inputs are incomplete; prepare the run again before execution.")
    claw_source = runtime_root / manifest["clawpack"]["root"]
    if str(claw_source) not in sys.path:
        sys.path.insert(0, str(claw_source))
    output = avac_dir / "_output"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    previous = Path.cwd()
    previous_argv = sys.argv
    try:
        os.chdir(avac_dir)
        # Execute the manifest-verified backend without copying code into the
        # data workspace.  Supplying a virtual run-local __file__ preserves the
        # legacy backend's config/topography-relative path contract.
        namespace = {"__name__": "__main__", "__file__": str(avac_dir / "setrun.py")}
        # QGIS and test launchers can have unrelated command-line arguments;
        # setrun.py must never treat them as AVAC backend arguments.
        sys.argv = [str(avac_dir / "setrun.py")]
        with suppress_pyclaw_file_logging():
            exec(compile(backend.read_bytes(), str(avac_dir / "setrun.py"), "exec"), namespace)  # noqa: S102
    finally:
        sys.argv = previous_argv
        os.chdir(previous)
    data_files = sorted(avac_dir.glob("*.data"))
    if not data_files:
        raise RuntimeValidationError("Bundled Clawpack generated no .data files.")
    for data_file in data_files:
        shutil.copy2(data_file, output / data_file.name)
    return output


def runtime_solver(runtime_root: str | Path) -> Path:
    root = Path(runtime_root).expanduser().resolve()
    manifest = validate_runtime(root)
    return root / manifest["solver"]["path"]
