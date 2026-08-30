from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from avac_qgis.core.configuration import controlled_values, load_complete_configuration
from avac_qgis.core.rheology import altitude_zone_ids


ROOT = Path(__file__).resolve().parents[2]


def test_fortran_coulomb_yield_and_moving_source_use_consistent_geometry():
    """Static yield stays tan(theta)=mu while moving flow is slope-corrected."""
    src2 = (ROOT / "avac-main" / "src" / "AVAC" / "src2.f90").read_text(encoding="utf-8")
    rheology = (ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90").read_text(encoding="utf-8")
    setrun = (ROOT / "avac-main" / "src" / "AVAC" / "setrun.py").read_text(encoding="utf-8")

    assert "tau_driving_rho = g * h * dtan(theta_local)" in src2
    assert "cartesian_speed_after" in src2
    assert "subroutine cartesian_source_coefficients" in rheology
    assert "sin2_phi * tan_psi + mu * cos_phi * cos_psi" in rheology
    assert "grav / (xi * h * cos_phi * cos_psi)" in rheology
    assert "mu*cos(theta)*dx" not in setrun

    mu, gravity, depth = 0.37, 9.81, 1.4
    critical_slope = np.arctan(mu)
    driving = gravity * depth * np.tan(critical_slope)
    resistance = mu * gravity * depth
    assert driving == pytest.approx(resistance)


def test_cartesian_voellmy_plane_matches_the_physical_terminal_speed(tmp_path):
    """Compile the actual Fortran source and test a 30-degree planar flow."""
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the AVAC source-level rheology test")

    source = ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90"
    driver = tmp_path / "driver.f90"
    driver.write_text(
        """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: theta, h_normal, h_vertical, mu, xi, grav
  real(kind=8) :: v_terminal, u_horizontal, a, b, cp, cs, ts
  theta = 30.d0 * acos(-1.d0) / 180.d0
  h_normal = 1.d0
  h_vertical = h_normal / cos(theta)
  mu = 0.2d0
  xi = 1000.d0
  grav = 9.81d0
  v_terminal = sqrt(xi*h_normal*(sin(theta)-mu*cos(theta)))
  u_horizontal = v_terminal*cos(theta)
  call cartesian_source_coefficients(h_vertical,u_horizontal,0.d0, &
       -tan(theta),0.d0,mu,xi,0.d0,300.d0,grav,2,a,b,cp,cs,ts)
  write(*,'(6(es24.16,1x))') a,b,cp,cs,ts,u_horizontal
end program driver
""".strip() + "\n",
        encoding="utf-8",
    )
    executable = tmp_path / "driver"
    subprocess.run(
        [compiler, "-O0", "-J", str(tmp_path), str(source), str(driver), "-o", str(executable)],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    values = np.fromstring(subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True
    ).stdout, sep=" ")
    a, b, cos_phi, cos_psi, tan_psi, horizontal_terminal = values

    # GeoClaw supplies g*tan(theta); the added source is -a-b*u^2.
    assert 9.81 * np.tan(np.deg2rad(30.0)) - a - b * horizontal_terminal**2 == pytest.approx(0.0, abs=1e-12)
    assert cos_phi == pytest.approx(np.cos(np.deg2rad(30.0)))
    assert cos_psi == pytest.approx(np.cos(np.deg2rad(30.0)))
    assert tan_psi == pytest.approx(np.tan(np.deg2rad(30.0)))


def test_avac_wet_dry_velocity_regularization_is_exact_then_damps():
    """The AVAC-only Kurganov--Petrova treatment preserves resolved flow."""
    source_dir = ROOT / "avac-main" / "src" / "AVAC"
    rheology = (source_dir / "rheology_module.f90").read_text(encoding="utf-8")
    src2 = (source_dir / "src2.f90").read_text(encoding="utf-8")
    b4step2 = (source_dir / "b4step2.f90").read_text(encoding="utf-8")
    rpn2 = (source_dir / "rpn2_geoclaw.f").read_text(encoding="utf-8")
    makefile = (source_dir / "Makefile").read_text(encoding="utf-8")
    wave_makefile = (ROOT / "avac-main" / "src" / "Wave" / "Makefile").read_text(encoding="utf-8")
    step2 = (
        ROOT
        / "avac-main"
        / "clawpack-v5.14.0"
        / "geoclaw"
        / "src"
        / "2d"
        / "shallow"
        / "step2.f90"
    ).read_text(encoding="utf-8")

    assert "subroutine regularized_velocity" in rheology
    assert "0.02d0 * min(dx, dy)" in src2
    assert "call regularized_velocity" in src2
    assert "call regularized_velocity" in b4step2
    assert "call regularized_velocity" in rpn2
    assert "FFLAGS += -DAVAC_POSITIVITY_RELIMITER" in makefile
    assert "FFLAGS += -cpp" in wave_makefile
    assert "AVAC_POSITIVITY_RELIMITER" not in wave_makefile
    assert "#ifdef AVAC_POSITIVITY_RELIMITER" in step2
    assert "logical, parameter :: relimit = .true." in step2
    assert (source_dir / "fgmax_values.f90").is_file()

    def velocity(depth: float, momentum: float, cutoff: float) -> float:
        denominator = np.sqrt(depth**4 + max(depth**4, cutoff**4))
        return np.sqrt(2.0) * depth * momentum / denominator

    momentum = 7.5
    cutoff = 0.05
    assert velocity(cutoff, momentum, cutoff) == pytest.approx(momentum / cutoff)
    assert velocity(0.50, momentum, cutoff) == pytest.approx(momentum / 0.50)
    assert abs(velocity(0.001, momentum, cutoff)) < abs(momentum / 0.001) * 1.0e-3


def test_altitude_zone_ids_match_solver_lower_bound_convention():
    elevations = np.array([[np.nan, 1500.0, 1680.0], [1680.1, 1900.0, 2500.0]])

    result = altitude_zone_ids(elevations, [1680.0, 1900.0])

    assert result.dtype == np.uint16
    assert np.array_equal(result, np.array([[0, 1, 2], [2, 3, 3]], dtype=np.uint16))


def test_altitude_zone_ids_rejects_nonascending_thresholds():
    with pytest.raises(ValueError, match="strictly ascending"):
        altitude_zone_ids(np.array([[1200.0]]), [1700.0, 1700.0])


def test_lac_lachat_two_zone_configuration_classifies_high_terrain():
    """The published two-zone case must retain its >= 1680 m upper zone."""
    from pathlib import Path

    config = Path(__file__).resolve().parents[2] / "avac-main" / "src" / "AVAC" / "AVAC_configuration300.yaml"
    values = controlled_values(load_complete_configuration(config))

    assert values["rheology.z_breaks"] == [1680]
    assert np.array_equal(
        altitude_zone_ids(np.array([[1679.99, 1680.0, 2200.0]]), values["rheology.z_breaks"]),
        np.array([[1, 2, 2]], dtype=np.uint16),
    )
