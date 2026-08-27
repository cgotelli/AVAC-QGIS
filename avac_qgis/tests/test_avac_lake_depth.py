from __future__ import annotations

import json

import numpy as np
from osgeo import gdal, osr

from avac_qgis.core.avac_lake_depth import _write_lake_zero_product
from avac_qgis.core.preprocessing import AvacRaster
from avac_qgis.core.wave_project import prepare_wave_scenario


def test_lake_zero_product_preserves_avac_source_and_masks_all_bands(tmp_path):
    """AVAC-Depth replaces export-only clipping with a reusable raster product."""
    avac_root = tmp_path / "runs" / "completed"
    (avac_root / "AVAC" / "_output").mkdir(parents=True)
    (avac_root / "AVAC" / "_output" / "fort.q0000").write_text("fixture\n", encoding="utf-8")
    (avac_root / ".avac_qgis_run.json").write_text(
        json.dumps({"status": "completed", "avac_directory": "AVAC", "dem_crs": "EPSG:2056"}),
        encoding="utf-8",
    )
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "computation:\n  t_max: 10\n  nb_simul: 2\n", encoding="utf-8",
    )
    raster = AvacRaster(
        np.array([-.5, .5, 1.5, 2.5]), np.array([-.5, .5, 1.5, 2.5]), np.ones((4, 4)),
        {"xmin": -1., "xmax": 3., "ymin": -1., "ymax": 3., "ncols": 4, "nrows": 4,
         "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1,
    )
    rings = [(np.array([[0., 0.], [2., 0.], [2., 2.], [0., 2.], [0., 0.]]), [])]
    wave_root = prepare_wave_scenario(
        tmp_path, avac_root, raster, rings, water_level=1.5, cell_size=1.,
        domain={"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.},
    )
    source = tmp_path / "source_depth.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(source), 8, 8, 2, gdal.GDT_Float32)
    dataset.SetGeoTransform((-3., 1., 0., 5., 0., -1.))
    crs = osr.SpatialReference(); crs.SetFromUserInput("EPSG:2056")
    dataset.SetProjection(crs.ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(np.full((8, 8), 3., dtype=np.float32))
    dataset.GetRasterBand(2).WriteArray(np.full((8, 8), 7., dtype=np.float32))
    dataset = None

    product = tmp_path / "avac_depth_lake_zero.tif"
    maximums, zeroed_cells = _write_lake_zero_product(source, wave_root, product)

    source_dataset, product_dataset = gdal.Open(str(source)), gdal.Open(str(product))
    assert source_dataset is not None and product_dataset is not None
    source_values = source_dataset.GetRasterBand(1).ReadAsArray()
    first = product_dataset.GetRasterBand(1).ReadAsArray()
    second = product_dataset.GetRasterBand(2).ReadAsArray()
    source_dataset = product_dataset = None
    assert maximums == [3., 7.]
    assert zeroed_cells > 0
    assert np.all(source_values == 3.)
    assert np.count_nonzero(first == 0.) >= 4
    assert np.count_nonzero(second == 0.) >= 4
    assert first[0, 0] == 3. and first[-1, -1] == 3.
