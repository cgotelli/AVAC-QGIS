"""Regression checks for deliberate invalid/cancelled AVAC-QGIS states."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from avac_qgis.core.configuration import load_complete_configuration
from avac_qgis.core.preprocessing import AvacRaster, PreparationCancelled, prepare_inputs
from avac_qgis.core.results import discover_results
from avac_qgis.core.run_project import RUN_FORMAT, read_run_metadata, validate_prepared_run, write_run_metadata


def expect(exception, callback) -> None:
    try:
        callback()
    except exception:
        return
    raise AssertionError(f"Expected {exception.__name__}")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bad_config = root / "bad.yaml"
        bad_config.write_text("release: []\n", encoding="utf-8")
        expect(ValueError, lambda: load_complete_configuration(bad_config))

        marker = {"format": RUN_FORMAT, "status": "completed", "avac_directory": "AVAC", "dem_crs": "EPSG:2154"}
        (root / "AVAC").mkdir()
        write_run_metadata(root, marker)
        expect(ValueError, lambda: validate_prepared_run(root / "AVAC"))
        expect(ValueError, lambda: discover_results(root))

    # Cancellation is checked during row-wise input writing, before an input
    # directory can become a prepared runnable case.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        template = Path(__file__).resolve().parents[1] / "resources" / "AVAC_configuration100.yaml"
        raster = AvacRaster(
            np.arange(4.0), np.arange(4.0), np.zeros((4, 4)),
            {"xmin": 0.0, "xmax": 4.0, "ymin": 0.0, "ymax": 4.0, "ncols": 4, "nrows": 4, "cellsize": 1.0, "nodata_value": -9999.0},
            "EPSG:2154", 1,
        )
        run_root = root / "run"
        expect(PreparationCancelled, lambda: prepare_inputs(
            run_root, raster, [(np.array([[-1., -1.], [2., -1.], [2., 2.], [-1., 2.]]), [])], template, {}, cancelled=lambda: True,
        ))
        assert not (run_root / "AVAC" / "AVAC_configuration.yaml").exists()
    print("invalid configuration/run/results and cancelled input preparation: PASS")


if __name__ == "__main__":
    main()
