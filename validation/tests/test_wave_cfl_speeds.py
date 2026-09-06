"""Compare WAVE's speed-only callback with the real augmented Riemann solver.

Only framework parameter modules are stubbed. Both callbacks, the augmented
utilities, transverse solver, limiters, step2_cfl and accepted step2 are the
production routines. Checks are bitwise, not tolerance-based.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLAW = ROOT / "avac-main/clawpack-v5.14.0"
WAVE = ROOT / "avac-main/src/WAVE"

MODULES = """module geoclaw_module
  implicit none
  real(kind=8) :: grav=9.81d0,dry_tolerance=1.d-4,rho=1000.d0
  real(kind=8) :: earth_radius=6367500.d0,deg2rad=0.017453292519943295d0
  integer :: coordinate_system=1
  logical :: use_fwave_positivity_limiter=.false.
end module
module amr_module
  implicit none
  integer :: mcapa=0,mwaves=3,method(7)=0,mthlim(3)=1
  logical :: use_fwaves=.true.
end module
module storm_module
  implicit none
  logical :: pressure_forcing=.false.
  integer :: pressure_index=4
end module
module test_cases
  use geoclaw_module
  use, intrinsic :: iso_fortran_env, only: int64
  implicit none
  integer(int64) :: seed=1234567_int64
contains
  real(kind=8) function random_unit() result(r)
    seed=modulo(seed*48271_int64,2147483647_int64)
    r=dble(seed)/2147483647.d0
  end function
  subroutine state(kind,pos,neq,q,a)
    integer,intent(in) :: kind,pos,neq
    real(kind=8),intent(out) :: q(neq),a(4)
    real(kind=8) :: h,u,v,b,c
    logical :: left
    left=modulo(pos,12)<6
    h=2.d0;u=0.d0;v=0.d0;b=0.d0
    select case(kind)
    case(0) ! Entirely empty.
      h=0.d0
    case(1) ! Positive dry films, including exactly dry_tolerance.
      h=merge(dry_tolerance,.5d0*dry_tolerance,left);u=3.d0;v=-7.d0
    case(2) ! Identical wet rest states.
    case(3) ! Lake at rest on nonconstant terrain.
      b=.125d0*modulo(pos,12);h=10.d0-b
    case(4) ! Uniform moving water.
      u=10.d0;v=-7.d0
    case(5,6) ! Left/right wet water facing an impermeable high dry wall.
      if (left.eqv.(kind==6)) then
        h=0.d0;b=100.d0
      endif
      u=merge(1.d0,-1.d0,left)
    case(7,8) ! Left/right inundation of a low dry cell.
      if (left.eqv.(kind==8)) then
        h=0.d0;b=.2d0
      endif
      u=merge(1.d0,-1.d0,left)
    case(9) ! Wall predicate at exactly the free-surface elevation.
      if (.not.left) then
        h=0.d0;b=2.d0
      endif
    case(10) ! First representable wet depth above the dry threshold.
      h=nearest(dry_tolerance,1.d0)
    case(11) ! Threshold-depth neighbor beside wet water.
      h=merge(dry_tolerance,2.d0,left)
    case(12) ! Negative depths: only the first three q components are cleared.
      h=merge(-1.d-8,2.d0,left);u=7.d0;v=-3.d0
    case(13) ! Strong colliding flows.
      h=merge(10.d0,.5d0,left);u=merge(30.d0,-20.d0,left);v=4.d0
    case(14) ! Diverging rarefactions.
      u=merge(-15.d0,15.d0,left)
    case(15) ! Transcritical flow immediately around the gravity-wave speed.
      c=sqrt(grav*h);u=nearest(c,merge(-1.d0,1.d0,left))
    case(16) ! Large, finite velocity of either sign.
      u=merge(5000.d0,-5000.d0,left);v=-.25d0*u
    case(17) ! Nonzero subnormal-scale momentum must not become a rest test.
      u=1.d-200;v=-1.d-200
    case(18) ! Unequal wet depths near the dry threshold.
      h=merge(nearest(dry_tolerance,1.d0),2.d0*dry_tolerance,left)
    case(19) ! Moving water can overtop a bed above its initial free surface.
      u=15.d0
      if (.not.left) then
        h=0.d0;b=3.d0
      endif
    case(20) ! Wet/dry combinations near a downward bed jump.
      h=merge(0.d0,2.d0,left);b=merge(-10.d0,0.d0,left)
    case(21) ! Residual momentum in zero-depth cells.
      h=0.d0
    case default ! Deterministic independent random reconstructed states.
      h=10.d0**(-5.d0+8.d0*random_unit())
      if(random_unit()<.2d0) h=0.d0
      u=400.d0*(random_unit()-.5d0)
      v=100.d0*(random_unit()-.5d0)
      b=100.d0*(random_unit()-.5d0)
    end select
    q=123.d0
    q(1:3)=[h,h*u,h*v]
    if(kind==21) q(2:3)=[1.d-8,-1.d-8]
    a=[b,1.d0+.01d0*modulo(pos,17),.3d0+.01d0*modulo(pos,13), &
       90000.d0+100.d0*modulo(pos,19)]
  end subroutine
  logical function exact(a,b)
    real(kind=8),intent(in) :: a(:),b(:)
    exact=size(a)==size(b)
    if(exact) exact=all(transfer(a,[0_int64],size(a))==transfer(b,[0_int64],size(b)))
  end function
