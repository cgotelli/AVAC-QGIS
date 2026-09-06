"""Compile WAVE's actual FGout setup, interpolation, and binary writer."""

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


SOURCE = Path(__file__).resolve().parents[2] / "avac-main" / "src" / "WAVE" / "fgout_module.f90"


@pytest.fixture(scope="module")
def fgout_writer(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the WAVE FGout buffer regression")
    work = tmp_path_factory.mktemp("wave-fgout-buffers")
    stubs = work / "stubs.f90"
    driver = work / "driver.f90"
    executable = work / "driver"
    stubs.write_text(_STUBS, encoding="utf-8")
    driver.write_text(_DRIVER, encoding="utf-8")
    subprocess.run(
        [compiler, "-O0", "-cpp", "-fcheck=all", "-ffree-line-length-none",
         str(stubs), str(SOURCE), str(driver), "-o", str(executable)],
        cwd=work, check=True, capture_output=True, text=True,
    )
    return executable


@pytest.mark.parametrize("meqn,mx,my", [(3, 4, 3), (4, 4, 3), (7, 4, 3), (3, 1, 3), (3, 4, 1), (3, 1, 1)])
def test_exact_equation_sized_buffers_preserve_all_written_fields(fgout_writer, tmp_path, meqn, mx, my):
    (tmp_path / "fgout-input.data").write_text(
        f"1\n1\n1\n2\n0\n1\n2\n3\n{mx} {my}\n-3 2\n"
        f"{-3 + mx * 1.25} {2 + my * .75}\n"
        + " ".join(map(str, range(1, meqn + 3))) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(fgout_writer)], input=f"{meqn} {mx} {my}\n", cwd=tmp_path,
        check=True, capture_output=True, text=True,
    )
    values = np.fromfile(tmp_path / "fgout0001.b0001", dtype="<f8").reshape((meqn + 2, mx, my), order="F")
    i, j = np.meshgrid(np.arange(1, mx + 1), np.arange(1, my + 1), indexing="ij")
    q = np.stack([100 * m + 10 * i + j for m in range(1, meqn + 1)])
    bed = 500 + 2 * i - 3 * j
    expected = np.concatenate((q, (q[0] + bed)[None], bed[None]))
    assert np.array_equal(values, expected)


_STUBS = """
module amr_module
  integer,parameter :: parmunit=99
  real(kind=8) :: tstart_thisrun=0.d0
end module
module utility_module
contains
  subroutine parse_values(str,n,values)
    character(len=*),intent(in) :: str
    integer,intent(out) :: n
    real(kind=8),intent(out) :: values(:)
    ! Test inputs request every q/eta/bathymetry field.
    n=size(values)
    read(str,*) values
  end subroutine
end module
module geoclaw_module
  real(kind=8),parameter :: dry_tolerance=1.d-4
end module
subroutine opendatafile(unit,fname)
  integer,intent(in) :: unit
  character(len=*),intent(in) :: fname
  open(unit,file=fname,status='old')
end subroutine
"""

_DRIVER = """
program check_fgout_buffers
  use fgout_module
  use, intrinsic :: ieee_arithmetic, only: ieee_is_nan
  implicit none
  integer,parameter :: mbc=5
  integer :: meqn,mx,my,m,i,j
  real(kind=8),allocatable :: q(:,:,:),aux(:,:,:)
  type(fgout_grid),pointer :: fg
  read(*,*) meqn,mx,my
  open(99,status='scratch')
  call set_fgout(.false.,meqn,'fgout-input.data')
  ! Legacy waves_utilities still relies on this public flag.
  if (.not. module_setup) error stop 'setup flag was not set'
  fg=>FGOUT_fgrids(1)
  if (any(shape(fg%early)/=[meqn+3,mx,my])) error stop 'early buffer shape'
  if (any(shape(fg%late)/=[meqn+3,mx,my])) error stop 'late buffer shape'
  if (fg%num_vars/=meqn+3) error stop 'variable count'
  if (fg%eta_index/=meqn+1) error stop 'eta index'
  if (fg%bathy_index/=meqn+2) error stop 'bed index'
  if (fg%time_index/=meqn+3) error stop 'time index'
  if (fg%nqout/=meqn+2 .or. .not.all(fg%q_out_vars)) error stop 'output selection'
  if (.not.all(ieee_is_nan(fg%early))) error stop 'early initialization'
  if (.not.all(ieee_is_nan(fg%late))) error stop 'late initialization'
  allocate(q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc))
  allocate(aux(1,1-mbc:mx+mbc,1-mbc:my+mbc))
  do j=1-mbc,my+mbc
    do i=1-mbc,mx+mbc
      do m=1,meqn
        q(m,i,j)=100*m+10*i+j
      enddo
      aux(1,i,j)=500+2*i-3*j
    enddo
  enddo
  call fgout_interp(1,fg,0.d0,q,meqn,mx,my,mbc,1.25d0,.75d0,-3.d0,2.d0,1,aux)
  q=2.d0*q
  call fgout_interp(2,fg,1.d0,q,meqn,mx,my,mbc,1.25d0,.75d0,-3.d0,2.d0,1,aux)
  if (.not.all(fg%early(fg%time_index,:,:)==0.d0)) error stop 'early time'
  if (.not.all(fg%late(fg%time_index,:,:)==1.d0)) error stop 'late time'
  if (.not.all(fg%late(1:meqn,:,:)==2.d0*fg%early(1:meqn,:,:))) error stop 'late q'
  call fgout_write(fg,0.d0,1)
end program
"""
