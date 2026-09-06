"""Actual pressure/flux/source regressions for granular static interfaces.

The probe links production b4step2, rpn2, augmented Riemann utilities,
transverse solver, flux2, step2 and src2. Only framework configuration and
inactive storm/topography callbacks are stubbed. The conservative update and
Godunov source ordering follow stepgrid; this is a small fixed patch, not an
AMR solver or terrain-ingestion replacement. No sentinel Riemann solver is used.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]

MODULES = """module geoclaw_module
  implicit none
  real(kind=8) :: grav=9.81d0,dry_tolerance=1.d-4,rho=300.d0
  real(kind=8) :: earth_radius=1.d0,deg2rad=1.d0,speed_limit=1.d99
  integer :: coordinate_system=1,num_manning=1
  logical :: friction_forcing=.true.,use_fwave_positivity_limiter=.true.
  real(kind=8) :: friction_depth=1.d6,manning_coefficient(1)=0.d0,manning_break(1)=0.d0
end module
module amr_module
  implicit none
  integer :: mcapa=0,mwaves=3,method(7)=0,mthlim(3)=1,outunit=6
  real(kind=8) :: xlower=0.d0,xupper=60.d0,ylower=0.d0,yupper=45.d0,NEEDS_TO_BE_SET=-1.d99
  logical :: xperdom=.false.,yperdom=.false.,spheredom=.false.,use_fwaves=.true.
end module
module topo_module
  implicit none
  integer :: num_dtopo=0,aux_finalized=2
  real(kind=8) :: topotime=0.d0,xlowdtopo=0.d0,xhidtopo=0.d0,ylowdtopo=0.d0,yhidtopo=0.d0
end module
module storm_module
  implicit none
  logical :: pressure_forcing=.false.
  integer :: pressure_index=1
contains
  subroutine set_storm_fields(maux,mbc,mx,my,xl,yl,dx,dy,t,aux)
    integer :: maux,mbc,mx,my
    real(kind=8) :: xl,yl,dx,dy,t,aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
    if(pressure_forcing) error stop 'Probe does not support storms'
  end subroutine
end module
subroutine setaux(mbc,mx,my,xl,yl,dx,dy,maux,aux)
  integer :: mbc,mx,my,maux
  real(kind=8) :: xl,yl,dx,dy,aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
  error stop 'Prescribed probe terrain must already be finalized'
end subroutine
subroutine check4nans(meqn,mbc,mx,my,q,t,stage)
  use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
  integer :: meqn,mbc,mx,my,stage
  real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc),t
  if(.not.all(ieee_is_finite(q))) error stop 'Nonfinite probe state'
