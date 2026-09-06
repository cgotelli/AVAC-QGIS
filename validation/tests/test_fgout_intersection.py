"""Compiled equivalence of bounded FGout interpolation and the full-grid scan."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d"
    / "shallow" / "fgout_module.f90"
)
WAVE_SOURCE = ROOT / "avac-main" / "src" / "WAVE" / "fgout_module.f90"


@pytest.fixture(scope="module", params=[SOURCE, WAVE_SOURCE], ids=["shared", "wave"])
def interpolate_patch(tmp_path_factory, request):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the FGout interpolation regression")
    source = request.param.read_text(encoding="utf-8")
    grid_type = source[
        source.index("    type fgout_grid"):
        source.index("    end type fgout_grid") + len("    end type fgout_grid")
    ]
    routine = source[
        source.index("    subroutine fgout_interp("):
        source.index("    end subroutine fgout_interp")
        + len("    end subroutine fgout_interp")
    ]
    reference = routine.replace(
        "subroutine fgout_interp(", "subroutine fgout_interp_reference("
    ).replace(
        "end subroutine fgout_interp", "end subroutine fgout_interp_reference"
    )
    # Retain the former full-grid traversal while sharing the actual
    # interpolation arithmetic and inclusive coordinate predicate.
    assert reference.count("do ifg=ifg_first,ifg_last") == 1
    assert reference.count("do jfg=jfg_first,jfg_last") == 1
    reference = reference.replace("do ifg=ifg_first,ifg_last", "do ifg=1,fgrid%mx")
    reference = reference.replace("do jfg=jfg_first,jfg_last", "do jfg=1,fgrid%my")
    bilinear = source[
        source.index("    real(kind=8) pure function interpolate("):
        source.index("    end function interpolate")
        + len("    end function interpolate")
    ]
    work = tmp_path_factory.mktemp("fgout-intersection")
    driver = work / "driver.f90"
    executable = work / "driver"
    driver.write_text(
        "module geoclaw_module\n"
        "  real(kind=8), parameter :: dry_tolerance=1.d-4\n"
        "end module geoclaw_module\n"
        "module fgout_probe\nimplicit none\n"
        + grid_type + "\ncontains\n" + routine + "\n" + reference + "\n"
        + bilinear + "\nend module fgout_probe\n"
        + _DRIVER,
        encoding="utf-8",
    )
    subprocess.run(
        [compiler, "-O2", "-fcheck=all", "-ffpe-trap=invalid,zero,overflow", "-ffree-line-length-none",
         str(driver), "-o", str(executable)],
        cwd=work, check=True, capture_output=True, text=True,
    )

    def probe(grid, patch, fgrid_type):
        result = subprocess.run(
            [str(executable)],
            input=" ".join(map(str, (*grid, *patch, fgrid_type))) + "\n",
            cwd=work, check=True, capture_output=True, text=True,
        )
        return np.fromstring(result.stdout, sep=" ", dtype=int)

    return probe


_DRIVER = """
program check_fgout
  use fgout_probe
  implicit none
  integer, parameter :: meqn=3,maux=1,mbc=5
  real(kind=8), parameter :: sentinel=-987654321.d0
  type(fgout_grid) :: bounded,reference
  real(kind=8), allocatable :: q(:,:,:),aux(:,:,:)
  real(kind=8) :: dxc,dyc,xlowc,ylowc,t
  integer :: mxc,myc,which,i,j,m,differences,updated,untouched,inactive_changes

  read(*,*) bounded%mx,bounded%my,bounded%x_low,bounded%y_low, &
      bounded%dx,bounded%dy,mxc,myc,xlowc,ylowc,dxc,dyc,which
  bounded%num_vars=6
  bounded%bathy_index=4
  bounded%eta_index=5
  bounded%time_index=6
  reference=bounded
  allocate(bounded%early(6,bounded%mx,bounded%my))
  allocate(bounded%late(6,bounded%mx,bounded%my))
  allocate(reference%early(6,bounded%mx,bounded%my))
  allocate(reference%late(6,bounded%mx,bounded%my))
  bounded%early=sentinel
  bounded%late=sentinel
  reference%early=sentinel
  reference%late=sentinel
  allocate(q(meqn,1-mbc:mxc+mbc,1-mbc:myc+mbc))
  allocate(aux(maux,1-mbc:mxc+mbc,1-mbc:myc+mbc))
  do j=1-mbc,myc+mbc
    do i=1-mbc,mxc+mbc
      do m=1,meqn
        q(m,i,j)=dble(m*1000+i*11+j*7)/13.d0
      enddo
      if (modulo(i+j,3)==0) q(:,i,j)=0.d0
      aux(1,i,j)=dble(i*i+17*j)/7.d0
    enddo
  enddo
  t=2.125d0
  call fgout_interp(which,bounded,t,q,meqn,mxc,myc,mbc,dxc,dyc, &
      xlowc,ylowc,maux,aux)
  call fgout_interp_reference(which,reference,t,q,meqn,mxc,myc,mbc, &
      dxc,dyc,xlowc,ylowc,maux,aux)
  differences=count(bounded%early /= reference%early) &
      +count(bounded%late /= reference%late)
  if (which==1) then
    updated=count(bounded%early(6,:,:) == t)
    untouched=count(bounded%early == sentinel)
    inactive_changes=count(bounded%late /= sentinel)
  else
    updated=count(bounded%late(6,:,:) == t)
    untouched=count(bounded%late == sentinel)
    inactive_changes=count(bounded%early /= sentinel)
  endif
  write(*,*) differences,updated,untouched,inactive_changes
