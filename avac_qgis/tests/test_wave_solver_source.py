"""Contracts separating shared water corrections from AVAC-only physics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WAVE = ROOT / "avac-main" / "src" / "WAVE"
AVAC = ROOT / "avac-main" / "src" / "AVAC"


def source(name: str) -> str:
    return (WAVE / name).read_text(encoding="utf-8").lower()


def test_wave_uses_standard_water_riemann_solver_not_avac_yield_solver():
    makefile = source("Makefile")
    assert "$(claw)/riemann/src/rpn2_geoclaw.f" in makefile
    assert "./rpn2_geoclaw.f" not in makefile
    assert "d-claw" not in source("src2.f90")
    assert "rheology_module" not in source("src2.f90")
    assert "imodel_rh" not in source("src2.f90")
    assert "d-claw" in (AVAC / "rpn2_geoclaw.f").read_text().lower()


def test_wave_does_not_enable_granular_depth_amr_transfer():
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in WAVE.glob("*.f90")
    )
    assert "conserve_depth_amr = .true." not in combined


def test_wave_initial_state_is_conservative_and_supports_momentum():
    qinit = source("qinit_module.f90")
    assert "qinit_cell_average" in qinit
    assert "qinit_type == 5" in qinit
    assert "qinit_state(3,num_points)" in qinit
    assert "q(m,i,j) = dq" in qinit


def test_wave_dry_state_definition_matches_geoclaw_riemann_solver():
    before = source("b4step2.f90")
    source_step = source("src2.f90")
    assert "q(1,i,j)<=dry_tolerance" in before
    assert "q(1,i,j) <= dry_tolerance" in source_step
    assert "q(2,i,j) = 0.d0" in source_step
    assert "q(3,i,j) = 0.d0" in source_step


def test_hydraulic_boundaries_are_optional_and_compiled():
    makefile = source("Makefile")
    setprob = source("setprob.f90")
    assert "./hydraulic_bc_module.f90" in makefile
    assert "./bc2amr.f90" in makefile
    assert "$(geolib)/bc2amr.f90" in makefile
    assert "call setup_hydraulic_bc()" in setprob
    assert "if (.not.exists)" in source("hydraulic_bc_module.f90")


def test_internal_inflow_v2_is_conservative_across_amr_cell_areas():
    module = source("internal_inflow_module.f90")
    assert "version /= 1 .and. version /= 2" in module
    assert "if (inflow_version == 2) rate = rate / (dx*dy)" in module


def test_runtime_never_reuses_legacy_amr_dependent_source():
    execution = (ROOT / "avac_qgis" / "core" / "wave_execution.py").read_text(encoding="utf-8").lower()
    boundaries = (ROOT / "avac_qgis" / "core" / "wave_boundaries.py").read_text(encoding="utf-8").lower()
    assert 'int(summary.get("source_format", 0)) != 2' in execution
    assert '"source_format": 2' in boundaries
