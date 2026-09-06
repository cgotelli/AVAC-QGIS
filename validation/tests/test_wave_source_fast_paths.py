"""Compiled equivalence controls for WAVE inflow and stationary Manning work."""
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
WAVE = ROOT / "avac-main/src/WAVE"
BOX_CHECKS = (
    "        if (inflow_xmax < xlower .or. inflow_xmin >= xlower + mx*dx) return\n"
    "        if (inflow_ymax < ylower .or. inflow_ymin >= ylower + my*dy) return\n"
)
BINARY_SEARCH = """            lo = 1
            hi = inflow_ntimes
            do while (hi-lo > 1)
                midpoint = lo + (hi-lo)/2
                if (sample_time < inflow_times(midpoint)) then
                    hi = midpoint
                else
                    lo = midpoint
                end if
            end do
            it = lo
"""
LINEAR_SEARCH = """            do it = 1, inflow_ntimes - 1
                if (sample_time >= inflow_times(it) .and. sample_time < inflow_times(it+1)) exit
            end do
"""
MANNING_SKIP = "                        if (q(2,i,j) == 0.d0 .and. q(3,i,j) == 0.d0) cycle\n"


def _write_inflow(path, *, version=2, times=(0., .1, .7, 1.8, 2., 5., 13.), empty=False, gentle=False):
    if gentle:
        points = [(0.25, 0.25)]
    else:
        # Several sources share a receiving cell; their floating-point
        # accumulation order must be retained, including canceling momenta.
        points = [(0., 0.), (.25, .25), (.75, .25), (1., 1.),
                  (2., 1.5), (4., 3.), (2., 2.), (.25, .25)]
    if empty:
        points = []
    lines = [str(version), f"{len(times)} {len(points)}", " ".join(map(str, times))]
    for k, point in enumerate(points):
        lines.append(" ".join(map(str, point)))
        for t in times:
            rate = .1 + .01 * (k+1) + .02*t*t
            momentum = .2*rate if gentle else (1.e16 if k == 1 else -1.e16 if k == 2 else .3*rate)
            lines.append(f"{rate:.17g} {momentum:.17g} {-.2*rate:.17g}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


INFLOW_DRIVER = """program inflow_probe
  use internal_inflow_module, only: read_internal_inflow,apply_internal_inflow
  use internal_inflow_reference, only: read_reference=>read_internal_inflow,apply_reference=>apply_internal_inflow
  implicit none
  integer,parameter :: neq=4,ng=2,nx=4,ny=3,ncalls=5
  real(kind=8) :: q(neq,1-ng:nx+ng,1-ng:ny+ng,ncalls),ref(neq,1-ng:nx+ng,1-ng:ny+ng,ncalls)
  real(kind=8) :: xl,yl,dx,dy,t,dt,call_times(ncalls),totals(3)
  integer :: k,threads
  character(len=1024) :: path
  call get_command_argument(1,path)
  call read_internal_inflow(trim(path));call read_reference(trim(path))
  read(*,*) xl,yl,dx,dy,t,dt,threads
  call_times=t+dt*[0.d0,2.d0,-1.d0,0.d0,1.d0]
  q=0.d0;ref=0.d0;q(4,:,:,:)=17.d0;ref(4,:,:,:)=17.d0
  !$omp parallel do num_threads(threads) private(k)
  do k=1,ncalls
    call apply_internal_inflow(neq,ng,nx,ny,xl,yl,dx,dy,q(:,:,:,k),call_times(k),dt)
  enddo
  !$omp end parallel do
  do k=1,ncalls
    call apply_reference(neq,ng,nx,ny,xl,yl,dx,dy,ref(:,:,:,k),call_times(k),dt)
  enddo
  if(any(q/=ref)) error stop 'Inflow differs from the original full-scan algorithm'
  if(any(q(4,:,:,:)/=17.d0)) error stop 'Inflow modified an unrelated equation'
  do k=1,ncalls
    totals=[sum(q(1,1:nx,1:ny,k)),sum(q(2,1:nx,1:ny,k)),sum(q(3,1:nx,1:ny,k))]*dx*dy
    write(*,'(a,3(es26.17e3,1x))') 'RESULT ',totals
  enddo
end program
"""


MODULES = """module geoclaw_module
  implicit none
  real(kind=8) :: grav=9.81d0,dry_tolerance=1.d-4,speed_limit=50.d0,friction_depth=20.d0
  real(kind=8) :: manning_coefficient(2)=[.03d0,.1d0],manning_break(2)=[0.d0,1.d99]
  real(kind=8) :: spherical_distance=0.d0,RAD2DEG=57.29577951308232d0,pi=3.141592653589793d0
  real(kind=8) :: DEG2RAD=.0174532925199433d0,rho_air=1.15d0,rho(1)=1000.d0,earth_radius=6367500.d0
  logical :: friction_forcing=.true.,coriolis_forcing=.false.
  integer :: coordinate_system=1,sphere_source=1,num_manning=2
contains
  real(kind=8) function coriolis(y)
    real(kind=8),intent(in) :: y
    coriolis=1.d-4
  end function
end module
module storm_module
  implicit none
  logical :: wind_forcing=.false.,pressure_forcing=.false.
  integer :: wind_index=3,pressure_index=1
contains
  real(kind=8) function wind_drag(speed,angle)
    real(kind=8),intent(in) :: speed,angle
    wind_drag=.001d0
  end function
  real(kind=8) function storm_direction(t)
    real(kind=8),intent(in) :: t
    storm_direction=0.d0
  end function
  function storm_location(t) result(xy)
    real(kind=8),intent(in) :: t
    real(kind=8) :: xy(2)
    xy=[0.d0,0.d0]
  end function
end module
module friction_module
  implicit none
  logical :: variable_friction=.false.
  integer :: friction_index=2
end module
"""

SOURCE_DRIVER = """program source_probe
  use geoclaw_module
  use storm_module
  use friction_module
  use internal_inflow_module, only: read_internal_inflow
  implicit none
  integer,parameter :: neq=4,ng=2,nx=4,ny=3,na=4
  integer :: i,j,motion,variable,forcing,friction
  real(kind=8) :: q(neq,1-ng:nx+ng,1-ng:ny+ng),ref(neq,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: aux(na,1-ng:nx+ng,1-ng:ny+ng),auxref(na,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: depth,t,dt,initial_momentum
  character(len=1024) :: path
  call get_command_argument(1,path)
  call read_internal_inflow(trim(path))
  read(*,*) depth,motion,variable,forcing,friction,t,dt
  variable_friction=variable==1;friction_forcing=friction==1
  coriolis_forcing=forcing==1;wind_forcing=forcing==1
  q=0.d0;aux=0.d0;q(1,:,:)=depth;q(4,:,:)=17.d0
  do j=1-ng,ny+ng
    do i=1-ng,nx+ng
      aux(:,i,j)=[real(i-2,8),.04d0,2.d0,1.d0]
      if(motion==1) q(2:3,i,j)=[.3d0*depth,-.2d0*depth]
      if(motion==2) q(2:3,i,j)=[1.d-200,-1.d-200]
      if(motion==3) q(2:3,i,j)=[1.d-8,-1.d-8]
    enddo
  enddo
  initial_momentum=sum(abs(q(2:3,1:nx,1:ny)))
  ref=q;auxref=aux
  call src2(neq,ng,nx,ny,0.d0,0.d0,1.d0,1.d0,q,na,aux,t,dt)
  call src2_reference(neq,ng,nx,ny,0.d0,0.d0,1.d0,1.d0,ref,na,auxref,t,dt)
  if(any(q/=ref).or.any(aux/=auxref)) error stop 'Manning shortcut changed production source results'
  if(any(q(4,:,:)/=17.d0)) error stop 'Source modified an unrelated equation'
  write(*,'(a,4(es26.17e3,1x))') 'RESULT ',q(1:3,1,1),sum(abs(q(2:3,1:nx,1:ny)))
end program
"""


def _compile(build, sources):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for WAVE source equivalence")
    executable = build / "probe.exe"
    result = subprocess.run(
        [compiler, "-O2", "-fopenmp", "-fcheck=all", "-ffree-line-length-none", "-J", str(build),
         *map(str, sources), "-o", str(executable)], cwd=build, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    def run(path, values):
        result = subprocess.run(
            [str(executable), str(path)], input=" ".join(map(str, values))+"\n", cwd=build,
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        rows = [np.fromstring(line[7:], sep=" ") for line in result.stdout.splitlines() if line.startswith("RESULT ")]
        assert rows and all(np.isfinite(row).all() for row in rows), result.stdout
        return np.array(rows)

    return run


@pytest.fixture(scope="module")
def inflow_probe(tmp_path_factory):
    build = tmp_path_factory.mktemp("wave_inflow_fast")
    source = (WAVE / "internal_inflow_module.f90").read_text(encoding="utf-8")
    assert source.count(BOX_CHECKS) == source.count(BINARY_SEARCH) == 1
    source = source.replace(BOX_CHECKS, "").replace(BINARY_SEARCH, LINEAR_SEARCH)
    reference = build / "inflow_reference.f90"
    reference.write_text(source.replace("internal_inflow_module", "internal_inflow_reference"), encoding="utf-8")
    driver = build / "driver.f90"
    driver.write_text(INFLOW_DRIVER, encoding="utf-8")
    return _compile(build, [WAVE / "internal_inflow_module.f90", reference, driver])


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("time", [-1., -.05, .05, .65, 1.75, 4.95, 12.95, 13.1])
@pytest.mark.parametrize("threads", [1, 4])
def test_inflow_search_preserves_times_order_and_parallel_results(inflow_probe, tmp_path, version, time, threads):
    path = tmp_path / "inflow.data"
    _write_inflow(path, version=version)
    inflow_probe(path, [0., 0., 1., 1., time, .1, threads])


@pytest.mark.parametrize("patch", [
    (-4., 0., 1., 1.), (4., 0., 1., 1.), (0., -3., 1., 1.), (0., 3., 1., 1.),
    (4., 3., 1., 1.),  # Bounding-box maximum belongs to both lower patch edges.
    (-100., -100., 1., 1.), (100., 100., 1., 1.), (0., 0., .5, .5), (1., 1., .25, .5),
])
def test_inflow_half_open_edges_and_refined_cells_match_reference(inflow_probe, tmp_path, patch):
    path = tmp_path / "inflow.data"
    _write_inflow(path)
    inflow_probe(path, [*patch, .05, .1, 4])


@pytest.mark.parametrize("empty,dt", [(True, .1), (False, 0.), (False, -.1)])
def test_inactive_inflow_is_unchanged(inflow_probe, tmp_path, empty, dt):
    path = tmp_path / "inflow.data"
    _write_inflow(path, times=(0., 1.), empty=empty)
    assert np.all(inflow_probe(path, [0., 0., 1., 1., .2, dt, 4]) == 0.)


def test_v2_integrated_inflow_is_independent_of_receiving_cell_area(inflow_probe, tmp_path):
    path = tmp_path / "inflow.data"
    _write_inflow(path, times=(0., 1.), gentle=True)
    coarse = inflow_probe(path, [0., 0., 1., 1., .2, .1, 1])
    fine = inflow_probe(path, [0., 0., .5, .5, .2, .1, 4])
    np.testing.assert_array_equal(coarse, fine)
    assert np.all(coarse[:, 0] > 0.)


@pytest.fixture(scope="module")
def source_probe(tmp_path_factory):
    build = tmp_path_factory.mktemp("wave_manning_fast")
    modules = build / "modules.f90"
    modules.write_text(MODULES, encoding="utf-8")
    source = (WAVE / "src2.f90").read_text(encoding="utf-8")
    assert source.count(MANNING_SKIP) == 1
    reference = build / "src2_reference.f90"
    reference.write_text(re.sub(r"\bsrc2\b", "src2_reference", source.replace(MANNING_SKIP, "")), encoding="utf-8")
    driver = build / "driver.f90"
    driver.write_text(SOURCE_DRIVER, encoding="utf-8")
    return _compile(build, [modules, WAVE / "internal_inflow_module.f90", WAVE / "src2.f90", reference, driver])


@pytest.mark.parametrize("depth,motion", [(0., 3), (1.e-4, 3), (.001, 0), (1., 0), (20., 0), (25., 0), (1., 1), (1., 2)])
@pytest.mark.parametrize("variable,forcing,friction", [(0, 0, 1), (1, 0, 1), (0, 1, 1), (0, 0, 0)])
def test_stationary_manning_skip_matches_production_source(source_probe, tmp_path, depth, motion, variable, forcing, friction):
    path = tmp_path / "inflow.data"
    _write_inflow(path, empty=True)
    source_probe(path, [depth, motion, variable, forcing, friction, .2, .1])


@pytest.mark.parametrize("depth", [0., .001, 1.])
@pytest.mark.parametrize("variable", [0, 1])
def test_injected_momentum_is_not_skipped_by_stationary_manning_path(source_probe, tmp_path, depth, variable):
    path = tmp_path / "inflow.data"
    _write_inflow(path, gentle=True)
    result = source_probe(path, [depth, 0, variable, 0, 1, .2, .1])[0]
    assert result[0] > depth
    assert result[1] > 0. and result[2] < 0. and result[3] > 0.