end program check_fgout
"""


@pytest.mark.parametrize("fgrid_type", [1, 2])
@pytest.mark.parametrize(
    "grid,patch",
    [
        ((31, 27, 0., 0., 1., 1.), (9, 8, 3., 4., 1., 1.)),
        # Both endpoints coincide with output centers, including ghost-cell
        # sampling at the inclusive upper computational-patch edge.
        ((13, 11, 0., 0., 1., 1.), (4, 3, .5, 2.5, 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, np.nextafter(.5, 1.), 2.5, 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, np.nextafter(.5, 0.), 2.5, 1., 1.)),
        ((31, 27, -17.3, -21.7, .7, 1.1), (7, 5, -6.75, -11.1, .3, .6)),
        ((31, 27, -17.3, -21.7, .3, .6), (7, 5, -15.75, -18.1, .7, 1.1)),
        ((31, 27, 2667311., 1169558., 2., 2.), (9, 8, 2667320., 1169569., 2., 2.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, -2., -1., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, 11., 9., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, -100., 2., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, 100., 2., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, 2., -100., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, 2., 100., 1., 1.)),
        ((13, 11, 0., 0., 1., 1.), (4, 3, 1.e30, -1.e30, 1.e25, 1.e25)),
        # A patch between output centers must leave every sentinel untouched.
        ((13, 11, 0., 0., 2., 2.), (1, 1, 1.2, 1.2, .2, .2)),
        ((13, 11, 0., 0., 1., 1.), (20, 20, -2., -2., 1., 1.)),
        ((1, 1, -1., -1., 2., 2.), (1, 1, 0., 0., 1., 1.)),
        ((1, 11, 0., 0., 0., 1.), (1, 3, 0., 2., 1., 1.)),
        ((13, 1, 0., 0., 1., 0.), (4, 1, 2., 0., 1., 1.)),
        ((1, 1, 0., 0., 0., 0.), (1, 1, 0., 0., 1., 1.)),
    ],
)
def test_bounded_scan_matches_full_scan_exactly(interpolate_patch, grid, patch, fgrid_type):
    differences, updated, untouched, inactive_changes = interpolate_patch(grid, patch, fgrid_type)
    mx, my, xlow, ylow, dx, dy = grid
    mxc, myc, xlowc, ylowc, dxc, dyc = patch
    x = xlow + (np.arange(mx) + .5) * dx
    y = ylow + (np.arange(my) + .5) * dy
    expected = np.count_nonzero((x >= xlowc) & (x <= xlowc + dxc * mxc))
    expected *= np.count_nonzero((y >= ylowc) & (y <= ylowc + dyc * myc))
    assert differences == 0
    assert updated == expected
    assert untouched == 6 * (mx * my - expected)
    assert inactive_changes == 0
