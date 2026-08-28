import json

import numpy as np

from avac_qgis.core.wave_results import (
    WAVE_RESULT_DIRECTORY,
    WAVE_RESULT_FORMAT,
    WaveDiscovery,
    WaveFrame,
    materialize_wave_results,
    wave_temporal_values,
)


def test_water_elevation_is_eta_only_in_wet_cells():
    bed = np.array([[1968.0, 1971.0], [1969.5, 1970.0]])
    depth = np.array([[2.0, 0.0], [0.5, 0.00001]])
    initial_surface = np.full((2, 2), 1970.0)

    elevation = wave_temporal_values("water_elevation", bed, depth, initial_surface)

    assert elevation[0, 0] == 1970.0
    assert elevation[1, 0] == 1970.0
    assert np.isnan(elevation[0, 1])
    assert np.isnan(elevation[1, 1])


def test_wave_depth_and_displacement_remain_distinct():
    bed = np.array([[10.0]])
    depth = np.array([[2.5]])
    initial_surface = np.array([[11.0]])

    assert wave_temporal_values("depth", bed, depth, initial_surface)[0, 0] == 2.5
    assert wave_temporal_values("surface_displacement", bed, depth, initial_surface)[0, 0] == 1.5


def test_existing_wave_products_are_reused_without_rewriting_loaded_rasters(tmp_path, monkeypatch):
    output = tmp_path / "Wave" / "_output"
    output.mkdir(parents=True)
    (output / "fgout0001.t0001").write_text("1.0\n", encoding="utf-8")
    (output / "fgout0001.b0001").write_bytes(b"frame")
    (tmp_path / "impulse_configuration.yaml").write_text("output: {}\n", encoding="utf-8")
    (tmp_path / ".avac_qgis_wave_run.json").write_text("{}\n", encoding="utf-8")
    result = tmp_path / WAVE_RESULT_DIRECTORY
    result.mkdir()
    products = {
        "temporal_surface_displacement.tif": b"temporal",
        "maximum_surface_rise.tif": b"rise",
        "maximum_surface_drawdown.tif": b"drawdown",
    }
    for name, content in products.items():
        (result / name).write_bytes(content)
    payload = {
        "format": WAVE_RESULT_FORMAT - 1,
        "source": str(tmp_path),
        "simulation_time_seconds": [1.0],
        "static": {
            "maximum_surface_rise": {"path": "maximum_surface_rise.tif"},
            "maximum_surface_drawdown": {"path": "maximum_surface_drawdown.tif"},
        },
        "temporal": {
            "surface_displacement": {"path": "temporal_surface_displacement.tif"},
        },
    }
    (result / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    discovery = WaveDiscovery(
        tmp_path, output, tmp_path / "runtime", "EPSG:2056", "binary", 10.0,
        "2026-08-28T12:00:00+02:00", (WaveFrame(1, 1.0),),
    )
    monkeypatch.setattr("avac_qgis.core.wave_results._valid_wave_product", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "avac_qgis.core.wave_results.load_wave_frame",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache miss rewrote a loaded raster")),
    )

    cached = materialize_wave_results(discovery)

    assert cached["format"] == WAVE_RESULT_FORMAT
    assert cached["raw_fingerprint"]
    assert cached["temporal"]["surface_displacement"]["path"] == "temporal_surface_displacement.tif"
    for name, content in products.items():
        assert (result / name).read_bytes() == content