end module
"""

LINE_DRIVER = """program line_probe
  use geoclaw_module
  use amr_module
  use storm_module
  use test_cases
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  implicit none
  integer,parameter :: nx=13,maxm=17,na=4
  integer :: neq,direction,capacity,pressure,alias,ng,kind,i
  real(kind=8),allocatable :: ql(:,:),qr(:,:),fl(:,:),fr(:,:),a(:,:),ar(:,:),a0(:,:),ar0(:,:)
  real(kind=8),allocatable :: fw(:,:,:),s(:,:),am(:,:),ap(:,:),ffw(:,:,:),fs(:,:),fam(:,:),fap(:,:)
  read(*,*) neq,direction,capacity,pressure,alias,ng
  mcapa=capacity;pressure_forcing=pressure==1
  if(capacity>0) coordinate_system=2
  allocate(ql(neq,1-ng:maxm+ng),qr(neq,1-ng:maxm+ng),fl(neq,1-ng:maxm+ng),fr(neq,1-ng:maxm+ng))
  allocate(a(na,1-ng:maxm+ng),ar(na,1-ng:maxm+ng),a0(na,1-ng:maxm+ng),ar0(na,1-ng:maxm+ng))
  allocate(fw(neq,3,1-ng:maxm+ng),s(3,1-ng:maxm+ng),am(neq,1-ng:maxm+ng),ap(neq,1-ng:maxm+ng))
  allocate(ffw(neq,3,1-ng:maxm+ng),fs(3,1-ng:maxm+ng),fam(neq,1-ng:maxm+ng),fap(neq,1-ng:maxm+ng))
  do kind=0,221
    do i=1-ng,maxm+ng
      call state(kind,i,neq,ql(:,i),a(:,i))
      if(alias==0.and.kind>21) then
        call state(kind,i+1,neq,qr(:,i),ar(:,i))
      else
        qr(:,i)=ql(:,i);ar(:,i)=a(:,i)
      endif
    enddo
    fl=ql;fr=qr;a0=a;ar0=ar
    fw=42.d0;s=42.d0;am=42.d0;ap=42.d0
    ffw=42.d0;fs=42.d0;fam=42.d0;fap=42.d0
    if(alias==1) then
      call rpn2(direction,maxm,neq,3,na,ng,nx,ql,ql,a,a,fw,s,am,ap)
      call rpn2_cfl(direction,maxm,neq,3,na,ng,nx,fl,fl,a,a,ffw,fs,fam,fap)
    else
      call rpn2(direction,maxm,neq,3,na,ng,nx,ql,qr,a,ar,fw,s,am,ap)
      call rpn2_cfl(direction,maxm,neq,3,na,ng,nx,fl,fr,a,ar,ffw,fs,fam,fap)
    endif
    if(.not.all(ieee_is_finite(s))) error stop 'Nonfinite oracle speed'
    if(.not.exact(reshape(s,[size(s)]),reshape(fs,[size(fs)]))) then
      write(*,*) 'Speed mismatch in case',kind, maxval(abs(s-fs))
      error stop 'Normal wave speeds differ'
    endif
    if(.not.exact(reshape(ql,[size(ql)]),reshape(fl,[size(fl)]))) error stop 'Left state cleanup differs'
    if(.not.exact(reshape(qr,[size(qr)]),reshape(fr,[size(fr)]))) error stop 'Right state cleanup differs'
    if(any(a/=a0).or.any(ar/=ar0)) error stop 'Auxiliary state changed'
    if(any(ffw/=0.d0).or.any(fam/=0.d0).or.any(fap/=0.d0)) error stop 'Speed-only flux outputs not initialized'
  enddo
  print *, 'PASS 222 slices'
