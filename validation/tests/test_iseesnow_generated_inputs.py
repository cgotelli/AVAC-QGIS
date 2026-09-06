"""Authenticate exported terrain as well as the original ISeeSnow DEM."""
import importlib.util
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "iseesnow_generated_input_driver",
    Path(__file__).resolve().parents[1] / "ISeeSnow/run_iseesnow_avac.py",
)
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)

FIGURE_SPEC = importlib.util.spec_from_file_location(
    "iseesnow_generated_input_figure",
    Path(__file__).resolve().parents[1] / "ISeeSnow/paper_figures/make_iseesnow_figures.py",
)
FIGURE = importlib.util.module_from_spec(FIGURE_SPEC)
FIGURE_SPEC.loader.exec_module(FIGURE)


EXPECTED_NATIVE_CONTROLS = {
    "adjoint.data", "amr.data", "claw.data", "dtopo.data",
    "fgmax_grids.data", "fgout_grids.data", "flagregions.data",
    "friction.data", "gauges.data", "geoclaw.data", "multilayer.data",
    "qinit.data", "refinement.data", "regions.data", "setprob.data",
    "surge.data", "topo.data",
}


def write_native_controls(output):
    for name in EXPECTED_NATIVE_CONTROLS:
        (output / name).write_text(f"native controls: {name}")


def test_driver_and_article_share_the_complete_managed_control_contract():
    assert DRIVER.ISEESNOW_NATIVE_CONTROL_FILENAMES == EXPECTED_NATIVE_CONTROLS
    assert FIGURE.ISEESNOW_NATIVE_CONTROL_FILENAMES is DRIVER.ISEESNOW_NATIVE_CONTROL_FILENAMES


def test_generated_input_manifest_records_actual_native_files(tmp_path):
    output = tmp_path / "AVAC/_output"
    output.mkdir(parents=True)
    terrain = tmp_path / "Topo/topography.asc"
    terrain.parent.mkdir()
    terrain.write_text("full precision terrain")
    (output.parent / "init.avacbin").write_bytes(b"native initial state")
    write_native_controls(output)
    (output / "extra_control.data").write_text("additional native controls")
    (output / "fort.log").write_text("not an input")
    records = DRIVER.capture_generated_input_manifest(tmp_path, output)
    assert {r["name"] for r in records} == {
        "Topo/topography.asc", "AVAC/init.avacbin", "AVAC/_output/extra_control.data",
        *(f"AVAC/_output/{name}" for name in EXPECTED_NATIVE_CONTROLS),
    }
    for record in records:
        assert DRIVER.sha256(Path(record["path"])) == record["sha256"]
    terrain.write_text("changed precision")
    record = next(r for r in records if r["name"] == "Topo/topography.asc")
    with pytest.raises(RuntimeError, match="Generated input"):
        DRIVER.require_file_unchanged(terrain, record["sha256"], "Generated input terrain")


def test_generated_manifest_rejects_missing_native_initial_state(tmp_path):
    output = tmp_path / "AVAC/_output"
    output.mkdir(parents=True)
    terrain = tmp_path / "Topo/topography.asc"
    terrain.parent.mkdir()
    terrain.write_text("terrain")
    write_native_controls(output)
    with pytest.raises(FileNotFoundError, match="init.avacbin"):
        DRIVER.capture_generated_input_manifest(tmp_path, output)


def test_article_checks_generated_terrain_and_complete_native_input_manifest(tmp_path):
    run = tmp_path / "Run"
    output = run / "AVAC/_output"
    output.mkdir(parents=True)
    terrain = run / "Topo/topography.asc"
    terrain.parent.mkdir()
    terrain.write_text("17 digit terrain")
    (output.parent / "init.avacbin").write_bytes(b"native initial state")
    write_native_controls(output)
    (output / "extra_control.data").write_text("additional native controls")
    records = DRIVER.capture_generated_input_manifest(run, output)
    summary = {"generated_input_manifest": records}
    assert FIGURE._verify_generated_inputs("case", tmp_path, summary) == records
    with pytest.raises(RuntimeError, match="omits"):
        FIGURE._verify_generated_inputs("case", tmp_path, {"generated_input_manifest": records[:-1]})
    with pytest.raises(RuntimeError, match="duplicate"):
        FIGURE._verify_generated_inputs("case", tmp_path, {"generated_input_manifest": records + records[:1]})
    without_extra = [r for r in records if r["name"] != "AVAC/_output/extra_control.data"]
    with pytest.raises(RuntimeError, match="omits native inputs"):
        FIGURE._verify_generated_inputs("case", tmp_path, {"generated_input_manifest": without_extra})
    extra = output / "extra_control.data"
    extra.write_text("changed extra controls")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        FIGURE._verify_generated_inputs("case", tmp_path, summary)
    extra.write_text("additional native controls")
    terrain.write_text("lower precision terrain")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        FIGURE._verify_generated_inputs("case", tmp_path, summary)


@pytest.mark.parametrize("missing", [None, *sorted(EXPECTED_NATIVE_CONTROLS)])
def test_capture_rejects_zero_or_missing_required_native_controls(tmp_path, missing):
    output = tmp_path / "AVAC/_output"
    output.mkdir(parents=True)
    terrain = tmp_path / "Topo/topography.asc"
    terrain.parent.mkdir()
    terrain.write_text("terrain")
    (output.parent / "init.avacbin").write_bytes(b"initial state")
    if missing is not None:
        write_native_controls(output)
        (output / missing).unlink()
    with pytest.raises(FileNotFoundError, match="native control inputs are missing"):
        DRIVER.capture_generated_input_manifest(tmp_path, output)


@pytest.mark.parametrize("missing", [None, *sorted(EXPECTED_NATIVE_CONTROLS)])
def test_article_rejects_removed_controls_even_when_manifest_records_are_removed(
    tmp_path, missing,
):
    run = tmp_path / "Run"
    output = run / "AVAC/_output"
    output.mkdir(parents=True)
    terrain = run / "Topo/topography.asc"
    terrain.parent.mkdir()
    terrain.write_text("terrain")
    (output.parent / "init.avacbin").write_bytes(b"initial state")
    write_native_controls(output)
    records = DRIVER.capture_generated_input_manifest(run, output)
    removed = EXPECTED_NATIVE_CONTROLS if missing is None else {missing}
    for name in removed:
        (output / name).unlink()
    records = [
        record for record in records
        if record["name"] not in {f"AVAC/_output/{name}" for name in removed}
    ]
    with pytest.raises(RuntimeError, match="omits native inputs"):
        FIGURE._verify_generated_inputs("case", tmp_path, {"generated_input_manifest": records})


def test_article_does_not_invent_generated_input_provenance_for_legacy_runs(tmp_path):
    assert FIGURE._verify_generated_inputs("case", tmp_path, {}) is None
    with pytest.raises(RuntimeError, match="invalid generated input manifest"):
        FIGURE._verify_generated_inputs("case", tmp_path, {"generated_input_manifest": []})
