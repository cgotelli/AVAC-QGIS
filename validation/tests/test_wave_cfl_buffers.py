"""Compile WAVE's real scratch module and the real shared CFL probe wrapper."""

from pathlib import Path
import importlib.util
import os
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2] / "avac-main"
BUFFERS = ROOT / "src/WAVE/wave_cfl_buffer_module.f90"
ADVANC = ROOT / "clawpack-v5.14.0/geoclaw/src/2d/shallow/advanc.f"


def test_wave_cfl_fast_path_is_wired_in_native_and_windows_builds_only():
    script = ROOT.parent / "tools/build_windows_solvers.py"
    spec = importlib.util.spec_from_file_location("wave_cfl_windows_build_probe", script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    wave = builder.TARGETS["WAVE"]["directory"]
    avac = builder.TARGETS["AVAC"]["directory"]
    wave_make = (wave / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"(?m)^FFLAGS\s*\+=.*-cpp\b.*-DWAVE_CFL_FAST_PATH\b", wave_make)
    for makefile in (avac / "Makefile", avac / "Makefile.windows"):
        assert "-DWAVE_CFL_FAST_PATH" not in makefile.read_text(encoding="utf-8")
    assert re.search(r"(?m)^include\s+Makefile\s*$", (wave / "Makefile.windows").read_text(encoding="utf-8"))

    sources, modules = builder._consolidated_sources(wave, real_world_topo=True)
    callback = wave / "rpn2_geoclaw_cfl.f90"
    assert sources.count(callback) == 1 and callback not in modules
    assert modules.count(BUFFERS) == 1 and BUFFERS not in sources
    assert sources.count(ADVANC) == 1 and ADVANC not in modules
    # Accepted steps still use the complete upstream water Riemann solver.
    full_riemann = builder.CLAWPACK / "riemann/src/rpn2_geoclaw.f"
    assert sources.count(full_riemann) == 1
    avac_sources, avac_modules = builder._consolidated_sources(avac, real_world_topo=True)
    assert callback not in avac_sources and BUFFERS not in avac_modules
    command = builder._make_command(
        "mingw32-make", builder.TARGETS["WAVE"], sources, modules,
        shell=None, real_world_topo=True,
    )
    # A command-line FFLAGS override would suppress Makefile's += flag.
    assert not any(argument.startswith("FFLAGS=") for argument in command)


@pytest.fixture(scope="module", params=[False, True], ids=["legacy", "wave-fast"])
def buffer_driver(request, tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the WAVE CFL buffer regression")
    work = tmp_path_factory.mktemp("wave-cfl-buffers")
    source = ADVANC.read_text(encoding="utf-8")
    start = source.index("      subroutine par_cfl_preflight(")
    stop = source.index("       subroutine prepgrids", start)
    (work / "probe.f").write_text(source[start:stop], encoding="utf-8")
    (work / "stubs.f90").write_text(_STUBS, encoding="utf-8")
    (work / "driver.f90").write_text(_DRIVER, encoding="utf-8")
    executable = work / "driver"
    subprocess.run(
        [compiler, "-O2", "-cpp", "-fopenmp", "-fcheck=all", "-Werror=array-temporaries",
         "-ffree-line-length-none", "-ffixed-line-length-none",
         *(["-DWAVE_CFL_FAST_PATH"] if request.param else []),
         str(BUFFERS), str(work / "stubs.f90"), str(work / "probe.f"),
         str(work / "driver.f90"), "-o", str(executable)],
        cwd=work, check=True, capture_output=True, text=True,
    )
    return executable


@pytest.mark.parametrize("threads", [1, 4])
def test_reused_storage_keeps_exact_shapes_and_trials_private(buffer_driver, threads):
    result = subprocess.run(
        [str(buffer_driver)], input="0\n", check=True, capture_output=True, text=True, timeout=30,
        env={**os.environ, "OMP_NUM_THREADS": str(threads), "OMP_DYNAMIC": "FALSE"},
    )
    assert "PASS" in result.stdout
    assert "array temporary" not in result.stderr.lower()


@pytest.mark.parametrize("invalid", [1, 2, 3, 4])
def test_invalid_scratch_dimensions_are_rejected(buffer_driver, invalid):
    result = subprocess.run([str(buffer_driver)], input=f"{invalid}\n", capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Invalid WAVE CFL scratch dimensions" in result.stderr


_STUBS = """
module amr_module
  implicit none
  integer, parameter :: ndilo=1, ndihi=2, ndjlo=3, ndjhi=4, nestlevel=5, store1=6, storeaux=7
  integer, parameter :: timemult=1, cornxlo=2, cornylo=3, npatch=17
  integer :: node(7,npatch), nghost=2
  real(kind=8) :: rnode(3,npatch), hxposs(2), hyposs(2), possk(2)
  real(kind=8) :: alloc(200000), accepted(200000)
end module

module probe_checks
  use amr_module
  use wave_cfl_buffer_module
  use omp_lib
  use, intrinsic :: iso_c_binding, only: c_ptr, c_loc, c_associated
  implicit none
  integer :: patch=0, pre_steps=0
!$omp threadprivate(patch,pre_steps)
contains
  subroutine check_values(q,aux,meqn,maux,mx,my,mbc,dt,after_b4)
    integer,intent(in) :: meqn,maux,mx,my,mbc
    real(kind=8),intent(in) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8),intent(in) :: aux(max(1,maux),1-mbc:mx+mbc,1-mbc:my+mbc),dt
    logical,intent(in) :: after_b4
    integer :: i,j,m,idx
    real(kind=8) :: value
    do j=1-mbc,my+mbc
      do i=1-mbc,mx+mbc
        do m=1,meqn
          idx=m+meqn*((i+mbc-1)+(mx+2*mbc)*(j+mbc-1))
          value=accepted(node(store1,patch)+idx-1)
          if (after_b4) value=value+rnode(timemult,patch)+dt
          if (q(m,i,j)/=value) error stop 'q copy/shape/trial isolation'
        enddo
        do m=1,maux
          idx=m+maux*((i+mbc-1)+(mx+2*mbc)*(j+mbc-1))
          value=accepted(node(storeaux,patch)+idx-1)
          if (after_b4) value=value-rnode(timemult,patch)-dt
          if (aux(m,i,j)/=value) error stop 'aux copy/shape/trial isolation'
        enddo
      enddo
    enddo
    if (maux==0 .and. any(aux/=0.d0)) error stop 'zero-aux dummy was not cleared'
  end subroutine

  subroutine check_storage()
    real(kind=8),pointer,contiguous :: q(:,:,:),a(:,:,:)
    type(c_ptr) :: q_address,a_address
    real(kind=8) :: sentinel
    integer :: worker
    worker=omp_get_thread_num()
    sentinel=-12345.d0-worker
    call get_wave_cfl_buffers(3,2,12,9,q,a)
    q_address=c_loc(q); a_address=c_loc(a)
    q=sentinel; a=sentinel
!$omp barrier
    ! Changing all dimensions must remap contiguous storage, not slice it.
    call get_wave_cfl_buffers(2,1,5,7,q,a)
    if (.not.c_associated(c_loc(q),q_address)) error stop 'q shrank/reallocated'
    if (.not.c_associated(c_loc(a),a_address)) error stop 'aux shrank/reallocated'
    if (size(q)/=70 .or. size(a)/=35) error stop 'active shape'
    if (.not.is_contiguous(q) .or. .not.is_contiguous(a)) error stop 'noncontiguous scratch'
    if (any(q/=sentinel) .or. any(a/=sentinel)) error stop 'worker storage shared'
    q=3.d0; a=4.d0
    call get_wave_cfl_buffers(3,2,12,9,q,a)
    if (q(1,12,2)/=3.d0 .or. q(2,12,2)/=sentinel) error stop 'q stride/sentinel'
    if (a(1,6,2)/=4.d0 .or. a(2,6,2)/=sentinel) error stop 'aux stride/sentinel'
    ! Grow and then return to a smaller allocation without losing its tail.
    call get_wave_cfl_buffers(5,4,19,17,q,a)
    q_address=c_loc(q); a_address=c_loc(a)
    q=sentinel; a=sentinel
    call get_wave_cfl_buffers(1,0,2,3,q,a)
    if (.not.c_associated(c_loc(q),q_address)) error stop 'grown q was not reused'
    if (.not.c_associated(c_loc(a),a_address)) error stop 'grown aux was not reused'
    q=0.d0; a=0.d0
    call get_wave_cfl_buffers(5,4,19,17,q,a)
    if (q(1,2,1)/=0.d0 .or. q(2,2,1)/=sentinel) error stop 'grown q tail'
    if (a(2,2,1)/=0.d0 .or. a(3,2,1)/=sentinel) error stop 'grown aux tail'
  end subroutine
end module

subroutine b4step2(mbc,mx,my,meqn,q,xlower,ylower,dx,dy,time,dt,maux,aux,actualstep)
  use probe_checks
  implicit none
  integer :: mbc,mx,my,meqn,maux
  real(kind=8),target :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8),target :: aux(max(1,maux),1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: xlower,ylower,dx,dy,time,dt
  logical :: actualstep
#ifdef WAVE_CFL_FAST_PATH
  real(kind=8),pointer,contiguous :: qp(:,:,:),ap(:,:,:)
  call get_wave_cfl_buffers(meqn,maux,mx+2*mbc,my+2*mbc,qp,ap)
  if (.not.c_associated(c_loc(q),c_loc(qp))) error stop 'q copy temporary'
  if (.not.c_associated(c_loc(aux),c_loc(ap))) error stop 'aux copy temporary'
#endif
  if (.not.actualstep) error stop 'probe did not prepare actual step'
  if (time/=rnode(timemult,patch)) error stop 'incorrect trial time'
  if (dt/=possk(node(nestlevel,patch))) error stop 'incorrect trial dt'
  if (xlower/=rnode(cornxlo,patch) .or. ylower/=rnode(cornylo,patch)) error stop 'patch coordinates'
  if (dx/=hxposs(node(nestlevel,patch)) .or. dy/=hyposs(node(nestlevel,patch))) error stop 'patch spacing'
  call check_values(q,aux,meqn,maux,mx,my,mbc,dt,.false.)
  q=q+time+dt
  if (maux>0) aux=aux-time-dt
  pre_steps=pre_steps+1
end subroutine

subroutine step2_cfl(maxm,meqn,maux,mbc,mx,my,q,aux,dx,dy,dt,cfl,rp)
  use probe_checks
  implicit none
  integer :: maxm,meqn,maux,mbc,mx,my,tag
  real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: aux(max(1,maux),1-mbc:mx+mbc,1-mbc:my+mbc),dx,dy,dt,cfl
  external rp
  if (maxm/=max(mx,my)) error stop 'wrong maximum dimension'
  call check_values(q,aux,meqn,maux,mx,my,mbc,dt,.true.)
  call rp(tag)
#ifdef WAVE_CFL_FAST_PATH
  if (tag/=22) error stop 'did not dispatch WAVE CFL solver'
#else
  if (tag/=11) error stop 'changed legacy Riemann dispatch'
#endif
  cfl=dt*(patch+dx+dy)
  q=-987654321.d0
  aux=987654321.d0
end subroutine

subroutine rpn2(tag)
  integer :: tag
  tag=11
end subroutine
subroutine rpn2_cfl(tag)
  integer :: tag
  tag=22
end subroutine
"""


_DRIVER = """
program test_buffers
  use probe_checks
  implicit none
  integer :: mode,team,trial,configuration,j,k,nvar,naux,nx,ny,mi,mj,slot,lev,thread_count
  real(kind=8) :: cfl,expected
  real(kind=8),pointer,contiguous :: q(:,:,:),a(:,:,:)
  read(*,*) mode
  select case(mode)
    case(1)
      call get_wave_cfl_buffers(-1,2,3,4,q,a)
    case(2)
      call get_wave_cfl_buffers(3,-1,3,4,q,a)
    case(3)
      call get_wave_cfl_buffers(3,2,0,4,q,a)
    case(4)
      call get_wave_cfl_buffers(3,2,3,-1,q,a)
  end select
  call omp_set_dynamic(.false.)
  thread_count=omp_get_max_threads()
  do team=1,4
    ! Exercise worker creation/retirement between parallel regions as well.
    if (team==2) then
      call omp_set_num_threads(1)
    else if (team==3) then
      call omp_set_num_threads(min(2,thread_count))
    else
      call omp_set_num_threads(thread_count)
    endif
!$omp parallel
    call check_storage()
!$omp end parallel
    do configuration=1,5
      nvar=2+mod(configuration,3)
      naux=mod(configuration,4)
      if (configuration==5) naux=0
      alloc=-99999.d0
      node=0
      slot=1
      hxposs=[.5d0,2.d0]; hyposs=[1.25d0,.25d0]
      do j=1,npatch
        nx=1+mod(j*configuration,11)
        ny=1+mod(j+configuration*3,13)
        node(ndilo,j)=-j; node(ndihi,j)=-j+nx-1
        node(ndjlo,j)=-3*j; node(ndjhi,j)=-3*j+ny-1
        node(nestlevel,j)=1+mod(j,2)
        node(store1,j)=slot
        slot=slot+nvar*(nx+2*nghost)*(ny+2*nghost)
        node(storeaux,j)=slot
        slot=slot+naux*(nx+2*nghost)*(ny+2*nghost)
        rnode(cornxlo,j)=-7.5d0*j; rnode(cornylo,j)=2.25d0*j
      enddo
      do k=1,slot-1
        alloc(k)=dble(mod(k,113)-57)/8.d0
      enddo
      accepted=alloc
      do trial=1,6
        ! Forward, repeated, backward, and smaller-step retry calls.
        possk(1)=.25d0/2.d0**mod(trial,3)
        possk(2)=.125d0/2.d0**mod(trial,3)
        rnode(timemult,:)=dble(mod(trial,3)-1)*.5d0
!$omp parallel do schedule(dynamic,1) private(j,nx,ny,mi,mj,cfl,expected,lev)
        do j=1,npatch
          patch=j
          pre_steps=0
          nx=node(ndihi,j)-node(ndilo,j)+1
          ny=node(ndjhi,j)-node(ndjlo,j)+1
          mi=nx+2*nghost; mj=ny+2*nghost
          call par_cfl_preflight(j,mi,mj,nvar,naux,cfl)
          lev=node(nestlevel,j)
          expected=possk(lev)*(j+hxposs(lev)+hyposs(lev))
          if (cfl/=expected) error stop 'changed preflight result'
          if (pre_steps/=1) error stop 'preparation not exactly once per probe'
        enddo
!$omp end parallel do
        if (any(alloc/=accepted)) error stop 'probe mutated accepted/shared state'
      enddo
    enddo
  enddo
  write(*,*) 'PASS'
end program
"""
