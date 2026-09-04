"""Contracts for AVAC's same-level wet/dry positivity limiter."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
CLAWPACK = ROOT / "avac-main" / "clawpack-v5.14.0"
AMRCLAW = CLAWPACK / "amrclaw" / "src" / "2d"
GEOCLAW = CLAWPACK / "geoclaw" / "src" / "2d" / "shallow"
AVAC = ROOT / "avac-main" / "src" / "AVAC"
WAVE = ROOT / "avac-main" / "src" / "WAVE"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_positivity_relimit_is_avac_only_and_uses_a_complete_halo():
    module = _source(GEOCLAW / "geoclaw_module.f90")
    setprob = _source(AVAC / "setprob.f90")
    step2 = _source(GEOCLAW / "step2.f90")
    flux2 = _source(GEOCLAW / "flux2fw.f")
    limiter = _source(AMRCLAW / "inlinelimiter.f")
    wave_setprob = _source(WAVE / "setprob.f90")
    makefile = _source(GEOCLAW / "Makefile.geoclaw")

    assert "logical :: use_fwave_positivity_limiter = .false." in module
    assert "use_fwave_positivity_limiter = imodel_rh >= 1 .and. mxnest == 1" in setprob
    assert "use_fwave_positivity_limiter" not in wave_setprob
    assert "nghost < 5" in setprob
    assert "mbc < 5" in step2
    assert "relimit => use_fwave_positivity_limiter" in step2
    assert "relimit => use_fwave_positivity_limiter" in flux2
    assert "call limiter_range" in flux2
    assert "mthlim,-1,mx+2" in flux2.replace(" ", "")
    assert "subroutine limiter_range" in limiter
    assert "do 190 i = ilo, ihi" in limiter
    assert "$(amrlib)/inlinelimiter.f" in makefile
    assert "$(amrlib)/limiter.f" not in makefile


def test_generated_avac_and_wave_ghost_widths_remain_separate():
    avac_setrun = _source(AVAC / "setrun.py")
    wave_setrun = _source(WAVE / "setrun.py")
    runtime = _source(ROOT / "validation" / "avac4qgis_validation" / "runtime.py")

    assert "clawdata.num_ghost = 5 if uses_positivity_relimit else 2" in avac_setrun
    assert "avac_ghost_cells = 5" in runtime
    assert "geoclaw_ghost_cells = 2" in runtime
    assert "clawdata.num_ghost = 2" in wave_setrun


def test_extended_limiter_populates_only_the_requested_outer_faces(tmp_path: Path):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the f-wave limiter regression")

    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    driver.write_text(
        """
program limiter_range_driver
  implicit none
  integer, parameter :: maxm=8, meqn=1, mwaves=1, mbc=5, mx=4
  integer :: mthlim(mwaves)
  real(kind=8) :: legacy(meqn,mwaves,1-mbc:maxm+mbc)
  real(kind=8) :: extended(meqn,mwaves,1-mbc:maxm+mbc)
  real(kind=8) :: speed(mwaves,1-mbc:maxm+mbc)

  legacy = 1.d0
  legacy(1,1,-1) = 0.25d0
  legacy(1,1,mx+3) = 0.25d0
  extended = legacy
  speed = 1.d0
  speed(1,mx+2) = -1.d0
  mthlim = 3

  call limiter(maxm,meqn,mwaves,mbc,mx,legacy,speed,mthlim)
  call limiter_range(maxm,meqn,mwaves,mbc,mx,extended,speed,mthlim,-1,mx+2)
  write(*,'(5(es24.16,1x))') legacy(1,1,0), legacy(1,1,mx+2), &
      extended(1,1,0), extended(1,1,mx+2), &
      maxval(abs(legacy(1,1,1:mx+1)-extended(1,1,1:mx+1)))
end program limiter_range_driver
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            compiler,
            "-O0",
            "-fcheck=all",
            "-ffixed-line-length-none",
            str(AMRCLAW / "inlinelimiter.f"),
            str(driver),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    values = np.fromstring(
        subprocess.run(
            [str(executable)], check=True, cwd=tmp_path, capture_output=True, text=True
        ).stdout,
        sep=" ",
    )

    assert values.size == 5
    legacy_left, legacy_right, extended_left, extended_right, interior_delta = values
    assert legacy_left == pytest.approx(1.0)
    assert legacy_right == pytest.approx(1.0)
    assert extended_left == pytest.approx(0.4)
    assert extended_right == pytest.approx(0.4)
    assert interior_delta == pytest.approx(0.0)


