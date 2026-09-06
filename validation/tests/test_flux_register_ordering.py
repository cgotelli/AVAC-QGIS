"""OpenMP checks for AVAC's conditional coarse/fine flux-register ordering."""

from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADVANC = (
    ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
    / "shallow" / "advanc.f"
)


@pytest.fixture(scope="module")
def ordered_flux_driver(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the OpenMP flux-register regression")
    source = ADVANC.read_text(encoding="utf-8")
    start = source.index("c     fluxsv writes coarse-patch fluxes")
    end = source.index("      if (node(ffluxptr,mptr) .ne. 0)", start)
    region = source[start:end]
    work = tmp_path_factory.mktemp("flux-register-ordering")
    driver = work / "driver.f"
    executable = work / "driver"
    driver.write_text(_PREFIX + region + _SUFFIX, encoding="utf-8")
    subprocess.run(
        [compiler, "-O0", "-fopenmp", "-fcheck=all", "-ffixed-line-length-none",
         str(driver), "-o", str(executable)],
        cwd=work, check=True, capture_output=True, text=True,
    )
    return executable


@pytest.mark.parametrize("mode,expected", [(0, []), (1, [1, 3, 5, 7]), (2, list(range(1, 9)))])
def test_only_flux_register_patches_wait_and_commit_in_grid_order(ordered_flux_driver, mode, expected):
    result = subprocess.run(
        [str(ordered_flux_driver)], input=f"{mode}\n", check=True,
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "OMP_NUM_THREADS": "4", "OMP_DYNAMIC": "FALSE"},
    )
    count, *observed = map(int, result.stdout.split())
    assert count == len(expected)
    assert observed == expected


@pytest.fixture(scope="module")
def level_scheduler_driver(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the OpenMP scheduler regression")
    source = ADVANC.read_text(encoding="utf-8")
    start = source.index("c     Select ordering from the actual coarse/fine flux registers.")
    end = source.index("c     Check fixed-grid terrain completion", start)
    work = tmp_path_factory.mktemp("level-scheduler")
    driver = work / "driver.f"
    executable = work / "driver"
    driver.write_text(_SCHEDULER_PREFIX + source[start:end] + _SCHEDULER_SUFFIX, encoding="utf-8")
    subprocess.run(
        [compiler, "-O0", "-fopenmp", "-fcheck=all", "-ffixed-line-length-none",
         str(driver), "-o", str(executable)],
        cwd=work, check=True, capture_output=True, text=True,
    )
    return executable


@pytest.mark.parametrize("mode,expected", [(0, []), (1, [1, 3, 5, 7]), (2, list(range(1, 9)))])
def test_actual_level_scheduler_avoids_ordered_retirement_without_registers(level_scheduler_driver, mode, expected):
    result = subprocess.run(
        [str(level_scheduler_driver)], input=f"{mode}\n", check=True,
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "OMP_NUM_THREADS": "2", "OMP_DYNAMIC": "FALSE"},
    )
    ordered, minimum_dt, count, *observed = map(int, result.stdout.split())
    assert ordered == int(mode != 0)
    assert minimum_dt == (6 if mode == 0 else 1)
    assert count == len(expected)
    assert observed == expected


