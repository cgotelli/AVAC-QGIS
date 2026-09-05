from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import shapefile
import yaml


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VALIDATION))

from avac_qgis.core.preprocessing import QINIT_BINARY_HEADER, QINIT_BINARY_MAGIC
from avac4qgis_validation.notebook import validation_case

SPEC = importlib.util.spec_from_file_location(
    "run_iseesnow_avac", VALIDATION / "ISeeSnow" / "run_iseesnow_avac.py"
)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)

FIGURE_SPEC = importlib.util.spec_from_file_location(
    "make_iseesnow_figures",
    VALIDATION / "ISeeSnow" / "paper_figures" / "make_iseesnow_figures.py",
)
assert FIGURE_SPEC is not None and FIGURE_SPEC.loader is not None
FIGURE = importlib.util.module_from_spec(FIGURE_SPEC)
FIGURE_SPEC.loader.exec_module(FIGURE)


def test_benchmark_domain_edges_and_results_share_supplied_cell_centres(tmp_path: Path) -> None:
    grid = DRIVER.EsriGrid(
        tmp_path / "dem.asc", 3, 2, 10.0, -5.0, 5.0, -9999.0,
        np.zeros((2, 3), dtype=float),
    )
    configuration_path = tmp_path / "AVAC_configuration.yaml"
    configuration_path.write_text("dem_extent: {}\n", encoding="utf-8")

    DRIVER.set_benchmark_computational_extent(configuration_path, grid)

    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    assert configuration["dem_extent"] == {
        "xmin": 7.5, "xmax": 22.5, "ymin": -7.5, "ymax": 2.5,
        "nbx": 3, "nby": 2, "cell_size": 5.0,
    }
    assert configuration["result_grid"] == {
        "xllcenter": 10.0, "yllcenter": -5.0,
        "ncols": 3, "nrows": 2, "cell_size": 5.0,
    }


def test_normal_pft_preserves_internal_south_to_north_orientation() -> None:
    peak = np.array([[1.0, 2.0], [3.0, 4.0]])
    initial = np.array([[5.0, 0.0], [0.0, 0.0]])
    cosine = np.array([[1.0, 0.5], [0.25, 0.125]])

    result = DRIVER.normal_peak_thickness(peak, initial, cosine)

    np.testing.assert_allclose(result, [[5.0, 1.0], [0.75, 0.5]])


def test_normal_release_depth_uses_fractional_cell_coverage() -> None:
    dem = DRIVER.EsriGrid(
        Path("flat.asc"), 2, 2, 0.0, 0.0, 5.0, -9999.0,
        np.zeros((2, 2), dtype=float),
    )
    coverage = np.array([[1.0, 0.5], [0.25, 0.0]])

    vertical_depth, cosine = DRIVER.normal_depth_to_vertical(dem, coverage)

    np.testing.assert_allclose(cosine, np.ones((2, 2)))
    np.testing.assert_allclose(
        vertical_depth,
        DRIVER.NORMAL_RELEASE_THICKNESS_M * coverage,
    )


def test_iseesnow_initial_condition_keeps_the_active_binary_qinit_contract(tmp_path: Path) -> None:
    dem = DRIVER.EsriGrid(
        tmp_path / "dem.asc", 3, 2, 10.0, -5.0, 5.0, -9999.0,
        np.zeros((2, 3), dtype=float),
    )
    raster = DRIVER.benchmark_raster(dem, crs_authid="")
    coverage = np.array([[1.0, 0.5, 0.0], [0.25, 0.0, 1.0]])
    destination = tmp_path / "init.avacbin"

    vertical_depth, cosine_slope = DRIVER.write_iseesnow_initial_condition(
        destination, raster, dem, coverage,
    )

    payload = destination.read_bytes()
    assert payload.startswith(QINIT_BINARY_MAGIC)
    magic, ncols, nrows, components, reserved, xlow, yhigh, dx, dy = QINIT_BINARY_HEADER.unpack_from(payload)
    assert (magic, ncols, nrows, components, reserved) == (QINIT_BINARY_MAGIC, 3, 2, 1, 0)
    assert (xlow, yhigh, dx, dy) == (10.0, 0.0, 5.0, 5.0)
    np.testing.assert_allclose(cosine_slope, np.ones((2, 3)))
    np.testing.assert_allclose(vertical_depth, DRIVER.NORMAL_RELEASE_THICKNESS_M * coverage)
    np.testing.assert_allclose(
        np.frombuffer(payload, dtype="<f8", offset=QINIT_BINARY_HEADER.size),
        np.flipud(vertical_depth).ravel(),
    )


