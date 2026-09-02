#!/usr/bin/env python3
"""Verify AVAC's curvature source terms in planar, concave, and convex limits.

The actual Fortran ``rheology_module`` is compiled and called for a material
element at the nadir of a planar, concave-circular, or convex-circular track.
At that point the bed slope is zero and the directional bed curvature is
constant, so the local Coulomb source has a closed analytical solution. A
second controlled suite uses a 30-degree tangent and zero applied force to
verify that the frozen cell-local source does not convert changing terrain
orientation into artificial map-plane acceleration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]

import sys

sys.path.insert(0, str(REPOSITORY / "validation"))
from avac4qgis_validation.plot_style import (  # noqa: E402
    PAPER_COLORS,
    apply_paper_style,
    figure_size,
)


GRAVITY = 9.81
MU = 0.30
RADIUS_M = 40.0
INITIAL_SPEED_M_S = 8.0
FINAL_TIME_S = 4.0
SUBSTEP_TEST_TIME_S = 2.0
TIMES_S = np.linspace(0.0, FINAL_TIME_S, 41)
CASES = (
    (0, "Planar", 0.0, PAPER_COLORS["orange"]),
    (1, "Concave circular", 1.0 / RADIUS_M, PAPER_COLORS["green"]),
    (2, "Convex circular", -1.0 / RADIUS_M, PAPER_COLORS["blue"]),
)
FROZEN_GEOMETRY_SLOPE_DEG = 30.0
FROZEN_GEOMETRY_INITIAL_MAP_SPEED_M_S = INITIAL_SPEED_M_S * np.cos(
    np.deg2rad(FROZEN_GEOMETRY_SLOPE_DEG)
)


def analytical_speed(time_s: np.ndarray, curvature: float) -> np.ndarray:
    """Closed solution of ds/dt = -mu (g + curvature*s^2)."""
    time_s = np.asarray(time_s, dtype=float)
    if curvature == 0.0:
        return np.maximum(0.0, INITIAL_SPEED_M_S - MU * GRAVITY * time_s)
    scale = np.sqrt(GRAVITY / abs(curvature))
    rate = MU * np.sqrt(GRAVITY * abs(curvature))
    if curvature > 0.0:
        phase = np.arctan(INITIAL_SPEED_M_S / scale) - rate * time_s
        return np.where(phase > 0.0, scale * np.tan(phase), 0.0)
    phase = np.arctanh(INITIAL_SPEED_M_S / scale) - rate * time_s
    return np.where(phase > 0.0, scale * np.tanh(phase), 0.0)


def frozen_cell_map_speed(time_s: np.ndarray) -> np.ndarray:
    """Zero-force solution of the frozen cell-local source."""
    time_s = np.asarray(time_s, dtype=float)
    return np.full_like(time_s, FROZEN_GEOMETRY_INITIAL_MAP_SPEED_M_S)


def compile_and_run() -> tuple[np.ndarray, np.ndarray, dict[tuple[int, int], float]]:
    compiler = shutil.which("gfortran")
    if compiler is None:
        raise RuntimeError("gfortran is required for curvature verification")
    rheology = REPOSITORY / "avac-main" / "src" / "AVAC" / "rheology_module.f90"
    driver_source = f"""
