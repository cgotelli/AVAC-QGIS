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

    assert "sqrt(q(1,i,j)) * speed" in flagging
    assert "sqrt(dry_tolerance) * speed_limit" in flagging
    assert ".not. conserve_depth_amr" in flagging
    assert "energy_speed > numerical_energy_speed" in flagging


def test_avac_uses_patch_consistent_second_order_limiting():
    step2 = _source(GEOCLAW / "step2.f90")
    flux2 = _source(GEOCLAW / "flux2fw.f")
    makefile = _source(AVAC / "Makefile")
    setrun = _source(AVAC / "setrun.py")

    assert "use geoclaw_module, only: dry_tolerance" in step2
    assert "avac_positivity_relimiter" in makefile
    assert "logical, parameter :: relimit = .false." in step2
    assert "relimit = conserve_depth_amr" not in step2
    assert "do i=1,mx" in step2
    assert "do j=1,my" in step2

    # Every AVAC run uses the same two-ghost method.  At the two patch-edge
    # interfaces the wave-family limiter is rebuilt from the conserved-state
    # jumps that are available, and identical, on both neighboring patches.
    assert "avac_patch_edge_limiter" in makefile
    assert "#ifdef avac_patch_edge_limiter" in flux2
    assert "fwave_edge(meqn,mwaves,2)" in flux2
    assert "dq_edge=q1d(m,ie)-q1d(m,ie-1)" in flux2
    assert "dq_upwind=q1d(m,ie-1)-q1d(m,ie-2)" in flux2
    assert "dq_upwind=q1d(m,ie+1)-q1d(m,ie)" in flux2
    assert "elseif (mthlim(mw).eq.5) then" in flux2
    assert "stop 'invalid limiter method'" in flux2
    assert "fwave(m,mw,ie)=wlimitr*fwave_edge(m,mw,ked)" in flux2
    assert "avac_conservative_mass_flux" not in makefile
    assert "shared_mass_flux" not in flux2

    assert "clawdata.num_ghost = 2" in setrun
    assert "num_ghost = 3" not in setrun
    assert "use_operational_voellmy_stencil" not in setrun


def test_avac_regularizes_transverse_riemann_velocity_without_damping_state():
    makefile = _source(AVAC / "Makefile")
    transverse = _source(
        ROOT
        / "avac-main"
        / "clawpack-v5.14.0"
        / "riemann"
        / "src"
        / "rpt2_geoclaw.f"
    )

    assert "avac_regularized_transverse_velocity" in makefile
    assert "#ifdef avac_regularized_transverse_velocity" in transverse
    assert transverse.count("h_eps = max(tol,1.d-8)") == 2
    assert "use rheology_module" not in transverse
