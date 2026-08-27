"""Fast non-QGIS result-discovery and geometry regression checks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from avac_qgis.core.results import GridGeometry, discover_results, geometry_from_axes, pressure_from_velocity


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    (root / "AVAC" / "_output").mkdir(parents=True)
    (root / ".avac_qgis_run.json").write_text(json.dumps({
        "format": 1, "status": "completed", "avac_directory": "AVAC", "dem_crs": "EPSG:2154",
    }), encoding="utf-8")
    (root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "computation:\n  output_directory: _output\nrheology:\n  rho: 275\noutput:\n  output_format: binary32\n",
        encoding="utf-8",
    )
    output = root / "AVAC" / "_output"
    for frame, seconds in ((3, 0.0), (17, 2.5), (91, 19.75)):
        (output / f"fgout0001.t{frame:04d}").write_text(f"{seconds:.8E} time\n", encoding="utf-8")
        (output / f"fgout0001.b{frame:04d}").write_bytes(b"x")
        (output / f"fgout0002.t{frame:04d}").write_text(f"{seconds:.8E} time\n", encoding="utf-8")
        (output / f"fgout0002.b{frame:04d}").write_bytes(b"x")
    (output / "fgmax0001.txt").write_text("0 0 0 0 0 0\n", encoding="utf-8")
    (output / "fgmax0002.txt").write_text("0 0 0 0 0 0\n", encoding="utf-8")
    discovered = discover_results(root)
    assert [item.frame_id for item in discovered.frames] == [3, 17, 91]
    assert [item.time_seconds for item in discovered.frames] == [0.0, 2.5, 19.75]
    assert discovered.rho == 275.0 and discovered.crs_authid == "EPSG:2154"
    refined = discover_results(root, 2)
    assert refined.fgout_grid == 2 and refined.fgmax_grid == 2 and refined.fgmax_path.name == "fgmax0002.txt"
    assert [item.frame_id for item in refined.frames] == [3, 17, 91]
    assert np.array_equal(pressure_from_velocity(np.array([0.0, 10.0]), discovered.rho), np.array([0.0, 13.75]))
    geometry = geometry_from_axes(np.array([10.0, 12.0, 14.0]), np.array([20.0, 23.0]))
    assert geometry == GridGeometry(3, 2, 9.0, 15.0, 18.5, 24.5, 2.0, 3.0)

print("result discovery/variable-time/georeferencing: PASS")
