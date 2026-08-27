"""Data-only normal-workspace validation and materialization regression."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from avac_qgis.core.workspace import completed_runs, create_run_root, materialize_layer_sources, validate_workspace
from avac_qgis.core.run_project import write_run_metadata


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    workspace = validate_workspace(root / "workspace")
    run_id, run = create_run_root(workspace)
    assert run.parent == workspace / "runs" and run_id.startswith("run_")
    # A deterministic timestamp collision is resolved without overwriting.
    run.mkdir(parents=True)
    second_id, second_run = create_run_root(workspace)
    assert second_run != run and second_id.endswith("_02")
    source = root / "source"; source.mkdir()
    dem = source / "dem.asc"; dem.write_text("dem", encoding="utf-8")
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        (source / f"release{suffix}").write_text(suffix, encoding="utf-8")
    provenance = materialize_layer_sources(run, str(dem), str(source / "release.shp"), "EPSG:2154", "EPSG:2154")
    assert (run / "inputs" / "dem" / "dem.asc").is_file()
    assert {Path(item["materialized_path"]).suffix for item in provenance["release"]["components"]} >= {".shp", ".shx", ".dbf", ".prj", ".cpg"}
    assert provenance["dem"]["source_sha256"] == provenance["dem"]["materialized_sha256"]
    assert not list(run.rglob("xgeoclaw")) and not list(run.rglob("*.dylib"))
    try:
        materialize_layer_sources(second_run, str(dem), str(source / "missing.shp"), "EPSG:2154", "EPSG:2154")
    except ValueError as exc:
        assert "materialized" in str(exc)
    else:
        raise AssertionError("Missing source dataset was accepted")
    try:
        validate_workspace("")
    except ValueError as exc:
        assert "Working Directory" in str(exc)
    else:
        raise AssertionError("Missing workspace was accepted")
    assert completed_runs(workspace) == []
    for name, status in (("run_A", "completed"), ("run_B", "cancelled"), ("run_C", "completed")):
        candidate = workspace / "runs" / name; candidate.mkdir()
        write_run_metadata(candidate, {"format": 1, "status": status, "avac_directory": "AVAC"})
    # Imported, immutable benchmark cases retain their completed result at
    # <workspace>/Run instead of synthesizing a normal run-id directory.
    imported = workspace / "Run"; imported.mkdir()
    write_run_metadata(imported, {"format": 1, "status": "completed", "avac_directory": "AVAC"})
    assert [path.name for path in completed_runs(workspace)] == ["run_C", "run_A", "Run"]
print("workspace validation, isolated run ids, data-only input materialization: PASS")
