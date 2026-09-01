#!/usr/bin/env python3
"""Verify AVAC static Coulomb and cohesive arrest at the yield boundary.

Eight short planar-bed runs exercise the production executable.  Four
physical states are mirrored so downhill is alternately in the positive and
negative x direction.  This separates a constitutive yield decision from a
left/right numerical bias and avoids using a full avalanche as a unit test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from avac4qgis_validation.plot_style import PAPER_COLORS, apply_paper_style, figure_size
from avac4qgis_validation.runtime import (
    CLAWPACK_SOURCE,
    _activate_packaged_clawpack,
    _replace_data_value,
    prepare_avac_coulomb_case,
    run_solver,
    solver_executable,
    working_directory,
)


HERE = Path(__file__).resolve().parent
GRAVITY = 9.81
RHO = 300.0
DEPTH = 1.0
MU = 0.20
DX = 0.10
XLOWER, XUPPER = -4.0, 4.0
YLOWER, YUPPER = 0.0, 2.0
T_FINAL = 0.10
NOUT = 4
INTERIOR_MARGIN = 1.0
TRANSVERSE_INTERIOR_MARGIN = 0.5
REST_TOLERANCE_M_S = 2.0e-11
MOTION_TOLERANCE_M_S = 1.0e-3
MIRROR_RELATIVE_TOLERANCE = 5.0e-3
TRANSVERSE_RELATIVE_TOLERANCE = 2.0e-2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def output_format(work: Path, frame: int) -> str:
    tokens = (work / f"fort.t{frame:04d}").read_text(encoding="utf-8").split()
    for token in tokens:
        if token.lower() in {"binary32", "binary64"}:
            return token.lower()
    raise RuntimeError(f"Could not determine output precision for frame {frame}")


def final_state(work: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with working_directory(work):
        _activate_packaged_clawpack(CLAWPACK_SOURCE)
        from clawpack.pyclaw.solution import Solution

        solution = Solution(NOUT, path=work, file_format=output_format(work, NOUT))
    if len(solution.states) != 1:
        raise RuntimeError("The focused arrest test requires one uniform-grid patch")
    state = solution.states[0]
    q = np.asarray(state.q, dtype=float)
    nx, ny = q.shape[1:]
    x = state.patch.lower_global[0] + (np.arange(nx) + 0.5) * state.patch.delta[0]
    y = state.patch.lower_global[1] + (np.arange(ny) + 0.5) * state.patch.delta[1]
    return x, y, q[0], q[1:3]


def yield_gradient(slope: float, cohesion: float) -> float:
    """Static |grad(eta)| limit for AVAC's vertical-depth convention."""
    cos2 = 1.0 / (1.0 + slope**2)
    return MU + cohesion / (RHO * GRAVITY * DEPTH * cos2)


def cases() -> list[dict[str, float | str | bool]]:
    cohesive_slope = 0.30
    cos2 = 1.0 / (1.0 + cohesive_slope**2)
    critical_cohesion = RHO * GRAVITY * DEPTH * cos2 * (cohesive_slope - MU)
    return [
        {"name": "Coulomb sub-yield", "model": "Coulomb", "slope": 0.18,
         "cohesion": 0.0, "should_move": False},
        {"name": "Coulomb super-yield", "model": "Coulomb", "slope": 0.22,
         "cohesion": 0.0, "should_move": True},
        {"name": "Cohesive below threshold", "model": "cohesive_Voellmy",
         "slope": cohesive_slope, "cohesion": 0.98 * critical_cohesion,
         "should_move": True},
        {"name": "Cohesive above threshold", "model": "cohesive_Voellmy",
         "slope": cohesive_slope, "cohesion": 1.02 * critical_cohesion,
         "should_move": False},
    ]


def compact_cases() -> list[dict[str, float | str | bool]]:
    return [
        {"name": "Compact Coulomb sub-yield", "model": "Coulomb",
         "slope": 0.18, "cohesion": 0.0, "should_move": False},
        {"name": "Compact Coulomb super-yield", "model": "Coulomb",
         "slope": 0.22, "cohesion": 0.0, "should_move": True},
    ]


