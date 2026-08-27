"""Optional QGIS runner for the real-case GeoClaw terrain-edge regression."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

import numpy as np
import yaml
from qgis.core import QgsRasterLayer, QgsRectangle

sys.path.insert(0, os.environ["AVAC_QGIS_SOURCE_ROOT"])

from avac_qgis.core.preprocessing import raster_from_qgis_layer, write_topography  # noqa: E402
from avac_qgis.core.wave_execution import prepare_wave_runtime_execution  # noqa: E402
from avac_qgis.core.wave_project import _write_force_dry_mask, terrain_for_wave_domain  # noqa: E402


try:
    root = Path(os.environ["AVAC_EDGE_CASE"])
    terrain_layer = QgsRasterLayer(os.environ["AVAC_EDGE_DEM"], "edge regression terrain")
    if not terrain_layer.isValid():
        raise RuntimeError("Edge-regression terrain did not load in QGIS.")
    config = yaml.safe_load((root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    domain = {key: float(config["lake"][key]) for key in ("xmin", "xmax", "ymin", "ymax")}
    cell = float(config["computation"]["cell_size"])
    extent = QgsRectangle(domain["xmin"] - cell, domain["ymin"] - cell,
                          domain["xmax"] + cell, domain["ymax"] + cell)
    native = raster_from_qgis_layer(terrain_layer, extent=extent)
    wave_raster = terrain_for_wave_domain(native, domain, cell)
    write_topography(root / "Topo" / "topography_lake.asc", wave_raster)
    solver_shape = (wave_raster.z.shape[0] - 2, wave_raster.z.shape[1] - 2)
    _write_force_dry_mask(root / "Topo" / "mask.asc", np.ones(solver_shape, dtype=bool), domain, cell)
    prepare_wave_runtime_execution(os.environ["AVAC_EDGE_RUNTIME"], root, os.environ["AVAC_EDGE_AVAC"])
    print(f"prepared edge-regression case: {root}")
    sys.stdout.flush()
    os._exit(0)
except BaseException:  # noqa: BLE001
    traceback.print_exc()
    sys.stderr.flush()
    os._exit(1)
