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


def ensure_iseesnow() -> Path:
    """Return the pinned ISeeSnow dataset, downloading it when absent."""
    target = VALIDATION_ROOT / "_data" / "ISeeSnow"
    if (target / "data").is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="avac4qgis-iseesnow-") as temporary:
        archive = Path(temporary) / "ISeeSnow.zip"
        with urlopen(ISEESNOW_URL, timeout=120) as response, archive.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temporary)
        extracted = Path(temporary) / f"ISeeSnow-{ISEESNOW_VERSION}"
        if not (extracted / "data").is_dir():
            raise RuntimeError("Downloaded ISeeSnow archive does not contain the expected data directory")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(extracted, target)
    return target
