#!/usr/bin/env python3
"""Exercise AVAC depth positivity and conservation on non-planar terrain.

The case is deliberately a property test, not a fitted avalanche scenario.  A
compact two-dimensional release moves over smooth, spatially varying terrain
inside a closed domain.  With no mass source and no open boundary, the finite-
volume update must keep depth nonnegative and conserve the discrete volume.
The same state is run on a uniform mesh and with dynamically regridded AMR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np

from avac4qgis_validation.runtime import (
    CLAWPACK_SOURCE,
    _activate_packaged_clawpack,
    maximum_written_amr_level,
    prepare_avac_coulomb_case,
    run_solver,
    solver_executable,
    working_directory,
)


HERE = Path(__file__).resolve().parent
XLOWER, XUPPER = -8.0, 8.0
YLOWER, YUPPER = -2.0, 2.0
BASE_DX = 0.20
T_FINAL = 1.0
NOUT = 10
DRY_TOLERANCE = 1.0e-8
# A closed finite-volume run should not acquire a material amount of mass.
# For the production second-order wet/dry method, accept changes below 0.1%;
# the analytical and intercomparison cases remain the accuracy gates.
VOLUME_RELATIVE_TOLERANCE = 1.0e-3


def bed(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Smooth inclined terrain with longitudinal and transverse variation."""
    ridge = 0.18 * np.exp(-((X - 0.4) / 1.5) ** 2 - (Y / 0.9) ** 2)
    undulation = 0.035 * np.sin(0.75 * X) * np.cos(1.1 * Y)
    return -0.12 * X + ridge + undulation


