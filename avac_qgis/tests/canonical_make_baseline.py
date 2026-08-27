"""Build/run the canonical source baseline from QGIS-prepared scientific inputs.

This is deliberately a development-only regression harness.  It consumes the
already verified canonical QGIS input trio and invokes the historical Make
path in a new isolated directory; normal plugin execution never uses it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from avac_qgis.core.run_project import materialize_solver_tree, update_run_status


SOURCE_RUN = Path(os.environ["AVAC_QGIS_CANONICAL_RUNTIME_RUN"]).resolve()
DESTINATION = Path(os.environ["AVAC_QGIS_CANONICAL_MAKE_RUN"]).resolve()
BACKEND = Path(os.environ.get("AVAC_QGIS_CANONICAL_BACKEND", "avac-main/Lac_Clusaz/AVAC")).resolve()
CLAW = Path(os.environ["AVAC_QGIS_CLAW_ROOT"]).resolve()
PYTHON = Path(os.environ["AVAC_QGIS_CLAW_PYTHON"]).resolve()


def main() -> None:
    source_avac = SOURCE_RUN / "AVAC"
    if not (source_avac / "AVAC_configuration.yaml").is_file():
        raise RuntimeError(f"Canonical runtime input is incomplete: {source_avac}")
    avac = materialize_solver_tree(DESTINATION, BACKEND, {"canonical_fixture": "canonical_lac_clusaz_300"})
    shutil.copy2(SOURCE_RUN / "Topo" / "topography.asc", DESTINATION / "Topo" / "topography.asc")
    shutil.copy2(source_avac / "init.xyz", avac / "init.xyz")
    configuration = yaml.safe_load((source_avac / "AVAC_configuration.yaml").read_text(encoding="utf-8"))
    configuration["computation"]["topo_dir"] = str((DESTINATION / "Topo").resolve())
    configuration["file_names"]["topo_directory"] = str((DESTINATION / "Topo").resolve())
    (avac / "AVAC_configuration.yaml").write_text(yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8")
    update_run_status(avac, "prepared")
    environment = dict(os.environ)
    environment.update({"CLAW": str(CLAW), "CLAW_PYTHON": str(PYTHON), "OMP_NUM_THREADS": "8"})
    result = subprocess.run(["make", "clean"], cwd=avac, env=environment, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("make clean failed:\n" + result.stdout + result.stderr)
    result = subprocess.run(["make", ".output"], cwd=avac, env=environment, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("make .output failed:\n" + result.stdout + result.stderr)
    update_run_status(avac, "completed", exit_code=0)
    output = avac / "_output"
    print(f"CANONICAL_MAKE_BASELINE=PASS root={DESTINATION} output={output} files={len(list(output.iterdir()))}")


if __name__ == "__main__":
    main()
