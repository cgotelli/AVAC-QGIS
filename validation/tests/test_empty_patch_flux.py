"""Compare the empty-patch shortcut with the actual, unshortened flux solver.

Production normal/transverse Riemann solvers, limiters, and flux kernels are
compiled together.  Reference entry points omit only the new early return.
Counting wrappers verify that empty patches avoid the work and that wet
ghosts, residual momentum, and nonzero shallow films retain the full path.
"""
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
import pytest

from test_static_interface_balance import MODULES


ROOT = Path(__file__).resolve().parents[2]
AVAC = ROOT / "avac-main/src/AVAC"
CLAW = ROOT / "avac-main/clawpack-v5.14.0"
STEP2 = CLAW / "geoclaw/src/2d/shallow/step2.f90"

DRIVER = """module probe_counts
  integer :: normal_calls=0
end module
program empty_patch_probe
  use geoclaw_module
  use amr_module
  use rheology_module
  use probe_counts
  implicit none
  integer,parameter :: nx=12,ny=10,ng=5,neq=3,na=3
  integer :: kind,model,relimit,order,capacity,i,j,calls_step,calls_probe,ref_calls
  real(kind=8) :: q(neq,1-ng:nx+ng,1-ng:ny+ng),a(na,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: qr(neq,1-ng:nx+ng,1-ng:ny+ng),ar(na,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: q0(neq,1-ng:nx+ng,1-ng:ny+ng),a0(na,1-ng:nx+ng,1-ng:ny+ng)
  real(kind=8) :: flux(neq,1-ng:nx+ng,1-ng:ny+ng,4),ref(neq,1-ng:nx+ng,1-ng:ny+ng,4)
  real(kind=8) :: cfl,cfl_ref,cfl_probe,cfl_probe_ref,flux_norm
  external counted_rpn,rpt2
  read(*,*) kind,model,relimit,order,capacity
  imodel_rh=model;rho_rh=rho;n_zones_rh=1
  allocate(mu_zones_rh(1),xi_zones_rh(1),C_zones_rh(1))
  mu_zones_rh=.4d0;xi_zones_rh=1000.d0;C_zones_rh=20.d0
  dx_avac=2.d0;dy_avac=3.d0;dt_avac=.01d0
  use_fwave_positivity_limiter=relimit==1
  method(2)=order;method(3)=2;mcapa=capacity
  q=0.d0;a=0.d0;a(2,:,:)=-1.d0;a(3,:,:)=1.d0
  do j=1-ng,ny+ng
    do i=1-ng,nx+ng
      a(1,i,j)=1000.d0-.3d0*i+.1d0*j+.001d0*i*j
      if(capacity>0) a(capacity,i,j)=1.d0+.001d0*(i*i+j*j)
    enddo
  enddo
  select case(kind)
  case(0) ! Exactly empty, including the ghosts.
  case(1) ! West ghost next to the dry interior.
    q(:,0,5)=[1.d0,.2d0,.1d0]
  case(2) ! East ghost.
    q(:,nx+1,5)=[1.d0,-.2d0,.1d0]
  case(3) ! South ghost.
    q(:,5,0)=[1.d0,.1d0,.2d0]
  case(4) ! North ghost.
    q(:,5,ny+1)=[1.d0,.1d0,-.2d0]
  case(5) ! Even the outermost corner ghost disables the shortcut.
    q(:,1-ng,1-ng)=[1.d0,.2d0,.1d0]
  case(6) ! A film below dry_tolerance is still a nonempty state.
    q(1,:,:)=.5d0*dry_tolerance
  case(7) ! Residual momentum at zero depth must not be discarded here.
    q(2,5,5)=1.d-8
  case(8) ! A wet interior and a surrounding dry front.
    q(:,5,5)=[1.d0,.2d0,.1d0]
  case default
    error stop 'Unknown empty-patch probe'
  end select
  q0=q;a0=a;qr=q;ar=a
  flux=42.d0;ref=42.d0;normal_calls=0;cfl=-1.d0;cfl_ref=-1.d0
  call step2(nx,neq,na,ng,nx,ny,q,a,2.d0,3.d0,.01d0,cfl, &
             flux(:,:,:,1),flux(:,:,:,2),flux(:,:,:,3),flux(:,:,:,4),counted_rpn,rpt2)
  calls_step=normal_calls;normal_calls=0
  call step2_reference(nx,neq,na,ng,nx,ny,qr,ar,2.d0,3.d0,.01d0,cfl_ref, &
             ref(:,:,:,1),ref(:,:,:,2),ref(:,:,:,3),ref(:,:,:,4),counted_rpn,rpt2)
  ref_calls=normal_calls
  if(any(flux/=ref).or.cfl/=cfl_ref) error stop 'Flux or CFL differs from the unshortened solver'
  if(any(q/=qr).or.any(q/=q0).or.any(a/=ar).or.any(a/=a0)) error stop 'Flux call altered its input'
  normal_calls=0;cfl_probe=-1.d0;cfl_probe_ref=-1.d0
  call step2_cfl(nx,neq,na,ng,nx,ny,q,a,2.d0,3.d0,.01d0,cfl_probe,counted_rpn)
  calls_probe=normal_calls;normal_calls=0
  call step2_cfl_reference(nx,neq,na,ng,nx,ny,qr,ar,2.d0,3.d0,.01d0,cfl_probe_ref,counted_rpn)
  if(cfl_probe/=cfl_probe_ref.or.cfl_probe/=cfl) error stop 'CFL probe differs'
  if(any(q/=q0).or.any(qr/=q0).or.any(a/=a0).or.any(ar/=a0)) error stop 'CFL call altered its input'
  if(ref_calls<=0.or.normal_calls<=0) error stop 'Reference did not execute normal Riemann sweeps'
  flux_norm=sum(abs(flux))
  write(*,'(2(es25.17,1x),3(i8,1x))') cfl,flux_norm,calls_step,calls_probe,ref_calls
end program
subroutine counted_rpn(ixy,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,al,ar,fw,s,am,ap)
  use probe_counts
  implicit none
  integer :: ixy,maxm,meqn,mwaves,maux,mbc,mx
  real(kind=8) :: ql(meqn,1-mbc:maxm+mbc),qr(meqn,1-mbc:maxm+mbc)
  real(kind=8) :: al(maux,1-mbc:maxm+mbc),ar(maux,1-mbc:maxm+mbc)
  real(kind=8) :: fw(meqn,mwaves,1-mbc:maxm+mbc),s(mwaves,1-mbc:maxm+mbc)
  real(kind=8) :: am(meqn,1-mbc:maxm+mbc),ap(meqn,1-mbc:maxm+mbc)
  normal_calls=normal_calls+1
  call rpn2(ixy,maxm,meqn,mwaves,maux,mbc,mx,ql,qr,al,ar,fw,s,am,ap)
end subroutine
"""