def release(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Compact parabolic cap with a genuine two-dimensional wet--dry margin."""
    radius_squared = ((X + 4.2) / 1.45) ** 2 + (Y / 0.95) ** 2
    return 0.75 * np.maximum(1.0 - radius_squared, 0.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_data_value(path: Path, label: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"=: {label}"
    for index, line in enumerate(lines):
        if marker in line:
            lines[index] = f"{value:<20} {line[line.index('=:'):]}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise KeyError(f"Could not find {label!r} in {path}")


def prepare(
    mode: str,
    run_root: Path,
    *,
    order: int = 2,
    transverse_waves: int = 2,
) -> Path:
    levels = 1 if mode == "uniform" else 2
    work = prepare_avac_coulomb_case(
        run_root,
        xlower=XLOWER,
        xupper=XUPPER,
        ylower=YLOWER,
        yupper=YUPPER,
        dx=BASE_DX,
        t_final=T_FINAL,
        nout=NOUT,
        mu=0.0,
        depth=release,
        bed=bed,
        refinement=levels,
        boundary_west="wall",
        boundary_east="wall",
        boundary_south="wall",
        boundary_north="wall",
    )
    replace_data_value(work / "geoclaw.data", "dry_tolerance", f"{DRY_TOLERANCE:.12g}")
    replace_data_value(work / "geoclaw.data", "speed_limit", "20.0")
    replace_data_value(work / "claw.data", "dt_initial", "0.001")
    replace_data_value(work / "claw.data", "cfl_desired", "0.15")
    replace_data_value(work / "claw.data", "cfl_max", "0.45")
    replace_data_value(work / "claw.data", "order", str(order))
    replace_data_value(
        work / "claw.data", "transverse_waves", str(transverse_waves)
    )
    replace_data_value(work / "amr.data", "max1d", "400")
    if mode == "amr":
        replace_data_value(work / "amr.data", "refinement_ratios_x", "2")
        replace_data_value(work / "amr.data", "refinement_ratios_y", "2")
        replace_data_value(work / "amr.data", "refinement_ratios_t", "2")
        replace_data_value(work / "amr.data", "flag_richardson", "F")
        replace_data_value(work / "amr.data", "flag2refine", "T")
        replace_data_value(work / "amr.data", "regrid_interval", "1")
        replace_data_value(work / "refinement.data", "wave_tolerance", "1.e6")
        replace_data_value(work / "refinement.data", "speed_tolerance", "0.08")
        replace_data_value(
            work / "refinement.data", "variable_dt_refinement_ratios", "F"
        )
    else:
        replace_data_value(work / "amr.data", "flag_richardson", "F")
        replace_data_value(work / "amr.data", "flag2refine", "F")
    return work


def numbered_frames(work: Path) -> list[int]:
    return sorted(
        int(path.name.replace("fort.q", ""))
        for path in work.glob("fort.q*")
        if path.name.replace("fort.q", "").isdigit()
    )


def output_format(work: Path, frame: int) -> str:
    tokens = (work / f"fort.t{frame:04d}").read_text(encoding="utf-8").split()
    for token in tokens:
        if token.lower() in {"binary32", "binary64"}:
            return token.lower()
    raise RuntimeError(f"Could not determine binary precision for frame {frame}")


def active_mask(state, states) -> np.ndarray:
    """Mask coarse cells covered by any finer AMR patch."""
    patch = state.patch
    nx, ny = state.q.shape[1:3]
    x = patch.lower_global[0] + (np.arange(nx) + 0.5) * patch.delta[0]
    y = patch.lower_global[1] + (np.arange(ny) + 0.5) * patch.delta[1]
    mask = np.ones((nx, ny), dtype=bool)
    for finer in states:
        if finer.patch.level <= patch.level:
            continue
        fine_patch = finer.patch
        covered_x = (
            (x >= fine_patch.lower_global[0] - 1.0e-12)
            & (x <= fine_patch.upper_global[0] + 1.0e-12)
        )
        covered_y = (
            (y >= fine_patch.lower_global[1] - 1.0e-12)
            & (y <= fine_patch.upper_global[1] + 1.0e-12)
        )
        if np.any(covered_x) and np.any(covered_y):
            mask[np.ix_(covered_x, covered_y)] = False
    return mask


def frame_diagnostics(solution) -> dict[str, object]:
    volume = 0.0
    minimum_depth = np.inf
    negative_cells = 0
    wet_x: list[np.ndarray] = []
    wet_y: list[np.ndarray] = []
    for state in solution.states:
        patch = state.patch
        h = np.asarray(state.q[0], dtype=float)
        mask = active_mask(state, solution.states)
        active_depth = h[mask]
        volume += float(np.sum(active_depth) * patch.delta[0] * patch.delta[1])
        if active_depth.size:
            minimum_depth = min(minimum_depth, float(np.min(active_depth)))
            negative_cells += int(np.count_nonzero(active_depth < -DRY_TOLERANCE))

        nx, ny = h.shape
        x = patch.lower_global[0] + (np.arange(nx) + 0.5) * patch.delta[0]
        y = patch.lower_global[1] + (np.arange(ny) + 0.5) * patch.delta[1]
        wet = mask & (h > DRY_TOLERANCE)
        if np.any(wet):
            X, Y = np.meshgrid(x, y, indexing="ij")
            wet_x.append(X[wet])
            wet_y.append(Y[wet])

    if wet_x:
        x_values = np.concatenate(wet_x)
        y_values = np.concatenate(wet_y)
        clearance = min(
            float(np.min(x_values) - XLOWER),
            float(XUPPER - np.max(x_values)),
            float(np.min(y_values) - YLOWER),
            float(YUPPER - np.max(y_values)),
        )
    else:
        clearance = np.nan
    layout_signature = ";".join(sorted(
        f"{state.patch.level}:"
        f"{state.patch.lower_global[0]:.12g},{state.patch.lower_global[1]:.12g}:"
        f"{state.patch.upper_global[0]:.12g},{state.patch.upper_global[1]:.12g}"
        for state in solution.states
    ))
    return {
        "time_s": float(solution.t),
        "volume_m3": volume,
        "minimum_depth_m": minimum_depth,
        "negative_active_cells": negative_cells,
        "maximum_level": max(state.patch.level for state in solution.states),
        "patch_count": len(solution.states),
        "patch_layout_signature": layout_signature,
        "wet_boundary_clearance_m": clearance,
    }


def extract(work: Path) -> list[dict[str, object]]:
    frames = numbered_frames(work)
    if not frames:
        raise RuntimeError(f"No AVAC output frames found in {work}")
    source_root = CLAWPACK_SOURCE
    diagnostics: list[dict[str, object]] = []
    with working_directory(work):
        _activate_packaged_clawpack(source_root)
        from clawpack.pyclaw.solution import Solution

        for frame in frames:
            solution = Solution(
                frame,
                path=work,
                file_format=output_format(work, frame),
            )
            diagnostics.append(frame_diagnostics(solution))
    return diagnostics


def summarize(mode: str, work: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    volume = np.asarray([row["volume_m3"] for row in rows], dtype=float)
    minimum_depth = np.asarray([row["minimum_depth_m"] for row in rows], dtype=float)
    negative_cells = np.asarray([row["negative_active_cells"] for row in rows], dtype=int)
    clearance = np.asarray([row["wet_boundary_clearance_m"] for row in rows], dtype=float)
    relative_error = (volume - volume[0]) / volume[0]
    patch_counts = np.asarray([row["patch_count"] for row in rows], dtype=int)
    maximum_levels = np.asarray([row["maximum_level"] for row in rows], dtype=int)
    patch_layouts = [str(row["patch_layout_signature"]) for row in rows]
    patch_layout_changes = sum(
        left != right for left, right in zip(patch_layouts[:-1], patch_layouts[1:])
    )
    relative_range = float(np.ptp(volume) / volume[0])
    expected_level = 1 if mode == "uniform" else 2
    speed_limit_resets = (work / "solver.log").read_text(
        encoding="utf-8"
    ).count("getmaxspeed reset")
    passed = bool(
        relative_range <= VOLUME_RELATIVE_TOLERANCE
        and int(np.sum(negative_cells)) == 0
        and speed_limit_resets == 0
        and int(np.max(maximum_levels)) == expected_level
        and (mode == "uniform" or patch_layout_changes > 0)
    )
    return {
        "mode": mode,
        "solver": str(solver_executable("avac")),
        "solver_sha256": sha256(solver_executable("avac")),
        "domain_m": [XLOWER, XUPPER, YLOWER, YUPPER],
        "base_dx_m": BASE_DX,
        "t_final_s": float(rows[-1]["time_s"]),
        "output_frames": len(rows),
        "initial_volume_m3": float(volume[0]),
        "final_volume_m3": float(volume[-1]),
        "absolute_volume_range_m3": float(np.ptp(volume)),
        "relative_volume_range": relative_range,
        "maximum_relative_volume_gain": float(np.max(relative_error)),
        "maximum_relative_volume_loss": float(-np.min(relative_error)),
        "minimum_active_depth_m": float(np.min(minimum_depth)),
        "negative_active_cell_observations": int(np.sum(negative_cells)),
        "speed_limit_resets": speed_limit_resets,
        "minimum_wet_boundary_clearance_m": float(np.nanmin(clearance)),
        "maximum_amr_level_seen": maximum_written_amr_level(work),
        "patch_count_range": [int(np.min(patch_counts)), int(np.max(patch_counts))],
        "patch_layout_changes": patch_layout_changes,
        "relative_volume_tolerance": VOLUME_RELATIVE_TOLERANCE,
        "passed": passed,
        "_rows": rows,
    }


def save_mode_results(run_root: Path, summary: dict[str, object]) -> None:
    results = run_root / "results"
    results.mkdir(exist_ok=True)
    rows = summary.pop("_rows")
    columns = np.asarray([
        [
            row["time_s"], row["volume_m3"], row["minimum_depth_m"],
            row["negative_active_cells"], row["maximum_level"],
            row["patch_count"], row["wet_boundary_clearance_m"],
        ]
        for row in rows
    ], dtype=float)
    np.savetxt(
        results / "conservation_history.csv",
        columns,
        delimiter=",",
        header=(
            "time_s,volume_m3,minimum_depth_m,negative_active_cells,"
            "maximum_level,patch_count,wet_boundary_clearance_m"
        ),
        comments="",
    )
    (results / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    summary["_rows"] = rows


def plot(variant: str, summaries: dict[str, dict[str, object]]) -> Path:
    figures = HERE / "figures"
    figures.mkdir(exist_ok=True)
    figure_path = figures / f"{variant}_real_terrain_conservation.png"
    colors = {"uniform": "#E69F73", "amr": "#75B9E7"}

    x = np.linspace(XLOWER, XUPPER, 321)
    y = np.linspace(YLOWER, YUPPER, 81)
    X, Y = np.meshgrid(x, y)
    Z = bed(X, Y)
    H = release(X, Y)

    fig, axes = plt.subplots(1, 3, figsize=(13.0, 3.9))
    terrain = axes[0].contourf(X, Y, Z, levels=18, cmap="Greens", alpha=0.78)
    axes[0].contour(X, Y, H, levels=[0.05, 0.25, 0.50], colors="#D55E00", linewidths=1.2)
    axes[0].set(xlabel="x (m)", ylabel="y (m)", title="Terrain and initial release")
    fig.colorbar(terrain, ax=axes[0], label="bed elevation (m)", shrink=0.86)

    for mode, summary in summaries.items():
        rows = summary["_rows"]
        time = np.asarray([row["time_s"] for row in rows], dtype=float)
        volume = np.asarray([row["volume_m3"] for row in rows], dtype=float)
        patches = np.asarray([row["patch_count"] for row in rows], dtype=float)
        axes[1].plot(
            time, (volume - volume[0]) / volume[0], marker="o", ms=3.0,
            color=colors[mode], label=mode.upper(),
        )
        axes[2].step(time, patches, where="post", color=colors[mode], label=mode.upper())

    axes[1].axhspan(
        -VOLUME_RELATIVE_TOLERANCE, VOLUME_RELATIVE_TOLERANCE,
        color="#8BCF9B", alpha=0.22, label="acceptance band",
    )
    axes[1].set(
        xlabel="time (s)", ylabel="relative volume change",
        title="Discrete volume conservation",
    )
    axes[2].set(xlabel="time (s)", ylabel="active patches", title="Dynamic AMR activity")
    for axis in axes[1:]:
        axis.grid(alpha=0.25)
        axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)
    return figure_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="current")
    parser.add_argument("--mode", choices=("uniform", "amr", "both"), default="both")
    parser.add_argument("--cores", type=int, default=4)
    parser.add_argument("--order", choices=(1, 2), type=int, default=2)
    parser.add_argument("--transverse-waves", choices=(0, 1, 2), type=int, default=2)
    args = parser.parse_args()
    if args.cores < 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.variant):
        raise ValueError("cores must be positive and variant must be filename-safe")

    modes = ("uniform", "amr") if args.mode == "both" else (args.mode,)
    summaries: dict[str, dict[str, object]] = {}
    for mode in modes:
        run_root = HERE / "runs" / f"{args.variant}_{mode}"
        work = prepare(
            mode,
            run_root,
            order=args.order,
            transverse_waves=args.transverse_waves,
        )
        run_solver("avac", work, cores=args.cores)
        summary = summarize(mode, work, extract(work))
        save_mode_results(run_root, summary)
        summaries[mode] = summary

    figure = plot(args.variant, summaries)
    public_summaries = {
        mode: {key: value for key, value in summary.items() if key != "_rows"}
        for mode, summary in summaries.items()
    }
    combined = {
        "variant": args.variant,
        "all_modes_passed": all(summary["passed"] for summary in summaries.values()),
        "modes": public_summaries,
        "figure": str(figure),
    }
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    (results / f"{args.variant}_summary.json").write_text(
        json.dumps(combined, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(combined, indent=2))


if __name__ == "__main__":
    main()
