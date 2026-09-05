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


def test_curved_frozen_source_does_not_create_coordinate_acceleration(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  integer :: step
  real(kind=8) :: slope, speed, curvature, a, b, cp, cs, ts, kv
  real(kind=8) :: direct_speed, repeated_speed
  slope = -tan(30.d0*acos(-1.d0)/180.d0)
  speed = 8.d0*cos(30.d0*acos(-1.d0)/180.d0)
  curvature = 1.d0/40.d0
  call cartesian_source_coefficients(1.d0,speed,0.d0,slope,0.d0, &
       curvature,0.d0,0.d0,0.d0,0.d0,0.d0,300.d0,0.d0,1, &
       a,b,cp,cs,ts,kv)
  direct_speed = cartesian_speed_after(speed,20.d0,1.d0,speed,0.d0, &
       slope,0.d0,curvature,0.d0,0.d0,0.d0,0.d0,0.d0,300.d0,0.d0,1)
  repeated_speed = speed
  do step = 1, 20
    repeated_speed = cartesian_speed_after(repeated_speed,1.d0,1.d0, &
         repeated_speed,0.d0,slope,0.d0,curvature,0.d0,0.d0, &
         0.d0,0.d0,0.d0,300.d0,0.d0,1)
  end do
  write(*,*) a,b,direct_speed,repeated_speed,speed
end program driver
""")
    assert values.size == 5
    a, b, direct_speed, repeated_speed, speed = values
    assert a == 0.0
    assert b == 0.0
    assert np.all(np.isfinite(values))
    assert direct_speed == pytest.approx(speed, abs=1e-12)
    assert repeated_speed == pytest.approx(speed, abs=1e-12)


def test_circular_track_projection_locks_planes_and_exposes_basis_gap(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8), parameter :: grav=9.81d0, mu=0.4d0, radius=400.d0
  real(kind=8), parameter :: surface_speed=80.d0
  real(kind=8) :: theta, horizontal_speed, bed_slope, bed_hessian
  real(kind=8) :: a, b, cp, cs, ts, kv
  real(kind=8) :: flat_acceleration, plane_acceleration, curve_acceleration

  call cartesian_source_coefficients(1.d0,surface_speed,0.d0, &
       0.d0,0.d0,0.d0,0.d0,0.d0,mu,0.d0,0.d0,300.d0,grav,1, &
       a,b,cp,cs,ts,kv)
  flat_acceleration = -a - b*surface_speed**2

  theta = 34.d0*acos(-1.d0)/180.d0
  horizontal_speed = surface_speed*cos(theta)
  bed_slope = -tan(theta)
  call cartesian_source_coefficients(1.d0,horizontal_speed,0.d0, &
       bed_slope,0.d0,0.d0,0.d0,0.d0,mu,0.d0,0.d0,300.d0,grav,1, &
       a,b,cp,cs,ts,kv)
  plane_acceleration = grav*tan(theta) - a - b*horizontal_speed**2

  ! For a circle, geometric curvature kappa and the graph Hessian satisfy
  ! kappa = B_xx*cos(theta)^3.  AVAC projects the tangential force onto
  ! horizontal velocity but deliberately omits changing-basis transport.
  bed_hessian = (1.d0/radius)/cos(theta)**3
  call cartesian_source_coefficients(1.d0,horizontal_speed,0.d0, &
       bed_slope,0.d0,bed_hessian,0.d0,0.d0,mu,0.d0,0.d0, &
       300.d0,grav,1,a,b,cp,cs,ts,kv)
  curve_acceleration = grav*tan(theta) - a - b*horizontal_speed**2
  write(*,'(6(es24.16,1x))') flat_acceleration,plane_acceleration, &
       curve_acceleration,cp,cs,kv
end program driver
""")
    flat, plane, curved_reduced, cos_phi, cos_psi, graph_curvature = values
    gravity = 9.81
    mu = 0.4
    radius = 400.0
    surface_speed = 80.0
    theta = np.deg2rad(34.0)
    geometric_curvature = 1.0 / radius

    flat_reference = -mu * gravity
    plane_reference = np.cos(theta) * gravity * (
        np.sin(theta) - mu * np.cos(theta)
    )
    curved_tangential = gravity * np.sin(theta) - mu * (
        gravity * np.cos(theta) + geometric_curvature * surface_speed**2
    )
    curved_reduced_reference = np.cos(theta) * curved_tangential
    changing_basis_acceleration = (
        geometric_curvature * surface_speed**2 * np.sin(theta)
    )
    curved_terrain_following_reference = (
        curved_reduced_reference + changing_basis_acceleration
    )

    # Flat and constant-slope Coulomb dynamics are exact controls: their
    # coordinate basis does not rotate, so no curved-coordinate term exists.
    assert flat == pytest.approx(flat_reference, abs=2.0e-14)
    assert plane == pytest.approx(plane_reference, abs=2.0e-14)
    assert cos_phi == pytest.approx(np.cos(theta), abs=2.0e-14)
    assert cos_psi == pytest.approx(np.cos(theta), abs=2.0e-14)
    assert graph_curvature == pytest.approx(
        geometric_curvature / np.cos(theta) ** 3, abs=2.0e-14
    )

    # This assertion documents, rather than repairs, the production model:
    # its curved result is the projected tangential force.  A material point
    # following the circle also receives the positive changing-basis term.
    assert curved_reduced == pytest.approx(
        curved_reduced_reference, abs=2.0e-13
    )
    assert curved_terrain_following_reference - curved_reduced == pytest.approx(
        changing_basis_acceleration, abs=2.0e-13
    )
    assert changing_basis_acceleration > 8.0


