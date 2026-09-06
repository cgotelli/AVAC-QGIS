"""Exact Riemann equivalence when moving interfaces skip static-yield work.

The reference removes only the early necessary-condition gate.  Both versions
use production augmented Riemann and rheology routines.  A counter inserted
into the test copy of the rheology module measures avoided source calls;
it does not replace any numerical operation.
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
GATE = (
    "     &       hL .gt. drytol .and. hR .gt. drytol .and.\n"
    "     &       spd_L .eq. 0.d0 .and. spd_R .eq. 0.d0) then\n"
)

DRIVER = """program static_yield_fast_probe
  use geoclaw_module
  use amr_module
  use rheology_module
  implicit none
  integer,parameter :: nx=14,ng=5,neq=3,na=3,face=7
  integer :: kind,model,direction,i,moving,fast_calls,reference_calls
  real(kind=8) :: dt,velocity,depth,face_norm
  real(kind=8) :: ql(neq,1-ng:nx+ng),qr(neq,1-ng:nx+ng)
  real(kind=8) :: al(na,1-ng:nx+ng),ar(na,1-ng:nx+ng)
  real(kind=8) :: qlr(neq,1-ng:nx+ng),qrr(neq,1-ng:nx+ng)
  real(kind=8) :: alr(na,1-ng:nx+ng),arr(na,1-ng:nx+ng)
  real(kind=8) :: fw(neq,3,1-ng:nx+ng),fwr(neq,3,1-ng:nx+ng)
  real(kind=8) :: s(3,1-ng:nx+ng),sr(3,1-ng:nx+ng)
  real(kind=8) :: am(neq,1-ng:nx+ng),ap(neq,1-ng:nx+ng)
  real(kind=8) :: amr(neq,1-ng:nx+ng),apr(neq,1-ng:nx+ng)
  read(*,*) kind,model,direction,dt
  imodel_rh=model;rho_rh=rho;n_zones_rh=2
  allocate(mu_zones_rh(2),xi_zones_rh(2),C_zones_rh(2),z_breaks_rh(1))
  mu_zones_rh=[.4d0,.5d0];xi_zones_rh=[1000.d0,500.d0]
  C_zones_rh=[20.d0,80.d0];z_breaks_rh=1000.5d0
  dx_avac=2.d0;dy_avac=3.d0;dt_avac=dt;mcapa=0
  ql=0.d0;qr=0.d0;al=0.d0;ar=0.d0
  al(2,:)=.25d0;al(3,:)=1.d0
  do i=1-ng,nx+ng
    ql(1,i)=2.d0+.03d0*i
    al(1,i)=1000.d0+.05d0*i+.001d0*i*i
  enddo
  select case(kind)
  case(0:3) ! Motion in each member LL,L,R,RR of the four-cell stencil.
    moving=face-2+kind
    ql(2,moving)=.3d0*ql(1,moving)
    ql(3,moving)=-.2d0*ql(1,moving)
  case(4) ! Every interface is moving.
    ql(2,:)=.3d0*ql(1,:);ql(3,:)=-.2d0*ql(1,:)
  case(5) ! Reversing velocity at successive wet interfaces.
    do i=1-ng,nx+ng
      velocity=.3d0;if(modulo(i,2)==0) velocity=-.3d0
      ql(2,i)=velocity*ql(1,i);ql(3,i)=-velocity*ql(1,i)
    enddo
  case(6) ! Opposing reconstructed LL/RR momenta average to exact rest.
    ql(2,face-2)=.3d0*ql(1,face-2)
    ql(3,face+1)=-.2d0*ql(1,face+1)
  case(7) ! Static, sub-yield, including cohesive/altitude-zone variants.
  case(8) ! Static, super-yield diagnostic must keep the dynamic solver.
    al(2,:)=1.5d0
  case(9) ! Stationary wet/dry edge.
    ql(:,face:)=0.d0
  case(10) ! Advancing wet/dry edge.
    ql(:,face:)=0.d0
    ql(2,:)=.3d0*ql(1,:);ql(3,:)=-.2d0*ql(1,:)
  case(11) ! Nonzero film below dry_tolerance.
    ql(1,:)=.5d0*dry_tolerance
  case(12) ! Nonzero momentum whose squared computed speed underflows.
    ql(2,:)=1.d-200*ql(1,:)
  case default
    error stop 'Unknown static-yield fast-path probe'
  end select
  qr=ql;ar=al
  if(kind==6) then
    qr(2,face-2)=-ql(2,face-2)
    qr(3,face+1)=-ql(3,face+1)
  endif
  qlr=ql;qrr=qr;alr=al;arr=ar
  friction_probe_calls=0
  call rpn2(direction,nx,neq,3,na,ng,nx,ql,qr,al,ar,fw,s,am,ap)
  fast_calls=friction_probe_calls;friction_probe_calls=0
  call rpn2_reference(direction,nx,neq,3,na,ng,nx,qlr,qrr,alr,arr,fwr,sr,amr,apr)
  reference_calls=friction_probe_calls
  if(any(fw/=fwr).or.any(s/=sr).or.any(am/=amr).or.any(ap/=apr)) &
    error stop 'Riemann result differs from the ungated production algorithm'
  if(any(ql/=qlr).or.any(qr/=qrr).or.any(al/=alr).or.any(ar/=arr)) &
    error stop 'Riemann input mutation differs'
  face_norm=sum(abs(fw(:,:,face)))
  write(*,'(es25.17,1x,2(i8,1x))') face_norm,fast_calls,reference_calls
