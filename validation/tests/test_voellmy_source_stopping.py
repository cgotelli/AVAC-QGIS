"""The actual Voellmy source must retain its exact stopping/drag impulse.

Only parameter modules are stubbed; production rheology and src2 are compiled.
These are source-only controls, not evidence about a producing native timestep.
The explicit source override supports red/green audits against frozen runtimes.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("AVAC_VOELLMY_SOURCE_TEST_DIR", ROOT / "avac-main/src/AVAC"))


@pytest.fixture(scope="module")
def source_update(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the compiled Voellmy source controls")
    build = tmp_path_factory.mktemp("voellmy_source")
    modules = build / "modules.f90"
    modules.write_text(
        """module geoclaw_module
  implicit none
  real(kind=8) :: grav=9.81d0,dry_tolerance=1.d-4,speed_limit=1.d99
  logical :: friction_forcing=.true.
  real(kind=8) :: friction_depth=1.d6
  integer :: num_manning=1
  real(kind=8) :: manning_coefficient(1)=0.03d0,manning_break(1)=1.d9
end module
module amr_module
  implicit none
  real(kind=8) :: xlower=0.d0,xupper=5.d0,ylower=0.d0,yupper=5.d0
  logical :: xperdom=.false.,yperdom=.false.
end module
""", encoding="utf-8")
    driver = build / "driver.f90"
    driver.write_text(
        """program source_driver
  use geoclaw_module
  use rheology_module
  implicit none
  integer,parameter :: meqn=3,maux=3,mbc=2,mx=5,my=5
  real(kind=8) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
  real(kind=8) :: h,u,v,bx,by,dt_total,dt,cohesion,datum,x,y
  real(kind=8) :: speed,exact_speed,a,b,cp,cs,ts,curv,mu,xi,c
  integer :: model,steps,step,i,j
  read(*,*) model,h,u,v,bx,by,dt_total,steps,cohesion,datum
  imodel_rh=model
  rho_rh=300.d0
  n_zones_rh=2
  allocate(z_breaks_rh(1),mu_zones_rh(2),xi_zones_rh(2),C_zones_rh(2))
  z_breaks_rh=[500.d0]
  mu_zones_rh=[.2d0,.25d0]
  xi_zones_rh=[2000.d0,1000.d0]
  C_zones_rh=[cohesion,2.d0*cohesion]
  state_momentum_regularization_depth_rh=.05d0
  voellmy_state_momentum_regularization_depth_rh=.1d0
  aux=0.d0
  do j=1-mbc,my+mbc
    do i=1-mbc,mx+mbc
      x=real(i-3,8)
      y=real(j-3,8)
      aux(1,i,j)=datum+bx*x+by*y
      q(:,i,j)=[h,h*u,h*v]
    enddo
  enddo
  call get_mu_xi(aux(1,3,3),mu,xi,c)
  speed=sqrt(u*u+v*v)
  call cartesian_source_coefficients(h,u,v,bx,by,0.d0,0.d0,0.d0,mu,xi,c,rho_rh, &
    grav,model,a,b,cp,cs,ts,curv)
  exact_speed=cartesian_speed_after(speed,dt_total,h,u,v,bx,by,0.d0,0.d0,0.d0, &
    mu,xi,c,rho_rh,grav,model)
  dt=dt_total/real(steps,8)
  do step=1,steps
    call src2(meqn,mbc,mx,my,0.d0,0.d0,1.d0,1.d0,q,maux,aux,real(step-1,8)*dt,dt)
  enddo
  write(*,'(9(es26.18,1x))') q(:,3,3),exact_speed,a,b,mu,xi,c
