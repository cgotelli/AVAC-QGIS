"""Exercise terrain transport through the actual production src2 routine.

The Geoclaw stub supplies only global parameters.  Geometry, transport,
constitutive sources, and their ordering are compiled from production code.
No solver executable or benchmark-specific configuration is required.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "avac-main" / "src" / "AVAC"


@pytest.fixture(scope="module")
def source_step(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the compiled terrain-source checks")
    build = tmp_path_factory.mktemp("terrain_src2")
    stub = build / "geoclaw_module.f90"
    stub.write_text(
        """module geoclaw_module
  implicit none
  real(kind=8) :: grav=0.d0, dry_tolerance=1.d-4, speed_limit=1.d99
  logical :: friction_forcing=.true.
  real(kind=8) :: friction_depth=1.d6
  integer :: num_manning=1
  real(kind=8) :: manning_coefficient(1)=0.d0, manning_break(1)=0.d0
end module geoclaw_module
""",
        encoding="utf-8",
    )
    driver = build / "driver.f90"
    driver.write_text(
        """program terrain_src2_driver
  use geoclaw_module
  use rheology_module
  implicit none
  integer, parameter :: meqn=3, maux=2, mbc=2
  integer :: mx, my, i, j, ghost_mode, friction_flag
  real(kind=8) :: dt, u, v, h, bx, by, bxx, bxy, byy, x, y, datum
  real(kind=8), allocatable :: q(:,:,:), aux(:,:,:)
  read(*,*) mx,my,dt,ghost_mode,friction_flag,friction_depth,u,v,h,bx,by,bxx,bxy,byy,datum
  friction_forcing = friction_flag == 1
  imodel_rh = 1
  n_zones_rh = 1
  rho_rh = 300.d0
  state_momentum_regularization_depth_rh = 0.d0
  voellmy_state_momentum_regularization_depth_rh = 0.d0
  allocate(mu_zones_rh(1),xi_zones_rh(1),C_zones_rh(1))
  mu_zones_rh = 0.d0
  xi_zones_rh = 0.d0
  C_zones_rh = 0.d0
  allocate(q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc))
  allocate(aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc))
  aux = 0.d0
  do j=1-mbc,my+mbc
    do i=1-mbc,mx+mbc
      x=dble(i-1)
      y=dble(j-1)
      aux(1,i,j)=datum+bx*x+by*y+0.5d0*bxx*x*x+bxy*x*y+0.5d0*byy*y*y
      if (ghost_mode == 1 .and. (i<1 .or. i>mx .or. j<1 .or. j>my)) then
        aux(1,i,j)=1000.d0+17.d0*x*x-31.d0*y*y+7.d0*x*y
      endif
      q(:,i,j)=[h,h*u,h*v]
    enddo
  enddo
  call src2(meqn,mbc,mx,my,0.d0,0.d0,1.d0,1.d0,q,maux,aux,0.d0,dt)
  do j=1,my
    do i=1,mx
      write(*,'(2(i4,1x),3(es25.17,1x))') i,j,q(:,i,j)
    enddo
  enddo
