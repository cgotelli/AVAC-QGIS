from __future__ import annotations

import json

import numpy as np
import pytest
import yaml

from avac_qgis.core.preprocessing import AvacRaster
from avac_qgis.core.wave_project import (
    WAVE_MARKER,
    _write_force_dry_mask,
    avac_computation_domain,
    prepare_wave_lake,
    prepare_wave_scenario,
    shoreline_faces_from_wet_mask,
    terrain_for_wave_domain,
    validate_wave_source_compatibility,
    wave_lake_mask_from_rings,
)


def test_wave_preparation_is_isolated_and_reuses_previewed_lake(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    avac_root = workspace / "runs" / "run_completed"
    output = avac_root / "AVAC" / "_output"
    output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    source_origin = "2026-08-15T10:00:00+02:00"
    (avac_root / ".avac_qgis_run.json").write_text(
        json.dumps({"format": 1, "status": "completed", "created_at": source_origin,
                    "temporal_origin_iso": source_origin}), encoding="utf-8",
    )
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "dem_extent:\n  xmin: 0\n  xmax: 2\n  ymin: 0\n  ymax: 2\n"
        "computation:\n  t_max: 42\n  nb_simul: 21\n",
        encoding="utf-8",
    )
    before = (avac_root / ".avac_qgis_run.json").read_bytes()
    raster = AvacRaster(np.array([-.5, .5, 1.5, 2.5]), np.array([-.5, .5, 1.5, 2.5]), np.ones((4, 4)),
                        {"xmin": -1., "xmax": 3., "ymin": -1., "ymax": 3., "ncols": 4, "nrows": 4, "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1)
    ring = [(np.array([[0., 0.], [2., 0.], [2., 2.], [0., 2.], [0., 0.]]), [])]
    prepared_lake = prepare_wave_lake(
        raster, ring, water_level=1.5, cell_size=1.,
        domain={"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.}, dry_tolerance=.001,
    )
    assert prepared_lake.initial_depth.shape == (4, 4)
    import avac_qgis.core.wave_project as wave_project
    monkeypatch.setattr(
        wave_project,
        "prepare_wave_lake",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preview lake was recomputed")),
    )
    root = prepare_wave_scenario(
        workspace, avac_root, raster, ring, water_level=1.5, cell_size=1.,
        domain={"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.},
        parameters={"damping": .25, "land_strickler": 11., "water_strickler": 31., "friction_depth_limit": 21.,
                    "dry_limit": .001, "wave_tolerance_flag": .15, "cfl_target": .45, "cfl_max": .9, "limiter": "vanleer"},
        gauges=[{"x": 1., "y": 1., "name": "Centre gauge"}],
        prepared_lake=prepared_lake,
    )
    assert root.parent == workspace / "wave_runs"
    assert (root / "Topo" / "topography_lake.asc").is_file()
    assert (root / "Topo" / "mask.asc").is_file()
    # GeoClaw's topotype-3 reader shifts corner-registered headers to cell
    # centres.  A complete one-cell terrain halo prevents zero-elevation
    # fractions in the south/west solver cells.
    topo_lines = (root / "Topo" / "topography_lake.asc").read_text(encoding="utf-8").splitlines()
    assert int(topo_lines[0].split()[1]) == 4
    assert int(topo_lines[1].split()[1]) == 4
    assert float(topo_lines[2].split()[1]) == -1.0
    assert float(topo_lines[3].split()[1]) == -1.0
    assert float(topo_lines[4].split()[1]) == 1.0
    # The WAVE Fortran force-dry reader reads a numeric value first on every
    # header line; labelled ESRI-ASCII headers are not accepted there.
    mask_lines = (root / "Topo" / "mask.asc").read_text(encoding="utf-8").splitlines()
    assert int(mask_lines[0].split()[0]) == 2
    assert int(mask_lines[1].split()[0]) == 2
    assert float(mask_lines[2].split()[0]) == -0.5
    assert float(mask_lines[3].split()[0]) == 0.5
    assert float(mask_lines[4].split()[0]) == 1.0
    assert int(mask_lines[5].split()[0]) == -9999
    assert {int(value) for row in mask_lines[6:] for value in row.split()} <= {0, 1}
    assert (root / "CL").is_dir()
    config = yaml.safe_load((root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    assert config["computation"]["boundary"] == "extrap"
    assert config["computation"]["mode"] == "internal_shoreline"
    assert config["coupling"] == {"mode": "internal_shoreline", "shoreline_faces": "CL/shoreline_faces.txt",
                                  "inflow": "CL/internal_inflow.data"}
    faces = np.loadtxt(root / "CL" / "shoreline_faces.txt", comments="#", ndmin=2)
    assert faces.shape[1] == 7 and faces.shape[0] == 8
    assert config["computation"]["t_max"] == 42.0
    assert config["computation"]["nb_simul"] == 21
    assert config["output"]["delta_t"] == 2.0
    assert config["topo_files"]["mask_raster"] == "mask.asc"
    assert config["topo_files"]["shoreline_guard_cells"] == 0
    assert config["topo_files"]["shoreline_guard_rim_cells"] == 0
    assert config["lake"] == {"topography": "topography_lake.asc", "water_level": 1.5,
                              "xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.}
    assert (config["computation"]["damping"], config["computation"]["cfl_target"], config["computation"]["cfl_max"], config["computation"]["limiter"]) == (.25, .45, .9, "vanleer")
    assert config["rheology"]["Strickler"] == [11., 31.]
    assert config["gauges"] == {"gauge_recording": True, "0": {"x": 1., "y": 1., "name": "Centre gauge"}}
    assert "postprocessing" not in config
    marker = json.loads((root / WAVE_MARKER).read_text(encoding="utf-8"))
    assert marker["source_avac_run"] == str(avac_root.resolve())
    assert marker["temporal_origin_iso"] == source_origin
    assert (avac_root / ".avac_qgis_run.json").read_bytes() == before


def test_force_dry_file_maps_exactly_to_every_solver_cell(tmp_path):
    """Emulate GeoClaw qinit's one-based/reversed mask lookup."""
    domain = {"xmin": 10., "xmax": 18., "ymin": 20., "ymax": 26.}
    cell = 2.
    wet = np.array([
        [True, False, True, False],
        [False, True, False, True],
        [True, True, False, False],
    ])
    path = tmp_path / "mask.asc"
    _write_force_dry_mask(path, wet, domain, cell)
    lines = path.read_text(encoding="utf-8").splitlines()
    ncols, nrows = int(lines[0].split()[0]), int(lines[1].split()[0])
    xlow, ylow, spacing = (float(lines[index].split()[0]) for index in (2, 3, 4))
    raw = np.loadtxt(path, skiprows=6, dtype=int)
    mapped = np.zeros_like(wet)
    for row in range(nrows):
        y = domain["ymin"] + (row + .5) * cell
        file_row = nrows - int((y - ylow + 1.e-7) / spacing)
        for column in range(ncols):
            x = domain["xmin"] + (column + .5) * cell
            file_column = int((x - xlow + 1.e-7) / spacing)
            mapped[row, column] = raw[file_row - 1, file_column - 1] == 0
    assert np.array_equal(mapped, wet)


def test_wave_preparation_rejects_domain_outside_terrain(tmp_path):
    workspace = tmp_path / "workspace"
    avac_root = workspace / "runs" / "run_completed"
    output = avac_root / "AVAC" / "_output"; output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    (avac_root / ".avac_qgis_run.json").write_text(json.dumps({"format": 1, "status": "completed"}), encoding="utf-8")
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text("computation:\n  t_max: 42\n  nb_simul: 21\n", encoding="utf-8")
    raster = AvacRaster(np.array([0., 1., 2.]), np.array([0., 1., 2.]), np.ones((3, 3)),
                        {"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2., "ncols": 3, "nrows": 3, "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1)
    ring = [(np.array([[0., 0.], [2., 0.], [2., 2.], [0., 2.], [0., 0.]]), [])]
    with pytest.raises(ValueError, match="fully covered"):
        prepare_wave_scenario(workspace, avac_root, raster, ring, water_level=1.5, cell_size=1.,
                              domain={"xmin": -1., "xmax": 1., "ymin": 0., "ymax": 2.})


def test_wave_source_rejects_a_different_case_crs_and_nonoverlapping_domain(tmp_path):
    avac_root = tmp_path / "run"
    output = avac_root / "AVAC" / "_output"; output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    marker = {"format": 1, "status": "completed", "dem_crs": "EPSG:2154"}
    (avac_root / ".avac_qgis_run.json").write_text(json.dumps(marker), encoding="utf-8")
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "dem_extent:\n  xmin: 0\n  xmax: 10\n  ymin: 0\n  ymax: 10\n",
        encoding="utf-8",
    )
    domain = {"xmin": 20., "xmax": 30., "ymin": 20., "ymax": 30.}
    with pytest.raises(ValueError, match="AVAC run uses EPSG:2154.*Wave terrain uses EPSG:2056"):
        validate_wave_source_compatibility(avac_root, "EPSG:2056", domain)
    with pytest.raises(ValueError, match="does not overlap"):
        validate_wave_source_compatibility(avac_root, "EPSG:2154", domain)


def test_wave_domain_is_exactly_the_completed_avac_domain(tmp_path):
    avac_root = tmp_path / "run"
    output = avac_root / "AVAC" / "_output"
    output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    (avac_root / ".avac_qgis_run.json").write_text(
        json.dumps({"format": 1, "status": "completed"}), encoding="utf-8",
    )
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "dem_extent:\n  xmin: 10.5\n  xmax: 30.5\n  ymin: 40\n  ymax: 70\n",
        encoding="utf-8",
    )

    assert avac_computation_domain(avac_root) == {
        "xmin": 10.5, "xmax": 30.5, "ymin": 40., "ymax": 70.,
    }


def test_wave_preparation_accepts_a_coarser_whole_number_grid(tmp_path):
    workspace = tmp_path / "workspace"
    avac_root = workspace / "runs" / "completed"; output = avac_root / "AVAC" / "_output"
    output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    (avac_root / ".avac_qgis_run.json").write_text(json.dumps({"format": 1, "status": "completed"}), encoding="utf-8")
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text("computation:\n  t_max: 10\n  nb_simul: 2\n", encoding="utf-8")
    raster = AvacRaster(np.arange(-1.5, 6., dtype=float), np.arange(-1.5, 6., dtype=float), np.arange(64., dtype=float).reshape(8, 8),
                        {"xmin": -2., "xmax": 6., "ymin": -2., "ymax": 6., "ncols": 8, "nrows": 8, "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1)
    ring = [(np.array([[0., 0.], [4., 0.], [4., 4.], [0., 4.], [0., 0.]]), [])]
    root = prepare_wave_scenario(workspace, avac_root, raster, ring, water_level=30., cell_size=2.,
                                 domain={"xmin": 0., "xmax": 4., "ymin": 0., "ymax": 4.})
    configuration = yaml.safe_load((root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    assert configuration["computation"]["limiter"] == "vanleer"
    assert configuration["computation"]["boundary"] == "extrap"
    header = (root / "Topo" / "topography_lake.asc").read_text(encoding="utf-8").splitlines()[:6]
    assert int(header[0].split()[1]) == 4 and int(header[1].split()[1]) == 4
    assert float(header[2].split()[1]) == -2.0 and float(header[3].split()[1]) == -2.0
    assert float(header[4].split()[1]) == 2.0


def test_wave_terrain_halo_does_not_shrink_a_full_dem_domain():
    raster = AvacRaster(
        np.array([.5, 1.5]), np.array([.5, 1.5]), np.array([[10., 11.], [12., 13.]]),
        {"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2., "ncols": 2, "nrows": 2,
         "cellsize": 1., "nodata_value": -9999.}, "EPSG:2056", 1,
    )
    terrain = terrain_for_wave_domain(
        raster, {"xmin": 0., "xmax": 2., "ymin": 0., "ymax": 2.}, 1.,
    )
    assert terrain.z.shape == (4, 4)
    assert terrain.metadata["xmin"] == -1. and terrain.metadata["xmax"] == 3.
    assert terrain.metadata["ymin"] == -1. and terrain.metadata["ymax"] == 3.
    assert np.array_equal(
        terrain.z,
        np.array([[10., 10., 11., 11.], [10., 10., 11., 11.],
                  [12., 12., 13., 13.], [12., 12., 13., 13.]]),
    )


def test_diagonal_lake_shoreline_is_grid_aligned_and_points_inward():
    wet = np.array([[True, False, False], [True, True, False], [True, True, True]])
    faces = shoreline_faces_from_wet_mask(
        wet, {"xmin": 0., "xmax": 3., "ymin": 0., "ymax": 3.}, 1.,
    )
    assert faces.shape == (12, 7)
    assert set(map(tuple, faces[:, 4:6])) <= {(-1., 0.), (1., 0.), (0., -1.), (0., 1.)}
    assert np.all(faces[:, 6] == 1.)


def test_wave_lake_scanline_mask_preserves_polygon_holes():
    x = y = np.arange(.5, 4., 1.)
    rings = [(
        np.array([[0., 0.], [4., 0.], [4., 4.], [0., 4.], [0., 0.]]),
        [np.array([[1., 1.], [3., 1.], [3., 3.], [1., 3.], [1., 1.]])],
    )]
    mask = wave_lake_mask_from_rings(rings, x, y)
    assert np.array_equal(
        mask,
        np.array([[True, True, True, True], [True, False, False, True],
                  [True, False, False, True], [True, True, True, True]]),
    )


def test_wave_lake_mask_includes_a_partially_intersected_shoreline_cell():
    """Water level follows the lake polygon footprint, not only cell centres."""
    x = y = np.array([.5, 1.5])
    # The narrow polygon crosses all four cells but contains no cell centre.
    rings = [(
        np.array([[.9, .9], [1.1, .9], [1.1, 1.1], [.9, 1.1], [.9, .9]]),
        [],
    )]
    mask = wave_lake_mask_from_rings(rings, x, y)
    assert np.array_equal(mask, np.ones((2, 2), dtype=bool))


def test_coarse_wave_lake_mask_uses_source_grid_coverage_not_a_tiny_sliver():
    """A 0.5 m polygon cannot turn a whole 2.5 m Wave cell into water."""
    x = y = np.array([1.25, 3.75])
    narrow = [(
        np.array([[.1, .1], [.9, .1], [.9, 4.9], [.1, 4.9], [.1, .1]]), [],
    )]
    broad = [(
        np.array([[.1, .1], [1.9, .1], [1.9, 4.9], [.1, 4.9], [.1, .1]]), [],
    )]
    narrow_mask = wave_lake_mask_from_rings(narrow, x, y, source_cell_size=.5)
    broad_mask = wave_lake_mask_from_rings(broad, x, y, source_cell_size=.5)
    assert not narrow_mask[0, 0]  # 2 of 5 source columns: below 50% coverage.
    assert broad_mask[0, 0]       # 4 of 5 source columns: above 50% coverage.


def test_submerged_exterior_bathymetry_gets_an_exterior_only_waterline_shelf(tmp_path):
    """Build a zero-depth numerical shoreline without permanent dry land."""
    workspace = tmp_path / "workspace"
    avac_root = workspace / "runs" / "completed"
    output = avac_root / "AVAC" / "_output"; output.mkdir(parents=True)
    (output / "fort.q0000").write_text("fixture", encoding="utf-8")
    (avac_root / ".avac_qgis_run.json").write_text(
        json.dumps({"format": 1, "status": "completed"}), encoding="utf-8",
    )
    (avac_root / "AVAC" / "AVAC_configuration.yaml").write_text(
        "computation:\n  t_max: 20\n  nb_simul: 20\n", encoding="utf-8",
    )
    coordinates = np.arange(-1.5, 10., dtype=float)
    raster = AvacRaster(
        coordinates, coordinates, np.zeros((12, 12), dtype=float),
        {"xmin": -2., "xmax": 10., "ymin": -2., "ymax": 10.,
         "ncols": 12, "nrows": 12, "cellsize": 1., "nodata_value": -9999.},
        "EPSG:2056", 1,
    )
    ring = [(np.array([[1., 1.], [7., 1.], [7., 7.], [1., 7.], [1., 1.]]), [])]
    root = prepare_wave_scenario(
        workspace, avac_root, raster, ring, water_level=1., cell_size=1.,
        domain={"xmin": 0., "xmax": 8., "ymin": 0., "ymax": 8.},
    )
    config = yaml.safe_load((root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    assert config["topo_files"]["shoreline_guard_rim_cells"] == 1
    assert config["topo_files"]["shoreline_guard_cells"] > 0
    faces = np.loadtxt(root / "CL" / "shoreline_faces.txt", comments="#", ndmin=2)
    assert faces.shape == (24, 7)

    prepared = prepare_wave_lake(
        raster, ring, water_level=1., cell_size=1.,
        domain={"xmin": 0., "xmax": 8., "ymin": 0., "ymax": 8.},
    )
    finite = np.isfinite(prepared.raster.z)
    # No polygon-exterior topography sample remains below the prescribed
    # water surface; GeoClaw therefore has no hydrostatic exterior water to
    # fall into the lake when force-dry expires.
    assert np.all(prepared.raster.z[(~prepared.inside) & finite] >= 1.0001)
    # The one-cell interior rim removes deep samples from the bilinear support
    # of dry exterior cells, while a wet core remains available to the solver.
    assert prepared.stabilization_radius_cells == 1
    assert np.any(prepared.inside & finite & (prepared.raster.z < 1.))
    assert np.all(np.isnan(prepared.initial_depth[~prepared.inside]))
