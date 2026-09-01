"""Source-level contract for AVAC's conservative AMR state transfer."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GEOCLAW = ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d" / "shallow"
AVAC = ROOT / "avac-main" / "src" / "AVAC"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_conservative_amr_mode_is_opt_in_and_avac_enables_it():
    module = _source(GEOCLAW / "geoclaw_module.f90")
    setprob = _source(AVAC / "setprob.f90")

    assert "logical :: conserve_depth_amr = .false." in module
    assert "conserve_depth_amr = .true." in setprob


def test_new_fine_patches_transfer_depth_without_subtracting_topography():
    filval = _source(GEOCLAW / "filval.f90")
    filpatch = _source(GEOCLAW / "filpatch.f90")

    for source in (filval, filpatch):
        assert "if (conserve_depth_amr) then" in source
        assert "max_offset_x" in source
        assert "max_offset_y" in source
        assert "slope_scale" in source

    assert "coarseval(2+ii) = max(valc(1,i+ii,j), 0.d0)" in filval
    assert "eta_coarse(i_coarse,j_coarse) = max(h, 0.d0)" in filpatch
    # The non-AVAC branch remains present for GeoClaw/WAVE lake-at-rest
    # interpolation; AVAC must take the direct-depth branch above instead.
    assert "h_fine = max(eta_fine - aux(" in filpatch


def test_fine_to_coarse_avac_restriction_uses_all_children():
    update = _source(GEOCLAW / "update.f90")

    block_start = update.index("if (conserve_depth_amr) then")
    water_branch = update.index("else if (nwet > 0) then", block_start)
    avac_block = update[block_start:water_branch]

    assert "hc = hsum / totrat" in avac_block
    assert "huc = husum / totrat" in avac_block
    assert "hvc = hvsum / totrat" in avac_block
    assert "/ nwet" not in avac_block


def test_avac_speed_refinement_rejects_numerically_dry_kinetic_films():
    flagging = _source(GEOCLAW / "flag2refine2.f90")
    setprob = _source(AVAC / "setprob.f90")

    assert "sqrt(q(1,i,j)) * speed" in flagging
    assert "sqrt(refinement_energy_depth)" in flagging
    assert "speed_tolerance(m)" in flagging
    assert "sqrt(dry_tolerance) * speed_limit" not in flagging
    assert "refinement_energy_depth = velocity_depth_threshold_rh" in setprob
    assert ".not. conserve_depth_amr" in flagging
    assert "energy_speed > numerical_energy_speed" in flagging


def test_avac_positivity_repair_uses_local_inflow_only():
    stepgrid = _source(GEOCLAW / "stepgrid.f")

    assert "if (conserve_depth_amr) then" in stepgrid
    assert "call redistribute_negative_depth" in stepgrid
    assert "remaining = -q(1,i,j)" in stepgrid
    assert "carries_inflow" in stepgrid
    assert "q(2,ni(n),nj(n))*dble(i-ni(n))" in stepgrid
    assert "factor = max(0.d0,1.d0-take/available)" in stepgrid
    assert "q(m,ni(n),nj(n)) = factor*q(m,ni(n),nj(n))" in stepgrid
    assert "static reservoir" in stepgrid


def test_wave_does_not_enable_avac_conservative_depth_mode():
    wave = _source(ROOT / "avac-main" / "src" / "WAVE" / "setprob.f90")

    assert "conserve_depth_amr = .true." not in wave