end program
"""

PATCH_DRIVER = """program patch_probe
  use geoclaw_module
  use amr_module
  use storm_module
  use test_cases
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  implicit none
  integer,parameter :: nx=12,ny=9,na=4
  integer :: neq,capacity,pressure,ng,kind,i,j,k
  real(kind=8),allocatable :: q(:,:,:),a(:,:,:),q0(:,:,:),a0(:,:,:),flux(:,:,:,:)
  real(kind=8) :: dt,dx,dy,cfl,cfl_fast,cfl_step,limits(5),time_steps(4)
  real(kind=8) :: cell(5),auxcell(4)
  external rpn2,rpn2_cfl,rpt2
  read(*,*) neq,capacity,pressure,ng
  mcapa=capacity;pressure_forcing=pressure==1
  if(capacity>0) coordinate_system=2
  use_fwave_positivity_limiter=ng==5
  method(2)=2;method(3)=2
  allocate(q(neq,1-ng:nx+ng,1-ng:ny+ng),q0(neq,1-ng:nx+ng,1-ng:ny+ng))
  allocate(a(na,1-ng:nx+ng,1-ng:ny+ng),a0(na,1-ng:nx+ng,1-ng:ny+ng))
  allocate(flux(neq,1-ng:nx+ng,1-ng:ny+ng,4))
  dx=1.7d0;dy=.9d0;time_steps=[0.d0,.001d0,.123d0,1000.d0]
  do kind=0,45
    do j=1-ng,ny+ng
      do i=1-ng,nx+ng
        call state(kind,i+2*j,neq,q(:,i,j),a(:,i,j))
      enddo
    enddo
    ! Include patches with entirely dry interiors and water only in ghosts.
    if(kind>=22.and.kind<=26) then
      q=0.d0
      call state(4,1,neq,cell(1:neq),auxcell)
      select case(kind)
      case(22)
        q(:,0,4)=cell(1:neq)
      case(23)
        q(:,nx+1,4)=cell(1:neq)
      case(24)
        q(:,5,0)=cell(1:neq)
      case(25)
        q(:,5,ny+1)=cell(1:neq)
      case(26)
        q(:,1-ng,1-ng)=cell(1:neq)
      end select
    endif
    q0=q;a0=a
    do k=1,size(time_steps)
      dt=time_steps(k)
      call step2_cfl(nx,neq,na,ng,nx,ny,q,a,dx,dy,dt,cfl,rpn2)
      call step2_cfl(nx,neq,na,ng,nx,ny,q,a,dx,dy,dt,cfl_fast,rpn2_cfl)
      call step2(nx,neq,na,ng,nx,ny,q,a,dx,dy,dt,cfl_step, &
                 flux(:,:,:,1),flux(:,:,:,2),flux(:,:,:,3),flux(:,:,:,4),rpn2,rpt2)
      if(.not.ieee_is_finite(cfl)) error stop 'Nonfinite oracle CFL'
      if(.not.exact([cfl,cfl],[cfl_fast,cfl_step])) then
        write(*,*) 'CFL mismatch in case',kind,k,cfl,cfl_fast,cfl_step
        error stop 'Patch CFL differs'
      endif
      limits=[.5d0,1.d0,nearest(cfl,-1.d0),cfl,nearest(cfl,1.d0)]
      if(any((cfl<=limits).neqv.(cfl_fast<=limits))) error stop 'CFL acceptance differs'
      if(.not.exact(reshape(q,[size(q)]),reshape(q0,[size(q0)]))) error stop 'Patch state changed'
      if(any(a/=a0)) error stop 'Patch auxiliary state changed'
    enddo
  enddo
  print *, 'PASS 184 patch CFL decisions'
