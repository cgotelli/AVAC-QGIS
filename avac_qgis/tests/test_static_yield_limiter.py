"""Regression tests for AVAC's vector-aware static-yield Riemann guard."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
AVAC = ROOT / "avac-main" / "src" / "AVAC"


_STUBS = """
module geoclaw_module
  implicit none
  real(kind=8) :: grav = 9.81d0
  real(kind=8) :: dry_tolerance = 1.d-12
  real(kind=8) :: rho = 300.d0
  real(kind=8) :: earth_radius = 1.d0
  real(kind=8) :: deg2rad = 1.d0
  integer :: coordinate_system = 1
end module geoclaw_module

module amr_module
  implicit none
  integer :: mcapa = 0
end module amr_module

module storm_module
  implicit none
  logical :: pressure_forcing = .false.
  integer :: pressure_index = 1
end module storm_module

subroutine riemanntype(hL,hR,uL,uR,hm,s1m,s2m,rare1,rare2,iwave,drytol,grav)
  implicit none
  integer, intent(in) :: iwave
  logical, intent(out) :: rare1, rare2
  real(kind=8), intent(in) :: hL,hR,uL,uR,drytol,grav
  real(kind=8), intent(out) :: hm,s1m,s2m
  hm = hL
  s1m = 0.d0
  s2m = 0.d0
  rare1 = .false.
  rare2 = .false.
end subroutine riemanntype

subroutine riemann_aug_JCP(maxiter,meqn,mwaves,hL,hR,huL,huR,hvL,hvR, &
                           bL,bR,uL,uR,vL,vR,phiL,phiR,pL,pR,sE1,sE2, &
                           drytol,grav,rho,sw,fw)
  implicit none
  integer, intent(in) :: maxiter, meqn, mwaves
  real(kind=8), intent(in) :: hL,hR,huL,huR,hvL,hvR,bL,bR,uL,uR,vL,vR
  real(kind=8), intent(in) :: phiL,phiR,pL,pR,sE1,sE2,drytol,grav,rho
  real(kind=8), intent(out) :: sw(3), fw(meqn,3)

  ! A nonzero sentinel means rpn2 reached the underlying Riemann solve rather
  ! than taking the static-yield early exit.
  sw = 0.d0
  fw = 0.d0
  sw(1) = 1.d0
  fw(1,1) = 1.d0
end subroutine riemann_aug_JCP
"""


def _compile_rpn_driver(tmp_path: Path) -> np.ndarray:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the AVAC Riemann regression")
    stubs = tmp_path / "stubs.f90"
    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    stubs.write_text(_STUBS.strip() + "\n", encoding="utf-8")
    driver.write_text("""
program static_yield_driver
  use rheology_module
  use geoclaw_module, only: coordinate_system
  implicit none
  real(kind=8) :: super_x, super_y, sub_x, sub_y, axial_x
  real(kind=8) :: wet_dry_super, wet_dry_sub, legacy_super, spherical_sub

  imodel_rh = 1
  rho_rh = 300.d0
  dx_avac = 1.d0
  dy_avac = 1.d0
  dt_avac = 0.01d0
  n_zones_rh = 1
  if (allocated(mu_zones_rh)) deallocate(mu_zones_rh)
  if (allocated(xi_zones_rh)) deallocate(xi_zones_rh)
  if (allocated(C_zones_rh)) deallocate(C_zones_rh)
  allocate(mu_zones_rh(1), xi_zones_rh(1), C_zones_rh(1))
  mu_zones_rh = 0.5d0
  xi_zones_rh = 1.d12
  C_zones_rh = 0.d0

  call run_wet_case(0.4d0, dsqrt(0.4d0**2 + 0.4d0**2)/0.5d0, 1, super_x)
  call run_wet_case(0.4d0, dsqrt(0.4d0**2 + 0.4d0**2)/0.5d0, 2, super_y)
  call run_wet_case(0.3d0, dsqrt(0.3d0**2 + 0.3d0**2)/0.5d0, 1, sub_x)
  call run_wet_case(0.3d0, dsqrt(0.3d0**2 + 0.3d0**2)/0.5d0, 2, sub_y)
  call run_wet_case(0.49d0, 0.49d0/0.5d0, 1, axial_x)
  call run_wet_dry_case(dsqrt(0.4d0**2 + 0.4d0**2)/0.5d0, wet_dry_super)
  call run_wet_dry_case(dsqrt(0.3d0**2 + 0.3d0**2)/0.5d0, wet_dry_sub)
  call run_legacy_wet_case(0.4d0, legacy_super)
  coordinate_system = 2
  call run_wet_case(0.3d0, 0.d0, 1, spherical_sub)
  coordinate_system = 1
  write(*,*) super_x, super_y, sub_x, sub_y, axial_x, wet_dry_super, wet_dry_sub, legacy_super, spherical_sub

