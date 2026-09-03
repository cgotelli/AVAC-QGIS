from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _setrun_whole_cell_count():
    """Load the small pure grid-count helper without importing Clawpack."""
    path = ROOT / "avac-main" / "src" / "AVAC" / "setrun.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    helper = next(
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == "_whole_cell_count"
    )
    namespace = {"np": np}
    module = ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 - local source under test
    return namespace["_whole_cell_count"]


def _refines(depth: float, speed: float, speed_tolerance: float, reference_depth: float) -> bool:
    """Python statement of the Fortran conservative kinetic-energy guard."""
    return (
        speed > speed_tolerance
        and depth**0.5 * speed > reference_depth**0.5 * speed_tolerance
    )


def test_amr_energy_guard_resolves_meaningful_motion_without_velocity_cap():
    assert _refines(0.05, 0.051, 0.05, 0.05)
    assert _refines(0.005, 0.20, 0.05, 0.05)
    assert not _refines(1.0e-4, 0.20, 0.05, 0.05)


def test_fortran_amr_guard_is_independent_of_speed_limit():
    flagger = (
        ROOT
        / "avac-main"
        / "clawpack-v5.14.0"
        / "geoclaw"
        / "src"
        / "2d"
        / "shallow"
        / "flag2refine2.f90"
    ).read_text(encoding="utf-8")
    setprob = (ROOT / "avac-main" / "src" / "AVAC" / "setprob.f90").read_text(encoding="utf-8")

    assert "refinement_energy_depth" in flagger
    assert "sqrt(refinement_energy_depth)" in flagger
    assert "speed_tolerance(m)" in flagger
    assert "sqrt(dry_tolerance) * speed_limit" not in flagger
    assert "refinement_energy_depth = velocity_depth_threshold_rh" in setprob


def test_avac_runtime_disables_the_shared_solver_velocity_cap():
    setrun = (ROOT / "avac-main" / "src" / "AVAC" / "setrun.py").read_text(
        encoding="utf-8"
    )

    assert "geo_data.speed_limit         = 1.0e99" in setrun


def test_setrun_preserves_valid_float_domains_and_rejects_partial_cells():
    """Grid counts must not lose a cell to binary floating-point truncation."""
    count_cells = _setrun_whole_cell_count()

    # This is a valid 0.1-m-wide domain, but direct ``int(span / dx)`` gives
    # zero on ordinary binary floats because the subtraction is just below 0.1.
    assert int((967799.1 - 967799.0) / 0.1) == 0
    assert count_cells(967799.0, 967799.1, 0.1, "x") == 1
    assert count_cells(0.0, 0.3, 0.1, "x") == 3
    with pytest.raises(ValueError, match="whole number"):
        count_cells(0.0, 0.25, 0.1, "x")

    source = (ROOT / "avac-main" / "src" / "AVAC" / "setrun.py").read_text(encoding="utf-8")
    for expected in (
        "nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['cell_size'], 'x')",
        "nx = _whole_cell_count(Param['xlower'], Param['xupper'], Param['dx'], 'x')",
        "fgout.nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['cell_size'], 'x')",
        "fgout.nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['dx'], 'x')",
        "fgout_zoom.nx = _whole_cell_count(",
    ):
        assert expected in source


def test_sloping_bed_front_diagnostic_is_not_derived_from_speed_limit():
    driver = (
        ROOT
        / "validation"
        / "AVAC"
        / "Coulomb_sloping_bed"
        / "run_avac_validation.py"
    ).read_text(encoding="utf-8")

    assert "FRONT_ENERGY_SPEED_THRESHOLD_M32_S = 5.0e-5" in driver
    assert 'read_data_value(work / "geoclaw.data", "speed_limit")' not in driver