end program
""", encoding="utf-8")
    executable = build / "source_driver.exe"
    subprocess.run(
        [compiler, "-O0", "-fcheck=all", "-J", str(build), str(modules),
         str(SOURCE / "rheology_module.f90"), str(SOURCE / "src2.f90"),
         str(driver), "-o", str(executable)],
        cwd=build, check=True, capture_output=True, text=True, timeout=60)

    def run(*, model=2, h=.00011349974374752492, u=.1, v=0., bx=-.3,
            by=0., dt=.1, steps=1, cohesion=0., datum=0.):
        values = (model, h, u, v, bx, by, dt, steps, cohesion, datum)
        process = subprocess.run(
            [str(executable)], input=" ".join(map(str, values)) + "\n",
            cwd=build, check=True, capture_output=True, text=True, timeout=15)
        data = np.fromstring(process.stdout, sep=" ")
        assert data.shape == (9,), process.stdout
        return {"q": data[:3], "helper_speed": data[3], "a": data[4],
                "b": data[5], "mu": data[6], "xi": data[7], "cohesion": data[8]}

    return run


@pytest.mark.parametrize("model", [2, 3])
@pytest.mark.parametrize("datum", [0., 1000.])
def test_superyield_exact_stop_keeps_voellmy_impulse(source_update, model, datum):
    result = source_update(model=model, datum=datum, cohesion=1.e-5)
    assert result["helper_speed"] == 0.
    assert result["q"][0] == .00011349974374752492
    np.testing.assert_array_equal(result["q"][1:], [0., 0.])
    assert result["mu"] == (.2 if datum == 0. else .25)
    assert result["xi"] == (2000. if datum == 0. else 1000.)


@pytest.mark.parametrize("model", [2, 3])
@pytest.mark.parametrize("h", [np.nextafter(1.e-4, np.inf), .0001055, .00011349974374752492])
def test_stiff_thin_layer_cannot_restore_large_incoming_momentum(source_update, model, h):
    result = source_update(model=model, h=h, u=72671.8769, dt=.3, cohesion=1.e-5)
    assert result["b"] > 0.
    assert result["helper_speed"] == 0.
    np.testing.assert_array_equal(result["q"], [h, 0., 0.])


@pytest.mark.parametrize("steps", [2, 10, 100, 1000])
def test_affine_frozen_source_stop_is_subdivision_consistent(source_update, steps):
    one = source_update()
    divided = source_update(steps=steps)
    assert one["helper_speed"] == divided["helper_speed"] == 0.
    np.testing.assert_array_equal(one["q"][1:], [0., 0.])
    np.testing.assert_array_equal(divided["q"], one["q"])


@pytest.mark.parametrize("model", [2, 3])
def test_nonstopping_frozen_source_matches_helper_and_subdivision(source_update, model):
    options = dict(model=model, h=.7, u=4., v=3., bx=-.3, by=-.1, dt=.1, cohesion=10.)
    one = source_update(**options)
    divided = source_update(**options, steps=100)
    expected = .7 * np.array([1., 4.*one["helper_speed"]/5., 3.*one["helper_speed"]/5.])
    np.testing.assert_allclose(one["q"], expected, rtol=3.e-13, atol=1.e-14)
    np.testing.assert_allclose(divided["q"], one["q"], rtol=3.e-12, atol=1.e-14)


def test_uphill_cartesian_correction_remains_positive(source_update):
    result = source_update(h=1., u=.1, bx=2., dt=.01)
    assert result["a"] < 0.
    assert result["helper_speed"] > .1
    assert result["q"][1] == pytest.approx(result["helper_speed"], rel=1.e-13)


@pytest.mark.parametrize("model", [0, 1, 2, 3])
def test_zero_duration_leaves_wet_momentum_unchanged(source_update, model):
    result = source_update(model=model, h=.4, u=3., v=-2., bx=-.3, dt=0., cohesion=10.)
    np.testing.assert_array_equal(result["q"], [.4, .4*3., .4*-2.])


def test_legacy_coulomb_superyield_path_is_unchanged(source_update):
    # Deliberate scoped preservation, not approval of its inherited fallback.
    result = source_update(model=1, h=.1, u=.1, dt=.1)
    assert result["helper_speed"] == 0.
    np.testing.assert_array_equal(result["q"], [.1, .1*.1, 0.])


def test_horizontal_coulomb_uses_existing_exact_friction(source_update):
    result = source_update(model=1, h=.4, u=2., bx=0., dt=.1)
    np.testing.assert_allclose(result["q"], [.4, .4*(2.-.2*9.81*.1), 0.], rtol=1.e-14)


def test_water_uses_existing_manning_update(source_update):
    h, speed, dt, manning = .4, 2., .1, .03
    result = source_update(model=0, h=h, u=speed, bx=0., dt=dt)
    expected = h*speed/(1.+dt*9.81*manning**2*speed/h**(4./3.))
    np.testing.assert_allclose(result["q"], [h, expected, 0.], rtol=1.e-14)
