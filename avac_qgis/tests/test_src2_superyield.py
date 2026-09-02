"""Regression coverage for the moving-state static-yield source safeguard."""

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
  real(kind=8) :: speed_limit = 1.d6
  logical :: friction_forcing = .true.
  real(kind=8) :: friction_depth = 1.d6
  integer :: num_manning = 1
  real(kind=8) :: manning_coefficient(1) = 0.d0
  real(kind=8) :: manning_break(1) = 0.d0
end module geoclaw_module
"""


def _compile_src2_driver(tmp_path: Path) -> np.ndarray:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the AVAC source-step regression")

    stubs = tmp_path / "stubs.f90"
    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    stubs.write_text(_STUBS.strip() + "\n", encoding="utf-8")
    driver.write_text("""
program src2_superyield_driver
  use geoclaw_module
  use rheology_module
  implicit none
  real(kind=8) :: super_speed, super_hu, super_hv
  real(kind=8) :: sub_speed, sub_hu, sub_hv
  real(kind=8) :: curved_hu, curved_hv

  friction_forcing = .true.
  friction_depth = 1.d6
  dry_tolerance = 1.d-12
  imodel_rh = 1
  rho_rh = 300.d0
  n_zones_rh = 1
  if (allocated(mu_zones_rh)) deallocate(mu_zones_rh)
  if (allocated(xi_zones_rh)) deallocate(xi_zones_rh)
  if (allocated(C_zones_rh)) deallocate(C_zones_rh)
  allocate(mu_zones_rh(1), xi_zones_rh(1), C_zones_rh(1))
  mu_zones_rh = 0.2d0
  xi_zones_rh = 1.d12
  C_zones_rh = 0.d0

  ! A frozen source step is strongly decelerating in both cases.  The first
  ! plane is nevertheless super-yield (|grad B|=0.8 > mu), whereas the
  ! second is statically supportable (|grad B|=0.1 < mu).
  call run_plane(-0.8d0, super_speed, super_hu, super_hv)
  call run_plane(-0.1d0, sub_speed, sub_hu, sub_hv)
  call run_curved_zero_force(curved_hu, curved_hv)
  write(*,'(8(es24.16,1x))') super_speed, super_hu, super_hv, &
                               sub_speed, sub_hu, sub_hv, curved_hu, curved_hv

contains

  subroutine run_plane(bed_slope, speed_out, hu_out, hv_out)
    implicit none
    integer, parameter :: meqn = 3, mbc = 2, mx = 3, my = 3, maux = 1
    real(kind=8), intent(in) :: bed_slope
    real(kind=8), intent(out) :: speed_out, hu_out, hv_out
    integer :: i, j
    real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)

    q = 0.d0
    aux = 0.d0
    do j = 1-mbc, my+mbc
      do i = 1-mbc, mx+mbc
        q(1,i,j) = 1.d0
        q(2,i,j) = 0.006d0
        q(3,i,j) = 0.008d0
        aux(1,i,j) = bed_slope*dble(i)
      end do
    end do

    speed_out = cartesian_speed_after(0.01d0,0.01d0,1.d0,0.006d0,0.008d0, &
                                      bed_slope,0.d0,0.d0,0.d0,0.d0, &
                                      mu_zones_rh(1),xi_zones_rh(1), &
                                      C_zones_rh(1),rho_rh,grav,imodel_rh)
    call src2(meqn,mbc,mx,my,0.d0,0.d0,1.d0,1.d0,q,maux,aux,0.d0,0.01d0)
    hu_out = q(2,2,2)
    hv_out = q(3,2,2)
  end subroutine run_plane

  subroutine run_curved_zero_force(hu_out, hv_out)
    implicit none
    integer, parameter :: meqn = 3, mbc = 2, mx = 3, my = 3, maux = 1
    integer :: i, j, step
    real(kind=8), intent(out) :: hu_out, hv_out
    real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8) :: x, slope, curvature, initial_speed

    ! This is a regression of AVAC's deliberately reduced Cartesian source,
    ! not a claim about a terrain-following material path.  With gravity and
    ! resistance disabled, repeated source calls on curved topography must
    ! leave the stored map-plane momentum unchanged.  A cell-local tangent
    ! rotation would compound at every split source call and fail this test.
    grav = 0.d0
    mu_zones_rh = 0.d0
    slope = -tan(30.d0*acos(-1.d0)/180.d0)
    curvature = 1.d0/40.d0
    initial_speed = 8.d0/sqrt(1.d0+slope**2)
    q = 0.d0
    aux = 0.d0
    do j = 1-mbc, my+mbc
      do i = 1-mbc, mx+mbc
        x = 10.d0*dble(i-2)
        q(1,i,j) = 1.d0
        q(2,i,j) = initial_speed
        aux(1,i,j) = slope*x + 0.5d0*curvature*x**2
      end do
    end do
    do step = 1, 100
      call src2(meqn,mbc,mx,my,0.d0,0.d0,10.d0,10.d0,q,maux,aux, &
                0.d0,0.01d0)
    end do
    hu_out = q(2,2,2)
    hv_out = q(3,2,2)
  end subroutine run_curved_zero_force

end program src2_superyield_driver
""".strip() + "\n", encoding="utf-8")
    subprocess.run(
        [
            compiler, "-O0", "-fcheck=all", "-J", str(tmp_path), str(stubs),
            str(AVAC / "rheology_module.f90"), str(AVAC / "src2.f90"),
            str(driver), "-o", str(executable),
        ],
        check=True, cwd=tmp_path, capture_output=True, text=True,
    )
    return np.fromstring(
        subprocess.run([str(executable)], check=True, cwd=tmp_path,
                       capture_output=True, text=True).stdout,
        sep=" ",
    )


def test_src2_does_not_zero_a_moving_super_yield_state(tmp_path: Path):
    (
        super_speed,
        super_hu,
        super_hv,
        sub_speed,
        sub_hu,
        sub_hv,
        curved_hu,
        curved_hv,
    ) = _compile_src2_driver(tmp_path)

    # The source-only scalar solve reaches zero in both cases.  It may safely
    # stop only the sub-yield cell.  A super-yield state must retain a nonzero
    # vector velocity until the coupled flow update supplies its direction.
    assert super_speed == pytest.approx(0.0, abs=1.0e-14)
    assert super_hu == pytest.approx(0.006, abs=1.0e-14)
    assert super_hv == pytest.approx(0.008, abs=1.0e-14)
    assert sub_speed == pytest.approx(0.0, abs=1.0e-14)
    assert sub_hu == pytest.approx(0.0, abs=1.0e-14)
    assert sub_hv == pytest.approx(0.0, abs=1.0e-14)
    # This locks in the intentionally reduced Cartesian model: no untracked
    # changing-basis rotation may be applied as a repeated cell-local source.
    assert curved_hu == pytest.approx(
        8.0 * np.cos(np.deg2rad(30.0)), abs=1.0e-13
    )
    assert curved_hv == pytest.approx(0.0, abs=1.0e-13)
