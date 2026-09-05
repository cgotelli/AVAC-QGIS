from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


VALIDATION = Path(__file__).resolve().parents[1]


def _load_driver(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, VALIDATION / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_kerswell_explicit_solver_threads_source_run_and_provenance(
    tmp_path: Path, monkeypatch,
) -> None:
    driver = _load_driver(
        "kerswell_explicit_solver_driver",
        "AVAC/Kerswell_Coulomb/run_avac_validation.py",
    )
    solver = tmp_path / "frozen solver" / "xgeoclaw.exe"
    solver.parent.mkdir()
    solver.write_bytes(b"exact solver")
    source = tmp_path / "repository source" / "AVAC"
    source.mkdir(parents=True)
    (source / "setrun.py").write_text("# exact backend\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def unexpected_resolver(kind: str) -> Path:
        raise AssertionError(f"explicit solver unexpectedly resolved {kind}")

    def fake_prepare(case: Path, **kwargs) -> Path:
        observed["source_override"] = kwargs["source_override"]
        observed["initial_dt_factor"] = kwargs["initial_dt_factor"]
        work = case / "AVAC"
        work.mkdir(parents=True)
        return work

    def fake_run(kind: str, work: Path, cores: int, *, executable_override) -> None:
        observed.update(kind=kind, work=work, cores=cores, solver=executable_override)

    def fake_extract(work: Path, controls: dict[str, object]):
        observed["extract_solver"] = controls["solver"]
        values = np.asarray([0.0, 1.0, 2.0])
        fields = np.zeros((3, 3))
        summary = {
            "_front": values,
            "_rear": values,
            "_rear_exact": values,
            "_mass": values,
        }
        return values, values, fields, fields, summary

    monkeypatch.setattr(driver, "HERE", tmp_path)
    monkeypatch.setattr(driver, "AVAC_SOURCE", source)
    monkeypatch.setattr(driver, "solver_executable", unexpected_resolver)
    monkeypatch.setattr(driver, "prepare_avac_coulomb_case", fake_prepare)
    monkeypatch.setattr(
        driver,
        "configure_analytical_coulomb_amr_compatibility",
        lambda work: {"analytical_validation_ghost_cells": 2},
    )
    monkeypatch.setattr(driver, "moving_front_corridors", lambda *args, **kwargs: [])
    monkeypatch.setattr(driver, "configure_front_amr", lambda *args, **kwargs: {})
    monkeypatch.setattr(driver, "run_solver", fake_run)
    monkeypatch.setattr(driver, "extract", fake_extract)
    monkeypatch.setattr(driver, "plot", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run_avac_validation.py", "--solver", str(solver), "--cores", "1",
         "--solver-source", str(source), "--ny", "11", "--case-name", "kshort",
         "--initial-dt-factor", "0.15"],
    )

    driver.main()

    assert observed["source_override"] == source
    assert observed["initial_dt_factor"] == pytest.approx(0.15)
    assert observed["solver"] == solver.resolve()
    assert observed["extract_solver"] == str(solver.resolve())
    assert driver.TRANSVERSE_CELLS == 11
    controls = json.loads(
        (tmp_path / "kshort" / "controls.json").read_text(encoding="utf-8")
    )
    assert controls["source_setrun"] == str((source / "setrun.py").resolve())
    assert controls["solver"] == str(solver.resolve())
    assert controls["width_base_cells"] == 11
    assert controls["requested_t_final_s"] == 10.0
    assert controls["outputs"] == 200
    assert controls["initial_dt_factor"] == pytest.approx(0.15)
    assert controls["initial_dt_s"] == pytest.approx(
        0.15 * 0.01 / np.sqrt(driver.GRAVITY)
    )


def test_prepare_coulomb_case_retains_legacy_initial_dt_default(
    tmp_path: Path, monkeypatch,
) -> None:
    runtime_module = __import__(
        "avac4qgis_validation.runtime", fromlist=["prepare_avac_coulomb_case"]
    )
    replacements: dict[str, str] = {}
    monkeypatch.setattr(runtime_module, "_run_setrun", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runtime_module,
        "_replace_data_value",
        lambda path, label, value: replacements.__setitem__(label, value),
    )

    runtime_module.prepare_avac_coulomb_case(
        tmp_path / "legacy-default",
        xlower=0.0,
        xupper=1.0,
        ylower=0.0,
        yupper=1.0,
        dx=0.5,
        t_final=1.0,
        nout=4,
        mu=0.1,
        depth=lambda X, Y: np.ones_like(X),
    )

    assert float(replacements["dt_initial"]) == pytest.approx(
        0.2 * 0.5 / np.sqrt(runtime_module.GRAVITY)
    )


@pytest.mark.parametrize("initial_dt_factor", [0.0, -0.1, np.nan, np.inf, -np.inf])
def test_prepare_coulomb_case_rejects_invalid_initial_dt_before_cleanup(
    tmp_path: Path, monkeypatch, initial_dt_factor: float,
) -> None:
    runtime_module = __import__(
        "avac4qgis_validation.runtime", fromlist=["prepare_avac_coulomb_case"]
    )

    def unexpected_cleanup(case: Path) -> None:
        raise AssertionError(f"invalid factor unexpectedly cleaned {case}")

    monkeypatch.setattr(runtime_module, "clean_case", unexpected_cleanup)
    with pytest.raises(ValueError, match="initial_dt_factor must be finite and positive"):
        runtime_module.prepare_avac_coulomb_case(
            tmp_path / "invalid-factor",
            xlower=0.0,
            xupper=1.0,
            ylower=0.0,
            yupper=1.0,
            dx=0.5,
            t_final=1.0,
            nout=4,
            mu=0.1,
            depth=lambda X, Y: np.ones_like(X),
            initial_dt_factor=initial_dt_factor,
        )


def test_kerswell_output_schedule_rejects_partial_and_off_cadence() -> None:
    driver = _load_driver(
        "kerswell_output_schedule_driver",
        "AVAC/Kerswell_Coulomb/run_avac_validation.py",
    )
    complete = np.linspace(0.0, 10.0, 200)
    driver.require_complete_output_schedule(complete, 10.0, 200)
    serialized = np.asarray([float(f"{value:.8E}") for value in complete])
    driver.require_complete_output_schedule(serialized, 10.0, 200)

    with pytest.raises(RuntimeError, match="incomplete or off cadence"):
        driver.require_complete_output_schedule(complete[:-1], 10.0, 200)
    shifted = complete.copy()
    shifted[100] += 0.01
    with pytest.raises(RuntimeError, match="incomplete or off cadence"):
        driver.require_complete_output_schedule(shifted, 10.0, 200)


def test_sloping_bed_explicit_solver_bypasses_default_resolver(
    tmp_path: Path, monkeypatch,
) -> None:
    driver = _load_driver(
        "sloping_explicit_solver_driver",
        "AVAC/Coulomb_sloping_bed/run_avac_validation.py",
    )
    solver = tmp_path / "frozen solver" / "xgeoclaw.exe"
    solver.parent.mkdir()
    solver.write_bytes(b"exact solver")
    source = tmp_path / "repository source" / "AVAC"
    source.mkdir(parents=True)
    (source / "setrun.py").write_text("# exact backend\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def unexpected_resolver(kind: str) -> Path:
        raise AssertionError(f"explicit solver unexpectedly resolved {kind}")

    def fake_prepare(case: Path, *args) -> Path:
        observed["prepare_solver"] = args[-2]
        observed["prepare_source"] = args[-1]
        work = case / "AVAC"
        work.mkdir(parents=True)
        (case / "controls.json").write_text(
            json.dumps({
                "source_setrun_sha256": driver.sha256(source / "setrun.py"),
                "solver_sha256": driver.sha256(solver),
            }),
            encoding="utf-8",
        )
        return work

    def fake_run(work: Path, cores: int, selected: Path) -> None:
        observed.update(work=work, cores=cores, run_solver=selected)

    monkeypatch.setattr(driver, "HERE", tmp_path)
    monkeypatch.setattr(driver, "solver_executable", unexpected_resolver)
    monkeypatch.setattr(driver, "prepare", fake_prepare)
    monkeypatch.setattr(driver, "run", fake_run)
    monkeypatch.setattr(driver, "extract", lambda case: ({}, case / "results"))
    monkeypatch.setattr(driver, "plot", lambda case: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run_avac_validation.py", "--solver", str(solver), "--cores", "1",
         "--solver-source", str(source), "--case-name", "sshort"],
    )

    driver.main()

    assert observed["prepare_solver"] == solver.resolve()
    assert observed["prepare_source"] == source.resolve()
    assert observed["run_solver"] == solver.resolve()


def test_sloping_output_schedule_rejects_partial_and_off_cadence() -> None:
    driver = _load_driver(
        "sloping_output_schedule_driver",
        "AVAC/Coulomb_sloping_bed/run_avac_validation.py",
    )
    complete = np.linspace(0.0, 6.0, 60)
    driver.require_complete_output_schedule(complete, 6.0, 60)
    serialized = np.asarray([float(f"{value:.8E}") for value in complete])
    driver.require_complete_output_schedule(serialized, 6.0, 60)

    with pytest.raises(RuntimeError, match="incomplete or off cadence"):
        driver.require_complete_output_schedule(complete[:23], 6.0, 60)
    shifted = complete.copy()
    shifted[30] += 0.01
    with pytest.raises(RuntimeError, match="incomplete or off cadence"):
        driver.require_complete_output_schedule(shifted, 6.0, 60)