end program terrain_src2_driver
""",
        encoding="utf-8",
    )
    executable = build / "terrain_src2.exe"
    subprocess.run(
        [compiler, "-O2", "-fcheck=all", "-J", str(build), str(stub),
         str(SOURCE / "rheology_module.f90"), str(SOURCE / "src2.f90"),
         str(driver), "-o", str(executable)],
        cwd=build,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    def run(
        shape=(7, 7), dt=0.04, ghost_mode=0, friction=True, friction_depth=1.0e6,
        velocity=(3.0, -1.0), depth=1.0,
        polynomial=(-0.7, 0.1, 0.04, -0.01, -0.02), datum=0.0,
    ):
        values = [*shape, dt, ghost_mode, int(friction), friction_depth,
                  *velocity, depth, *polynomial, datum]
        completed = subprocess.run(
            [str(executable)],
            input=" ".join(format(float(value), ".17g") for value in values) + "\n",
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        rows = np.fromstring(completed.stdout, sep=" ").reshape((-1, 5))
        return rows[:, 2:].reshape((*shape[::-1], 3)).transpose((1, 0, 2))

    return run


@pytest.mark.parametrize("shape", [(7, 7), (7, 1), (1, 7), (7, 2), (2, 7), (2, 2)])
def test_affine_beds_remain_exact_with_hostile_ghost_closure(source_step, shape):
    result = source_step(
        shape=shape, ghost_mode=1, friction=False, polynomial=(-0.5, 0.25, 0.0, 0.0, 0.0)
    )
    assert np.array_equal(result, np.broadcast_to([1.0, 3.0, -1.0], (*shape, 3)))


@pytest.mark.parametrize("friction", [False, True])
def test_curved_transport_is_independent_of_ghost_closure(source_step, friction):
    normal = source_step(friction=friction, ghost_mode=0)
    hostile = source_step(friction=friction, ghost_mode=1)
    assert np.array_equal(normal, hostile)
    assert np.max(np.abs(hostile[:, :, 1] - 3.0)) > 1.0e-3


def test_geometry_does_not_depend_on_friction_enablement_or_depth(source_step):
    enabled = source_step(friction=True)
    disabled = source_step(friction=False)
    excluded_depth = source_step(friction=True, friction_depth=0.5)
    assert disabled == pytest.approx(enabled, abs=3.0e-15)
    assert excluded_depth == pytest.approx(enabled, abs=3.0e-15)
    assert np.max(np.abs(enabled[:, :, 1] - 3.0)) > 1.0e-3


@pytest.mark.parametrize("curvature", [(0.0, 0.0, 0.0), (0.0625, 0.03125, -0.125)])
def test_vertical_datum_does_not_change_geometry_or_affine_classification(source_step, curvature):
    # Dyadic coordinates retain their exact sampled elevations under this
    # datum shift, isolating geometry from storage-roundoff changes.
    polynomial = (-0.5, 0.25, *curvature)
    baseline = source_step(polynomial=polynomial, friction=False)
    shifted = source_step(polynomial=polynomial, friction=False, datum=1.0e12)
    assert np.array_equal(baseline, shifted)


@pytest.mark.parametrize("shape", [(7, 7), (7, 1), (1, 7), (7, 2)])
def test_geometry_never_creates_motion_from_rest(source_step, shape):
    result = source_step(shape=shape, ghost_mode=1, velocity=(0.0, 0.0))
    assert np.array_equal(result, np.broadcast_to([1.0, 0.0, 0.0], (*shape, 3)))


def test_narrow_curved_strip_transports_and_is_axis_covariant(source_step):
    x_result = source_step(
        shape=(7, 1), velocity=(3.0, 0.0), ghost_mode=1,
        polynomial=(-0.7, 0.0, 0.04, 0.0, 0.0), friction=False,
    )
    y_result = source_step(
        shape=(1, 7), velocity=(0.0, 3.0), ghost_mode=1,
        polynomial=(0.0, -0.7, 0.0, 0.0, 0.04), friction=False,
    )
    assert np.max(np.abs(x_result[:, 0, 1] - 3.0)) > 1.0e-3
    assert y_result[0, :, :] == pytest.approx(x_result[:, 0, :][:, [0, 2, 1]], abs=3.0e-15)


@pytest.mark.parametrize("shape", [(7, 7), (7, 2), (7, 1)])
def test_boundary_geometry_preserves_tangent_energy_on_quadratic_bed(source_step, shape):
    bx, by, bxx, bxy, byy = (-0.7, 0.25, 0.04, 0.0, 0.0)
    if shape[1] == 1:
        by = 0.0
    dt = 0.04
    velocity = np.array([3.0, -1.0])
    result = source_step(
        shape=shape, dt=dt, ghost_mode=1, friction=False,
        polynomial=(bx, by, bxx, bxy, byy), velocity=velocity,
    )
    hessian = np.array([[bxx, bxy], [bxy, byy]])
    for i in range(shape[0]):
        for j in range(shape[1]):
            arrival = np.array([bx, by]) + hessian @ np.array([i, j])
            departure = arrival - dt * hessian @ velocity
            next_velocity = result[i, j, 1:]
            before = velocity @ velocity + (velocity @ departure) ** 2
            after = next_velocity @ next_velocity + (next_velocity @ arrival) ** 2
            assert after == pytest.approx(before, rel=4.0e-14)
    assert np.array_equal(result[:, :, 0], np.ones(shape))


def test_production_step_converges_to_connection_on_curved_corner(source_step):
    # Corner (0,0) requires wholly interior derivatives extrapolated to the
    # physical cell.  All first/second derivatives here are known exactly.
    velocity = np.array([3.0, -1.0])
    slope = np.array([-0.7, 0.1])
    hessian = np.array([[0.04, -0.01], [-0.01, -0.02]])
    expected = -slope * (velocity @ hessian @ velocity) / (1.0 + slope @ slope)
    errors = []
    for dt in [0.01, 0.005, 0.0025]:
        result = source_step(dt=dt, friction=False, ghost_mode=1)
        acceleration = (result[0, 0, 1:] - velocity) / dt
        errors.append(np.linalg.norm(acceleration - expected))
    assert errors[1] < 0.51 * errors[0]
    assert errors[2] < 0.51 * errors[1]
    assert errors[2] < 1.0e-4