_SCHEDULER_PREFIX = """
      module amr_module
      implicit none
      integer,parameter :: ndilo=1,ndihi=2,ndjlo=3,ndjhi=4,cfluxptr=5
      integer :: node(5,8),numgrids(1),listStart(1),listOfGrids(8)
      integer :: mxnest=3,nghost=5,intrat(1),intratx(1),intraty(1)
      integer :: listsp(1)
      real(kind=8) :: rvol,rvoll(1),alloc(1),rnode(1,8)
      end module amr_module

      module patch_workers
      use amr_module
      use omp_lib
      implicit none
      integer :: mode,third_started=0,ncommitted=0,committed(8)=0
      contains
      subroutine par_advanc(mptr,mitot,mjtot,nvar,naux,dtnew)
      integer,intent(in) :: mptr,mitot,mjtot,nvar,naux
      real(kind=8),intent(out) :: dtnew
      integer :: seen
      real(kind=8) :: until
      if (mode==0) then
          if (mptr==1) then
c             With only two workers, iteration three can start only when
c             the other worker retires iteration two.  ORDERED scheduling
c             blocks that retirement even if no ORDERED region is entered.
              do
!$OMP ATOMIC READ
                  seen=third_started
                  if (seen==1) exit
              enddo
          else if (mptr==3) then
!$OMP ATOMIC WRITE
              third_started=1
          endif
      else
          until=omp_get_wtime()+dble(9-mptr)*0.001d0
          do while (omp_get_wtime()<until)
          enddo
      endif
c     The real flux-register region is compiled separately above.  This
c     stub isolates scheduler behavior while preserving its ordered commit.
      if (node(cfluxptr,mptr)/=0) then
!$OMP ORDERED
          ncommitted=ncommitted+1
          committed(ncommitted)=mptr
!$OMP END ORDERED
      endif
      dtnew=dble(9-mptr)
      end subroutine par_advanc
      end module patch_workers

      program check_scheduler
      use amr_module
      use patch_workers
      implicit none
      integer :: level,nvar,naux,j,mptr,nx,ny,mitot,mjtot,mythread,levSt
      real(kind=8) :: hx,hy,dtnew,dtlevnew
      logical :: level_has_coarse_flux
      read(*,*) mode
      level=1
      nvar=3
      naux=3
      hx=2.d0
      hy=2.d0
      dtlevnew=1.d99
      node=1
      node(cfluxptr,:)=0
      numgrids=8
      if (mode==0) then
          numgrids=3
      else if (mode==1) then
          node(cfluxptr,1:8:2)=1
      else
          node(cfluxptr,:)=1
      endif
      listStart=1
      do j=1,8
          listOfGrids(j)=j
      enddo
"""

_SCHEDULER_SUFFIX = """
      write(*,*) merge(1,0,level_has_coarse_flux),nint(dtlevnew),
     &           ncommitted,committed(1:ncommitted)
      end program check_scheduler
"""


_PREFIX = """
      module flux_probe
      implicit none
      integer :: committed(8)=0,ncommitted=0
      contains
      subroutine fluxsv(mptr,fm,fp,gm,gp,slot,mitot,mjtot,
     &                  nvar,lsp,delt,hx,hy)
      integer,intent(in) :: mptr,mitot,mjtot,nvar,lsp
      real(kind=8),intent(in) :: fm(1),fp(1),gm(1),gp(1),slot
      real(kind=8),intent(in) :: delt,hx,hy
      ncommitted=ncommitted+1
      committed(ncommitted)=mptr
      end subroutine fluxsv
      end module flux_probe

      program check_ordering
      use flux_probe
      use omp_lib
      implicit none
      integer :: mode,npatch,j,mptr,ready,local_ready
      integer,parameter :: cfluxptr=1,level=1
      integer :: node(1,8),listsp(1),mitot,mjtot,nvar
      real(kind=8) :: fm(1),fp(1),gm(1),gp(1),alloc(1)
      real(kind=8) :: delt,hx,hy,until
      read(*,*) mode
      node=0
      npatch=8
      if (mode==0) then
          npatch=2
      else if (mode==1) then
          node(1,1:8:2)=1
      else
          node=1
      endif
      ready=0
      listsp=1
      mitot=1
      mjtot=1
      nvar=1
      fm=0.d0
      fp=0.d0
      gm=0.d0
      gp=0.d0
      alloc=0.d0
      delt=1.d0
      hx=1.d0
      hy=1.d0

!$OMP PARALLEL DO ORDERED SCHEDULE(DYNAMIC,1)
!$OMP& PRIVATE(j,mptr,local_ready,until)
      do j=1,npatch
          mptr=j
          if (j==1 .and. mode/=2) then
c             Iteration two has no register to write and must be able to
c             pass this region before iteration one finishes computing.
c             An unconditional ORDERED barrier deadlocks this handshake.
              do
!$OMP ATOMIC READ
                  local_ready=ready
                  if (local_ready==1) exit
              enddo
          else if (mode==2) then
c             Let later computations finish earlier; register commits
c             must still follow the original grid order.
              until=omp_get_wtime()+dble(9-j)*0.001d0
              do while (omp_get_wtime()<until)
              enddo
          endif
"""

_SUFFIX = """
          if (j==2 .and. mode/=2) then
!$OMP ATOMIC WRITE
              ready=1
          endif
      enddo
!$OMP END PARALLEL DO
      write(*,*) ncommitted,committed(1:ncommitted)
      end program check_ordering
"""
