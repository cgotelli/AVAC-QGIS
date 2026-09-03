"""Source-level contract for AVAC's conservative AMR state transfer."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


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


def test_avac_positivity_repair_uses_local_downstream_recipients_only():
    stepgrid = _source(GEOCLAW / "stepgrid.f")

    assert "if (conserve_depth_amr) then" in stepgrid
    assert "call redistribute_negative_depth" in stepgrid
    assert "remaining = -q(1,i,j)" in stepgrid
    assert "carries_outflow" in stepgrid
    assert "q(2,ni(n),nj(n))*dble(ni(n)-i)" in stepgrid
    assert "q(3,ni(n),nj(n))*dble(nj(n)-j)" in stepgrid
    assert "q(2,ni(n),nj(n))*dble(i-ni(n))" not in stepgrid
    assert "factor = max(0.d0,1.d0-take/available)" in stepgrid
    assert "q(m,ni(n),nj(n)) = factor*q(m,ni(n),nj(n))" in stepgrid
    assert "downstream recipient" in stepgrid


def _compile_positivity_repair_driver(tmp_path: Path) -> np.ndarray:
    """Compile the fixed-form repair routine and exercise its donor direction."""
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the AVAC positivity regression")

    source = (GEOCLAW / "stepgrid.f").read_text(encoding="utf-8")
    start = source.lower().index("      subroutine redistribute_negative_depth")
    repair = tmp_path / "redistribute_negative_depth.f"
    driver = tmp_path / "driver.f90"
    repair_object = tmp_path / "redistribute_negative_depth.o"
    executable = tmp_path / "driver"
    repair.write_text(source[start:], encoding="utf-8")
    driver.write_text(
        """
program positivity_repair_driver
  implicit none
  integer, parameter :: nvar = 3, mitot = 5, mjtot = 5, mbc = 1
  real(kind=8) :: q(nvar,mitot,mjtot)
  real(kind=8) :: mass_before, mass_after

  q = 0.d0

  ! The centre cell has overshot below zero.  East and north are downstream
  ! recipients (their momentum points away from it); west and south point
  ! into the undershot cell and must remain unchanged.
  q(:,3,3) = (/ -0.5d0, 0.6d0, -0.8d0 /)
  q(:,4,3) = (/  1.d0, 2.d0,  0.5d0 /)
  q(:,3,4) = (/  1.d0,-0.25d0,4.d0 /)
  q(:,2,3) = (/  1.d0, 1.d0,  0.2d0 /)
  q(:,3,2) = (/  1.d0, 0.1d0,3.d0 /)

  mass_before = sum(q(1,2:4,2:4))
  call redistribute_negative_depth(q,mitot,mjtot,mbc,nvar,1.d-12)
  mass_after = sum(q(1,2:4,2:4))
  write(*,'(17(es24.16,1x))') mass_before, mass_after, q(:,3,3), &
       q(:,4,3), q(:,3,4), q(:,2,3), q(:,3,2)
end program positivity_repair_driver
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            compiler,
            "-O0",
            "-fcheck=all",
            "-ffixed-form",
            "-ffixed-line-length-none",
            str(repair),
            "-c",
            "-o",
            str(repair_object),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            compiler,
            "-O0",
            "-fcheck=all",
            str(driver),
            str(repair_object),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    return np.fromstring(
        subprocess.run(
            [str(executable)], check=True, cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout,
        sep=" ",
    )


def test_avac_positivity_repair_debits_downstream_recipients(tmp_path: Path):
    values = _compile_positivity_repair_driver(tmp_path)
    assert values.size == 17

    mass_before, mass_after = values[:2]
    centre = values[2:5]
    east = values[5:8]
    north = values[8:11]
    west = values[11:14]
    south = values[14:17]

    # The 0.5 depth deficit is recovered from the two downstream recipients,
    # giving each the common factor 1 - 0.5 / (1 + 1) = 0.75.  This preserves
    # total depth and each recipient's velocity, while leaving upstream cells
    # untouched.  The preceding inflow-direction implementation did exactly
    # the opposite and fails these four directional assertions.
    assert mass_after == pytest.approx(mass_before, abs=1.0e-14)
    np.testing.assert_allclose(centre, 0.0, atol=1.0e-14)
    np.testing.assert_allclose(east, (0.75, 1.5, 0.375), atol=1.0e-14)
    np.testing.assert_allclose(north, (0.75, -0.1875, 3.0), atol=1.0e-14)
    np.testing.assert_allclose(west, (1.0, 1.0, 0.2), atol=1.0e-14)
    np.testing.assert_allclose(south, (1.0, 0.1, 3.0), atol=1.0e-14)


def test_wave_does_not_enable_avac_conservative_depth_mode():
    wave = _source(ROOT / "avac-main" / "src" / "WAVE" / "setprob.f90")

    assert "conserve_depth_amr = .true." not in wave
