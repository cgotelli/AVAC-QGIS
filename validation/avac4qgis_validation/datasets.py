"""Download versioned external datasets required by published notebooks."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
import zipfile


VALIDATION_ROOT = Path(__file__).resolve().parents[1]
ISEESNOW_VERSION = "1.0"
ISEESNOW_URL = "https://github.com/avaframe/ISeeSnow/archive/refs/tags/1.0.zip"
ISEESNOW_REQUIRED_FILES = (
    "simulationResultTable.csv",
    "data/IdealizedTopo/Inputs/DEM_IdealizedTopo.asc",
    "data/IdealizedTopo/Inputs/release1HS.shp",
    "data/RealTopo/Inputs/DEM_RealTopo.asc",
    "data/RealTopo/Inputs/relWog.shp",
    "data/CoulombOnly/Inputs/DEM_CoulombOnly.asc",
    "data/CoulombOnly/Inputs/release1HS.shp",
)


def iseesnow_dataset_complete(root: Path) -> bool:
    """Return whether *root* contains the pinned benchmark inputs and table."""
    return all((root / relative).is_file() for relative in ISEESNOW_REQUIRED_FILES)


def ensure_iseesnow() -> Path:
    """Return the pinned ISeeSnow dataset, repairing it when absent or partial."""
    target = VALIDATION_ROOT / "_data" / "ISeeSnow"
    if iseesnow_dataset_complete(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="avac4qgis-iseesnow-") as temporary:
        archive = Path(temporary) / "ISeeSnow.zip"
        with urlopen(ISEESNOW_URL, timeout=120) as response, archive.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temporary)
        extracted = Path(temporary) / f"ISeeSnow-{ISEESNOW_VERSION}"
        if not iseesnow_dataset_complete(extracted):
            raise RuntimeError("Downloaded ISeeSnow archive is missing required benchmark files")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(extracted, target)
    return target
