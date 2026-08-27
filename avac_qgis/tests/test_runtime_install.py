"""Development-artifact validation and atomic installation regression."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from avac_qgis.core.runtime import RuntimeValidationError, install_runtime_archive, validate_runtime


def main() -> None:
    archive = Path(os.environ["AVAC_QGIS_RUNTIME_ARCHIVE"])
    version = os.environ["AVAC_QGIS_RUNTIME_VERSION"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        installed = install_runtime_archive(archive, version, destination_root=root)
        manifest = validate_runtime(installed, expected_version=version)
        assert manifest["architecture"] == "arm64"
        # The test installation is explicitly isolated under ``root``.  Do
        # not make its result depend on whether a real first-use installation
        # already exists in Application Support.
        solver = installed / "bin" / "xgeoclaw"
        solver.write_bytes(solver.read_bytes() + b"corrupt")
        try:
            validate_runtime(installed, expected_version=version)
        except RuntimeValidationError as exc:
            assert "hash mismatch" in str(exc)
        else:
            raise AssertionError("Corrupt solver was accepted")
        repaired = install_runtime_archive(archive, version, destination_root=root)
        assert validate_runtime(repaired, expected_version=version)["runtime_version"] == version
    print("runtime manifest validation, corrupt-runtime replacement, and staged install: PASS")


if __name__ == "__main__":
    main()