_STEP2_STUBS = """
module geoclaw_module
  implicit none
  real(kind=8) :: dry_tolerance = 1.d-12
  logical :: use_fwave_positivity_limiter = .false.
end module geoclaw_module

module amr_module
  implicit none
  integer :: mwaves = 1
  integer :: mcapa = 0
end module amr_module

subroutine flux2(ixy,maxm,meqn,maux,mbc,mx,q1d,dtdx1d,aux1,aux2,aux3, &
                 faddm,faddp,gaddm,gaddp,cfl1d,rpn2,rpt2)
  use geoclaw_module, only: use_fwave_positivity_limiter
  implicit none
  integer :: ixy,maxm,meqn,maux,mbc,mx
  real(kind=8) :: q1d(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: dtdx1d(1-mbc:maxm+mbc)
  real(kind=8) :: aux1(maux,1-mbc:maxm+mbc)
  real(kind=8) :: aux2(maux,1-mbc:maxm+mbc)
  real(kind=8) :: aux3(maux,1-mbc:maxm+mbc)
  real(kind=8) :: faddm(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: faddp(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: gaddm(meqn,1-mbc:maxm+mbc,2)
  real(kind=8) :: gaddp(meqn,1-mbc:maxm+mbc,2)
  real(kind=8) :: cfl1d
  external rpn2,rpt2
  faddm = 0.d0
  faddp = 0.d0
  gaddm = 0.d0
  gaddp = 0.d0
  cfl1d = 0.d0
  if (use_fwave_positivity_limiter .and. ixy == 1) then
    faddm(1,2) = 1.d0
    faddp(1,2) = 1.d0
    if (meqn >= 3) then
      faddm(2,2) = 2.d0
      faddp(2,2) = 2.d0
      faddm(3,2) = 3.d0
      faddp(3,2) = 3.d0
    end if
  end if
end subroutine flux2

subroutine dummy_riemann
end subroutine dummy_riemann
"""


def test_flag_disabled_step2_is_bounds_safe_with_two_ghost_cells(tmp_path: Path):
    """The shared WAVE/GeoClaw path must retain its two-cell stencil."""
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the shared step2 regression")

    stubs = tmp_path / "stubs.f90"
    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    stubs.write_text(_STEP2_STUBS.strip() + "\n", encoding="utf-8")
    driver.write_text(
        """
program disabled_step2_driver
  use geoclaw_module
  implicit none
  integer, parameter :: maxm=2,meqn=1,maux=1,mbc=2,mx=2,my=2
  real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: fm(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: fp(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: gm(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: gp(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: cfl
  external dummy_riemann

  use_fwave_positivity_limiter = .false.
  q = 1.d0
  aux = 1.d0
  call step2(maxm,meqn,maux,mbc,mx,my,q,aux,1.d0,1.d0,0.1d0,cfl, &
             fm,fp,gm,gp,dummy_riemann,dummy_riemann)
  write(*,'(es24.16)') sum(abs(fm))+sum(abs(fp))+sum(abs(gm))+sum(abs(gp))+cfl
end program disabled_step2_driver
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            compiler,
            "-O0",
            "-fcheck=all",
            "-J",
            str(tmp_path),
            str(stubs),
            str(GEOCLAW / "step2.f90"),
            str(driver),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    value = float(
        subprocess.run(
            [str(executable)], check=True, cwd=tmp_path, capture_output=True, text=True
        ).stdout
    )
    assert value == pytest.approx(0.0)


def test_enabled_step2_limits_each_conserved_flux_before_the_update(tmp_path: Path):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the shared step2 regression")

    stubs = tmp_path / "stubs.f90"
    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    stubs.write_text(_STEP2_STUBS.strip() + "\n", encoding="utf-8")
    driver.write_text(
        """
program enabled_step2_driver
  use geoclaw_module
  implicit none
  integer, parameter :: maxm=2,meqn=3,maux=1,mbc=5,mx=2,my=2
  real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: fm(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: fp(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: gm(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: gp(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: cfl,hleft,hright
  external dummy_riemann

  use_fwave_positivity_limiter = .true.
  q = 0.d0
  q(1,:,:) = 0.1d0
  aux = 1.d0
  call step2(maxm,meqn,maux,mbc,mx,my,q,aux,1.d0,1.d0,1.d0,cfl, &
             fm,fp,gm,gp,dummy_riemann,dummy_riemann)
  hleft = q(1,1,1) - (fm(1,2,1)-fp(1,1,1)) &
                    - (gm(1,1,2)-gp(1,1,1))
  hright = q(1,2,1) - (fm(1,3,1)-fp(1,2,1)) &
                     - (gm(1,2,2)-gp(1,2,1))
  write(*,'(6(es24.16,1x))') hleft,hright,hleft+hright, &
      fm(1,2,1),fm(2,2,1)/fm(1,2,1),fm(3,2,1)/fm(1,2,1)
end program enabled_step2_driver
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            compiler,
            "-O0",
            "-fcheck=all",
            "-J",
            str(tmp_path),
            str(stubs),
            str(GEOCLAW / "step2.f90"),
            str(driver),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    values = np.fromstring(
        subprocess.run(
            [str(executable)], check=True, cwd=tmp_path, capture_output=True, text=True
        ).stdout,
        sep=" ",
    )

    assert values.size == 6
    hleft, hright, total, mass_flux, xmomentum_ratio, ymomentum_ratio = values
    assert hleft >= 0.0
    assert hleft < 2.0e-12
    assert hright == pytest.approx(0.2, abs=2.0e-12)
    assert total == pytest.approx(0.2, abs=2.0e-12)
    assert mass_flux == pytest.approx(0.1, abs=2.0e-12)
    assert xmomentum_ratio == pytest.approx(2.0)
    assert ymomentum_ratio == pytest.approx(3.0)
