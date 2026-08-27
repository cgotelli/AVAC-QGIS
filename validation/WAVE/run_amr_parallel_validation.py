#!/usr/bin/env python3
"""Lightweight WAVE AMR-consistency and OpenMP-reproducibility checks."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent

from avac4qgis_validation.runtime import (
    CLAWPACK_SOURCE,
    _activate_packaged_clawpack,
    centerline,
    fgout_frame,
    fgout_times,
    prepare_wave_hydraulic_case,
    run_solver,
    runtime,
)


CASE = HERE/"08_amr_parallel"
XLOWER, XUPPER = 0.0, 2.0
YLOWER, YUPPER = 0.0, 0.2
T_FINAL = 0.25
COARSE_DX = 0.05
FINE_DX = 0.005  # WAVE level 1 -> 2 refinement ratio is 10.


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def depth(x, y):
    return np.where(x <= 1.0, 0.1, 0.0)


def prepare(folder: str, dx: float, *, refinement: int = 1,
            forced_regions=None) -> Path:
    return prepare_wave_hydraulic_case(
        CASE/folder, xlower=XLOWER, xupper=XUPPER,
        ylower=YLOWER, yupper=YUPPER, dx=dx,
        t_final=T_FINAL, nout=5,
        bed=lambda x, y: np.zeros_like(x), depth=depth,
        boundary_west="wall", boundary_east="wall",
        boundary_south="periodic", boundary_north="periodic",
        limiter="mc", max1d=60, refinement=refinement,
        forced_regions=forced_regions,
    )


def execute(work: Path, cores: int) -> float:
    started = time.perf_counter()
    run_solver("wave", work, cores=cores)
    return time.perf_counter()-started


def final_centerline(work: Path) -> tuple[np.ndarray, np.ndarray]:
    number = len(fgout_times("wave", work))
    with contextlib.redirect_stdout(io.StringIO()):
        frame = fgout_frame("wave", work, number)
    return centerline(frame, "h")


def fgout_mass_change(work: Path, dx: float) -> tuple[float, float, float]:
    numbers = (1, len(fgout_times("wave", work)))
    masses = []
    for number in numbers:
        with contextlib.redirect_stdout(io.StringIO()):
            frame = fgout_frame("wave", work, number)
        masses.append(float(np.sum(np.ma.filled(frame.h, 0.0))*dx*dx))
    relative = (masses[1]-masses[0])/masses[0]
    return masses[0], masses[1], relative


def native_composite_mass_change(work: Path) -> tuple[float, float, float]:
    """Integrate the non-overlapping finest native AMR cells.

    This validation forces the finest level over the complete rectangular
    domain. Therefore selecting the maximum level in each native frame is the
    exact composite grid: at level 1 it is the base domain; at level 2 the
    forced fine patches cover the entire domain and the underlying coarse
    cells must not be counted a second time.
    """
    _activate_packaged_clawpack(CLAWPACK_SOURCE)
    from clawpack import pyclaw

    frame_ids = sorted(
        int(path.name.replace("fort.t", ""))
        for path in work.glob("fort.t*")
        if path.name.replace("fort.t", "").isdigit()
    )
    masses = []
    domain_area = (XUPPER-XLOWER)*(YUPPER-YLOWER)
    for frame_id in (frame_ids[0], frame_ids[-1]):
        solution = pyclaw.Solution()
        solution.read(
            frame_id, path=str(work), file_format="binary", read_aux=False
        )
        finest = max(state.patch.level for state in solution.states)
        states = [state for state in solution.states if state.patch.level == finest]
        covered_area = sum(
            state.q.shape[1]*state.q.shape[2]
            * float(state.grid.delta[0])*float(state.grid.delta[1])
            for state in states
        )
        if not np.isclose(covered_area, domain_area, rtol=0.0, atol=1.0e-12):
            raise RuntimeError(
                f"Finest native level {finest} covers {covered_area} m2, "
                f"expected the forced full domain {domain_area} m2"
            )
        masses.append(sum(
            float(np.sum(np.ma.filled(state.q[0], 0.0)))
            * float(state.grid.delta[0])*float(state.grid.delta[1])
            for state in states
        ))
    return masses[0], masses[1], (masses[1]-masses[0])/masses[0]


def maximum_written_level(work: Path) -> int:
    frames = sorted(
        path for path in work.glob("fort.q*")
        if path.name.replace("fort.q", "").isdigit()
    )
    if not frames:
        raise RuntimeError(f"No native WAVE frames in {work}")
    levels = [
        int(match.group(1))
        for match in re.finditer(
            r"^\s*(\d+)\s+AMR_level\s*$",
            frames[-1].read_text(), flags=re.MULTILINE,
        )
    ]
    if not levels:
        raise RuntimeError(f"No AMR patch levels in {frames[-1]}")
    return max(levels)


def final_patch_count(work: Path) -> int:
    headers = sorted(
        path for path in work.glob("fort.q*")
        if path.name.replace("fort.q", "").isdigit()
    )
    if not headers:
        raise RuntimeError(f"No native WAVE frame headers in {work}")
    return headers[-1].read_text().count("grid_number")


def final_binary(work: Path, pattern: str) -> Path:
    paths = sorted(work.glob(pattern))
    if not paths:
        raise RuntimeError(f"No files matching {pattern} in {work}")
    return paths[-1]


def main() -> None:
    CASE.mkdir(parents=True, exist_ok=True)
    coarse = prepare("uniform_coarse", COARSE_DX)
    fine_1 = prepare("uniform_fine_1core", FINE_DX)
    fine_8 = prepare("uniform_fine_8core", FINE_DX)
    amr_1 = prepare(
        "amr_level2_1core", COARSE_DX, refinement=2,
        forced_regions=[(2, 2, 0.0, T_FINAL,
                         XLOWER, XUPPER, YLOWER, YUPPER)],
    )
    amr_8 = prepare(
        "amr_level2_8core", COARSE_DX, refinement=2,
        forced_regions=[(2, 2, 0.0, T_FINAL,
                         XLOWER, XUPPER, YLOWER, YUPPER)],
    )

    elapsed = {
        "uniform_coarse_8core": execute(coarse, 8),
        "uniform_fine_1core": execute(fine_1, 1),
        "uniform_fine_8core": execute(fine_8, 8),
        "amr_level2_1core": execute(amr_1, 1),
        "amr_level2_8core": execute(amr_8, 8),
    }
    xc, hc = final_centerline(coarse)
    x1, h1 = final_centerline(fine_1)
    x8, h8 = final_centerline(fine_8)
    xa1, ha1 = final_centerline(amr_1)
    xa8, ha8 = final_centerline(amr_8)
    if not np.array_equal(x1, x8):
        raise RuntimeError("Serial and parallel fixed-grid coordinates differ")
    if not np.array_equal(xa1, xa8):
        raise RuntimeError("Serial and parallel AMR fixed-grid coordinates differ")
    parallel_delta = h8-h1
    amr_parallel_delta = ha8-ha1
    reference_on_coarse = np.interp(xc, x8, h8)
    reference_on_amr = np.interp(xa8, x8, h8)
    coarse_delta = hc-reference_on_coarse
    amr_delta = ha8-reference_on_amr
    coarse_rms = float(np.sqrt(np.mean(coarse_delta**2)))
    amr_rms = float(np.sqrt(np.mean(amr_delta**2)))

    results = CASE/"results"
    figures = CASE/"figures"
    results.mkdir(exist_ok=True)
    figures.mkdir(exist_ok=True)
    amr_level_1core = maximum_written_level(amr_1)
    amr_level_8core = maximum_written_level(amr_8)
    if amr_level_1core != 2 or amr_level_8core != 2:
        raise RuntimeError(
            "Forced AMR runs reached levels "
            f"{amr_level_1core} and {amr_level_8core}, expected 2"
        )
    native_parallel_equal = (
        final_binary(fine_1, "fort.b*").read_bytes()
        == final_binary(fine_8, "fort.b*").read_bytes()
    )
    fgout_parallel_equal = (
        final_binary(fine_1, "fgout0001.b*").read_bytes()
        == final_binary(fine_8, "fgout0001.b*").read_bytes()
    )
    amr_native_parallel_equal = (
        final_binary(amr_1, "fort.b*").read_bytes()
        == final_binary(amr_8, "fort.b*").read_bytes()
    )
    amr_fgout_parallel_equal = (
        final_binary(amr_1, "fgout0001.b*").read_bytes()
        == final_binary(amr_8, "fgout0001.b*").read_bytes()
    )
    mass = {
        "uniform_coarse": fgout_mass_change(coarse, COARSE_DX),
        "uniform_fine_1core": fgout_mass_change(fine_1, FINE_DX),
        "uniform_fine_8core": fgout_mass_change(fine_8, FINE_DX),
        # The AMR run's fixed output grid is the base 0.05 m grid.
        "amr_level2_1core": fgout_mass_change(amr_1, COARSE_DX),
        "amr_level2_8core": fgout_mass_change(amr_8, COARSE_DX),
    }
    native_mass = {
        "uniform_coarse": native_composite_mass_change(coarse),
        "uniform_fine_1core": native_composite_mass_change(fine_1),
        "uniform_fine_8core": native_composite_mass_change(fine_8),
        "amr_level2_1core": native_composite_mass_change(amr_1),
        "amr_level2_8core": native_composite_mass_change(amr_8),
    }
    summary = {
        "solver": str(runtime("wave")/"xgeoclaw"),
        "solver_sha256": digest(runtime("wave")/"xgeoclaw"),
        "case": "flat-bed dry dam break",
        "coarse_dx_m": COARSE_DX,
        "fine_dx_m": FINE_DX,
        "amr_refinement_ratio": 10,
        "amr_maximum_written_level": amr_level_8core,
        "amr_maximum_written_level_1core": amr_level_1core,
        "amr_maximum_written_level_8core": amr_level_8core,
        "coarse_vs_uniform_fine_rms_depth_difference_m": coarse_rms,
        "amr2_vs_uniform_fine_rms_depth_difference_m": amr_rms,
        "amr_error_ratio_to_coarse": amr_rms/coarse_rms if coarse_rms else 0.0,
        "parallel_bitwise_equal_float32_fgout": bool(np.array_equal(h1, h8)),
        "parallel_final_native_binary_bitwise_equal": native_parallel_equal,
        "parallel_final_fgout_binary_bitwise_equal": fgout_parallel_equal,
        "parallel_uniform_fine_patch_count": final_patch_count(fine_8),
        "parallel_rms_depth_difference_m": float(np.sqrt(np.mean(parallel_delta**2))),
        "parallel_maximum_depth_difference_m": float(np.max(abs(parallel_delta))),
        "amr_parallel_bitwise_equal_float32_fgout": bool(np.array_equal(ha1, ha8)),
        "amr_parallel_final_native_binary_bitwise_equal": amr_native_parallel_equal,
        "amr_parallel_final_fgout_binary_bitwise_equal": amr_fgout_parallel_equal,
        "amr_parallel_rms_depth_difference_m": float(
            np.sqrt(np.mean(amr_parallel_delta**2))
        ),
        "amr_parallel_maximum_depth_difference_m": float(
            np.max(abs(amr_parallel_delta))
        ),
        "amr_parallel_patch_count_1core": final_patch_count(amr_1),
        "amr_parallel_patch_count_8core": final_patch_count(amr_8),
        "elapsed_wall_seconds": elapsed,
        "fine_parallel_speedup_1core_over_8core": elapsed["uniform_fine_1core"]/elapsed["uniform_fine_8core"],
        "amr_parallel_speedup_1core_over_8core": elapsed["amr_level2_1core"]/elapsed["amr_level2_8core"],
        "fgout_mass_initial_final_relative_change": {
            name: {"initial_m3": values[0], "final_m3": values[1],
                   "relative_change": values[2]}
            for name, values in mass.items()
        },
        "fgout_mass_note": (
            "Visualization-grid quadrature only; do not use as the AMR "
            "conservation metric when the sharp front is finer than fgout."
        ),
        "native_composite_mass_initial_final_relative_change": {
            name: {"initial_m3": values[0], "final_m3": values[1],
                   "relative_change": values[2]}
            for name, values in native_mass.items()
        },
    }
    (results/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    np.savetxt(
        results/"final_profiles.csv",
        np.column_stack((xc, hc, ha1, ha8, reference_on_coarse)), delimiter=",",
        header=(
            "x_m,uniform_coarse_h_m,amr_level2_1core_h_m,"
            "amr_level2_8core_h_m,uniform_fine_sampled_h_m"
        ),
        comments="",
    )

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2), constrained_layout=True)
    axes[0].plot(x8, h8, color="#d62728", lw=2.0,
                 label="uniform 0.005 m reference")
    axes[0].plot(xc, hc, color="#777777", lw=1.5, ls=(0, (5, 2)),
                 label="uniform 0.05 m")
    axes[0].plot(xa8, ha8, color="#0057b8", lw=1.7, ls=(0, (1.5, 1.5)),
                 label="AMR level 2 (0.05 -> 0.005 m)")
    axes[0].set(xlabel="x (m)", ylabel="water depth (m)",
                title="AMR consistency at t = 0.25 s")
    axes[0].grid(alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(x1, parallel_delta, color="#5e3c99", lw=1.8,
                 label="uniform 0.005 m: 8-core minus 1-core")
    axes[1].plot(xa8, amr_parallel_delta, color="#e66101", lw=1.3,
                 ls=(0, (5, 2)), label="AMR level 2: 8-core minus 1-core")
    axes[1].set(xlabel="x (m)", ylabel="8-core minus 1-core depth (m)",
                title="OpenMP reproducibility, with and without AMR")
    axes[1].grid(alpha=0.25)
    axes[1].legend(frameon=False, fontsize=8)
    fig.savefig(figures/"wave_amr_parallel_validation.png", dpi=240)
    plt.close(fig)

    report = HERE/"comparison_report.md"
    report_text = report.read_text() if report.is_file() else "# WAVE validation report\n"
    maximum_native_mass_drift = max(
        abs(values[2]) for values in native_mass.values()
    )
    marker = "\n## AMR and OpenMP validation\n"
    if marker in report_text:
        start = report_text.index(marker)
        end = report_text.find("\n## ", start+len(marker))
        if end < 0:
            end = len(report_text)
        report_text = report_text[:start].rstrip()+"\n"+report_text[end:].lstrip()
    report_text += (
        marker+"\n"
        "A small flat-bed dry dam break was run on a 0.05 m uniform grid, "
        "a 0.005 m uniform reference grid, and a level-2 WAVE AMR grid whose "
        "10:1 refinement reaches 0.005 m. Native output confirms that level 2 "
        f"was created. The AMR/reference RMS depth difference is `{amr_rms:.7g} m`, "
        f"versus `{coarse_rms:.7g} m` for the coarse grid. The uniform fine case "
        "was independently run with one and eight OpenMP threads; their maximum "
        f"depth difference is `{summary['parallel_maximum_depth_difference_m']:.7g} m`. "
        "The level-2 AMR case was also independently run with one and eight "
        "threads—the exact combined AMR/OpenMP regression—and its maximum depth "
        f"difference is `{summary['amr_parallel_maximum_depth_difference_m']:.7g} m`. "
        "The summary also records byte-for-byte comparisons of the final native "
        "AMRClaw binary and fixed-grid binary, so float32 display precision cannot "
        "hide a parallel difference. Conservation is measured from the native "
        "non-overlapping composite AMR cells, not from a coarsely sampled map; "
        "the largest relative native mass drift among the five closed-domain "
        f"runs is `{maximum_native_mass_drift:.7g}`. "
        "Timing is reported for transparency but reproducibility, not speedup on "
        "this deliberately small case, is the acceptance criterion.\n"
    )
    report.write_text(report_text)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