end program
"""


@pytest.fixture(scope="module")
def static_yield_probe(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required for static-yield gate equivalence")
    build = tmp_path_factory.mktemp("static_yield_fast_path")
    modules = build / "modules.f90"
    modules.write_text(MODULES, encoding="utf-8")
    rheology = build / "rheology_module.f90"
    source = (AVAC / "rheology_module.f90").read_text(encoding="utf-8")
    source = re.sub(r"(?im)^\s*contains\s*$", "    integer :: friction_probe_calls=0\ncontains", source, count=1)
    begin = source.index("    function friction_speed_after(")
    end = source.index("    end function friction_speed_after", begin)
    body = source[begin:end]
    statement = "        if (speed <= 0.d0 .or. dt <= 0.d0 .or. h <= 0.d0) then"
    assert body.count(statement) == 1
    body = body.replace(statement, "        friction_probe_calls=friction_probe_calls+1\n" + statement)
    rheology.write_text(source[:begin] + body + source[end:], encoding="utf-8")
    reference = build / "rpn2_reference.f"
    source = (AVAC / "rpn2_geoclaw.f").read_text(encoding="utf-8")
    assert source.count(GATE) == 1
    source = source.replace(GATE, "     &       hL .gt. drytol .and. hR .gt. drytol) then\n")
    reference.write_text(re.sub(r"\brpn2\b", "rpn2_reference", source), encoding="utf-8")
    driver = build / "driver.f90"
    driver.write_text(DRIVER, encoding="utf-8")
    executable = build / "probe.exe"
    result = subprocess.run(
        [compiler, "-O2", "-fopenmp", "-fcheck=all", "-ffixed-line-length-none",
         "-ffree-line-length-none", "-J", str(build), str(modules), str(rheology),
         str(AVAC / "rpn2_geoclaw.f"), str(reference),
         str(CLAW / "riemann/src/geoclaw_riemann_utils.f"), str(driver), "-o", str(executable)],
        cwd=build, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    def run(kind, model, direction, dt):
        result = subprocess.run(
            [str(executable)], input=f"{kind} {model} {direction} {dt}\n",
            cwd=build, capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        values = np.fromstring(result.stdout, sep=" ")
        assert values.size == 3 and np.isfinite(values).all(), result.stdout
        return values

    return run


@pytest.mark.parametrize("kind", range(13))
@pytest.mark.parametrize("model", [1, 2, 3])
@pytest.mark.parametrize("direction", [1, 2])
def test_static_yield_gate_matches_production_for_every_stencil_state(static_yield_probe, kind, model, direction):
    face_norm, fast_calls, reference_calls = static_yield_probe(kind, model, direction, .01)
    assert fast_calls <= reference_calls
    if kind in (4, 5):
        assert fast_calls == 0 < reference_calls
    if kind in (0, 1, 2, 3, 4, 5, 8, 10):
        assert face_norm > 0
    if kind in (7, 12):
        assert face_norm == 0
        assert fast_calls == reference_calls > 0


@pytest.mark.parametrize("dt", [0., 1.e-12, 1., 1000.])
@pytest.mark.parametrize("kind", [4, 5, 7, 12])
def test_gate_retains_exact_rest_independently_of_predicted_stopping_time(static_yield_probe, kind, dt):
    _, fast_calls, reference_calls = static_yield_probe(kind, 2, 1, dt)
    if kind in (4, 5):
        assert fast_calls == 0 < reference_calls
    else:
        assert fast_calls == reference_calls > 0
