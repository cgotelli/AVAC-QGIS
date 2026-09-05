#!/usr/bin/env python3
"""Expose the changing-basis limitation on a terrain-following circular track.

This is a diagnostic verification, not an alternative AVAC constitutive law.
It compares a material point written in terrain-following coordinates with the
reduced Cartesian projection used by AVAC's local source.  Both descriptions
must agree exactly on flat and constant-slope beds.  On a curved bed the
reduced description deliberately omits the changing-basis acceleration; the
resulting difference is recorded rather than silently treated as a reference
solution for production.

The state integrated here is the squared terrain-tangent speed ``w = v_s^2``
as a function of bed arc length.  Pressure gradients and thickness evolution
are excluded so that the coordinate effect is isolated.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Callable, NamedTuple

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]

sys.path.insert(0, str(REPOSITORY / "validation"))
from avac4qgis_validation.plot_style import (  # noqa: E402
    PAPER_COLORS,
    apply_paper_style,
    figure_size,
)


GRAVITY_M_S2 = 9.81
COULOMB_MU = 0.4
TRACK_RADIUS_M = 400.0
ENTRY_SLOPE_DEG = 34.0
ENTRY_SPEED_M_S = 102.4
ZERO_FORCE_SPEED_M_S = 80.0
INTEGRATION_STEPS = 4000
OUTPUT_SAMPLES = 401


class TrackCase(NamedTuple):
    name: str
    title: str
    length_m: float
    entry_slope_rad: float
    curvature_per_m: float
    gravity_m_s2: float
    coulomb_mu: float
    entry_speed_m_s: float
    control: bool


class TrackHistory(NamedTuple):
    arc_length_m: np.ndarray
    horizontal_x_m: np.ndarray
    elevation_change_m: np.ndarray
    slope_rad: np.ndarray
    time_s: np.ndarray
    surface_speed_m_s: np.ndarray
    horizontal_speed_m_s: np.ndarray
    omitted_basis_acceleration_m_s2: np.ndarray


def slope_angle(case: TrackCase, arc_length_m: float | np.ndarray) -> float | np.ndarray:
    """Return the positive downslope angle along the track."""
    return case.entry_slope_rad - case.curvature_per_m * np.asarray(arc_length_m)


def terrain_following_dw_ds(case: TrackCase, arc_length_m: float, speed_squared: float) -> float:
    """Return ``d(v_s^2)/ds`` for a Coulomb point constrained to the bed."""
    theta = float(slope_angle(case, arc_length_m))
    return (
        2.0 * case.gravity_m_s2 * (np.sin(theta) - case.coulomb_mu * np.cos(theta))
        - 2.0 * case.coulomb_mu * case.curvature_per_m * speed_squared
    )


def reduced_cartesian_dw_ds(case: TrackCase, arc_length_m: float, speed_squared: float) -> float:
    """Return the surface-speed equation implied by AVAC's reduced map state.

    AVAC evolves horizontal velocity.  Without changing-basis transport, its
    reconstructed terrain-tangent speed contains the additional term
    ``-kappa * v_s^2 * tan(theta)`` in ``dv_s/dt``.
    """
    theta = float(slope_angle(case, arc_length_m))
    return terrain_following_dw_ds(case, arc_length_m, speed_squared) - (
        2.0 * case.curvature_per_m * speed_squared * np.tan(theta)
    )


def _rk4_step(
    rhs: Callable[[TrackCase, float, float], float],
    case: TrackCase,
    arc_length_m: float,
    speed_squared: float,
    step_m: float,
) -> float:
    k1 = rhs(case, arc_length_m, speed_squared)
    k2 = rhs(case, arc_length_m + 0.5 * step_m, speed_squared + 0.5 * step_m * k1)
    k3 = rhs(case, arc_length_m + 0.5 * step_m, speed_squared + 0.5 * step_m * k2)
    k4 = rhs(case, arc_length_m + step_m, speed_squared + step_m * k3)
    return speed_squared + step_m * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0


def integrate_track(case: TrackCase, formulation: str) -> TrackHistory:
    """Integrate one point through a plane or circular transition."""
    if formulation == "terrain_following":
        rhs = terrain_following_dw_ds
    elif formulation == "reduced_cartesian":
        rhs = reduced_cartesian_dw_ds
    else:
        raise ValueError(f"unknown formulation: {formulation}")

    arc_length = np.linspace(0.0, case.length_m, INTEGRATION_STEPS + 1)
    step_m = float(arc_length[1] - arc_length[0])
    speed_squared = np.empty_like(arc_length)
    speed_squared[0] = case.entry_speed_m_s**2
    for index in range(INTEGRATION_STEPS):
        next_value = _rk4_step(
            rhs, case, float(arc_length[index]), float(speed_squared[index]), step_m
        )
        if not np.isfinite(next_value) or next_value <= 0.0:
            raise RuntimeError(
                f"{case.name}/{formulation} stopped before the end of the verification track"
            )
        speed_squared[index + 1] = next_value

    theta = np.asarray(slope_angle(case, arc_length), dtype=float)
    surface_speed = np.sqrt(speed_squared)
    horizontal_speed = surface_speed * np.cos(theta)

    if case.curvature_per_m == 0.0:
        horizontal_x = arc_length * np.cos(case.entry_slope_rad)
        elevation_change = -arc_length * np.sin(case.entry_slope_rad)
    else:
        inverse_curvature = 1.0 / case.curvature_per_m
        horizontal_x = inverse_curvature * (
            np.sin(case.entry_slope_rad) - np.sin(theta)
        )
        elevation_change = inverse_curvature * (
            np.cos(case.entry_slope_rad) - np.cos(theta)
        )

    inverse_speed = 1.0 / surface_speed
    time_s = np.zeros_like(arc_length)
    time_s[1:] = np.cumsum(
        0.5 * step_m * (inverse_speed[:-1] + inverse_speed[1:])
    )
    omitted_basis = case.curvature_per_m * speed_squared * np.sin(theta)
    return TrackHistory(
        arc_length,
        horizontal_x,
        elevation_change,
        theta,
        time_s,
        surface_speed,
        horizontal_speed,
        omitted_basis,
    )


def verification_cases() -> tuple[TrackCase, ...]:
    theta = np.deg2rad(ENTRY_SLOPE_DEG)
    circular_length = TRACK_RADIUS_M * theta
    return (
        TrackCase(
            "flat_coulomb",
            "Flat Coulomb control",
            20.0,
            0.0,
            0.0,
            GRAVITY_M_S2,
            COULOMB_MU,
            30.0,
            True,
        ),
        TrackCase(
            "constant_slope_coulomb",
            "34-degree Coulomb control",
            200.0,
            theta,
            0.0,
            GRAVITY_M_S2,
            COULOMB_MU,
            30.0,
            True,
        ),
        TrackCase(
            "circular_zero_force",
            "Circular changing-basis control",
            circular_length,
            theta,
            1.0 / TRACK_RADIUS_M,
            0.0,
            0.0,
            ZERO_FORCE_SPEED_M_S,
            False,
        ),
        TrackCase(
            "circular_coulomb",
            "Circular Coulomb track",
            circular_length,
            theta,
            1.0 / TRACK_RADIUS_M,
            GRAVITY_M_S2,
            COULOMB_MU,
            ENTRY_SPEED_M_S,
            False,
        ),
    )


def run_verification() -> tuple[
    dict[tuple[str, str], TrackHistory], list[dict[str, float | str | bool]]
]:
    histories: dict[tuple[str, str], TrackHistory] = {}
    summaries: list[dict[str, float | str | bool]] = []
    for case in verification_cases():
        terrain = integrate_track(case, "terrain_following")
        reduced = integrate_track(case, "reduced_cartesian")
        histories[(case.name, "terrain_following")] = terrain
        histories[(case.name, "reduced_cartesian")] = reduced
        difference = terrain.surface_speed_m_s - reduced.surface_speed_m_s
        summaries.append(
            {
                "case": case.name,
                "control": case.control,
                "track_length_m": case.length_m,
                "entry_slope_degrees": np.rad2deg(case.entry_slope_rad),
                "exit_slope_degrees": np.rad2deg(terrain.slope_rad[-1]),
                "curvature_per_m": case.curvature_per_m,
                "terrain_following_exit_speed_m_s": terrain.surface_speed_m_s[-1],
                "reduced_cartesian_exit_speed_m_s": reduced.surface_speed_m_s[-1],
                "exit_speed_difference_m_s": difference[-1],
                "maximum_speed_difference_m_s": float(np.max(np.abs(difference))),
                "terrain_following_travel_time_s": terrain.time_s[-1],
                "reduced_cartesian_travel_time_s": reduced.time_s[-1],
                "maximum_omitted_basis_acceleration_m_s2": float(
                    np.max(terrain.omitted_basis_acceleration_m_s2)
                ),
            }
        )

        if case.control:
            if not np.array_equal(
                terrain.surface_speed_m_s, reduced.surface_speed_m_s
            ):
                raise RuntimeError(
                    f"flat/constant-slope control changed for {case.name}"
                )

    zero_force = next(row for row in summaries if row["case"] == "circular_zero_force")
    expected_reduced_exit = ZERO_FORCE_SPEED_M_S * np.cos(np.deg2rad(ENTRY_SLOPE_DEG))
    if not np.isclose(
        float(zero_force["terrain_following_exit_speed_m_s"]),
        ZERO_FORCE_SPEED_M_S,
        rtol=0.0,
        atol=2.0e-11,
    ):
        raise RuntimeError("terrain-following zero-force speed is not invariant")
    if not np.isclose(
        float(zero_force["reduced_cartesian_exit_speed_m_s"]),
        expected_reduced_exit,
        rtol=0.0,
        atol=2.0e-9,
    ):
        raise RuntimeError("reduced zero-force result differs from its closed solution")
    if float(zero_force["exit_speed_difference_m_s"]) <= 0.0:
        raise RuntimeError("circular track did not expose the changing-basis speed loss")
    return histories, summaries


def write_history(
    path: Path, histories: dict[tuple[str, str], TrackHistory]
) -> None:
    fields = (
        "case",
        "formulation",
        "arc_length_m",
        "horizontal_x_m",
        "elevation_change_m",
        "slope_degrees",
        "time_s",
        "surface_speed_m_s",
        "horizontal_speed_m_s",
        "omitted_basis_acceleration_m_s2",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for (case, formulation), history in histories.items():
            output_indices = np.linspace(
                0, history.arc_length_m.size - 1, OUTPUT_SAMPLES, dtype=int
            )
            for index in output_indices:
                writer.writerow(
                    {
                        "case": case,
                        "formulation": formulation,
                        "arc_length_m": f"{history.arc_length_m[index]:.12g}",
                        "horizontal_x_m": f"{history.horizontal_x_m[index]:.12g}",
                        "elevation_change_m": f"{history.elevation_change_m[index]:.12g}",
                        "slope_degrees": f"{np.rad2deg(history.slope_rad[index]):.12g}",
                        "time_s": f"{history.time_s[index]:.12g}",
                        "surface_speed_m_s": f"{history.surface_speed_m_s[index]:.12g}",
                        "horizontal_speed_m_s": f"{history.horizontal_speed_m_s[index]:.12g}",
                        "omitted_basis_acceleration_m_s2": (
                            f"{history.omitted_basis_acceleration_m_s2[index]:.12g}"
                        ),
                    }
                )


def plot_histories(
    path: Path, histories: dict[tuple[str, str], TrackHistory]
) -> None:
    apply_paper_style()
    figure, axes = plt.subplots(2, 2, figsize=figure_size(2, aspect=0.70))
    for axis, case in zip(axes.flat, verification_cases(), strict=True):
        terrain = histories[(case.name, "terrain_following")]
        reduced = histories[(case.name, "reduced_cartesian")]
        axis.plot(
            terrain.horizontal_x_m,
            terrain.surface_speed_m_s,
            color=PAPER_COLORS["green"],
            label="terrain-following",
        )
        axis.plot(
            reduced.horizontal_x_m,
            reduced.surface_speed_m_s,
            color=PAPER_COLORS["orange"],
            linestyle="--",
            label="reduced Cartesian",
        )
        axis.set_title(case.title, loc="left")
        axis.set_xlabel("Horizontal distance (m)")
        axis.set_ylabel(r"Surface speed (m s$^{-1}$)")
        axis.set_ylim(bottom=0.0)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=2)
    figure.subplots_adjust(bottom=0.15, hspace=0.42, wspace=0.30)
    figure.savefig(path, dpi=300)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=HERE)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    results = output_root / "results"
    figures = output_root / "figures"
    results.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    histories, summaries = run_verification()
    write_history(results / "circular_track_history.csv", histories)
    summary = {
        "method": (
            "terrain-following Coulomb point dynamics compared with AVAC's "
            "reduced horizontal-velocity projection"
        ),
        "scope": (
            "diagnostic only; isolates curved-coordinate transport and does not "
            "replace the production depth-integrated equations"
        ),
        "gravity_m_s2": GRAVITY_M_S2,
        "coulomb_mu": COULOMB_MU,
        "circular_track_radius_m": TRACK_RADIUS_M,
        "integration_steps": INTEGRATION_STEPS,
        "output_samples_per_formulation": OUTPUT_SAMPLES,
        "cases": summaries,
    }
    (results / "circular_track_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    plot_histories(figures / "circular_track_coordinate_verification.png", histories)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
