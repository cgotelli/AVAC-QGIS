"""Regression coverage for the shared AVAC/Wave QGIS temporal timeline."""

from __future__ import annotations

import json
from types import SimpleNamespace

from avac_qgis.core.results import RESULT_DIRECTORY, RESULT_FORMAT, _raw_fingerprint, cached_results
from avac_qgis.core.simulation_time import temporal_band_records
from avac_qgis.core.wave_results import _wave_temporal_origin_iso


def test_legacy_wave_scenario_inherits_its_source_avac_temporal_origin(tmp_path):
    avac_root = tmp_path / "runs" / "run_20260815_100000"
    avac_root.mkdir(parents=True)
    source_origin = "2026-08-15T10:00:00+02:00"
    (avac_root / ".avac_qgis_run.json").write_text(
        json.dumps({"format": 1, "status": "completed", "created_at": source_origin,
                    "temporal_origin_iso": source_origin}), encoding="utf-8",
    )
    wave_root = tmp_path / "wave_runs" / "wave_20260815_110000"
    wave_root.mkdir(parents=True)
    wave_marker = {"format": 1, "status": "completed", "created_at": "2026-08-15T11:00:00+02:00",
                   "source_avac_run": str(avac_root)}

    origin = _wave_temporal_origin_iso(wave_root, wave_marker)

    assert origin == source_origin
    avac_ranges = temporal_band_records(origin, [0.0, 5.0, 10.0])
    wave_ranges = temporal_band_records(origin, [0.0, 5.0, 10.0])
    assert [record["start_iso"] for record in wave_ranges] == [record["start_iso"] for record in avac_ranges]
    assert [record["end_iso"] for record in wave_ranges] == [record["end_iso"] for record in avac_ranges]


def test_previous_avac_result_manifest_is_not_reused_after_temporal_metadata_change(tmp_path):
    """Force one regeneration so existing GeoTIFF bands receive the shared axis."""
    output = tmp_path / "AVAC" / "_output"
    output.mkdir(parents=True)
    discovery = SimpleNamespace(run_root=tmp_path, output_dir=output)
    result_dir = tmp_path / RESULT_DIRECTORY
    result_dir.mkdir()
    (result_dir / "results.json").write_text(
        json.dumps({"format": RESULT_FORMAT - 1, "raw_fingerprint": _raw_fingerprint(discovery),
                    "static": {}, "temporal": {}}), encoding="utf-8",
    )

    assert cached_results(discovery) is None