program curvature_validation
  use rheology_module
  implicit none
  integer :: case_id, sample, substep
  real(kind=8) :: curvature, time_s, speed, substep_speed
  real(kind=8), parameter :: grav={GRAVITY:.17g}d0, mu={MU:.17g}d0
  real(kind=8), parameter :: radius={RADIUS_M:.17g}d0
  real(kind=8), parameter :: initial_speed={INITIAL_SPEED_M_S:.17g}d0
  real(kind=8), parameter :: final_time={FINAL_TIME_S:.17g}d0
  real(kind=8), parameter :: substep_time={SUBSTEP_TEST_TIME_S:.17g}d0
  do case_id = 0, 2
    if (case_id == 0) then
      curvature = 0.d0
    else if (case_id == 1) then
      curvature = 1.d0/radius
    else
      curvature = -1.d0/radius
    end if
    do sample = 0, 40
      time_s = final_time*dble(sample)/40.d0
      speed = cartesian_speed_after(initial_speed,time_s,1.d0, &
           initial_speed,0.d0,0.d0,0.d0,curvature,0.d0,0.d0, &
           mu,0.d0,0.d0,300.d0,grav,1)
      write(*,'(i2,1x,2(es24.16,1x))') case_id,time_s,speed
    end do
    speed = cartesian_speed_after(initial_speed,substep_time,1.d0, &
         initial_speed,0.d0,0.d0,0.d0,curvature,0.d0,0.d0, &
         mu,0.d0,0.d0,300.d0,grav,1)
    substep_speed = initial_speed
    do substep = 1, 8
      substep_speed = cartesian_speed_after(substep_speed,substep_time/8.d0, &
           1.d0,substep_speed,0.d0,0.d0,0.d0,curvature,0.d0,0.d0, &
           mu,0.d0,0.d0,300.d0,grav,1)
    end do
    write(*,'(i2,1x,2(es24.16,1x))') case_id,-1.d0,speed
    write(*,'(i2,1x,2(es24.16,1x))') case_id,-2.d0,substep_speed
  end do
  do case_id = 0, 2
    if (case_id == 0) then
      curvature = 0.d0
    else if (case_id == 1) then
      curvature = 1.d0/radius
    else
      curvature = -1.d0/radius
    end if
    do sample = 0, 40
      time_s = final_time*dble(sample)/40.d0
      speed = cartesian_speed_after(initial_speed*cos(30.d0*acos(-1.d0)/180.d0), &
           time_s,1.d0,initial_speed*cos(30.d0*acos(-1.d0)/180.d0),0.d0, &
           -tan(30.d0*acos(-1.d0)/180.d0),0.d0,curvature,0.d0,0.d0, &
           0.d0,0.d0,0.d0,300.d0,0.d0,1)
      write(*,'(i2,1x,2(es24.16,1x))') case_id+10,time_s,speed
    end do
  end do
