"""Compiled checks of finite, energy-preserving terrain-basis transport.

These exercise the production Fortran helper rather than a Python duplicate.
The differential test independently checks the constrained-particle equation;
the finite tests check the physical invariants needed at curved transitions.
"""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
RHEOLOGY = ROOT / "avac-main" / "src" / "AVAC" / "rheology_module.f90"


@pytest.fixture(scope="module")
def transport(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the compiled terrain-transport checks")
    build = tmp_path_factory.mktemp("terrain_transport")
    driver = build / "driver.f90"
    executable = build / "transport.exe"
    driver.write_text(
        """program transport_driver
  use rheology_module, only: terrain_tangent_transport
  implicit none
  real(kind=8) :: u, v, bx0, by0, bx1, by1, un, vn
  integer :: io
  do
    read(*,*,iostat=io) u, v, bx0, by0, bx1, by1
    if (io /= 0) exit
    call terrain_tangent_transport(u,v,bx0,by0,bx1,by1,un,vn)
    write(*,'(2(es25.17,1x))') un,vn
  end do
end program transport_driver
""",
        encoding="utf-8",
    )
    subprocess.run(
        [compiler, "-O2", "-fcheck=all", "-J", str(build), str(RHEOLOGY),
         str(driver), "-o", str(executable)],
        cwd=build,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    def run(velocity, departure, arrival):
        values = [*velocity, *departure, *arrival]
        completed = subprocess.run(
            [str(executable)],
            input=" ".join(format(float(value), ".17g") for value in values) + "\n",
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return np.fromstring(completed.stdout, sep=" ")

    return run


def tangent_energy(velocity, slope):
    velocity = np.asarray(velocity)
    return float(velocity @ velocity + (velocity @ slope) ** 2)


@pytest.mark.parametrize("slope", [(0.0, 0.0), (-0.6745, 0.0), (1.2, -0.7)])
def test_affine_bed_is_exact_identity(transport, slope):
    velocity = np.array([18.3, -7.1])
    assert np.array_equal(transport(velocity, slope, slope), velocity)


def test_zero_velocity_remains_exactly_zero(transport):
    assert np.array_equal(transport([0.0, 0.0], [0.8, -0.3], [-0.4, 0.9]), [0.0, 0.0])


@pytest.mark.parametrize(
    "velocity,departure,arrival",
    [([31.0, -8.0], [-0.7, 0.1], [-0.2, 0.8]),
     ([-12.0, 19.0], [1.7, -2.2], [-0.9, 1.4]),
     ([0.0, 6.0], [2.0, 0.0], [-3.0, 0.0])],
)
def test_finite_rotation_preserves_tangent_energy(transport, velocity, departure, arrival):
    result = transport(velocity, departure, arrival)
    assert tangent_energy(result, arrival) == pytest.approx(
        tangent_energy(velocity, departure), rel=3.0e-14
    )


def test_circular_transition_matches_changing_horizontal_projection(transport):
    speed = 80.0
    angles = np.deg2rad([34.0, 27.0, 19.0, 6.0, 0.0])
    result = np.array([speed * math.cos(angles[0]), 0.0])
    for departure, arrival in zip(angles[:-1], angles[1:]):
        result = transport(result, [-math.tan(departure), 0.0], [-math.tan(arrival), 0.0])
        assert result == pytest.approx([speed * math.cos(arrival), 0.0], abs=8.0e-14)


def test_reverse_transport_recovers_velocity(transport):
    velocity = np.array([31.0, -8.0])
    departure, arrival = [-0.7, 0.1], [-0.2, 0.8]
    result = transport(velocity, departure, arrival)
    recovered = transport(result, arrival, departure)
    assert recovered == pytest.approx(velocity, abs=8.0e-14)


def test_horizontal_rotation_covariance(transport):
    angle = math.radians(57.0)
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    velocity = np.array([31.0, -8.0])
    departure, arrival = np.array([-0.7, 0.1]), np.array([-0.2, 0.8])
    result = transport(velocity, departure, arrival)
    rotated = transport(rotation @ velocity, rotation @ departure, rotation @ arrival)
    assert rotated == pytest.approx(rotation @ result, abs=8.0e-14)


def test_small_displacement_matches_full_geodesic_acceleration(transport):
    velocity = np.array([31.0, -8.0])
    slope = np.array([-0.7, 0.1])
    hessian = np.array([[0.004, -0.001], [-0.001, -0.002]])
    expected = -slope * (velocity @ hessian @ velocity) / (1.0 + slope @ slope)
    errors = []
    for dt in [0.001, 0.0005, 0.00025]:
        departure = slope - dt * hessian @ velocity
        result = transport(velocity, departure, slope)
        errors.append(np.linalg.norm((result - velocity) / dt - expected))
    # First-order departure geometry must converge to the complete vector
    # connection, including the component normal to horizontal flow direction.
    assert errors[1] < 0.51 * errors[0]
    assert errors[2] < 0.51 * errors[1]
    assert errors[2] < 8.0e-5


def test_nearly_opposed_normals_have_no_rational_pole(transport):
    slope = 1.0e9
    velocity = [1.0e-9, 3.0]
    result = transport(velocity, [slope, 0.0], [-slope, 0.0])
    assert np.all(np.isfinite(result))
    assert result == pytest.approx([1.0e-9, 3.0], rel=3.0e-14, abs=1.0e-22)
    assert tangent_energy(result, [-slope, 0.0]) == pytest.approx(
        tangent_energy(velocity, [slope, 0.0]), rel=3.0e-14
    )
