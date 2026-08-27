#!/usr/bin/env python3
"""Run identical Baines bump checks with the rebuilt AVAC and WAVE solvers."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent

from avac4qgis_validation.runtime import (
    GRAVITY,
    centerline,
    fgout_frame,
    fgout_times,
    prepare_avac_hydraulic_case,
    prepare_wave_hydraulic_case,
    run_solver,
    runtime,
)


CASE = HERE / "07_baines_flow_over_bump"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def bump(x, y=0.0):
    x = np.asarray(x)
    return np.where((x > 8.0) & (x < 12.0), 0.2 - 0.05*(x-10.0)**2, 0.0)


DISCHARGE = 4.0
REFERENCE_DEPTH = 2.0
HEAD = REFERENCE_DEPTH + DISCHARGE**2 / (
    2.0 * GRAVITY * REFERENCE_DEPTH**2
)


def baines_depth(x, y):
    bed = np.asarray(bump(x, y))
    result = np.empty_like(bed, dtype=float)
    for index, elevation in enumerate(bed.ravel()):
        roots = np.roots(
            [1.0, float(elevation-HEAD), 0.0,
             DISCHARGE**2/(2.0*GRAVITY)]
        )
        candidates = [
            root.real for root in roots
            if abs(root.imag) < 1.0e-10
            and root.real > 0.0
            and DISCHARGE/(root.real*np.sqrt(GRAVITY*root.real)) < 1.0
        ]
        result.ravel()[index] = max(candidates)
    return result


def read_frame(solver: str, work: Path, number: int):
    with contextlib.redirect_stdout(io.StringIO()):
        return fgout_frame(solver, work, number)


def history(
    solver: str, work: Path, scenario: str
) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
    rows = []
    final = None
    for number, time in enumerate(fgout_times(solver, work), start=1):
        frame = read_frame(solver, work, number)
        x, h = centerline(frame, "h")
        if scenario == "steady":
            exact = baines_depth(x, np.zeros_like(x))
            error = h-exact
            rows.append((time, np.max(abs(error)), np.mean(abs(error)),
                         np.sqrt(np.mean(error**2))))
            final = (x, h, exact)
        else:
            error = h+bump(x)-REFERENCE_DEPTH
            rows.append((time, np.max(abs(error)), np.sqrt(np.mean(error**2))))
            final = (x, h, np.full_like(h, REFERENCE_DEPTH)-bump(x))
    if final is None:
        raise RuntimeError(f"No {solver.upper()} fixed-grid output in {work}")
    return np.asarray(rows), final


def prepare_pair(solver: str, common: dict) -> tuple[Path, Path]:
    prepare = (
        prepare_wave_hydraulic_case
        if solver == "wave"
        else prepare_avac_hydraulic_case
    )
    solver_dir = CASE / solver
    steady = prepare(
        solver_dir / "steady_subcritical", **common,
        state=lambda x, y: (
            baines_depth(x, y),
            np.full_like(x, DISCHARGE, dtype=float),
            np.zeros_like(x, dtype=float),
        ),
        boundary_west="user", boundary_east="user",
        hydraulic_boundaries={
            1: (3, REFERENCE_DEPTH, DISCHARGE),
            2: (3, REFERENCE_DEPTH, DISCHARGE),
        },
    )
    rest = prepare(
        solver_dir / "lake_at_rest", **common,
        depth=lambda x, y: REFERENCE_DEPTH-bump(x, y),
        boundary_west="wall", boundary_east="wall",
    )
    return steady, rest


def main() -> None:
    dx = 0.05
    common = dict(
        xlower=0.0, xupper=25.0, ylower=0.0, yupper=1.0,
        dx=dx, t_final=10.0, nout=100, bed=bump,
        boundary_south="periodic", boundary_north="periodic", max1d=130,
    )
    runs = {}
    for solver in ("avac", "wave"):
        steady, rest = prepare_pair(solver, common)
        run_solver(solver, steady, cores=8)
        run_solver(solver, rest, cores=8)
        steady_rows, steady_final = history(solver, steady, "steady")
        rest_rows, _rest_final = history(solver, rest, "rest")
        runs[solver] = {
            "steady_rows": steady_rows,
            "steady_final": steady_final,
            "rest_rows": rest_rows,
        }
    results = CASE/"results"
    figures = CASE/"figures"
    results.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    for solver, data in runs.items():
        np.savetxt(
            results/f"{solver}_baines_steady_error.csv",
            data["steady_rows"], delimiter=",",
            header="time_s,Linf_depth_m,L1_depth_m,L2_depth_m", comments="",
        )
        np.savetxt(
            results/f"{solver}_lake_at_rest_error.csv",
            data["rest_rows"], delimiter=",",
            header="time_s,Linf_eta_m,L2_eta_m", comments="",
        )

    x, wave_numerical, exact = runs["wave"]["steady_final"]
    _x, avac_numerical, _exact = runs["avac"]["steady_final"]
    steady_rows = runs["wave"]["steady_rows"]
    rest_rows = runs["wave"]["rest_rows"]
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2), constrained_layout=True)
    axes[0].fill_between(x, bump(x), wave_numerical+bump(x), color="#b9dff0")
    axes[0].plot(x, bump(x), color="saddlebrown", lw=1.5, label="Topography")
    axes[0].plot(x, exact+bump(x), color="#d62728", lw=1.7,
                 label="Baines analytical surface")
    axes[0].plot(x, avac_numerical+bump(x), color="#2ca02c", lw=1.7,
                 ls="--", label="AVAC")
    axes[0].plot(x, wave_numerical+bump(x), color="#0057b8", lw=1.7,
                 ls=(0, (1.5, 1.5)), label="WAVE")
    axes[0].set(xlabel="x (m)", ylabel="elevation (m)",
                title="Subcritical Baines flow at 10 s")
    axes[0].grid(alpha=0.22)
    axes[0].legend(frameon=False, fontsize=8)
    for solver, color, style in (
        ("AVAC", "#2ca02c", "--"), ("WAVE", "#0057b8", ":")
    ):
        data = runs[solver.lower()]
        axes[1].semilogy(data["steady_rows"][:, 0], data["steady_rows"][:, 3],
                         color=color, ls=style,
                         label=f"{solver}: Baines RMS depth error")
        axes[1].semilogy(data["rest_rows"][:, 0], data["rest_rows"][:, 1],
                         color=color, ls=style, alpha=0.7,
                         label=f"{solver}: lake-at-rest max surface error")
    axes[1].set(xlabel="time (s)", ylabel="error (m)",
                title="Well-balanced diagnostics")
    axes[1].grid(alpha=0.22)
    axes[1].legend(frameon=False, fontsize=8)
    fig.savefig(figures/"avac_wave_baines_and_lake_at_rest.png", dpi=240)
    plt.close(fig)

    wave_executable = runtime("wave")/"xgeoclaw"
    avac_executable = runtime("avac")/"xgeoclaw"
    summary = {
        "wave_solver": str(wave_executable),
        "wave_solver_sha256": digest(wave_executable),
        "avac_solver": str(avac_executable),
        "avac_solver_sha256": digest(avac_executable),
        "dx_m": dx,
        "cells_x": 500,
        "cells_y": 20,
        "final_time_s": 10.0,
        "wave_baines_steady_maximum_depth_error_m": float(steady_rows[-1, 1]),
        "wave_baines_steady_rms_depth_error_m": float(steady_rows[-1, 3]),
        "wave_lake_at_rest_maximum_surface_error_m": float(rest_rows[-1, 1]),
        "wave_lake_at_rest_rms_surface_error_m": float(rest_rows[-1, 2]),
        "avac_baines_steady_maximum_depth_error_m": float(runs["avac"]["steady_rows"][-1, 1]),
        "avac_baines_steady_rms_depth_error_m": float(runs["avac"]["steady_rows"][-1, 3]),
        "avac_lake_at_rest_maximum_surface_error_m": float(runs["avac"]["rest_rows"][-1, 1]),
        "avac_lake_at_rest_rms_surface_error_m": float(runs["avac"]["rest_rows"][-1, 2]),
        "wave_avac_final_depth_rms_difference_m": float(
            np.sqrt(np.mean((wave_numerical-avac_numerical)**2))
        ),
    }
    (results/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    report = HERE/"comparison_report.md"
    report_text = report.read_text() if report.is_file() else "# WAVE validation report\n"
    marker = "\n## Baines flow over a bump and lake at rest\n"
    if marker in report_text:
        start = report_text.index(marker)
        end = report_text.find("\n## ", start+len(marker))
        if end < 0:
            end = len(report_text)
        report_text = report_text[:start].rstrip()+"\n"+report_text[end:].lstrip()
    report_text += (
        marker+"\n"
        "The rebuilt AVAC and WAVE solvers were tested with exactly the same "
        "steady subcritical Baines state and matching stage/discharge boundary "
        "data, plus the associated lake-at-rest state. At 10 s, WAVE's steady "
        f"depth RMS error is `{summary['wave_baines_steady_rms_depth_error_m']:.6g} m` "
        f"and AVAC's is `{summary['avac_baines_steady_rms_depth_error_m']:.6g} m`. "
        "Their final depth profiles differ by "
        f"`{summary['wave_avac_final_depth_rms_difference_m']:.6g} m` RMS. "
        "Neither run uses a fitted momentum impulse.\n"
    )
    report.write_text(report_text)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