def run_one(
    output_root: Path,
    specification: dict[str, float | str | bool],
    orientation: int,
    cores: int,
) -> dict[str, float | str | bool | int]:
    slug = str(specification["name"]).lower().replace(" ", "_").replace("-", "_")
    run_root = output_root / "runs" / f"{slug}_{'positive' if orientation > 0 else 'negative'}"
    slope = float(specification["slope"])
    cohesion = float(specification["cohesion"])

    def bed(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
        del Y
        return -orientation * slope * X

    work = prepare_avac_coulomb_case(
        run_root,
        xlower=XLOWER,
        xupper=XUPPER,
        ylower=YLOWER,
        yupper=YUPPER,
        dx=DX,
        t_final=T_FINAL,
        nout=NOUT,
        mu=MU,
        depth=lambda X, Y: np.full_like(X, DEPTH),
        bed=bed,
        boundary_west="extrap",
        boundary_east="extrap",
        boundary_south="periodic",
        boundary_north="periodic",
        model=str(specification["model"]),
        cohesion=cohesion,
        rho=RHO,
        xi=1.0e12,
    )
    _replace_data_value(work / "amr.data", "max1d", "200")
    execution = run_solver("avac", work, cores=cores)
    x, y, h, momentum = final_state(work)
    interior_x = (x >= XLOWER + INTERIOR_MARGIN) & (x <= XUPPER - INTERIOR_MARGIN)
    interior_y = ((y >= YLOWER + TRANSVERSE_INTERIOR_MARGIN)
                  & (y <= YUPPER - TRANSVERSE_INTERIOR_MARGIN))
    interior = interior_x[:, None] & interior_y[None, :]
    speed_x = np.divide(momentum[0], h, out=np.zeros_like(h), where=h > 0.0)
    speed_y = np.divide(momentum[1], h, out=np.zeros_like(h), where=h > 0.0)
    downhill_speed = orientation * speed_x[interior]
    return {
        "case": str(specification["name"]),
        "model": str(specification["model"]),
        "orientation": orientation,
        "slope": slope,
        "mu": MU,
        "cohesion_pa": cohesion,
        "yield_gradient": yield_gradient(slope, cohesion),
        "yield_margin": slope - yield_gradient(slope, cohesion),
        "should_move": bool(specification["should_move"]),
        "mean_downhill_speed_m_s": float(np.mean(downhill_speed)),
        "maximum_absolute_speed_m_s": float(np.max(np.hypot(speed_x[interior], speed_y[interior]))),
        "maximum_cross_slope_speed_m_s": float(np.max(np.abs(speed_y[interior]))),
        "minimum_depth_m": float(np.min(h)),
        "maximum_depth_m": float(np.max(h)),
        "solver_wall_s": float(execution["wall_s"]),
    }


def run_compact(
    output_root: Path,
    specification: dict[str, float | str | bool],
    cores: int,
) -> dict[str, float | str | bool | int]:
    """Run a symmetric triangular deposit that includes two wet/dry edges."""
    slug = str(specification["name"]).lower().replace(" ", "_").replace("-", "_")
    run_root = output_root / "runs" / slug
    surface_slope = float(specification["slope"])
    maximum_depth = 0.60

    def depth(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
        del Y
        return np.maximum(0.0, maximum_depth - surface_slope * np.abs(X))

    work = prepare_avac_coulomb_case(
        run_root,
        xlower=XLOWER,
        xupper=XUPPER,
        ylower=YLOWER,
        yupper=YUPPER,
        dx=DX,
        t_final=T_FINAL,
        nout=NOUT,
        mu=MU,
        depth=depth,
        bed=lambda X, Y: np.zeros_like(X),
        boundary_west="extrap",
        boundary_east="extrap",
        boundary_south="periodic",
        boundary_north="periodic",
    )
    _replace_data_value(work / "amr.data", "max1d", "200")
    execution = run_solver("avac", work, cores=cores)
    x, y, h, momentum = final_state(work)
    u = np.divide(momentum[0], h, out=np.zeros_like(h), where=h > 0.0)
    v = np.divide(momentum[1], h, out=np.zeros_like(h), where=h > 0.0)
    interior_y = ((y >= YLOWER + TRANSVERSE_INTERIOR_MARGIN)
                  & (y <= YUPPER - TRANSVERSE_INTERIOR_MARGIN))
    support_radius = maximum_depth / surface_slope
    left = ((x < -0.2) & (x > -support_radius + 0.2))[:, None] & interior_y[None, :]
    right = ((x > 0.2) & (x < support_radius - 0.2))[:, None] & interior_y[None, :]
    active = left | right
    left_outward = float(np.mean(-u[left]))
    right_outward = float(np.mean(u[right]))
    scale = max(abs(left_outward), abs(right_outward), MOTION_TOLERANCE_M_S)
    symmetry_error = abs(left_outward - right_outward) / scale
    return {
        "case": str(specification["name"]),
        "model": "Coulomb",
        "orientation": 0,
        "slope": surface_slope,
        "mu": MU,
        "cohesion_pa": 0.0,
        "yield_gradient": MU,
        "yield_margin": surface_slope - MU,
        "should_move": bool(specification["should_move"]),
        "mean_downhill_speed_m_s": 0.5 * (left_outward + right_outward),
        "maximum_absolute_speed_m_s": float(np.max(np.hypot(u[active], v[active]))),
        "maximum_cross_slope_speed_m_s": float(np.max(np.abs(v[active]))),
        "mirror_relative_error": symmetry_error,
        "minimum_depth_m": float(np.min(h)),
        "maximum_depth_m": float(np.max(h)),
        "solver_wall_s": float(execution["wall_s"]),
    }


def validate(rows: list[dict[str, float | str | bool | int]]) -> dict[str, float]:
    mirror_errors: list[float] = []
    for row in rows:
        speed = float(row["mean_downhill_speed_m_s"])
        maximum = float(row["maximum_absolute_speed_m_s"])
        if bool(row["should_move"]):
            if speed <= MOTION_TOLERANCE_M_S:
                raise RuntimeError(f"{row['case']} did not accelerate above yield: {speed:g} m/s")
        elif maximum > REST_TOLERANCE_M_S:
            raise RuntimeError(f"{row['case']} moved below yield: {maximum:g} m/s")
        cross_speed = float(row["maximum_cross_slope_speed_m_s"])
        cross_scale = max(maximum, MOTION_TOLERANCE_M_S)
        if cross_speed / cross_scale > TRANSVERSE_RELATIVE_TOLERANCE:
            raise RuntimeError(f"{row['case']} developed material transverse motion")
        if int(row["orientation"]) == 0 and float(row["mirror_relative_error"]) > MIRROR_RELATIVE_TOLERANCE:
            raise RuntimeError(f"{row['case']} developed a left/right bias")

    for name in sorted({str(row["case"]) for row in rows if int(row["orientation"]) != 0}):
        pair = [row for row in rows if row["case"] == name]
        positive = next(float(row["mean_downhill_speed_m_s"]) for row in pair if row["orientation"] == 1)
        negative = next(float(row["mean_downhill_speed_m_s"]) for row in pair if row["orientation"] == -1)
        scale = max(abs(positive), abs(negative), MOTION_TOLERANCE_M_S)
        mirror_errors.append(abs(positive - negative) / scale)
    maximum_mirror_error = max(mirror_errors, default=0.0)
    if maximum_mirror_error > MIRROR_RELATIVE_TOLERANCE:
        raise RuntimeError(f"Mirrored arrest cases differ by {maximum_mirror_error:.3g}")
    return {"maximum_mirror_relative_error": maximum_mirror_error}


def plot(rows: list[dict[str, float | str | bool | int]], output: Path) -> None:
    names = [str(case["name"]) for case in (*cases(), *compact_cases())]
    means, spreads = [], []
    for name in names:
        values = np.asarray([
            float(row["mean_downhill_speed_m_s"]) for row in rows if row["case"] == name
        ])
        means.append(float(np.mean(values)))
        spreads.append(float(0.5 * (np.max(values) - np.min(values))))

    apply_paper_style()
    figure, axis = plt.subplots(figsize=figure_size(2, aspect=0.46))
    colors = [PAPER_COLORS["blue"], PAPER_COLORS["orange"],
              PAPER_COLORS["red"], PAPER_COLORS["green"],
              PAPER_COLORS["purple"], PAPER_COLORS["yellow"]]
    axis.bar(np.arange(len(names)), means, yerr=spreads, color=colors,
             edgecolor=PAPER_COLORS["ink"], linewidth=0.6, capsize=3)
    axis.axhline(MOTION_TOLERANCE_M_S, color=PAPER_COLORS["ink"],
                 linewidth=1.0, linestyle="--", label="Motion threshold")
    axis.set_ylabel(r"Mean downslope speed at $t=0.1$ s (m s$^{-1}$)")
    axis.set_xticks(np.arange(len(names)), ["Coulomb\nbelow", "Coulomb\nabove",
                                             "Cohesive\nbelow $C_{cr}$", "Cohesive\nabove $C_{cr}$",
                                             "Compact\nbelow", "Compact\nabove"])
    axis.legend(loc="upper left")
    figure.savefig(output, dpi=300)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=HERE)
    parser.add_argument("--cores", type=int, default=1)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    (output_root / "results").mkdir(parents=True, exist_ok=True)
    (output_root / "figures").mkdir(parents=True, exist_ok=True)

    rows = [
        run_one(output_root, specification, orientation, args.cores)
        for specification in cases()
        for orientation in (-1, 1)
    ]
    rows.extend(run_compact(output_root, specification, args.cores)
                for specification in compact_cases())
    acceptance = validate(rows)
    plot(rows, output_root / "figures" / "static_cohesive_arrest.png")
    executable = solver_executable("avac")
    summary = {
        "method": "eight mirrored inclined-layer runs plus two compact wet/dry deposits",
        "depth_convention": "AVAC vertical depth; h_normal = h * cos(slope angle)",
        "transition_rule": "at equality the set-valued static branch arrests; below/above cases use 2% offsets",
        "rest_tolerance_m_s": REST_TOLERANCE_M_S,
        "motion_tolerance_m_s": MOTION_TOLERANCE_M_S,
        "solver": str(executable),
        "solver_sha256": sha256(executable),
        **acceptance,
        "cases": rows,
    }
    path = output_root / "results" / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