end subroutine
"""

DRIVER = """program static_interface_balance_probe
  use geoclaw_module
  use amr_module
  use rheology_module
  implicit none
  integer,parameter :: nx=12,ny=9,ng=5,neq=3,na=3,maxm=12
  integer :: mbc,mx,my,maux,kind,model,direction,order,nsteps,i,j,k,ii,jj,face
  real(kind=8) :: q(neq,1-ng:nx+ng,1-ng:ny+ng),a(na,1-ng:nx+ng,1-ng:ny+ng),q0(neq,nx,ny)
  real(kind=8) :: fm(neq,1-ng:nx+ng,1-ng:ny+ng),fp(neq,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: gm(neq,1-ng:nx+ng,1-ng:ny+ng),gp(neq,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: line(neq,1-ng:maxm+ng),al(na,1-ng:maxm+ng),rawaux(na,1-ng:maxm+ng)
  real(kind=8) :: fw(neq,3,1-ng:maxm+ng),s(3,1-ng:maxm+ng),am(neq,1-ng:maxm+ng),ap(neq,1-ng:maxm+ng)
  real(kind=8) :: dt,t,dx,dy,xl,yl,speed,cohesion,base,amplitude,pos,x,y,cfl,cflmax
  real(kind=8) :: markerleft,markerright,jump,guarded,unguarded,first_h,first_m,mass0,mass1
  real(kind=8) :: qdiff,hdiff,momentum,umax,hmin,hmax,firstsource
  external rpn2,rpt2
  read(*,*) kind,model,direction,order,dt,nsteps,speed,cohesion,base,amplitude,dx
  mx=nx;my=ny;mbc=ng;maux=na;dy=dx;xl=0.d0;yl=0.d0;t=0.d0
  xupper=dx*nx;yupper=dy*ny
  imodel_rh=model;rho_rh=rho;n_zones_rh=1
  allocate(mu_zones_rh(1),xi_zones_rh(1),C_zones_rh(1))
  mu_zones_rh=.4d0;xi_zones_rh=1.d12;C_zones_rh=cohesion
  state_momentum_regularization_depth_rh=.05d0
  voellmy_state_momentum_regularization_depth_rh=.1d0
  method(2)=order;method(3)=2;method(5)=1
  q=0.d0;a=0.d0
  do j=1,ny
    do i=1,nx
      x=(dble(i)-.5d0)*dx;y=(dble(j)-.5d0)*dy
      pos=dble(i-6);if(direction==2) pos=dble(j-5)
      q(1,i,j)=base
      select case(kind)
      case(1) ! Plateau-step-plateau: amplitude is the actual head jump.
        if(pos>=0.d0) q(1,i,j)=base+amplitude
      case(2) ! Alternating grid mode has zero centred gradient.
        if(modulo(int(pos),2)==0) q(1,i,j)=base+amplitude
      case(3) ! A one-cell-wide ridge, not a prescribed smooth slope.
        if(pos==0.d0) q(1,i,j)=base+amplitude
      case(4) ! Affine free surface; amplitude is head increment per cell.
        q(1,i,j)=base+amplitude*pos
      case(5) ! Oblique surface, equal increments in x and y.
        q(1,i,j)=base+amplitude*dble(i-6+j-5)
      case(6) ! Smooth sub-repose mound.
        q(1,i,j)=base+amplitude*exp(-dble((i-6)**2+(j-5)**2)/16.d0)
      case(7) ! Fully wet water lake over an affine bed.
        a(1,i,j)=.1d0*x+.05d0*y
        q(1,i,j)=base-a(1,i,j)
      case(8) ! Fully wet water lake over a quadratic bed.
        a(1,i,j)=.002d0*x*x+.001d0*y*y
        q(1,i,j)=base-a(1,i,j)
      case(9) ! Wet/dry water lake with a hydrostatic shoreline.
        a(1,i,j)=.5d0*x
        q(1,i,j)=max(0.d0,base-a(1,i,j))
      case(10) ! Granular wet edge / barely-wet film, amplitude is film depth.
        if(pos>=0.d0) q(1,i,j)=amplitude
      case default
        error stop 'Unknown probe pattern'
      end select
      q(2,i,j)=q(1,i,j)*speed
    end do
  end do
  q0=q(:,1:nx,1:ny);mass0=sum(q(1,1:nx,1:ny))*dx*dy;cflmax=0.d0
  do k=1,nsteps
    call boundaries()
    call b4step2(mbc,mx,my,neq,q,xl,yl,dx,dy,t,dt,maux,a,.true.)
    if(k==1) then
      if(direction==1) then
        line=q(:,:,5);al=a(:,:,5);face=6
      else
        line=0.d0;al=0.d0
        line(:,1-ng:ny+ng)=q(:,6,:);al(:,1-ng:ny+ng)=a(:,6,:);face=5
      endif
      markerleft=al(2,face-1);markerright=al(2,face)
      jump=abs(line(1,face)+al(1,face)-line(1,face-1)-al(1,face-1))
      ii=nx;if(direction==2) ii=ny
      call rpn2(direction,maxm,neq,mwaves,na,ng,ii,line,line,al,al,fw,s,am,ap)
      guarded=sum(abs(fw(:,:,face)))
      rawaux=al;rawaux(2,:)=-1.d0
      call rpn2(direction,maxm,neq,mwaves,na,ng,ii,line,line,rawaux,rawaux,fw,s,am,ap)
      unguarded=sum(abs(fw(:,:,face)))
    endif
    call step2(maxm,neq,maux,mbc,mx,my,q,a,dx,dy,dt,cfl,fm,fp,gm,gp,rpn2,rpt2)
    cflmax=max(cflmax,cfl)
    if(cfl>0.5d0) error stop 'Probe timestep exceeds diagnostic CFL bound'
    do j=1,ny
      do i=1,nx
        q(:,i,j)=q(:,i,j)-dt/dx*(fm(:,i+1,j)-fp(:,i,j))-dt/dy*(gm(:,i,j+1)-gp(:,i,j))
      end do
    end do
    if(k==1) then
      first_h=maxval(abs(q(1,1:nx,1:ny)-q0(1,:,:)))
      first_m=maxval(abs(q(2:3,1:nx,1:ny)-q0(2:3,:,:)))
    endif
    if(minval(q(1,1:nx,1:ny)) < -1.d-12) error stop 'Negative depth in probe'
    where(q(1,:,:)<dry_tolerance)
      q(1,:,:)=max(q(1,:,:),0.d0);q(2,:,:)=0.d0;q(3,:,:)=0.d0
    endwhere
    call src2(neq,mbc,mx,my,xl,yl,dx,dy,q,maux,a,t,dt)
    if(k==1) firstsource=maxval(abs(q(2:3,1:nx,1:ny)))
    t=t+dt
  end do
  mass1=sum(q(1,1:nx,1:ny))*dx*dy
  qdiff=maxval(abs(q(:,1:nx,1:ny)-q0));hdiff=maxval(abs(q(1,1:nx,1:ny)-q0(1,:,:)))
  momentum=maxval(abs(q(2:3,1:nx,1:ny)));umax=0.d0
  do j=1,ny
    do i=1,nx
      if(q(1,i,j)>dry_tolerance) umax=max(umax,sqrt(sum(q(2:3,i,j)**2))/q(1,i,j))
    end do
  end do
  hmin=minval(q(1,1:nx,1:ny));hmax=maxval(q(1,1:nx,1:ny))
  write(*,'(17(es25.17,1x))') markerleft,markerright,jump,guarded,unguarded,first_h,first_m, &
      firstsource,qdiff,hdiff,momentum,umax,mass1-mass0,hmin,hmax,cflmax,t
contains
  subroutine boundaries()
    integer :: i,j,ii,jj
    do j=1-ng,ny+ng
      jj=j
      if(j<1) jj=1-j
      if(j>ny) jj=2*ny+1-j
      do i=1-ng,nx+ng
        if(i>=1.and.i<=nx.and.j>=1.and.j<=ny) cycle
        ii=i
        if(i<1) ii=1-i
        if(i>nx) ii=2*nx+1-i
        q(:,i,j)=q(:,ii,jj);a(1,i,j)=a(1,ii,jj)
        if(i<1.or.i>nx) q(2,i,j)=-q(2,i,j)
        if(j<1.or.j>ny) q(3,i,j)=-q(3,i,j)
      enddo
    enddo
  end subroutine
end program
"""

FIELDS = ("yield_left", "yield_right", "face_head_jump", "guarded_fwave_norm",
          "unguarded_fwave_norm", "first_hyp_depth_change", "first_hyp_momentum_change",
          "first_postsource_momentum", "q_max_change", "depth_max_change",
          "final_momentum_max", "final_speed_max", "mass_change", "depth_min",
          "depth_max", "max_cfl", "time")


def compile_probe(build, avac=None, clawpack=None):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for actual pressure/flux/source checks")
    avac = Path(avac or ROOT / "avac-main/src/AVAC")
    clawpack = Path(clawpack or ROOT / "avac-main/clawpack-v5.14.0")
    build.mkdir(parents=True, exist_ok=True)
    modules, driver, executable = build / "modules.f90", build / "driver.f90", build / "probe.exe"
    modules.write_text(MODULES, encoding="utf-8");driver.write_text(DRIVER, encoding="utf-8")
    sources = [modules, avac / "rheology_module.f90", avac / "b4step2.f90",
               avac / "rpn2_geoclaw.f", clawpack / "riemann/src/geoclaw_riemann_utils.f",
               clawpack / "riemann/src/rpt2_geoclaw.f", avac / "flux2fw.f",
               clawpack / "amrclaw/src/2d/inlinelimiter.f",
               clawpack / "geoclaw/src/2d/shallow/step2.f90", avac / "src2.f90", driver]
    subprocess.run([compiler, "-O0", "-fopenmp", "-fcheck=all", "-ffixed-line-length-none",
                    "-ffree-line-length-none", "-J", str(build), *map(str, sources),
                    "-o", str(executable)], cwd=build, check=True, capture_output=True, text=True)

    def run(kind=1, *, model=1, direction=1, order=2, dt=.01, steps=1,
            speed=0., cohesion=0., base=3., amplitude=3., dx=5.):
        values = (kind, model, direction, order, dt, steps, speed, cohesion, base, amplitude, dx)
        result = subprocess.run([str(executable)], input=" ".join(map(str, values))+"\n",
                                cwd=build, capture_output=True, text=True, timeout=20, check=True)
        array = np.fromstring(result.stdout, sep=" ")
        assert array.size == len(FIELDS), result.stdout
        assert np.isfinite(array).all()
        return dict(zip(FIELDS, array))
    run.sources = sources
    run.executable = executable
    return run


@pytest.fixture(scope="module")
def pressure_probe(tmp_path_factory):
    return compile_probe(tmp_path_factory.mktemp("actual_static_interface"))


@pytest.mark.parametrize("base", [3., 50.])
@pytest.mark.parametrize("model", [1, 2, 3])
@pytest.mark.parametrize("direction", [1, 2])
def test_super_repose_plateau_head_jump_reaches_actual_pressure_solver(pressure_probe, base, model, direction):
    r = pressure_probe(base=base, model=model, direction=direction)
    assert max(r["yield_left"], r["yield_right"]) < 1
    assert r["face_head_jump"] > .4 * 5
    assert r["guarded_fwave_norm"] > 0
    assert r["guarded_fwave_norm"] == pytest.approx(r["unguarded_fwave_norm"], rel=1e-13)
    assert r["first_hyp_depth_change"] > 0
    assert abs(r["mass_change"]) < 1e-8


@pytest.mark.parametrize("kind", [2, 3])
@pytest.mark.parametrize("direction", [1, 2])
def test_grid_scale_super_repose_modes_are_not_falsely_pinned(pressure_probe, kind, direction):
    r = pressure_probe(kind, direction=direction)
    assert r["guarded_fwave_norm"] > 0
    assert r["first_hyp_depth_change"] > 0


@pytest.mark.parametrize("dx", [2.5, 5., 10.])
def test_interface_balance_scales_with_cell_width_not_a_case_specific_head(pressure_probe, dx):
    r = pressure_probe(dx=dx, amplitude=.6*dx)
    assert r["face_head_jump"] == pytest.approx(.6*dx)
    assert r["guarded_fwave_norm"] > 0


@pytest.mark.parametrize("kind,base,amplitude", [(4,50.,1.5), (6,3.,3.)])
def test_true_sub_repose_plane_and_smooth_pile_remain_static(pressure_probe, kind, base, amplitude):
    r = pressure_probe(kind, base=base, amplitude=amplitude, steps=8)
    assert r["q_max_change"] == 0
    assert r["final_momentum_max"] == 0


@pytest.mark.parametrize("direction", [1, 2])
def test_oblique_super_repose_gradient_is_not_replaced_by_componentwise_test(pressure_probe, direction):
    r = pressure_probe(5, base=50., amplitude=1.5, direction=direction)
    assert r["face_head_jump"] < .4*5
    assert min(r["yield_left"], r["yield_right"]) > 1
    assert r["guarded_fwave_norm"] > 0


def test_existing_cohesion_resistance_is_preserved(pressure_probe):
    stable = pressure_probe(model=3, cohesion=5000., amplitude=3.)
    unstable = pressure_probe(model=3, cohesion=5000., amplitude=6.)
    assert stable["q_max_change"] == 0
    assert unstable["guarded_fwave_norm"] > 0


@pytest.mark.parametrize("film", [0., .9999e-4, 1e-4, 1.0001e-4, 1.01e-4])
def test_super_repose_wet_edge_releases_on_both_sides_of_dry_threshold(pressure_probe, film):
    r = pressure_probe(10, amplitude=film)
    assert r["guarded_fwave_norm"] > 0
    assert r["first_hyp_depth_change"] > 0


def test_sub_repose_wet_dry_edge_still_remains_static(pressure_probe):
    r = pressure_probe(10, base=1.5, amplitude=0., steps=8)
    assert r["q_max_change"] == 0


@pytest.mark.parametrize("speed", [0., 1e-12, 1e-8, 1e-4])
def test_slow_super_repose_pressure_release_has_no_exact_rest_discontinuity(pressure_probe, speed):
    rest = pressure_probe()
    moving = pressure_probe(speed=speed)
    assert moving["guarded_fwave_norm"] > 0
    assert moving["guarded_fwave_norm"] == pytest.approx(rest["guarded_fwave_norm"], rel=2e-4)


@pytest.mark.parametrize("kind,base", [(7,50.), (8,50.), (9,20.)])
@pytest.mark.parametrize("order", [1, 2])
def test_actual_water_pressure_flux_source_preserves_lake_at_rest(pressure_probe, kind, base, order):
    r = pressure_probe(kind, model=0, base=base, steps=8, order=order)
    assert r["q_max_change"] < 1e-11
    assert abs(r["mass_change"]) < 1e-8