end program
"""


IEEE_DRIVER = """program ieee_probe
  use geoclaw_module
  use amr_module
  use storm_module
  use test_cases
  use, intrinsic :: ieee_arithmetic
  implicit none
  integer,parameter :: nx=8,ny=6,ng=2,neq=3,na=4
  integer :: direction,capacity,pressure,kind,i,j,k,invalid_flux_finite_cfl
  real(kind=8) :: q(neq,1-ng:nx+ng,1-ng:ny+ng),a(na,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: line(neq,1-ng:nx+ng),fast(neq,1-ng:nx+ng)
  real(kind=8) :: fw(neq,3,1-ng:nx+ng),s(3,1-ng:nx+ng),am(neq,1-ng:nx+ng),ap(neq,1-ng:nx+ng)
  real(kind=8) :: ffw(neq,3,1-ng:nx+ng),fs(3,1-ng:nx+ng),fam(neq,1-ng:nx+ng),fap(neq,1-ng:nx+ng)
  real(kind=8) :: nan,inf,cfl,cfl_fast
  logical :: accepted,fast_accepted
  external rpn2,rpn2_cfl
  read(*,*) direction,capacity,pressure
  mcapa=capacity;pressure_forcing=pressure==1
  if(capacity>0) coordinate_system=2
  nan=ieee_value(0.d0,ieee_quiet_nan);inf=ieee_value(0.d0,ieee_positive_inf)
  invalid_flux_finite_cfl=0
  do kind=1,19
    do j=1-ng,ny+ng
      do i=1-ng,nx+ng
        call state(4,i+2*j,neq,q(:,i,j),a(:,i,j))
      enddo
    enddo
    select case(kind)
    case(1)
      q(1,4,3)=nan
    case(2)
      q(2,4,3)=nan
    case(3)
      q(3,4,3)=nan
    case(4)
      a(1,4,3)=nan
    case(5)
      a(4,4,3)=nan
    case(6)
      a(3,4,3)=nan
    case(7)
      a(2,4,3)=nan
    case(8)
      q(1,4,3)=inf
    case(9)
      q(2,4,3)=inf
    case(10)
      q(3,4,3)=inf
    case(11)
      a(1,4,3)=inf
    case(12)
      q(1,4,3)=-inf
    case(13)
      q(1,4,3)=1.d160
    case(14)
      q(1,4,3)=1.d305
    case(15)
      q(2,4,3)=1.d300
    case(16)
      q(:,4,3)=[1.d-3,1.d308,0.d0]
    case(17)
      q(1,4,3)=1.d150;a(4,4,3)=1.d308
    case(18)
      q(:,4,3)=[nearest(dry_tolerance,1.d0),1.d150,-1.d150]
    case(19)
      q(1,4,3)=1.d-300;q(2:3,4,3)=1.d300
    end select
    line=q(:,:,3);fast=line
    call rpn2(direction,nx,neq,3,na,ng,nx,line,line,a(:,:,3),a(:,:,3),fw,s,am,ap)
    call rpn2_cfl(direction,nx,neq,3,na,ng,nx,fast,fast,a(:,:,3),a(:,:,3),ffw,fs,fam,fap)
    call same_ieee(reshape(s,[size(s)]),reshape(fs,[size(fs)]),'speeds')
    call same_ieee(reshape(line,[size(line)]),reshape(fast,[size(fast)]),'cleanup')
    call step2_cfl(nx,neq,na,ng,nx,ny,q,a,1.d0,1.d0,.001d0,cfl,rpn2)
    call step2_cfl(nx,neq,na,ng,nx,ny,q,a,1.d0,1.d0,.001d0,cfl_fast,rpn2_cfl)
    call same_ieee([cfl],[cfl_fast],'CFL')
    accepted=ieee_is_finite(cfl).and.cfl>=0.d0.and.cfl<=1.d0
    fast_accepted=ieee_is_finite(cfl_fast).and.cfl_fast>=0.d0.and.cfl_fast<=1.d0
    if(accepted.neqv.fast_accepted) error stop 'Changed invalid-state acceptance'
    if(.not.all(ieee_is_finite(fw)).and.ieee_is_finite(cfl)) invalid_flux_finite_cfl=invalid_flux_finite_cfl+1
  enddo
  print *, 'PASS 19 IEEE cases; legacy invalid flux with finite CFL:',invalid_flux_finite_cfl
contains
  subroutine same_ieee(a,b,label)
    real(kind=8),intent(in) :: a(:),b(:)
    character(*),intent(in) :: label
    integer :: k
    do k=1,size(a)
      if(ieee_is_nan(a(k)).and.ieee_is_nan(b(k))) cycle
      if(.not.exact(a(k:k),b(k:k))) then
        print *, 'IEEE mismatch',label,kind,k,a(k),b(k)
        error stop 'IEEE behavior differs'
      endif
    enddo
  end subroutine
end program
"""


BENCHMARK_DRIVER = """program callback_benchmark
  use geoclaw_module
  use amr_module
  use test_cases
  implicit none
  integer,parameter :: nx=256,ng=2,neq=3,na=4
  integer :: repeats,kind,i,k
  real(kind=8) :: q(neq,1-ng:nx+ng),a(na,1-ng:nx+ng)
  real(kind=8) :: fw(neq,3,1-ng:nx+ng),s(3,1-ng:nx+ng),am(neq,1-ng:nx+ng),ap(neq,1-ng:nx+ng)
  real(kind=8) :: t0,t1,t2,check_ref,check_fast
  read(*,*) kind,repeats
  do i=1-ng,nx+ng
    call state(kind,i,neq,q(:,i),a(:,i))
  enddo
  call cpu_time(t0)
  do k=1,repeats
    call rpn2(1,nx,neq,3,na,ng,nx,q,q,a,a,fw,s,am,ap)
  enddo
  call cpu_time(t1)
  check_ref=sum(s)
  do k=1,repeats
    call rpn2_cfl(1,nx,neq,3,na,ng,nx,q,q,a,a,fw,s,am,ap)
  enddo
  call cpu_time(t2)
  check_fast=sum(s)
  if(.not.exact([check_ref],[check_fast])) error stop 'Benchmark speed mismatch'
  write(*,'(a,1x,i0,2(1x,es14.6))') 'PASS callback CPU seconds',kind,t1-t0,t2-t1
end program
"""


@pytest.fixture(scope="module")
def cfl_probes(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for exact WAVE CFL equivalence")
    build = tmp_path_factory.mktemp("wave_cfl_speeds")
    modules = build / "modules.f90"
    modules.write_text(MODULES, encoding="utf-8")
    sources = [
        modules, CLAW / "riemann/src/rpn2_geoclaw.f",
        CLAW / "riemann/src/geoclaw_riemann_utils.f", WAVE / "rpn2_geoclaw_cfl.f90",
        CLAW / "riemann/src/rpt2_geoclaw.f", CLAW / "geoclaw/src/2d/shallow/flux2fw.f",
        CLAW / "amrclaw/src/2d/inlinelimiter.f", CLAW / "geoclaw/src/2d/shallow/step2.f90",
    ]
    result = subprocess.run(
        [compiler, "-O2", "-fcheck=all", "-ffpe-trap=invalid,zero,overflow",
         "-ffixed-line-length-none", "-ffree-line-length-none", "-J", str(build),
         "-c", *map(str, sources)], cwd=build, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name, source in (("line", LINE_DRIVER), ("patch", PATCH_DRIVER),
                         ("ieee", IEEE_DRIVER), ("benchmark", BENCHMARK_DRIVER)):
        driver = build / f"{name}.f90"
        driver.write_text(source, encoding="utf-8")
        # The IEEE diagnostic deliberately compares legacy NaN/overflow
        # behavior without trapping. All ordinary numerical probes trap.
        traps = [] if name == "ieee" else ["-ffpe-trap=invalid,zero,overflow"]
        result = subprocess.run(
            [compiler, "-O2", "-fcheck=all", *traps,
             "-ffree-line-length-none", "-J", str(build), str(driver),
             *(str(build / f"{path.stem}.o") for path in sources), "-o", str(build / name)],
            cwd=build, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def run(name, *args):
        result = subprocess.run(
            [str(build / name)], input=" ".join(map(str, args)) + "\n", cwd=build,
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout
        return result.stdout
    return run


@pytest.mark.parametrize("neq", [3, 5])
@pytest.mark.parametrize("direction", [1, 2])
@pytest.mark.parametrize("capacity", [0, 2])
@pytest.mark.parametrize("pressure", [0, 1])
@pytest.mark.parametrize("alias,ghost", [(0, 2), (1, 2), (1, 5)])
def test_exact_normal_speeds_and_input_cleanup(cfl_probes, neq, direction, capacity, pressure, alias, ghost):
    cfl_probes("line", neq, direction, capacity, pressure, alias, ghost)


@pytest.mark.parametrize("neq", [3, 5])
@pytest.mark.parametrize("capacity", [0, 2])
@pytest.mark.parametrize("pressure", [0, 1])
@pytest.mark.parametrize("ghost", [2, 5])
def test_exact_patch_cfl_matches_original_probe_and_accepted_step(cfl_probes, neq, capacity, pressure, ghost):
    cfl_probes("patch", neq, capacity, pressure, ghost)


@pytest.mark.parametrize("direction", [1, 2])
@pytest.mark.parametrize("capacity", [0, 2])
@pytest.mark.parametrize("pressure", [0, 1])
def test_nonfinite_and_extreme_states_preserve_legacy_cfl_decisions(cfl_probes, direction, capacity, pressure):
    cfl_probes("ieee", direction, capacity, pressure)