@pytest.fixture(scope="module", params=["avac", "wave"])
def empty_patch_probe(tmp_path_factory, request):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for empty-patch flux equivalence")
    build = tmp_path_factory.mktemp(f"empty_patch_flux_{request.param}")
    flux_source = (AVAC / "flux2fw.f" if request.param == "avac" else
                   CLAW / "geoclaw/src/2d/shallow/flux2fw.f")
    normal_source = (AVAC / "rpn2_geoclaw.f" if request.param == "avac" else
                     CLAW / "riemann/src/rpn2_geoclaw.f")
    modules = build / "modules.f90"
    modules.write_text(MODULES, encoding="utf-8")
    driver = build / "driver.f90"
    driver.write_text(DRIVER, encoding="utf-8")
    reference_step = build / "step2_reference.f90"
    step = STEP2.read_text(encoding="utf-8")
    guard = "    if (all(qold == 0.d0)) return\n"
    assert step.count(guard) == 1
    reference_step.write_text(
        re.sub(r"\bstep2\b", "step2_reference", step.replace(guard, "")), encoding="utf-8",
    )
    reference_probe = build / "step2_cfl_reference.f"
    flux = flux_source.read_text(encoding="utf-8")
    probe = flux[flux.index("      subroutine step2_cfl("):flux.index("      subroutine cfl_from_speeds(")]
    guard = "      if (all(qold .eq. 0.d0)) return\n"
    assert probe.count(guard) == 1
    reference_probe.write_text(
        re.sub(r"\bstep2_cfl\b", "step2_cfl_reference", probe.replace(guard, "")), encoding="utf-8",
    )
    executable = build / "probe.exe"
    sources = [
        modules, AVAC / "rheology_module.f90", normal_source,
        CLAW / "riemann/src/geoclaw_riemann_utils.f", CLAW / "riemann/src/rpt2_geoclaw.f",
        flux_source, CLAW / "amrclaw/src/2d/inlinelimiter.f",
        STEP2, reference_step, reference_probe, driver,
    ]
    result = subprocess.run(
        [compiler, "-O2", "-fopenmp", "-fcheck=all", "-ffixed-line-length-none",
         "-ffree-line-length-none", "-J", str(build), *map(str, sources), "-o", str(executable)],
        cwd=build, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    def run(kind, model, relimit, order, capacity=0):
        result = subprocess.run(
            [str(executable)], input=f"{kind} {model} {relimit} {order} {capacity}\n",
            cwd=build, capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        values = np.fromstring(result.stdout, sep=" ")
        assert values.size == 5, result.stdout
        assert np.isfinite(values).all()
        return values

    return run


@pytest.mark.parametrize("model,capacity", [(0, 0), (0, 2), (1, 0), (2, 0), (3, 0)])
@pytest.mark.parametrize("relimit,order", [(0, 1), (0, 2), (1, 1), (1, 2)])
def test_empty_patch_matches_full_flux_and_cfl_solver_without_riemann_calls(
    empty_patch_probe, model, capacity, relimit, order,
):
    cfl, flux_norm, step_calls, probe_calls, reference_calls = empty_patch_probe(
        0, model, relimit, order, capacity,
    )
    assert cfl == flux_norm == step_calls == probe_calls == 0
    assert reference_calls > 0


@pytest.mark.parametrize("kind", range(1, 9))
@pytest.mark.parametrize("relimit,order", [(0, 1), (0, 2), (1, 1), (1, 2)])
def test_nonempty_ghosts_films_and_momenta_retain_full_solver(empty_patch_probe, kind, relimit, order):
    cfl, flux_norm, step_calls, probe_calls, reference_calls = empty_patch_probe(kind, 2, relimit, order)
    assert step_calls == probe_calls == reference_calls
    assert step_calls > 0
    if kind in (1, 2, 3, 4, 8):
        assert cfl > 0
        assert flux_norm > 0
