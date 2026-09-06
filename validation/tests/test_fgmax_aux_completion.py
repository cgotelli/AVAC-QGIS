"""Compiled checks for FGmax terrain completion after a level's patch barrier."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
    / "shallow" / "fgmax_module.f90"
)


def test_auxiliary_completion_preserves_partial_levels_and_skips_completed_grids(tmp_path):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the FGmax completion regression")
    source = SOURCE.read_text(encoding="utf-8")
    # Compile the real module declarations and completion routine.  Its input
    # reader is unrelated and would otherwise require the full AMR executable.
    declarations = source[:source.index("contains") + len("contains")]
    helper = source[
        source.index("    subroutine fgmax_finalize_aux("):
        source.index("    end subroutine fgmax_finalize_aux")
        + len("    end subroutine fgmax_finalize_aux")
    ]
    driver = tmp_path / "driver.f90"
    executable = tmp_path / "driver"
    driver.write_text(
        "module amr_module\ninteger :: mxnest=3\nend module amr_module\n"
        + declarations + "\n" + helper + "\nend module fgmax_module\n" + _DRIVER,
        encoding="utf-8",
    )
    subprocess.run(
        [compiler, "-O0", "-fcheck=all", str(driver), "-o", str(executable)],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        [str(executable)], cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "FGmax completion checks passed"


_DRIVER = """
program check_completion
  use fgmax_module
  implicit none
  integer :: ifg
  real(kind=8) :: saved(3,1,4,2)

  ! Disabled FGmax must touch no grid or level storage.
  FG_num_fgrids=0
  call fgmax_finalize_aux(100)

  FG_num_fgrids=2
  do ifg=1,FG_num_fgrids
    allocate(FG_fgrids(ifg)%aux(3,1,4))
    allocate(FG_fgrids(ifg)%auxdone(3))
    FG_fgrids(ifg)%aux=FG_NOTSET
    FG_fgrids(ifg)%auxdone=.false.
  enddo
  FG_fgrids(1)%aux(1,1,1:3)=[-2.d0,0.d0,2.d0]
  FG_fgrids(1)%aux(2,1,:)=3.d0
  FG_fgrids(2)%aux(1,1,:)=7.d0
  do ifg=1,2
    saved(:,:,:,ifg)=FG_fgrids(ifg)%aux
  enddo

  call fgmax_finalize_aux(1)
  if (FG_fgrids(1)%auxdone(1)) error stop 'partial coverage marked complete'
  if (.not. FG_fgrids(2)%auxdone(1)) error stop 'complete grid left open'
  if (any(FG_fgrids(1)%auxdone(2:3))) error stop 'other levels changed'
  if (any(FG_fgrids(2)%auxdone(2:3))) error stop 'other grid levels changed'
  call fgmax_finalize_aux(1)
  if (FG_fgrids(1)%auxdone(1)) error stop 'repeated partial coverage completed'
  do ifg=1,2
    if (any(FG_fgrids(ifg)%aux /= saved(:,:,:,ifg))) error stop 'terrain changed'
  enddo

  call fgmax_finalize_aux(2)
  if (.not. FG_fgrids(1)%auxdone(2)) error stop 'second level did not complete'
  if (FG_fgrids(2)%auxdone(2)) error stop 'uncovered level marked complete'
  if (FG_fgrids(1)%auxdone(1)) error stop 'first level changed indirectly'

  ! New coverage can finish a level later, including one restored incomplete
  ! from a checkpoint.  Existing sampled terrain must remain untouched.
  FG_fgrids(1)%aux(1,1,4)=4.d0
  saved(1,1,4,1)=4.d0
  call fgmax_finalize_aux(1)
  if (.not. FG_fgrids(1)%auxdone(1)) error stop 'new coverage did not complete'
  do ifg=1,2
    if (any(FG_fgrids(ifg)%aux /= saved(:,:,:,ifg))) error stop 'terrain changed'
  enddo

  ! Deallocated terrain makes any accidental rescan of a completed grid fail
  ! under runtime bounds checks.  Restored true flags use this same fast path.
  deallocate(FG_fgrids(1)%aux,FG_fgrids(2)%aux)
  call fgmax_finalize_aux(1)
  if (.not. FG_fgrids(1)%auxdone(1)) error stop 'completed flag reset'
  if (.not. FG_fgrids(2)%auxdone(1)) error stop 'completed flag reset'

  print '(a)', 'FGmax completion checks passed'
end program check_completion
"""
