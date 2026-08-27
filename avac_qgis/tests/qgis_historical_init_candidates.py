"""Compare notebook-recorded release parameters with Task 3 init.xyz."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer, QgsVectorLayer

from avac_qgis.core.preprocessing import AvacRaster, initial_depth_from_release, release_mask_from_rings, rings_from_qgis_layer


CASE = Path("/Users/cmgotelli/Downloads/Lac_Clusaz")
REFERENCE = Path("/private/tmp/avac_qgis_profile.liiH9q/Lac_Clusaz/AVAC/init.xyz")
CANDIDATES = {
    "notebook_2025-08-30": {"d0": 1.77, "z_ref": 2000.0, "gradient_hypso": .03, "theta_cr": 30., "nu": .2, "correction_elevation": True, "correction_slope": True},
    "notebook_2025-08-29": {"d0": 1.56, "z_ref": 1490.0, "gradient_hypso": 0., "theta_cr": 30., "nu": .2, "correction_elevation": True, "correction_slope": True},
    "current_300": {"d0": 1.75, "z_ref": 1300.0, "gradient_hypso": .03, "theta_cr": 30., "nu": .2, "correction_elevation": True, "correction_slope": True},
}


def run() -> None:
    dem = QgsRasterLayer(str(CASE / "Topo" / "topo1m_simple.asc"), "DEM")
    dem.setCrs(QgsCoordinateReferenceSystem("EPSG:2154"))
    release = QgsVectorLayer(str(CASE / "Topo" / "ZA.shp"), "release", "ogr")
    provider, extent = dem.dataProvider(), dem.extent()
    width, height = dem.width(), dem.height()
    block = provider.block(1, extent, width, height)
    z = np.frombuffer(bytes(block.data()), dtype=np.float32).astype(float).reshape((height, width))[::-1]
    # Notebook/topotype coordinates are samples at xlower + i*cellsize.
    x = extent.xMinimum() + np.arange(width, dtype=float)
    y = extent.yMinimum() + np.arange(height, dtype=float)
    raster = AvacRaster(x, y, z, {"xmin": x[0], "xmax": x[-1], "ymin": y[0], "ymax": y[-1], "ncols": width, "nrows": height, "cellsize": 1., "nodata_value": -9999.}, "EPSG:2154", 1)
    mask = release_mask_from_rings(rings_from_qgis_layer(release, dem.crs()), x, y)
    reference = np.loadtxt(REFERENCE)[:, 2].reshape((height, width))[::-1]
    for name, release_parameters in CANDIDATES.items():
        depth = initial_depth_from_release(raster, mask, release_parameters)
        difference = np.abs(depth - reference)
        print(
            f"HISTORICAL_CANDIDATE {name} wet={np.count_nonzero(depth)} "
            f"min={depth[depth > 0].min():.12g} max={depth.max():.12g} sum={depth.sum():.12g} "
            f"max_abs={difference.max():.12g} mean_abs={difference.mean():.12g} "
            f"matching_wet={np.count_nonzero((depth == reference) & (reference > 0))}", flush=True,
        )
    QCoreApplication.quit()


QTimer.singleShot(0, run)