def test_copy_inputs_refreshes_existing_files_and_selects_official_parameter(
    tmp_path: Path, monkeypatch,
) -> None:
    benchmark = tmp_path / "benchmark"
    source = benchmark / "data" / "CoulombOnly" / "Inputs"
    source.mkdir(parents=True)
    official = {
        "DEM_CoulombOnly.asc": b"official dem",
        "release1HS.shp": b"official shape",
        "release1HS.shx": b"official index",
        "release1HS.dbf": b"official attributes",
        "simulationParameterValues_CoulombOnly.csv": b"official parameters",
    }
    for name, payload in official.items():
        (source / name).write_bytes(payload)
    case_root = tmp_path / "result" / "CoulombOnly"
    inputs_dir = case_root / "Inputs"
    inputs_dir.mkdir(parents=True)
    (inputs_dir / "DEM_CoulombOnly.asc").write_bytes(b"stale dem")
    (inputs_dir / "simulationParameterValues_stale.csv").write_bytes(b"stale")
    monkeypatch.setattr(DRIVER, "BENCHMARK_ROOT", benchmark)

    selected = DRIVER.copy_inputs("CoulombOnly", case_root)

    for name, payload in official.items():
        assert (inputs_dir / name).read_bytes() == payload
    assert selected["parameters"].name == "simulationParameterValues_CoulombOnly.csv"
    manifest = DRIVER.capture_official_input_manifest("CoulombOnly", case_root)
    assert {record["name"] for record in manifest} == set(official)
    DRIVER.require_input_manifest_unchanged(manifest)

    # Shapefile sidecars are solver inputs too; provenance must not cover only
    # the visible .shp path.
    (inputs_dir / "release1HS.dbf").write_bytes(b"replacement attributes")
    with pytest.raises(RuntimeError, match="release1HS.dbf"):
        DRIVER.require_input_manifest_unchanged(manifest)


