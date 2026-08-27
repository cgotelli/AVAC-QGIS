"""Regression: Wave and AVAC runtimes must not share an install location."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avac_qgis.core.runtime import install_runtime_archive, installed_runtime, validate_runtime


def main() -> None:
    archive = Path(os.environ["AVAC_QGIS_WAVE_RUNTIME_ARCHIVE"])
    version = os.environ["AVAC_QGIS_WAVE_RUNTIME_VERSION"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # An AVAC artifact can have the same manifest version.  The Wave
        # product directory must nevertheless receive its own backend.
        wave_root = root / "wave"
        installed = install_runtime_archive(archive, version, destination_root=wave_root)
        assert installed == (wave_root / version / "arm64").resolve()
        backend = installed / "backend" / "Wave" / "setrun.py"
        assert backend.is_file()
        backend_text = backend.read_text(encoding="utf-8")
        assert "force_dry.tend = 0.5+computation['t_0']" in backend_text
        assert "force_dry.tend = computation['t_max']" not in backend_text
        assert not (installed / "backend" / "AVAC" / "setrun.py").is_file()
        assert installed_runtime(version, destination_root=wave_root) == installed
        assert validate_runtime(installed, expected_version=version)["runtime_version"] == version
    print("isolated Wave runtime installation: PASS")


if __name__ == "__main__":
    main()