def test_convex_contact_transition_never_returns_a_pole_velocity(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: theta, speed, speed_new, contact_speed
  theta = 60.d0*acos(-1.d0)/180.d0
  speed = 8.d0
  contact_speed = sqrt(9.81d0/(1.d0/40.d0))
  speed_new = cartesian_speed_after(speed,20.d0,1.d0,speed,0.d0, &
       tan(theta),0.d0,-1.d0/40.d0,0.d0,0.d0,0.3d0,0.d0,0.d0, &
       300.d0,9.81d0,1)
  write(*,*) speed_new,contact_speed
end program driver
""")
    assert values.size == 2
    speed_new, contact_speed = values
    assert np.isfinite(speed_new)
    assert contact_speed < speed_new < 1.0e3


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


def test_state_regularization_depth_is_independent_and_physical() -> None:
    avac = ROOT / "avac-main" / "src" / "AVAC"
    module = (avac / "rheology_module.f90").read_text(encoding="utf-8")
    source = (avac / "src2.f90").read_text(encoding="utf-8")
    setrun = (avac / "setrun.py").read_text(encoding="utf-8")
    setprob = (avac / "setprob.f90").read_text(encoding="utf-8")

    assert "state_momentum_regularization_depth_rh = 0.05d0" in module
    assert "state_momentum_regularization_depth_rh)" in source
    regularization_block = source[source.index("if (patch_nonplanar) then") :]
    assert "velocity_depth_threshold_rh" not in regularization_block
    assert "0.02d0*min(dx,dy)" not in regularization_block
    assert "if (imodel_rh == 1) then" in source
    assert "ii = max(2, min(mx-1, i))" in source
    assert "jj = max(2, min(my-1, j))" in source
    assert "locally_nonplanar_bed(aux(1,ii,jj)" in source
    assert "state_momentum_regularization_depth" in setrun
    assert "read(7,*) state_momentum_regularization_depth" in setprob


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


def test_nonplanar_gate_is_datum_safe_and_detects_gentle_curvature(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  logical :: plane0, plane2k, plane1e8
  logical :: curve0, curve2k, curve1e8
  logical :: quadratic5, quadratic2p5, quadratic1p25

  plane0 = locally_nonplanar_bed(0.d0,-2.d0,2.d0,-3.d0,3.d0, &
                                 -5.d0,-1.d0,1.d0,5.d0)
  plane2k = locally_nonplanar_bed(2000.d0,1998.d0,2002.d0, &
                                  1997.d0,2003.d0,1995.d0, &
                                  1999.d0,2001.d0,2005.d0)
  plane1e8 = locally_nonplanar_bed(1.d8,1.d8-2.d0,1.d8+2.d0, &
                                   1.d8-3.d0,1.d8+3.d0,1.d8-5.d0, &
                                   1.d8-1.d0,1.d8+1.d0,1.d8+5.d0)

  curve0 = locally_nonplanar_bed(0.d0,-2.d0,2.0001d0,-3.d0,3.d0, &
                                 -5.d0,-0.9999d0,1.d0,5.0001d0)
  curve2k = locally_nonplanar_bed(2000.d0,1998.d0,2002.0001d0, &
                                  1997.d0,2003.d0,1995.d0, &
                                  1999.0001d0,2001.d0,2005.0001d0)
  curve1e8 = locally_nonplanar_bed(1.d8,1.d8-2.d0,1.d8+2.0001d0, &
                                   1.d8-3.d0,1.d8+3.d0,1.d8-5.d0, &
                                   1.d8-0.9999d0,1.d8+1.d0, &
                                   1.d8+5.0001d0)

  ! The same quadratic curvature sampled at successively finer spacings
  ! remains non-affine; the residual naturally scales with dx**2.
  quadratic5 = locally_nonplanar_bed(0.d0,0.00125d0,0.00125d0, &
                                     0.d0,0.d0,0.00125d0, &
                                     0.00125d0,0.00125d0,0.00125d0)
  quadratic2p5 = locally_nonplanar_bed(0.d0,0.0003125d0, &
                                       0.0003125d0,0.d0,0.d0, &
                                       0.0003125d0,0.0003125d0, &
                                       0.0003125d0,0.0003125d0)
  quadratic1p25 = locally_nonplanar_bed(0.d0,0.000078125d0, &
                                        0.000078125d0,0.d0,0.d0, &
                                        0.000078125d0,0.000078125d0, &
                                        0.000078125d0,0.000078125d0)
  write(*,'(9(i2,1x))') merge(1,0,plane0),merge(1,0,plane2k), &
       merge(1,0,plane1e8),merge(1,0,curve0),merge(1,0,curve2k), &
       merge(1,0,curve1e8),merge(1,0,quadratic5), &
       merge(1,0,quadratic2p5),merge(1,0,quadratic1p25)
end program driver
""")
    assert np.array_equal(values.astype(int), [0, 0, 0, 1, 1, 1, 1, 1, 1])