def test_overwrite_invalidates_summary_and_exact_generated_artifacts_first(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "CoulombOnly"
    run_root = case_root / "Run"
    run_root.mkdir(parents=True)
    pft, pfv, configuration = DRIVER.submission_paths("CoulombOnly", case_root)
    generated = (
        pft,
        pfv,
        configuration,
        case_root / "native_mass_history.csv",
        case_root / "solver.log",
        case_root / "run_summary.json",
    )
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale\n", encoding="utf-8")
        DRIVER.pending_artifact_path(path).write_text(
            "partial\n", encoding="utf-8"
        )
    unrelated = case_root / "Inputs" / "official.asc"
    unrelated.parent.mkdir()
    unrelated.write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--overwrite"):
        DRIVER.prepare_case_transaction("CoulombOnly", case_root, False)

    returned = DRIVER.prepare_case_transaction("CoulombOnly", case_root, True)

    assert returned == (
        run_root.resolve(), pft.resolve(), pfv.resolve(), configuration.resolve(),
        (case_root / "native_mass_history.csv").resolve(),
    )
    assert not run_root.exists()
    assert all(not path.exists() for path in generated)
    assert all(
        not DRIVER.pending_artifact_path(path).exists() for path in generated
    )
    assert unrelated.read_text(encoding="utf-8") == "keep\n"


def test_atomic_summary_writer_replaces_complete_json(tmp_path: Path) -> None:
    summary = tmp_path / "run_summary.json"
    summary.write_text('{"old": true}\n', encoding="utf-8")

    DRIVER.atomic_write_json(summary, {"status": "completed", "value": 3})

    assert json.loads(summary.read_text(encoding="utf-8")) == {
        "status": "completed",
        "value": 3,
    }
    assert not DRIVER.pending_artifact_path(summary).exists()


def test_iseesnow_rejects_zero_exit_solver_fatal_marker(
    tmp_path: Path, monkeypatch,
) -> None:
    solver = tmp_path / "xgeoclaw.exe"
    solver.write_bytes(b"fixture")
    output = tmp_path / "output"
    output.mkdir()
    log = tmp_path / "solver.log"

    def fake_run(command, *, cwd, env, stdout, stderr):
        stdout.write("**** Too many dt reductions ****\n")
        stdout.write("**** Stopping calculation ****\n")
        stdout.flush()
        return DRIVER.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(DRIVER.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="fatal marker"):
        DRIVER.launch_solver(solver, output, log, 1)


def test_iseesnow_rejects_zero_exit_accepted_cfl_violation(
    tmp_path: Path, monkeypatch,
) -> None:
    solver = tmp_path / "xgeoclaw.exe"
    solver.write_bytes(b"fixture")
    output = tmp_path / "output"
    output.mkdir()
    (output / "fort.amr").write_text(
        "maximum Courant number seen = 0.75\n", encoding="utf-8",
    )
    log = tmp_path / "solver.log"

    def fake_run(command, *, cwd, env, stdout, stderr):
        stdout.write(
            "*** WARNING *** Courant number  =  0.2185D+02  is larger "
            "than input cfl_max =   0.1000D+01  on grid 180 level   1\n"
        )
        stdout.flush()
        return DRIVER.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(DRIVER.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"accepted CFL violation.*21\.85"):
        DRIVER.launch_solver(solver, output, log, 1)


@pytest.mark.parametrize(
    "warning",
    (
        "Courant number = 1.25 is larger than input cfl_max = 1.0\n",
        "Courant number = ******** is larger\nthan input cfl_max = 1.0\n",
    ),
)
def test_iseesnow_rejects_any_cfl_warning_variant_in_fort_amr(
    tmp_path: Path, monkeypatch, warning: str,
) -> None:
    solver = tmp_path / "xgeoclaw.exe"
    solver.write_bytes(b"fixture")
    output = tmp_path / "output"
    output.mkdir()
    (output / "fort.amr").write_text(
        warning + "maximum Courant number seen = 1.00\n", encoding="utf-8",
    )
    log = tmp_path / "solver.log"

    def fake_run(command, *, cwd, env, stdout, stderr):
        stdout.write("normal completion\n")
        stdout.flush()
        return DRIVER.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(DRIVER.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="numeric value unavailable"):
        DRIVER.launch_solver(solver, output, log, 1)


def test_iseesnow_parses_clean_cfl_audit() -> None:
    diagnostics = DRIVER.solver_cfl_diagnostics(
        "normal completion\n",
        "maximum Courant number seen = 0.631D+00\n",
    )

    assert diagnostics == {
        "accepted_cfl_violation_count": 0,
        "maximum_courant_number": pytest.approx(0.631),
        "maximum_violating_courant_number": None,
        "first_accepted_cfl_violation": None,
    }


def test_iseesnow_deduplicates_same_cfl_warning_across_solver_logs() -> None:
    warning = (
        "*** WARNING *** Courant number  =  0.2185D+02  is larger "
        "than input cfl_max =   0.1000D+01  on grid 180 level   1\n"
    )

    diagnostics = DRIVER.solver_cfl_diagnostics(
        warning,
        warning + "maximum Courant number seen = 0.2185D+02\n",
    )

    assert diagnostics["accepted_cfl_violation_count"] == 1
    assert diagnostics["maximum_violating_courant_number"] == pytest.approx(21.85)
    assert diagnostics["maximum_courant_number"] == pytest.approx(21.85)


def _write_ascii_field(path: Path, values: np.ndarray) -> None:
    rows, columns = values.shape
    header = (
        f"ncols {columns}\n"
        f"nrows {rows}\n"
        "xllcenter 0\n"
        "yllcenter 0\n"
        "cellsize 5\n"
        "nodata_value -9999\n"
    )
    with path.open("w", encoding="utf-8") as stream:
        stream.write(header)
        np.savetxt(stream, values, fmt="%.9g")


def _write_clean_article_provenance(
    root: Path,
) -> dict[str, dict[str, float]]:
    expected: dict[str, dict[str, float]] = {}
    for index, (case, _label) in enumerate(FIGURE.CASES):
        case_root = root / case
        submission = case_root / "Submission"
        submission.mkdir(parents=True)
        pft = submission / f"{case}_AVAC4QGIS_pft.asc"
        pfv = submission / f"{case}_AVAC4QGIS_pfv.asc"
        pft_values = np.asarray([[0.0, 1.0 + index], [2.5 + index, 0.0]])
        pfv_values = np.asarray([[0.0, 10.0 + index], [20.5 + index, 0.0]])
        _write_ascii_field(pft, pft_values)
        _write_ascii_field(pfv, pfv_values)
        expected[case] = {
            "pft": float(np.max(pft_values)),
            "pfv": float(np.max(pfv_values)),
        }
        case_protocol = FIGURE.CASE_PROTOCOL[case]
        inputs = case_root / "Inputs"
        inputs.mkdir()
        dem = inputs / f"DEM_{case}.asc"
        release = inputs / "release.shp"
        dem.write_bytes(f"{case} dem".encode())
        release.write_bytes(f"{case} release".encode())
        official_input_manifest = [
            {
                "name": path.name,
                "path": str(path.resolve()),
                "sha256": FIGURE.sha256(path),
            }
            for path in (dem, release)
        ]
        template = case_root / "avac_iseesnow_template.yaml"
        template_payload = {
            "computation": {
                "t_max": 1200.0,
                "nb_simul": 120,
                "cfl_max": 1.0,
                "refinement": 1,
                "cell_size": 5.0,
                "state_momentum_regularization_depth": 0.05,
                "voellmy_state_momentum_regularization_depth": 0.10,
                "limiter": case_protocol["limiter"],
                "cfl_target": case_protocol["cfl_target"],
            },
            "output": {"delta_t": 10.0},
            "animation": {"n_out": 121},
            "rheology": {
                "model": case_protocol["model"],
                "mu": case_protocol["mu"],
                "xi": case_protocol["xi"],
            },
        }
        template.write_text(
            yaml.safe_dump(template_payload, sort_keys=False), encoding="utf-8"
        )
        plugin_case = case_root / f"AVAC4QGIS_ISeeSnow_{case}_Case.yaml"
        plugin_parameters = {
            **FIGURE.PLUGIN_COMMON_PROTOCOL,
            "computation.limiter": case_protocol["limiter"],
            "computation.cfl_target": case_protocol["cfl_target"],
            "rheology.model": case_protocol["model"],
            "rheology.mu": case_protocol["mu"],
            "rheology.xi": case_protocol["xi"],
        }
        plugin_case.write_text(
            yaml.safe_dump(
                {
                    "format": "AVAC4QGIS plugin configuration",
                    "version": 1,
                    "working_directory": str(case_root.resolve()),
                    "avac": {
                        "configuration_template": str(template.resolve()),
                        "parameters": plugin_parameters,
                        "inputs": {
                            "dem": {"source": str(dem.resolve())},
                            "release": {"source": str(release.resolve())},
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        configuration = submission / f"{case}_AVAC4QGIS.txt"
        configuration.write_text(
            "AVAC4QGIS ISeeSnow benchmark configuration\n"
            f"case = {case}\n"
            "execution_mode = current_source\n"
            "solver_sha256 = same-solver\n"
            "setrun_backend_sha256 = same-setrun\n"
            f"submission_pft_sha256 = {FIGURE.sha256(pft)}\n"
            f"submission_pfv_sha256 = {FIGURE.sha256(pfv)}\n"
            f"rheology = {case_protocol['model']}\n"
            f"mu = {case_protocol['mu']}\n"
            f"xi = {case_protocol['xi']}\n"
            "cell_size_m = 5\n"
            "refinement_levels = 1\n"
            "finest_effective_cell_size_m = 5\n"
            "simulation_end_ceiling_s = 1200\n"
            "native_state_output_interval_s = 10\n"
            "fixed_grid_output_interval_s = 10\n"
            "fixed_grid_output_frame_count = 121\n"
            f"limiter = {case_protocol['limiter']}\n"
            f"cfl_target = {case_protocol['cfl_target']}\n"
            "cfl_max = 1\n"
            "coulomb_state_momentum_regularization_depth_m = 0.05\n"
            "voellmy_state_momentum_regularization_depth_m = 0.10\n"
            "active_state_momentum_regularization_depth_m = "
            f"{case_protocol['active_state_momentum_regularization_depth_m']}\n",
            encoding="utf-8",
        )
        summary = {
            "case": case,
            "execution_mode": "current_source",
            **FIGURE.PUBLICATION_PROTOCOL,
            "limiter": case_protocol["limiter"],
            "cfl_target": case_protocol["cfl_target"],
            "active_state_momentum_regularization_depth_m": case_protocol[
                "active_state_momentum_regularization_depth_m"
            ],
            "state_momentum_regularization_depth_m": case_protocol[
                "active_state_momentum_regularization_depth_m"
            ],
            "accepted_cfl_violation_count": 0,
            "maximum_courant_number": 0.75,
            "solver_sha256": "same-solver",
            "setrun_backend_sha256": "same-setrun",
            "submission_pft_sha256": FIGURE.sha256(pft),
            "submission_pfv_sha256": FIGURE.sha256(pfv),
            "official_input_manifest": official_input_manifest,
            "configuration": str(configuration.resolve()),
            "plugin_case": str(plugin_case.resolve()),
        }
        (root / case / "run_summary.json").write_text(
            json.dumps(summary), encoding="utf-8",
        )
    return expected


def test_article_figure_requires_clean_same_source_cfl_provenance(
    tmp_path: Path,
) -> None:
    _write_clean_article_provenance(tmp_path)

    summaries = FIGURE.validate_current_source_results(tmp_path)

    assert set(summaries) == {case for case, _label in FIGURE.CASES}
    artifacts = summaries["IdealizedTopo"]["_article_verified_artifacts"]
    assert artifacts["plugin_case"]["sha256"] == FIGURE.sha256(
        Path(artifacts["plugin_case"]["path"])
    )
    assert len(artifacts["official_inputs"]) == 2
    bad_summary = tmp_path / "RealTopo" / "run_summary.json"
    payload = json.loads(bad_summary.read_text(encoding="utf-8"))
    payload["accepted_cfl_violation_count"] = 1
    bad_summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="accepted CFL violations"):
        FIGURE.validate_current_source_results(tmp_path)


@pytest.mark.parametrize(
    ("case", "field", "replacement"),
    (
        ("IdealizedTopo", "simulation_end_ceiling_seconds", 20.0),
        ("CoulombOnly", "limiter", "vanleer"),
        (
            "RealTopo",
            "active_state_momentum_regularization_depth_m",
            0.05,
        ),
    ),
)
def test_article_figure_rejects_a_nonselected_protocol(
    tmp_path: Path, case: str, field: str, replacement: object,
) -> None:
    _write_clean_article_provenance(tmp_path)
    summary_path = tmp_path / case / "run_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload[field] = replacement
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="selected publication protocol"):
        FIGURE.validate_current_source_results(tmp_path)


def test_article_figure_verifies_rheology_from_contained_plugin_case(
    tmp_path: Path,
) -> None:
    _write_clean_article_provenance(tmp_path)
    summary = json.loads(
        (tmp_path / "IdealizedTopo" / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )
    plugin_path = Path(summary["plugin_case"])
    plugin = yaml.safe_load(plugin_path.read_text(encoding="utf-8"))
    plugin["avac"]["parameters"]["rheology.model"] = "Coulomb"
    plugin_path.write_text(
        yaml.safe_dump(plugin, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="contained plugin-case YAML.*model"):
        FIGURE.validate_current_source_results(tmp_path)


@pytest.mark.parametrize(
    ("maximum_cfl", "cfl_max"),
    ((float("nan"), 1.0), (float("inf"), 1.0), (-0.1, 1.0), (0.5, 0.0)),
)
def test_article_figure_rejects_nonphysical_cfl_audit_values(
    tmp_path: Path, maximum_cfl: float, cfl_max: float,
) -> None:
    _write_clean_article_provenance(tmp_path)
    summary_path = tmp_path / "IdealizedTopo" / "run_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["maximum_courant_number"] = maximum_cfl
    payload["cfl_max"] = cfl_max
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid CFL audit"):
        FIGURE.validate_current_source_results(tmp_path)


def test_article_figure_reads_selected_peaks_from_validated_rasters_not_csv(
    tmp_path: Path,
) -> None:
    expected = _write_clean_article_provenance(tmp_path)
    # This derived report is deliberately stale. Selected article values must
    # never be read from it.
    (tmp_path / "field_summary.csv").write_text(
        "case,model,variable,peak\n"
        "IdealizedTopo,AVAC4QGIS,pft,999999\n"
        "IdealizedTopo,AVAC4QGIS,pfv,999999\n",
        encoding="utf-8",
    )
    summaries = FIGURE.validate_current_source_results(tmp_path)

    fields = FIGURE.validated_submission_fields(tmp_path, summaries)

    for case, values in expected.items():
        assert fields[case]["pft"]["peak"] == pytest.approx(values["pft"])
        assert fields[case]["pfv"]["peak"] == pytest.approx(values["pfv"])


def test_article_figure_rejects_duplicate_selected_submission_raster(
    tmp_path: Path,
) -> None:
    _write_clean_article_provenance(tmp_path)
    duplicate = (
        tmp_path / "CoulombOnly" / "Submission"
        / "duplicate_AVAC4QGIS_pft.asc"
    )
    duplicate.write_text("duplicate\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Expected one CoulombOnly PFT.*found 2"):
        FIGURE.validate_current_source_results(tmp_path)


def test_article_peer_table_rejects_missing_and_duplicate_rows(
    tmp_path: Path,
) -> None:
    source = (
        VALIDATION / "ISeeSnow" / "paper_figures"
        / "iseesnow_table_c1_core.csv"
    )
    table = pd.read_csv(source)
    missing = tmp_path / "missing.csv"
    table.drop(table[table["case"] == "CoulombOnly"].index[0]).to_csv(
        missing, index=False
    )
    with pytest.raises(RuntimeError, match="requires 11 CoulombOnly rows"):
        FIGURE.validated_peer_table(missing)

    duplicate = tmp_path / "duplicate.csv"
    pd.concat([table, table.iloc[[0]]], ignore_index=True).to_csv(
        duplicate, index=False
    )
    with pytest.raises(RuntimeError, match="duplicate case/model rows"):
        FIGURE.validated_peer_table(duplicate)


def test_coulomb_pfv_offscale_marker_keeps_all_peer_statistics() -> None:
    table_path = (
        VALIDATION / "ISeeSnow" / "paper_figures"
        / "iseesnow_table_c1_core.csv"
    )
    table, artifact = FIGURE.validated_peer_table(table_path)
    peers = table[table["case"] == "CoulombOnly"]
    values = peers["pfv_peak_mps"].to_numpy(float)

    statistics = FIGURE.peer_statistics(values)
    off_scale = FIGURE.coulomb_pfv_offscale_metadata(
        peers["model"].to_numpy(str), values, [105.0]
    )

    assert artifact["sha256"] == FIGURE.sha256(table_path)
    assert statistics["peer_count"] == 11
    assert statistics["peer_median"] == pytest.approx(np.median(values))
    assert statistics["peer_median"] != pytest.approx(
        np.median(values[peers["model"].to_numpy(str) != "r.avaflow"])
    )
    assert off_scale["model"] == "r.avaflow"
    assert off_scale["value"] == pytest.approx(322.59)
    assert off_scale["axis_min"] == pytest.approx(88.0)
    assert off_scale["axis_max"] == pytest.approx(118.0)
    assert off_scale["peer_count_in_statistics"] == 11
    assert off_scale["included_in_peer_statistics"] is True


def test_selected_runout_does_not_reopen_the_validated_pft(
    tmp_path: Path, monkeypatch,
) -> None:
    _write_clean_article_provenance(tmp_path)
    summaries = FIGURE.validate_current_source_results(tmp_path)
    fields = FIGURE.validated_submission_fields(tmp_path, summaries)

    def fail_reopen(_path: Path):
        raise AssertionError("validated PFT was reopened")

    monkeypatch.setattr(FIGURE, "read_ascii", fail_reopen)
    runout = FIGURE.runout_from_validated_field(
        fields["IdealizedTopo"]["pft"],
        {"_points": np.asarray([[0.0, 0.0], [10.0, 0.0]])},
    )

    assert runout == pytest.approx(5.0)


def test_thalweg_provenance_hashes_all_shapefile_sidecars(
    tmp_path: Path, monkeypatch,
) -> None:
    base = (
        tmp_path / "validation" / "_data" / "ISeeSnow" / "data"
        / "IdealizedTopo" / "Inputs" / "LINES" / "path_aimec"
    )
    base.parent.mkdir(parents=True)
    with shapefile.Writer(str(base), shapeType=shapefile.POLYLINE) as writer:
        writer.field("id", "N")
        writer.line([[[0.0, 0.0], [10.0, 0.0]]])
        writer.record(1)
    base.with_suffix(".prj").write_text("LOCAL_CS[]", encoding="utf-8")
    monkeypatch.setattr(FIGURE, "REPO", tmp_path)

    thalweg = FIGURE.validated_thalweg("IdealizedTopo")

    artifacts = thalweg["artifacts"]
    assert {Path(record["path"]).suffix for record in artifacts} == {
        ".dbf", ".prj", ".shp", ".shx",
    }
    assert all(
        record["sha256"] == FIGURE.sha256(Path(record["path"]))
        for record in artifacts
    )


def test_iseesnow_figure_notebook_uses_the_case_sensitive_published_path(tmp_path: Path) -> None:
    build_spec = importlib.util.spec_from_file_location("build_iseesnow_notebooks", VALIDATION / "build_notebooks.py")
    assert build_spec is not None and build_spec.loader is not None
    builder = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(builder)
    builder.ROOT = tmp_path

    builder.iseesnow_notebooks()

    notebook_path = tmp_path / "ISeeSnow" / "paper_figures" / "ISeeSnow_intercomparison_figures.ipynb"
    assert notebook_path.is_file()
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "validation_case('ISeeSnow', 'paper_figures')" in code
    assert validation_case("ISeeSnow", "paper_figures").path == VALIDATION / "ISeeSnow" / "paper_figures"


def test_iseesnow_requires_three_output_frames(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least three output frames"):
        DRIVER.configure_template(
            "IdealizedTopo", tmp_path,
            simulation_end_s=0.1,
            output_interval_s=0.1,
        )


def test_iseesnow_preserves_the_requested_fixed_grid_cadence() -> None:
    assert DRIVER.output_interval_count(1200.0, 10.0) == 120
    with pytest.raises(ValueError, match="exact multiple"):
        DRIVER.output_interval_count(0.25, 0.1)


def test_iseesnow_rejects_topography_paths_fortran_would_truncate(
    tmp_path: Path,
) -> None:
    short_run = tmp_path / "Run"
    assert DRIVER.require_supported_topography_path(short_run).name == "topography.asc"

    long_run = tmp_path / ("x" * DRIVER.FORTRAN_TOPOGRAPHY_PATH_LIMIT) / "Run"
    with pytest.raises(ValueError, match="shorter --results-root"):
        DRIVER.require_supported_topography_path(long_run)


def test_iseesnow_configures_state_regularization_independently_of_pfv(tmp_path: Path) -> None:
    destination = DRIVER.configure_template(
        "CoulombOnly",
        tmp_path,
        state_momentum_regularization_depth_m=0.075,
        voellmy_state_momentum_regularization_depth_m=0.125,
    )

    computation = yaml.safe_load(destination.read_text(encoding="utf-8"))["computation"]
    assert computation["velocity_depth_threshold"] == 0.05
    assert computation["state_momentum_regularization_depth"] == 0.075
    assert computation["voellmy_state_momentum_regularization_depth"] == 0.125
    assert computation["cfl_max"] == 1.0
    template = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert template["computation"]["nb_simul"] == 120
    assert template["animation"]["n_out"] == 121

    with pytest.raises(ValueError, match="non-negative and finite"):
        DRIVER.configure_template(
            "CoulombOnly",
            tmp_path,
            state_momentum_regularization_depth_m=float("nan"),
        )
    with pytest.raises(ValueError, match="Voellmy.*non-negative and finite"):
        DRIVER.configure_template(
            "IdealizedTopo",
            tmp_path,
            voellmy_state_momentum_regularization_depth_m=-0.01,
        )


@pytest.mark.parametrize(
    ("case_name", "expected"),
    (
        ("CoulombOnly", "minmod"),
        ("IdealizedTopo", "vanleer"),
        ("RealTopo", "vanleer"),
    ),
)
def test_iseesnow_uses_case_aware_default_limiter(
    case_name: str, expected: str, tmp_path: Path,
) -> None:
    case_root = tmp_path / case_name
    case_root.mkdir()
    destination = DRIVER.configure_template(case_name, case_root)

    computation = yaml.safe_load(destination.read_text(encoding="utf-8"))["computation"]
    assert DRIVER.selected_limiter(case_name) == expected
    assert computation["limiter"] == expected


@pytest.mark.parametrize("case_name", tuple(DRIVER.CASE_SPECIFICATIONS))
def test_iseesnow_preserves_explicit_limiter_override(
    case_name: str, tmp_path: Path,
) -> None:
    case_root = tmp_path / case_name
    case_root.mkdir()
    destination = DRIVER.configure_template(
        case_name, case_root, limiter="mc",
    )

    computation = yaml.safe_load(destination.read_text(encoding="utf-8"))["computation"]
    assert DRIVER.selected_limiter(case_name, "mc") == "mc"
    assert computation["limiter"] == "mc"


@pytest.mark.parametrize(
    ("case_name", "expected"),
    (("CoulombOnly", 0.25), ("IdealizedTopo", 0.5), ("RealTopo", 0.5)),
)
def test_iseesnow_uses_case_aware_default_cfl(
    case_name: str, expected: float, tmp_path: Path,
) -> None:
    case_root = tmp_path / case_name
    case_root.mkdir()

    destination = DRIVER.configure_template(case_name, case_root)

    computation = yaml.safe_load(destination.read_text(encoding="utf-8"))["computation"]
    assert DRIVER.selected_cfl_target(case_name) == expected
    assert computation["cfl_target"] == expected
    assert DRIVER.selected_cfl_target(case_name, 0.125) == 0.125


def test_practical_rest_rejects_an_early_three_frame_dip_and_later_rebound() -> None:
    rows = [
        {"time_seconds": float(index * 10), "moving_volume_fraction": fraction}
        for index, fraction in enumerate((0.2, 0.009, 0.008, 0.007, 0.02, 0.009, 0.008, 0.007))
    ]

    assert DRIVER.sustained_rest_times(rows) == (50.0, 70.0)
    assert DRIVER.rest_time(rows) == 70.0


def test_practical_rest_needs_three_outputs_remaining() -> None:
    rows = [
        {"time_seconds": 0.0, "moving_volume_fraction": 0.2},
        {"time_seconds": 10.0, "moving_volume_fraction": 0.009},
        {"time_seconds": 20.0, "moving_volume_fraction": 0.008},
    ]

    assert DRIVER.sustained_rest_times(rows) == (None, None)


def test_rest_reporting_requires_a_complete_native_history() -> None:
    rows = [
        {"frame": float(frame), "time_seconds": float(frame * 10)}
        for frame in range(4)
    ]
    DRIVER.require_complete_native_history(rows, 30.0, 10.0)

    with pytest.raises(RuntimeError, match="incomplete or non-contiguous"):
        DRIVER.require_complete_native_history(rows[:-1], 30.0, 10.0)
    off_cadence = [dict(row) for row in rows]
    off_cadence[-1]["time_seconds"] = 29.0
    with pytest.raises(RuntimeError, match="requested output cadence"):
        DRIVER.require_complete_native_history(off_cadence, 30.0, 10.0)


def test_native_bed_slopes_follow_q_array_axes() -> None:
    x = np.arange(4, dtype=float)[:, None]
    y = np.arange(3, dtype=float)[None, :]
    state = SimpleNamespace(aux=np.asarray([2.0 * x - 3.0 * y]))

    bx, by = DRIVER._native_bed_slopes(state, 1.0, 1.0)

    np.testing.assert_allclose(bx, 2.0)
    np.testing.assert_allclose(by, -3.0)


def test_raw_subthreshold_motion_is_audited_but_not_counted_as_practical_rest() -> None:
    depth = np.asarray([[0.01, 0.10]])
    speed = 0.02
    hu = depth * speed
    zeros = np.zeros_like(depth)

    moving, bands, reported_max = DRIVER._native_motion_statistics(
        depth, hu, zeros, zeros, zeros, np.ones_like(depth, dtype=bool), 1.0,
    )

    assert moving == pytest.approx(0.10)
    assert bands["moving_volume_vertical_h_dry_to_0p05_m3"] == pytest.approx(0.01)
    assert bands["moving_volume_vertical_h_0p10_to_0p20_m3"] == pytest.approx(0.10)
    assert reported_max == pytest.approx(speed)


def test_native_motion_rejects_nonfinite_state_instead_of_reporting_zero() -> None:
    depth = np.asarray([[0.10]])
    momentum = np.asarray([[float("nan")]])
    zeros = np.zeros_like(depth)

    with pytest.raises(RuntimeError, match="non-finite x momentum"):
        DRIVER._native_motion_statistics(
            depth,
            momentum,
            zeros,
            zeros,
            zeros,
            np.ones_like(depth, dtype=bool),
            1.0,
        )


def test_iseesnow_rebuilds_current_source_once_per_driver_process(
    tmp_path: Path, monkeypatch,
) -> None:
    """A pre-existing executable must not silently bypass the latest source."""
    source = tmp_path / "AVAC"
    source.mkdir()
    executable = source / ("xgeoclaw.exe" if DRIVER.os.name == "nt" else "xgeoclaw")
    executable.write_text("test executable", encoding="utf-8")
    calls: list[str] = []

    def build(kind: str) -> Path:
        calls.append(kind)
        return source

    monkeypatch.setattr(DRIVER, "build_solver", build)
    DRIVER.current_source_solver.cache_clear()
    try:
        assert DRIVER.current_source_solver() == executable
        assert DRIVER.current_source_solver() == executable
        assert calls == ["avac"]
    finally:
        DRIVER.current_source_solver.cache_clear()


def test_changed_solver_is_rejected(tmp_path: Path) -> None:
    solver = tmp_path / "xgeoclaw.exe"
    solver.write_bytes(b"first build")
    expected = DRIVER.sha256(solver)
    DRIVER.require_solver_unchanged(solver, expected)

    solver.write_bytes(b"replacement build")
    with pytest.raises(RuntimeError, match="changed during the validation run"):
        DRIVER.require_solver_unchanged(solver, expected)


def test_explicit_solver_requires_its_matching_source(tmp_path: Path) -> None:
    solver = tmp_path / "xgeoclaw.exe"
    solver.write_bytes(b"frozen executable")

    with pytest.raises(ValueError, match="must be supplied together"):
        DRIVER.run_case(
            "CoulombOnly",
            workers=1,
            overwrite=False,
            retain_raw_frames=False,
            spatial_order=2,
            solver_override=solver,
        )