end program curvature_validation
""".strip() + "\n"

    with tempfile.TemporaryDirectory(prefix="avac_curvature_") as temporary:
        temporary_path = Path(temporary)
        driver = temporary_path / "driver.f90"
        driver.write_text(driver_source, encoding="utf-8")
        executable = temporary_path / "curvature_validation"
        subprocess.run(
            [compiler, "-O2", "-J", str(temporary_path), str(rheology), str(driver), "-o", str(executable)],
            check=True,
            cwd=temporary_path,
            capture_output=True,
            text=True,
        )
        output = subprocess.run([str(executable)], check=True, capture_output=True, text=True).stdout

    rows = np.loadtxt(output.splitlines())
    histories = rows[(rows[:, 1] >= 0.0) & (rows[:, 0] < 10)]
    frozen_geometry_histories = rows[(rows[:, 1] >= 0.0) & (rows[:, 0] >= 10)]
    source_steps = {
        (int(row[0]), int(-row[1])): float(row[2])
        for row in rows[rows[:, 1] < 0.0]
    }
    return histories, frozen_geometry_histories, source_steps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=HERE)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    results = output_root / "results"
    figures = output_root / "figures"
    results.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    histories, frozen_geometry_histories, source_steps = compile_and_run()
    summary_rows: list[dict[str, float | str]] = []
    frozen_geometry_rows: list[dict[str, float | str]] = []

    apply_paper_style()
    figure, axes = plt.subplots(2, 1, figsize=figure_size(1, aspect=1.30), sharex=True)
    axis = axes[0]
    for case_id, name, curvature, color in CASES:
        selected = histories[histories[:, 0] == case_id]
        analytical = analytical_speed(selected[:, 1], curvature)
        error = np.abs(selected[:, 2] - analytical)
        one_step = source_steps[(case_id, 1)]
        eight_substeps = source_steps[(case_id, 2)]
        summary_rows.append(
            {
                "case": name,
                "directional_curvature_per_m": curvature,
                "initial_normal_acceleration_m_s2": GRAVITY + curvature * INITIAL_SPEED_M_S**2,
                "maximum_absolute_speed_error_m_s": float(np.max(error)),
                "substep_test_time_s": SUBSTEP_TEST_TIME_S,
                "one_step_speed_m_s": one_step,
                "eight_substep_speed_m_s": eight_substeps,
                "substep_difference_m_s": abs(one_step - eight_substeps),
            }
        )
        axis.plot(selected[:, 1], analytical, color=color, label=f"{name}: analytical")
        axis.scatter(
            selected[::4, 1], selected[::4, 2], color=color, facecolors="white",
            linewidths=0.8, s=23, label=f"{name}: AVAC source", zorder=3,
        )

    axis.set(ylabel=r"Map speed (m s$^{-1}$)", xlim=(0.0, FINAL_TIME_S))
    axis.set_ylim(bottom=0.0)
    frozen_geometry_axis = axes[1]
    for case_id, name, curvature, color in CASES:
        selected = frozen_geometry_histories[frozen_geometry_histories[:, 0] == case_id + 10]
        analytical = frozen_cell_map_speed(selected[:, 1])
        error = np.abs(selected[:, 2] - analytical)
        frozen_geometry_rows.append(
            {
                "case": name,
                "directional_curvature_per_m": curvature,
                "slope_degrees": FROZEN_GEOMETRY_SLOPE_DEG,
                "initial_map_speed_m_s": FROZEN_GEOMETRY_INITIAL_MAP_SPEED_M_S,
                "maximum_absolute_speed_error_m_s": float(np.max(error)),
            }
        )
        frozen_geometry_axis.plot(selected[:, 1], analytical, color=color, label=f"{name}: frozen-source solution")
        frozen_geometry_axis.scatter(
            selected[::4, 1], selected[::4, 2], color=color, facecolors="white",
            linewidths=0.8, s=23, label=f"{name}: AVAC source", zorder=3,
        )
    frozen_geometry_axis.set(
        xlabel="Time (s)", ylabel=r"Map speed (m s$^{-1}$)", xlim=(0.0, FINAL_TIME_S)
    )
    frozen_geometry_axis.set_ylim(bottom=0.0)
    axis.set_title("(a) Curvature-dependent Coulomb normal stress", loc="left")
    frozen_geometry_axis.set_title("(b) Frozen-cell geometry safeguard", loc="left")
    handles, labels = axis.get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=2)
    figure.subplots_adjust(bottom=0.22, hspace=0.34)
    figure.savefig(figures / "curvature_source_verification.png", dpi=300)
    plt.close(figure)

    np.savetxt(
        results / "speed_history.csv",
        histories,
        delimiter=",",
        header="case_id,time_s,avac_speed_m_s",
        comments="",
    )
    np.savetxt(
        results / "frozen_cell_geometry_speed_history.csv",
        frozen_geometry_histories,
        delimiter=",",
        header="case_id,time_s,avac_speed_m_s",
        comments="",
    )
    summary = {
        "method": "compiled AVAC rheology_module compared with closed local Coulomb solutions and a zero-force frozen-cell safeguard",
        "gravity_m_s2": GRAVITY,
        "coulomb_mu": MU,
        "track_radius_m": RADIUS_M,
        "initial_speed_m_s": INITIAL_SPEED_M_S,
        "contact_condition": "g + directional_curvature * speed^2 >= 0",
        "normal_stress_cases": summary_rows,
        "frozen_cell_geometry_cases": frozen_geometry_rows,
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if max(float(row["maximum_absolute_speed_error_m_s"]) for row in summary_rows) > 2.0e-12:
        raise RuntimeError("curvature source differs from its analytical controlled solution")
    if max(float(row["substep_difference_m_s"]) for row in summary_rows) > 2.0e-12:
        raise RuntimeError("curvature source is not invariant to controlled source substepping")
    if max(float(row["maximum_absolute_speed_error_m_s"]) for row in frozen_geometry_rows) > 2.0e-12:
        raise RuntimeError("frozen-cell curvature safeguard differs from its zero-force solution")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
