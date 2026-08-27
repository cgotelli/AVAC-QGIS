"""Exercise bundled Clawpack data generation inside the QGIS Python process.

Run with QGIS' ``--code`` option and set these explicit test-only variables:
``AVAC_QGIS_RUNTIME_ROOT`` (the extracted arm64 runtime) and
``AVAC_QGIS_RUNTIME_AVAC_DIR`` (a prepared run's AVAC directory).
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication

RUNTIME = Path(os.environ["AVAC_QGIS_RUNTIME_ROOT"]).resolve()
AVAC = Path(os.environ["AVAC_QGIS_RUNTIME_AVAC_DIR"]).resolve()
CLAW_SOURCE = RUNTIME / "python" / "clawpack-src"
REQUIRED_DATA = (
    "claw.data", "amr.data", "geoclaw.data", "refinement.data", "topo.data",
    "qinit.data", "fgmax_grids.data", "fgout_grids.data", "gauges.data",
)


def verify() -> None:
    try:
        workspace = Path(os.environ["AVAC_QGIS_WORKSPACE"]).resolve()
        sys.path.insert(0, str(workspace))
        from avac_qgis.core.runtime_execution import prepare_runtime_execution  # noqa: PLC0415
        if not (RUNTIME / "runtime-manifest.json").is_file():
            raise RuntimeError(f"Runtime manifest missing: {RUNTIME}")
        if not (CLAW_SOURCE / "clawpack" / "__init__.py").is_file():
            raise RuntimeError(f"Bundled Clawpack source missing: {CLAW_SOURCE}")
        if not (AVAC / "setrun.py").is_file() or not (AVAC / "AVAC_configuration.yaml").is_file():
            raise RuntimeError(f"Prepared AVAC inputs missing: {AVAC}")
        sys.path.insert(0, str(CLAW_SOURCE))
        import numpy  # noqa: PLC0415
        import yaml  # noqa: PLC0415
        import clawpack  # noqa: PLC0415
        from clawpack.clawutil import data  # noqa: PLC0415,F401
        from clawpack.geoclaw import fgmax_tools, fgout_tools  # noqa: PLC0415,F401

        before = {path.name for path in AVAC.glob("*.data")}
        output = prepare_runtime_execution(RUNTIME, AVAC)
        missing = [name for name in REQUIRED_DATA if not (AVAC / name).is_file() or not (output / name).is_file()]
        if missing:
            raise RuntimeError("Bundled Clawpack did not generate required data: " + ", ".join(missing))
        created = sorted(path.name for path in AVAC.glob("*.data") if path.name not in before)
        print(
            "QGIS_RUNTIME_CLAWPACK=PASS "
            f"python={sys.executable} numpy={numpy.__version__} yaml={yaml.__version__} "
            f"clawpack={clawpack.__version__} source={CLAW_SOURCE} "
            f"data_count={len(list(AVAC.glob('*.data')))} newly_created={','.join(created) or 'none'}",
            flush=True,
        )
    except Exception as exc:
        print(f"QGIS_RUNTIME_CLAWPACK=FAIL {type(exc).__name__}: {exc}", flush=True)
        result = os.environ.get("AVAC_QGIS_RUNTIME_RESULT")
        if result:
            Path(result).write_text(f"FAIL {type(exc).__name__}: {exc}\n", encoding="utf-8")
    finally:
        QgsApplication.quit()


QTimer.singleShot(0, verify)