def test_static_yield_ratio_uses_the_full_free_surface_gradient(tmp_path: Path):
    values = _compile_rheology_driver(tmp_path, """
program driver
  use rheology_module
  implicit none
  real(kind=8) :: diagonal_super, diagonal_sub, axial_sub
  diagonal_super = static_yield_ratio_2d(10.d0, -0.4d0, 0.4d0, -0.4d0, 0.4d0, &
       0.d0, 0.d0, 0.d0, 0.d0, 1.d0, 1.d0, 0.5d0, 0.d0, 300.d0, 9.81d0, 1)
  diagonal_sub = static_yield_ratio_2d(10.d0, -0.3d0, 0.3d0, -0.3d0, 0.3d0, &
       0.d0, 0.d0, 0.d0, 0.d0, 1.d0, 1.d0, 0.5d0, 0.d0, 300.d0, 9.81d0, 1)
  axial_sub = static_yield_ratio_2d(10.d0, -0.49d0, 0.49d0, 0.d0, 0.d0, &
       0.d0, 0.d0, 0.d0, 0.d0, 1.d0, 1.d0, 0.5d0, 0.d0, 300.d0, 9.81d0, 1)
  write(*,*) diagonal_super, diagonal_sub, axial_sub
end program driver
""")
    diagonal_super, diagonal_sub, axial_sub = values
    assert diagonal_super == pytest.approx(np.hypot(0.4, 0.4) / 0.5)
    assert diagonal_super > 1.0
    assert diagonal_sub == pytest.approx(np.hypot(0.3, 0.3) / 0.5)
    assert diagonal_sub < 1.0
    # A real axial sub-yield state must still be eligible: this prevents a
    # superficially similar but incorrect mu/sqrt(2) directional threshold.
    assert axial_sub == pytest.approx(0.49 / 0.5)
    assert axial_sub < 1.0


def test_fortran_source_uses_one_general_steep_slope_formulation():
    source = (ROOT / "avac-main" / "src" / "AVAC" / "src2.f90").read_text(encoding="utf-8")
    rheology = (ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90").read_text(encoding="utf-8")
    assert "cartesian_speed_after" in source
    assert "tau_driving_rho = g * h * dtan(theta_local)" in source
    assert "sin2_phi * tan_psi + mu * cos_phi * cos_psi" in rheology
    assert "grav / (xi * h * cos_phi * cos_psi)" in rheology
    assert "mu * curvature * cos_phi * cos_psi" in rheology
    assert "- curvature * tan_psi * cos_psi**2" not in rheology
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
