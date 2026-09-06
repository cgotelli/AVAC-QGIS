"""Compiled invariants for the AVAC shallow correction-flux stabilization.

This is not a calibration test: terrain, depth, and flux probes are synthetic.
Actual AVAC helper and flux2 sources are compiled; only Riemann outputs are
stubbed so the normal/transverse coupling can be independently checked.
"""
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

SOURCE = Path(__file__).resolve().parents[2] / "avac-main/src/AVAC"


def compile_driver(build, code, extra=(), stub=""):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    driver = build / "driver.f90"
    driver.write_text(code, encoding="utf-8")
    files = []
    if stub:
        stubfile = build / "stub.f90"
        stubfile.write_text(stub, encoding="utf-8")
        files.append(stubfile)
    exe = build / "probe.exe"
    command = [compiler, "-O2", "-fcheck=all", "-J", str(build),
               *map(str, files), str(SOURCE / "rheology_module.f90"),
               *map(str, extra), str(driver), "-o", str(exe)]
    result = subprocess.run(command, cwd=build, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    def run(values):
        result = subprocess.run([str(exe)], input=" ".join(map(str, values)) + "\n",
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return np.fromstring(result.stdout, sep=" ")
    return run


@pytest.fixture(scope="module")
def mask_probe(tmp_path_factory):
    run = compile_driver(tmp_path_factory.mktemp("curved_mask"), """program mask_driver
  use rheology_module
  implicit none
  integer, parameter :: mbc=5
  integer :: mx,my,nx,ny,ox,oy,mode,hostile,periodic,i,j
  real(kind=8) :: x,y,pi
  real(kind=8), allocatable :: bed(:,:),mask(:,:)
  read(*,*) mx,my,nx,ny,ox,oy,mode,hostile,periodic
  allocate(bed(1-mbc:mx+mbc,1-mbc:my+mbc),mask(1-mbc:mx+mbc,1-mbc:my+mbc))
  pi=acos(-1.d0)
  do j=1-mbc,my+mbc
    do i=1-mbc,mx+mbc
      x=dble(ox+i-1)
      y=dble(oy+j-1)
      if (periodic==1) then
        x=modulo(x,dble(nx))
        y=modulo(y,dble(ny))
      endif
      bed(i,j)=1200.d0-.72d0*x+.123d0*y
      if (mode==1) bed(i,j)=bed(i,j)+.003d0*x**3-.002d0*x*y**2
      if (mode==2) bed(i,j)=bed(i,j)+.08d0*x*y
      if (mode==3) bed(i,j)=sin(2.d0*pi*x/nx)*cos(2.d0*pi*y/ny)
      if (mode==4 .and. x>=5.d0) bed(i,j)=bed(i,j)+.2d0*(x-5.d0)**2
      if (hostile==1.and.periodic==0.and.(x<0.or.y<0.or.x>=nx.or.y>=ny)) &
        bed(i,j)=1000.d0+17.d0*x*x-31.d0*y*y+7.d0*x*y
    enddo
  enddo
  call terrain_nonplanarity_mask(mbc,mx,my,bed,dble(ox),dble(oy),1.d0,1.d0, &
                                 0.d0,dble(nx),0.d0,dble(ny),periodic==1,periodic==1,mask)
  do j=1,my
    do i=1,mx
      write(*,'(es25.17)') mask(i,j)
    enddo
  enddo
end program mask_driver
""")

    def probe(shape=(11, 9), domain=None, origin=(0, 0), mode=0, hostile=0, periodic=0):
        return run([*shape, *(domain or shape), *origin, mode, hostile, periodic]).reshape(shape[::-1])
    return probe


@pytest.mark.parametrize("shape", [(11, 9), (2, 7), (7, 2), (2, 2), (1, 7), (7, 1)])
def test_affine_mask_zero_with_hostile_exterior(mask_probe, shape):
    assert np.array_equal(mask_probe(shape, hostile=1), np.zeros(shape[::-1]))


@pytest.mark.parametrize("shape", [(11, 9), (2, 7), (7, 2), (2, 2)])
def test_bilinear_saddle_is_detected_in_narrow_domains(mask_probe, shape):
    assert np.array_equal(mask_probe(shape, mode=2, hostile=1), np.ones(shape[::-1]))


@pytest.mark.parametrize("mode,periodic", [(1, 0), (2, 0), (3, 1), (4, 0)])
@pytest.mark.parametrize("width", [1, 2, 3, 5])
def test_decomposition_invariance_with_genuine_internal_ghosts(mask_probe, mode, periodic, width):
    shape = (11, 9)
    whole = mask_probe(shape, mode=mode, hostile=1, periodic=periodic)
    stitched = np.zeros_like(whole)
    for x in range(0, shape[0], width):
        for y in range(0, shape[1], width):
            tile = (min(width, shape[0]-x), min(width, shape[1]-y))
            stitched[y:y+tile[1], x:x+tile[0]] = mask_probe(
                tile, domain=shape, origin=(x, y), mode=mode, hostile=1, periodic=periodic)
    assert np.array_equal(stitched, whole)


FLUX_STUB = """module amr_module
  implicit none
  logical :: use_fwaves=.true.
  integer :: mwaves=3,method(7)=0,mthlim(3)=0,mcapa=0
end module amr_module
module geoclaw_module
  implicit none
  integer :: coordinate_system=1
  real(kind=8) :: earth_radius=1.d0,deg2rad=1.d0
  logical :: use_fwave_positivity_limiter=.true.
end module geoclaw_module
"""

FLUX_DRIVER = """program flux_driver
  use rheology_module
  use amr_module
  use geoclaw_module
  implicit none
  integer, parameter :: mbc=5,mx=7,maxm=7,meqn=3,maux=3
  real(kind=8) :: q(meqn,1-mbc:maxm+mbc),a(maux,1-mbc:maxm+mbc),dt(1-mbc:maxm+mbc)
  real(kind=8) :: fm(meqn,1-mbc:maxm+mbc),fp(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: gm(meqn,1-mbc:maxm+mbc,2),gp(meqn,1-mbc:maxm+mbc,2)
  real(kind=8) :: h,mask,cfl
  integer :: i,m,side
  external rpn_stub,rpt_stub
  read(*,*) method(2),method(3),imodel_rh,coordinate_system,h,mask
  state_momentum_regularization_depth_rh=.05d0
  voellmy_state_momentum_regularization_depth_rh=.1d0
  q=0.d0
  q(1,:)=h
  q(2,:)=2.d0*h
  q(3,:)=-3.d0*h
  a=0.d0
  a(3,:)=mask
  dt=.1d0
  call flux2(1,maxm,meqn,maux,mbc,mx,q,dt,a,a,a,fm,fp,gm,gp,cfl,rpn_stub,rpt_stub)
  write(*,'(es25.17)') cfl
  do i=0,mx+2
    do m=1,meqn
      write(*,'(6(es25.17,1x))') fm(m,i),fp(m,i),gm(m,i,1),gp(m,i,1),gm(m,i,2),gp(m,i,2)
    enddo
  enddo
end program flux_driver
subroutine rpn_stub(ixy,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,al,ar,fw,s,am,ap)
  implicit none
  integer :: ixy,maxm,meqn,mwaves,maux,mbc,mx,i,m,k
  real(kind=8) :: ql(meqn,1-mbc:maxm+mbc),qr(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: al(maux,1-mbc:maxm+mbc),ar(maux,1-mbc:maxm+mbc)
  real(kind=8) :: fw(meqn,mwaves,1-mbc:maxm+mbc),s(mwaves,1-mbc:maxm+mbc)
  real(kind=8) :: am(meqn,1-mbc:maxm+mbc),ap(meqn,1-mbc:maxm+mbc)
  do i=1-mbc,maxm+mbc
    s(:,i)=[-1.d0,.4d0,2.d0]
    do m=1,meqn
      do k=1,mwaves
        fw(m,k,i)=dble(m*(k+1))*(1.d0+.01d0*i)
      enddo
      am(m,i)=dble(m)*.7d0
      ap(m,i)=dble(m)*-.3d0
    enddo
  enddo
end subroutine rpn_stub
subroutine rpt_stub(ixy,imp,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,a1,a2,a3,as,bm,bp)
  implicit none
  integer :: ixy,imp,maxm,meqn,mwaves,maux,mbc,mx
  real(kind=8) :: ql(meqn,1-mbc:maxm+mbc),qr(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: a1(maux,1-mbc:maxm+mbc),a2(maux,1-mbc:maxm+mbc),a3(maux,1-mbc:maxm+mbc)
  real(kind=8) :: as(meqn,1-mbc:maxm+mbc),bm(meqn,1-mbc:maxm+mbc),bp(meqn,1-mbc:maxm+mbc)
  bm=-2.d0*as
  bp=3.d0*as
end subroutine rpt_stub
subroutine limiter(maxm,meqn,mwaves,mbc,mx,wave,s,mthlim)
  implicit none
  integer :: maxm,meqn,mwaves,mbc,mx,mthlim(mwaves)
  real(kind=8) :: wave(meqn,mwaves,1-mbc:maxm+mbc),s(mwaves,1-mbc:maxm+mbc)
end subroutine limiter
subroutine limiter_range(maxm,meqn,mwaves,mbc,mx,wave,s,mthlim,ilo,ihi)
  implicit none
  integer :: maxm,meqn,mwaves,mbc,mx,mthlim(mwaves),ilo,ihi
  real(kind=8) :: wave(meqn,mwaves,1-mbc:maxm+mbc),s(mwaves,1-mbc:maxm+mbc)
end subroutine limiter_range
"""


@pytest.fixture(scope="module")
def flux_probe(tmp_path_factory):
    return compile_driver(tmp_path_factory.mktemp("correction_flux"), FLUX_DRIVER,
                          extra=[SOURCE / "flux2fw.f"], stub=FLUX_STUB)


@pytest.mark.parametrize("model", [1, 2, 3])
@pytest.mark.parametrize("fraction", [0.0, 0.1, 0.5, 1.0, 2.0])
@pytest.mark.parametrize("transverse", [0, 1, 2])
def test_same_factor_for_all_normal_and_transverse_corrections(flux_probe, model, fraction, transverse):
    h = fraction * (.05 if model == 1 else .1)
    first = flux_probe([1, transverse, model, 1, h, 1])
    flat = flux_probe([2, transverse, model, 1, h, 0])
    curved = flux_probe([2, transverse, model, 1, h, 1])
    ratio2 = fraction**2
    expected = 1.0 if fraction >= 1 else 2**.5*ratio2/(1+ratio2**2)**.5
    assert first[0] == flat[0] == curved[0]  # actual CFL reduction unchanged
    np.testing.assert_allclose(curved[1:]-first[1:], expected*(flat[1:]-first[1:]), atol=3e-15)


@pytest.mark.parametrize("model,coordinates", [(0, 1), (0, 2), (1, 2), (2, 2), (3, 2)])
def test_water_and_noncartesian_ignore_transient_mask(flux_probe, model, coordinates):
    a = flux_probe([2, 2, model, coordinates, .01, 0])
    b = flux_probe([2, 2, model, coordinates, .01, 1])
    np.testing.assert_array_equal(a, b)
