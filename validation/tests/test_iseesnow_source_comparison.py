"""Cross-source comparisons must authenticate data and expose unmatched controls."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "ISeeSnow" / "compare_source_runs.py"
SPEC = importlib.util.spec_from_file_location("iseesnow_source_comparison", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
COMPARISON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARISON)


@pytest.fixture
def authenticated_run(tmp_path: Path):
    root = tmp_path / "results"
    case = root / "CoulombOnly"
    official = tmp_path / "official"
    official.mkdir()
    (case / "Inputs").mkdir(parents=True)
    (case / "Submission").mkdir()
    (case / "Run/AVAC").mkdir(parents=True)
    original = official / "DEM_CoulombOnly.asc"
    original.write_text("1 2\n3 4\n")
    supplied = case / "Inputs" / original.name
    supplied.write_bytes(original.read_bytes())
    solver = tmp_path / "solver.exe"
    solver.write_bytes(b"immutable solver identity")
    backend = tmp_path / "setrun.py"
    backend.write_text("# immutable backend identity\n")
    fields = {}
    for variable in ("pft", "pfv"):
        fields[variable] = case / "Submission" / f"AVAC4QGIS_{variable}.asc"
        fields[variable].write_text("1 2\n3 4\n")
    mass = case / "native_mass_history.csv"
    mass.write_text("time,volume\n0,100\n1200,100\n")
    for name in ("initial_depth_normal.asc", "initial_depth_vertical.asc"):
        (case / name).write_text("1 2\n3 4\n")
    plugin = case / "plugin.yaml"
    plugin.write_text("rheology: Coulomb\n")
    configuration = case / "Submission" / "configuration.txt"
    configuration.write_text("recorded case controls\n")
    prepared = case / "Run/AVAC/AVAC_configuration.yaml"
    prepared.write_text("rheology: {model: Coulomb, mu: 0.4}\nrelease: {d0: 1.5}\ndem_extent: {cell_size: 5}\n")
    summary = {key: 1 for key in COMPARISON.PROTOCOL_KEYS}
    summary.update({
        "case": "CoulombOnly", "execution_mode": "current_source",
        "limiter": "minmod", "diagnostic_gauge": None,
        "simulation_end_ceiling_seconds": 1200.0, "fixed_grid_output_frame_count": 121,
        "solver": str(solver), "solver_sha256": COMPARISON.sha256(solver),
        "setrun_backend": str(backend), "setrun_backend_sha256": COMPARISON.sha256(backend),
        "submission_pft_sha256": COMPARISON.sha256(fields["pft"]),
        "submission_pfv_sha256": COMPARISON.sha256(fields["pfv"]),
        "official_input_manifest": [{"name": original.name, "path": str(supplied), "sha256": COMPARISON.sha256(original)}],
        "native_mass_history": str(mass), "plugin_case": str(plugin), "configuration": str(configuration),
        "accepted_cfl_violation_count": 0, "maximum_courant_number": 0.5, "cfl_max": 1.0,
    })
    summary_path = case / "run_summary.json"
    summary_path.write_text(json.dumps(summary))
    def grid(path):
        return SimpleNamespace(values_north=np.loadtxt(path), x_centres=np.arange(2), y_centres=np.arange(2))
    raster = SimpleNamespace(
        read_grid=grid,
        same_grid=lambda candidate, target: (candidate.values_north.shape == target.values_north.shape, "shape mismatch"),
    )
    paper = SimpleNamespace(unique_submission_path=lambda root, case, variable: fields[variable], yaml=yaml)
    def load(label="baseline"):
        return COMPARISON.load_run(root, "CoulombOnly", label, grid(original), official, raster, paper)
    return SimpleNamespace(load=load, summary=summary, summary_path=summary_path,
                           paths={"solver": solver, "backend": backend, "input": supplied,
                                  "official": original, **fields}, official=official)


@pytest.mark.parametrize("mode", ["current_source", "explicit_solver_source_snapshot"])
def test_recorded_source_or_packaged_files_are_authenticated(authenticated_run, mode):
    fixture = authenticated_run
    fixture.summary["execution_mode"] = mode
    fixture.summary_path.write_text(json.dumps(fixture.summary))
    result = fixture.load()
    assert result["provenance"]["execution_mode"] == mode
    assert result["provenance"]["solver"]["sha256"] == fixture.summary["solver_sha256"]
    np.testing.assert_array_equal(result["_fields"]["pft"]["_values_north"], [[1, 2], [3, 4]])


@pytest.mark.parametrize("key", ["solver", "backend", "input", "official", "pft", "pfv"])
def test_changed_authenticated_artifact_refuses_comparison(authenticated_run, key):
    authenticated_run.paths[key].write_bytes(b"9 8\n7 6\n")
    with pytest.raises(RuntimeError, match="Artifact hash mismatch"):
        authenticated_run.load()


@pytest.mark.parametrize("key", ["limiter", "solver_sha256", "submission_pfv_sha256", "maximum_courant_number"])
def test_missing_required_record_cannot_be_treated_as_matched(authenticated_run, key):
    del authenticated_run.summary[key]
    authenticated_run.summary_path.write_text(json.dumps(authenticated_run.summary))
    with pytest.raises(RuntimeError, match="lacks required fields"):
        authenticated_run.load()


def test_missing_official_input_record_is_rejected(authenticated_run):
    (authenticated_run.official / "release.shp").write_bytes(b"required official release")
    with pytest.raises(RuntimeError, match="official input manifest is incomplete"):
        authenticated_run.load()


def test_duration_mismatch_refuses_by_default_and_is_explicit_on_opt_in(authenticated_run):
    baseline = authenticated_run.load()
    candidate = copy.deepcopy(baseline)
    candidate["label"] = "candidate"
    candidate["protocol"]["simulation_end_ceiling_seconds"] = 120.0
    candidate["protocol"]["fixed_grid_output_frame_count"] = 13
    with pytest.raises(RuntimeError, match="explicitly unmatched diagnostic"):
        COMPARISON.compare_protocols([baseline, candidate])
    differences = COMPARISON.compare_protocols([baseline, candidate], allow_differences=True)
    assert differences["simulation_end_ceiling_seconds"] == {"baseline": 1200.0, "candidate": 120.0}
    assert differences["fixed_grid_output_frame_count"] == {"baseline": 121, "candidate": 13}


@pytest.mark.parametrize("section,key,value", [
    ("protocol", "limiter", "superbee"),
    ("physical_protocol", "rheology", {"mu": 0.5}),
])
def test_numerical_or_physical_mismatch_refuses(authenticated_run, section, key, value):
    baseline = authenticated_run.load()
    candidate = copy.deepcopy(baseline)
    candidate["label"] = "candidate"
    candidate[section][key] = value
    with pytest.raises(RuntimeError, match="protocol differs"):
        COMPARISON.compare_protocols([baseline, candidate])


def test_different_release_field_refuses_even_when_summary_controls_match(authenticated_run):
    baseline = authenticated_run.load()
    candidate = copy.deepcopy(baseline)
    candidate["label"] = "candidate"
    candidate["provenance"]["generated_initial_fields"]["initial_depth_normal.asc"]["sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="initial_field.initial_depth_normal.asc"):
        COMPARISON.compare_protocols([baseline, candidate])


def test_mixed_executable_suite_refuses(authenticated_run):
    baseline = authenticated_run.load()
    candidate = copy.deepcopy(baseline)
    candidate["label"] = "candidate"
    cases = [{"runs": [baseline, candidate]}, {"runs": copy.deepcopy([baseline, candidate])}]
    COMPARISON.validate_source_cohorts(cases)
    cases[1]["runs"][1]["provenance"]["solver"]["sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="candidate suite mixes"):
        COMPARISON.validate_source_cohorts(cases)


def test_nonfinite_cfl_diagnostic_refuses(authenticated_run):
    authenticated_run.summary["maximum_courant_number"] = float("nan")
    authenticated_run.summary_path.write_text(json.dumps(authenticated_run.summary))
    with pytest.raises(RuntimeError, match="finite CFL diagnostics"):
        authenticated_run.load()
