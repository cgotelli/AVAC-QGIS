"""Complete AVAC schema preservation and controlled-parameter regressions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
import numpy as np

from avac_qgis.core.configuration import apply_controlled_values, controlled_values, load_complete_configuration, validate_controlled_values, validate_grid_contract
from avac_qgis.core.preprocessing import AvacRaster, configuration_for_raster, materialize_configuration


TEMPLATE = Path(__file__).resolve().parents[1] / "resources" / "AVAC_configuration100.yaml"


def main() -> None:
    template = load_complete_configuration(TEMPLATE)
    values = controlled_values(template)
    assert values["computation.t_max"] == 150 and values["computation.nb_simul"] == 150 and values["animation.n_out"] == 151
    assert values["rheology.z_breaks"] == []
    assert not validate_grid_contract(template, 1.0)
    incompatible_grid = apply_controlled_values(template, {"computation.cell_size": 1.5})
    assert validate_grid_contract(incompatible_grid, 1.0)
    changed = dict(values)
    changed.update({"release.period_return": 300, "computation.t_max": 7, "computation.nb_simul": 3, "animation.n_out": 4, "rheology.model": "Coulomb"})
    assert not validate_controlled_values(changed)
    payload = apply_controlled_values(template, changed)
    assert payload["computation"]["t_max"] == 7 and payload["computation"]["nb_simul"] == 3 and payload["animation"]["n_out"] == 4
    assert payload["rheology"]["model"] == "Coulomb"
    assert payload["release"]["period_return"] == 300
    assert payload["gauges"] == template["gauges"] and payload["refinement"] == template["refinement"] and payload["file_names"] == template["file_names"]
    assert validate_controlled_values({**changed, "computation.cfl_target": 1.0, "computation.cfl_max": 0.5})
    zoned = {**changed, "rheology.model": "cohesive_Voellmy", "rheology.mu": [.30, .225],
             "rheology.xi": [600, 1200], "rheology.C": [100, 0], "rheology.z_breaks": [1680]}
    assert not validate_controlled_values(zoned)
    zoned_payload = apply_controlled_values(template, zoned)
    assert zoned_payload["rheology"]["z_breaks"] == [1680]
    assert zoned_payload["rheology"]["C"] == [100, 0]
    assert validate_controlled_values({**zoned, "rheology.z_breaks": []})
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "saved.yaml"
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        assert controlled_values(load_complete_configuration(path)) == changed
        raster = AvacRaster(np.arange(4.0), np.arange(4.0), np.zeros((4, 4)), {"xmin": 0.0, "xmax": 4.0, "ymin": 0.0, "ymax": 4.0, "ncols": 4, "nrows": 4, "cellsize": 1.0, "nodata_value": -9999.0}, "EPSG:2154", 1)
        generated = materialize_configuration(TEMPLATE, Path(directory) / "generated.yaml", raster, {"d0": 1.6}, Path(directory), changed)
        assert generated["computation"]["t_max"] == 7 and generated["animation"]["n_out"] == 4
        assert generated["release"]["period_return"] == 300
        assert not generated["gauges"]["gauge_recording"] and generated["gauges"]["gauges"] == template["gauges"]["gauges"]
        assert not generated["refinement"]["topo_refinement"]
        assert generated["dem_extent"] == {"xmin": 0.0, "xmax": 2.0, "ymin": 0.0, "ymax": 2.0, "nbx": 2, "nby": 2, "cell_size": 2.0, "nodata_value": -9999.0}
        refined = materialize_configuration(TEMPLATE, Path(directory) / "refined.yaml", raster, {"d0": 1.6}, Path(directory), changed, raster)
        assert refined["refinement"]["topo_refinement"] and refined["refinement"]["finer_dem"] == "fine_topography.asc"
        assert refined["refinement"]["fine_dict"]["cell_size"] == 1.0
        lachat = AvacRaster(np.empty(0), np.empty(0), np.empty((0, 0)), {"xmin": 967799.0, "xmax": 971701.0, "ymin": 6537699.0, "ymax": 6540901.0, "ncols": 3902, "nrows": 3202, "cellsize": 1.0, "nodata_value": -9999.0}, "EPSG:2154", 1)
        lachat_domain = configuration_for_raster(apply_controlled_values(template, changed), lachat)["dem_extent"]
        assert lachat_domain["xmin"] == 967799.0 and lachat_domain["xmax"] == 971699.0
        assert lachat_domain["ymin"] == 6537699.0 and lachat_domain["ymax"] == 6540899.0
        with_gauge = apply_controlled_values(template, changed)
        with_gauge["gauges"] = {"gauge_recording": True, "gauges": [[7, 50.0, 50.0]]}
        prepared = configuration_for_raster(with_gauge, raster)
        assert not prepared["gauges"]["gauge_recording"]
        assert prepared["gauges"]["gauges"] == [[7, 50.0, 50.0]]
    assert validate_controlled_values({**changed, "release.period_return": 0})
    print("configuration load/save/schema/duration/output/rheology/return-period: PASS")


if __name__ == "__main__":
    main()