contains

  subroutine run_wet_case(normal_gradient, yield_ratio, direction, fwave_norm)
    implicit none
    integer, parameter :: maxm = 4, meqn = 3, mwaves = 3, maux = 2, mbc = 2, mx = 4
    real(kind=8), intent(in) :: normal_gradient, yield_ratio
    integer, intent(in) :: direction
    real(kind=8), intent(out) :: fwave_norm
    integer :: i
    real(kind=8) :: ql(meqn,1-mbc:maxm+mbc), qr(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: auxl(maux,1-mbc:maxm+mbc), auxr(maux,1-mbc:maxm+mbc)
    real(kind=8) :: fwave(meqn,mwaves,1-mbc:maxm+mbc), s(mwaves,1-mbc:maxm+mbc)
    real(kind=8) :: amdq(meqn,1-mbc:maxm+mbc), apdq(meqn,1-mbc:maxm+mbc)

    ql = 0.d0
    qr = 0.d0
    auxl = 0.d0
    auxr = 0.d0
    auxl(2,:) = yield_ratio
    auxr(2,:) = yield_ratio
    do i = 1-mbc, maxm+mbc
      ql(1,i) = 10.d0 + normal_gradient*i
      qr(1,i) = ql(1,i)
    end do
    call rpn2(direction,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,auxl,auxr, &
              fwave,s,amdq,apdq)
    fwave_norm = sum(abs(fwave(:,:,2)))
  end subroutine run_wet_case

  subroutine run_wet_dry_case(yield_ratio, fwave_norm)
    implicit none
    integer, parameter :: maxm = 4, meqn = 3, mwaves = 3, maux = 2, mbc = 2, mx = 4
    real(kind=8), intent(in) :: yield_ratio
    real(kind=8), intent(out) :: fwave_norm
    real(kind=8) :: ql(meqn,1-mbc:maxm+mbc), qr(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: auxl(maux,1-mbc:maxm+mbc), auxr(maux,1-mbc:maxm+mbc)
    real(kind=8) :: fwave(meqn,mwaves,1-mbc:maxm+mbc), s(mwaves,1-mbc:maxm+mbc)
    real(kind=8) :: amdq(meqn,1-mbc:maxm+mbc), apdq(meqn,1-mbc:maxm+mbc)

    ql = 0.d0
    qr = 0.d0
    auxl = 0.d0
    auxr = 0.d0
    auxl(2,:) = yield_ratio
    auxr(2,:) = yield_ratio
    ! At i=2 the wet-left head is 0.4 < mu*dx, so the old directional
    ! wet/dry limiter would take its early exit regardless of transverse drive.
    qr(1,1) = 0.4d0
    call rpn2(1,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,auxl,auxr, &
              fwave,s,amdq,apdq)
    fwave_norm = sum(abs(fwave(:,:,2)))
  end subroutine run_wet_dry_case

  subroutine run_legacy_wet_case(normal_gradient, fwave_norm)
    implicit none
    ! An old one-auxiliary-field checkpoint has no full-vector marker.  It
    ! must be allowed to flow rather than silently reuse the faulty
    ! component-wise arrest rule.
    integer, parameter :: maxm = 4, meqn = 3, mwaves = 3, maux = 1, mbc = 2, mx = 4
    real(kind=8), intent(in) :: normal_gradient
    real(kind=8), intent(out) :: fwave_norm
    integer :: i
    real(kind=8) :: ql(meqn,1-mbc:maxm+mbc), qr(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: auxl(maux,1-mbc:maxm+mbc), auxr(maux,1-mbc:maxm+mbc)
    real(kind=8) :: fwave(meqn,mwaves,1-mbc:maxm+mbc), s(mwaves,1-mbc:maxm+mbc)
    real(kind=8) :: amdq(meqn,1-mbc:maxm+mbc), apdq(meqn,1-mbc:maxm+mbc)

    ql = 0.d0
    qr = 0.d0
    auxl = 0.d0
    auxr = 0.d0
    do i = 1-mbc, maxm+mbc
      ql(1,i) = 10.d0 + normal_gradient*i
      qr(1,i) = ql(1,i)
    end do
    call rpn2(1,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,auxl,auxr, &
              fwave,s,amdq,apdq)
    fwave_norm = sum(abs(fwave(:,:,2)))
  end subroutine run_legacy_wet_case

end program static_yield_driver
""".strip() + "\n", encoding="utf-8")
    subprocess.run(
        [
            compiler, "-O0", "-fopenmp", "-J", str(tmp_path), str(stubs),
            str(AVAC / "rheology_module.f90"), "-ffixed-line-length-none",
            str(AVAC / "rpn2_geoclaw.f"), str(driver), "-o", str(executable),
        ],
        check=True, cwd=tmp_path, capture_output=True, text=True,
    )
    return np.fromstring(
        subprocess.run([str(executable)], check=True, cwd=tmp_path,
                       capture_output=True, text=True).stdout,
        sep=" ",
    )


def test_static_yield_limiter_releases_vector_super_yield_flow(tmp_path: Path):
    values = _compile_rpn_driver(tmp_path)
    assert values.size == 9
    super_x, super_y, sub_x, sub_y, axial_x, wet_dry_super, wet_dry_sub, legacy_super, spherical_sub = values

    # eta_x=eta_y=0.4 and mu=0.5: each directional increment is sub-yield,
    # but the vector magnitude is sqrt(0.4^2 + 0.4^2) > mu.  Both sweeps must
    # reach the Riemann solver, represented by its nonzero sentinel f-wave.
    assert super_x > 0.0
    assert super_y > 0.0
    # A genuinely vector-sub-yield diagonal state remains arrested.
    assert sub_x == pytest.approx(0.0)
    assert sub_y == pytest.approx(0.0)
    # This guards against replacing mu with mu/sqrt(2), which would wrongly
    # release an ordinary one-directional 0.49 < mu deposit.
    assert axial_x == pytest.approx(0.0)
    # The same vector eligibility guard applies at arrested wet/dry fronts.
    assert wet_dry_super > 0.0
    assert wet_dry_sub == pytest.approx(0.0)
    assert legacy_super > 0.0
    # GeoClaw owns aux(2) as a capacity field on spherical grids.  It must
    # not be reinterpreted as AVAC's Cartesian static-yield marker.
    assert spherical_sub > 0.0


def test_static_yield_ratio_auxiliary_is_declared_and_refreshed():
    setrun = (AVAC / "setrun.py").read_text(encoding="utf-8")
    b4step = (AVAC / "b4step2.f90").read_text(encoding="utf-8")
    rpn = (AVAC / "rpn2_geoclaw.f").read_text(encoding="utf-8")
    prepreg = (
        ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
        / "shallow" / "prepregstep.f"
    ).read_text(encoding="utf-8")
    prepbig = (
        ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
        / "shallow" / "prepbigstep.f"
    ).read_text(encoding="utf-8")
    geoclaw_qinit = (
        ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
        / "shallow" / "qinit.f90"
    ).read_text(encoding="utf-8")

    assert "clawdata.num_aux = 2" in setrun
    assert "amrdata.aux_type = ['center', 'center']" in setrun
    assert "static_yield_ratio_2d" in b4step
    assert "aux(2,i,j) = static_yield_ratio_2d" in b4step
    assert "yield_ok_L" in rpn
    assert "yield_ok_R" in rpn
    assert "coordinate_system == 1" in b4step
    assert "coordinate_system .eq. 1" in rpn
    # Richardson scratch arrays already include ghost cells, so b4step2 must
    # receive the interior dimensions just as it does in the real advance.
    assert "call b4step2(nghost, nx, ny, nvar, valbig," in prepreg
    assert "call b4step2(nghost, mitot, mjtot" not in prepreg
    assert "call b4step2(nghost,nx/2,ny/2,nvar,valbgc," in prepbig
    assert "xlow,ylow,time,dt,naux,auxbgc,.true." not in prepbig
    # qinit_type=0 bypasses qinit_module:add_perturbation, so the active
    # GeoClaw qinit path must initialize the transient output field itself.
    assert "coordinate_system" in geoclaw_qinit
    assert "aux(2,:,:) = -1.d0" in geoclaw_qinit
