from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from avac_qgis.core.configuration import controlled_values, load_complete_configuration
from avac_qgis.core.rheology import altitude_zone_ids


ROOT = Path(__file__).resolve().parents[2]


def _compile_rheology_driver(tmp_path: Path, program: str) -> np.ndarray:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the AVAC source-level rheology test")
    source = ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90"
    driver = tmp_path / "driver.f90"
    driver.write_text(program.strip() + "\n", encoding="utf-8")
    executable = tmp_path / "driver"
    subprocess.run(
        [compiler, "-O0", "-J", str(tmp_path), str(source), str(driver), "-o", str(executable)],
        check=True, cwd=tmp_path, capture_output=True, text=True,
    )
    return np.fromstring(subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True,
    ).stdout, sep=" ")


def test_cartesian_source_is_exactly_the_existing_flat_bed_law(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: old_c, new_c, old_v, new_v, speed
  speed = 5.d0
  old_c = friction_speed_after(speed,0.03d0,1.4d0,0.37d0,1200.d0,0.d0,300.d0,9.81d0,1)
  new_c = cartesian_speed_after(speed,0.03d0,1.4d0,3.d0,4.d0,0.d0,0.d0, &
       0.d0,0.d0,0.d0,0.37d0,1200.d0,0.d0,300.d0,9.81d0,1)
  old_v = friction_speed_after(speed,0.03d0,1.4d0,0.37d0,1200.d0,0.d0,300.d0,9.81d0,2)
  new_v = cartesian_speed_after(speed,0.03d0,1.4d0,3.d0,4.d0,0.d0,0.d0, &
       0.d0,0.d0,0.d0,0.37d0,1200.d0,0.d0,300.d0,9.81d0,2)
  write(*,'(4(es24.16,1x))') old_c,new_c,old_v,new_v
end program driver
""")
    assert values[1] == values[0]
    assert values[3] == values[2]


def test_cartesian_voellmy_plane_matches_physical_terminal_speed(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: theta,h_normal,h_vertical,mu,xi,grav
  real(kind=8) :: v_terminal,u_horizontal,a,b,cp,cs,ts,curvature
  theta = 30.d0 * acos(-1.d0) / 180.d0
  h_normal = 1.d0
  h_vertical = h_normal / cos(theta)
  mu = 0.2d0
  xi = 1000.d0
  grav = 9.81d0
  v_terminal = sqrt(xi*h_normal*(sin(theta)-mu*cos(theta)))
  u_horizontal = v_terminal*cos(theta)
  call cartesian_source_coefficients(h_vertical,u_horizontal,0.d0, &
       -tan(theta),0.d0,0.d0,0.d0,0.d0,mu,xi,0.d0,300.d0,grav,2, &
       a,b,cp,cs,ts,curvature)
  write(*,'(7(es24.16,1x))') a,b,cp,cs,ts,curvature,u_horizontal
end program driver
""")
    a, b, cos_phi, cos_psi, tan_psi, curvature, horizontal_terminal = values
    theta = np.deg2rad(30.0)
    assert 9.81 * np.tan(theta) - a - b * horizontal_terminal**2 == pytest.approx(0.0, abs=1e-12)
    assert cos_phi == pytest.approx(np.cos(theta))
    assert cos_psi == pytest.approx(np.cos(theta))
    assert tan_psi == pytest.approx(np.tan(theta))
    assert curvature == 0.0


def test_curved_coordinate_transport_preserves_tangent_speed_locally(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: slope, speed, curvature, a, b, cp, cs, ts, kv
  slope = -tan(30.d0*acos(-1.d0)/180.d0)
  speed = 8.d0*cos(30.d0*acos(-1.d0)/180.d0)
  curvature = 1.d0/40.d0
  call cartesian_source_coefficients(1.d0,speed,0.d0,slope,0.d0, &
       curvature,0.d0,0.d0,0.d0,0.d0,0.d0,300.d0,0.d0,1, &
       a,b,cp,cs,ts,kv)
  write(*,'(7(es24.16,1x))') a,b,cp,cs,ts,kv,speed
end program driver
""")
    a, b, cos_phi, cos_psi, tan_psi, curvature, speed = values
    expected_acceleration = curvature * tan_psi * cos_psi**2 * speed**2
    assert a == 0.0
    assert -b * speed**2 == pytest.approx(expected_acceleration, abs=1e-13)
    assert cos_phi == pytest.approx(np.cos(np.deg2rad(30.0)))
    assert cos_psi == pytest.approx(np.cos(np.deg2rad(30.0)))


def test_shallow_velocity_regularization_is_exact_when_resolved(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: u1,v1,u2,v2
  call regularized_velocity(0.10d0,0.30d0,0.40d0,0.10d0,u1,v1)
  call regularized_velocity(0.05d0,0.15d0,0.20d0,0.10d0,u2,v2)
  write(*,'(4(es24.16,1x))') u1,v1,u2,v2
end program driver
""")
    assert values[0] == pytest.approx(3.0, abs=1e-15)
    assert values[1] == pytest.approx(4.0, abs=1e-15)
    assert np.hypot(values[2], values[3]) < 5.0
    assert values[2] / values[3] == pytest.approx(0.75)


def test_nonplanar_gate_rejects_flat_and_constant_slope_beds(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  logical :: flat, plane, curved
  flat = locally_nonplanar_bed(5.d0,5.d0,5.d0,5.d0,5.d0, &
                               5.d0,5.d0,5.d0,5.d0)
  plane = locally_nonplanar_bed(10.d0,8.d0,12.d0,7.d0,13.d0, &
                                5.d0,9.d0,11.d0,15.d0)
  curved = locally_nonplanar_bed(10.d0,8.d0,13.d0,7.d0,13.d0, &
                                 5.d0,10.d0,11.d0,16.d0)
  write(*,'(3(i2,1x))') merge(1,0,flat),merge(1,0,plane),merge(1,0,curved)
end program driver
""")
    assert np.array_equal(values.astype(int), [0, 0, 1])


def test_nonplanar_gate_ignores_submillimetric_topography_noise(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  logical :: noisy_plane, resolved_curve
  noisy_plane = locally_nonplanar_bed(2000.d0,1999.d0,2001.0005d0, &
                                      1998.d0,2002.d0,1997.d0, &
                                      1999.0005d0,2001.d0,2003.0005d0)
  resolved_curve = locally_nonplanar_bed(2000.d0,1999.d0,2001.01d0, &
                                         1998.d0,2002.d0,1997.d0, &
                                         1999.01d0,2001.d0,2003.01d0)
  write(*,'(2(i2,1x))') merge(1,0,noisy_plane),merge(1,0,resolved_curve)
end program driver
""")
    assert np.array_equal(values.astype(int), [0, 1])


def test_fortran_source_uses_one_general_steep_slope_formulation():
    source = (ROOT / "avac-main" / "src" / "AVAC" / "src2.f90").read_text(encoding="utf-8")
    rheology = (ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90").read_text(encoding="utf-8")
    assert "cartesian_speed_after" in source
    assert "tau_driving_rho = g * h * dtan(theta_local)" in source
    assert "sin2_phi * tan_psi + mu * cos_phi * cos_psi" in rheology
    assert "grav / (xi * h * cos_phi * cos_psi)" in rheology
    assert "mu * curvature * cos_phi * cos_psi" in rheology
    assert "curvature * tan_psi * cos_psi**2" in rheology
    assert "d2zdx2" in source
    assert "locally_nonplanar_bed" in source
    assert "regularized_velocity" in source


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
