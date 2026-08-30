#!/usr/bin/env python3
"""Verify AVAC-to-WAVE mass and momentum transfer with the production path.

The synthetic AVAC frames prescribe a smooth, spatially uniform shoreline
state.  They are written in AVAC's native output format, sampled by the real
Python converter, read by WAVE's Fortran source module, and integrated by the
current WAVE executable.  Small uniform and AMR domains keep the check fast.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "validation"))

from avac4qgis_validation.runtime import (  # noqa: E402
    CLAWPACK_SOURCE,
    _activate_packaged_clawpack,
    maximum_written_amr_level,
    prepare_wave_hydraulic_case,
    run_solver,
    solver_executable,
)
from avac_qgis.core.wave_boundaries import create_boundary_conditions  # noqa: E402


T_FINAL = 1.0
H_AVAC = 0.10
U_X = 0.020
U_Y = 0.010
LAKE_DEPTH = 0.50
STRAIGHT_LENGTH = 0.80
XLOWER, XUPPER = 0.0, 2.0
YLOWER, YUPPER = 0.0, 1.0


def pulse(time_s: float | np.ndarray) -> np.ndarray:
    time = np.asarray(time_s, dtype=float)
    phase = time / T_FINAL
    return np.where(
        (time >= 0.0) & (time <= T_FINAL),
        np.sin(np.pi * phase) * (1.0 + 0.25 * phase),
        0.0,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_ledger(*, length: float, un: float, ux: float, uy: float) -> np.ndarray:
    """Return exact volume and two depth-momentum integrals."""
    amplitude_integral = 2.25 * T_FINAL / np.pi
    amplitude_squared_integral = T_FINAL * (
        0.5 + 0.125 + 0.0625 * (1.0 / 6.0 - 1.0 / (4.0 * np.pi**2))
    )
    return np.array(
        [
            H_AVAC * un * length * amplitude_integral,
            H_AVAC * un * ux * length * amplitude_squared_integral,
            H_AVAC * un * uy * length * amplitude_squared_integral,
        ],
        dtype=float,
    )


def write_synthetic_avac(root: Path, spacing: float, *, ux: float = U_X, uy: float = U_Y) -> np.ndarray:
    """Write native AVAC frames that the production converter can sample."""
    output = root / "AVAC" / "_output"
    if root.exists():
        shutil.rmtree(root)
    output.mkdir(parents=True)
    (root / "AVAC" / "AVAC_configuration.yaml").write_text(
        json.dumps({"output": {"output_format": "ascii"}}, indent=2) + "\n"
    )

    count = int(round(T_FINAL / spacing))
    times = np.linspace(0.0, T_FINAL, count + 1)
    _activate_packaged_clawpack(CLAWPACK_SOURCE)
    from clawpack import pyclaw

    domain = pyclaw.Domain([-1.0, -0.2], [1.0, 1.2], [40, 28])
    for frame, time_s in enumerate(times):
        state = pyclaw.State(domain, 3)
        amplitude = float(pulse(time_s))
        state.q[0, :, :] = H_AVAC
        state.q[1, :, :] = H_AVAC * ux * amplitude
        state.q[2, :, :] = H_AVAC * uy * amplitude
        state.t = float(time_s)
        pyclaw.Solution(state, domain).write(
            frame, path=str(output), file_format="ascii", write_aux=False
        )
    return times


def straight_faces(dx: float) -> np.ndarray:
    y = np.arange(0.10 + 0.5 * dx, 0.90, dx)
    if not np.isclose(y.size * dx, STRAIGHT_LENGTH):
        raise RuntimeError("Straight shoreline discretization does not preserve its prescribed length")
    return np.column_stack(
        (np.full_like(y, 0.5 * dx), y, np.zeros_like(y), y,
         np.ones_like(y), np.zeros_like(y), np.full_like(y, dx))
    )


def diagonal_faces(dx: float) -> tuple[np.ndarray, float]:
    """Return equal east- and south-facing steps along a 45-degree shoreline."""
    n = int(round(0.4 / dx))
    rows: list[list[float]] = []
    for k in range(n):
        x0, y0 = 0.2 + k * dx, 0.7 - k * dx
        rows.append([x0 + 0.5 * dx, y0 - 0.5 * dx, x0, y0 - 0.5 * dx, 1.0, 0.0, dx])
        rows.append([x0 + 0.5 * dx, y0 - 0.5 * dx, x0 + 0.5 * dx, y0, 0.0, -1.0, dx])
    return np.asarray(rows, dtype=float), 2.0 * n * dx


def write_faces(case: Path, faces: np.ndarray) -> None:
    path = case / "CL" / "shoreline_faces.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(
        path, faces, fmt="%.12g",
        header="target_x target_y face_x face_y normal_into_lake_x normal_into_lake_y face_length",
    )


def prepare_wave(case: Path, dx: float, *, refinement: int = 1) -> Path:
    forced = None
    if refinement > 1:
        forced = [(refinement, refinement, 0.0, T_FINAL, XLOWER, XUPPER, YLOWER, YUPPER)]
    return prepare_wave_hydraulic_case(
        case,
        xlower=XLOWER, xupper=XUPPER, ylower=YLOWER, yupper=YUPPER,
        dx=dx, t_final=T_FINAL, nout=10,
        bed=lambda x, y: np.zeros_like(x),
        state=lambda x, y: (
            np.full_like(x, LAKE_DEPTH), np.zeros_like(x), np.zeros_like(x)
        ),
        boundary_west="periodic", boundary_east="periodic",
        boundary_south="periodic", boundary_north="periodic",
        limiter="mc", max1d=80, dry_tolerance=1.0e-4,
        refinement=refinement, forced_regions=forced,
    )


def read_internal_inflow(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tokens = path.read_text().split()
    cursor = 0
    version = int(tokens[cursor]); cursor += 1
    if version != 2:
        raise RuntimeError(f"Expected conservative source format 2, found {version}")
    ntimes, ncells = int(tokens[cursor]), int(tokens[cursor + 1]); cursor += 2
    times = np.asarray(tokens[cursor:cursor + ntimes], dtype=float); cursor += ntimes
    cells = np.empty((ncells, 2), dtype=float)
    rates = np.empty((ntimes, ncells, 3), dtype=float)
    for cell in range(ncells):
        cells[cell] = np.asarray(tokens[cursor:cursor + 2], dtype=float); cursor += 2
        rates[:, cell, :] = np.asarray(tokens[cursor:cursor + 3 * ntimes], dtype=float).reshape(ntimes, 3)
        cursor += 3 * ntimes
    if cursor != len(tokens):
        raise RuntimeError("Unexpected trailing values in internal inflow file")
    return times, cells, rates


def native_composite_integrals(work: Path, frame_id: int) -> np.ndarray:
    """Integrate h, hu and hv on a full-domain finest-level composite."""
    _activate_packaged_clawpack(CLAWPACK_SOURCE)
    from clawpack import pyclaw

    solution = pyclaw.Solution()
    solution.read(frame_id, path=str(work), file_format="binary", read_aux=False)
    finest = max(state.patch.level for state in solution.states)
    states = [state for state in solution.states if state.patch.level == finest]
    domain_area = (XUPPER - XLOWER) * (YUPPER - YLOWER)
    covered = sum(
        state.q.shape[1] * state.q.shape[2] * float(state.grid.delta[0]) * float(state.grid.delta[1])
        for state in states
    )
    if not np.isclose(covered, domain_area, rtol=0.0, atol=1.0e-10):
        raise RuntimeError(f"Finest WAVE level covers {covered} m2, expected {domain_area} m2")
    values = np.zeros(3)
    for state in states:
        area = float(state.grid.delta[0]) * float(state.grid.delta[1])
        values += np.sum(np.asarray(state.q[:3], dtype=float), axis=(1, 2)) * area
    return values


def converter_ledger(source: Path, case: Path, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    write_faces(case, faces)
    create_boundary_conditions(source, case, CLAWPACK_SOURCE, damping=1.0)
    times, cells, rates = read_internal_inflow(case / "CL" / "internal_inflow.data")
    total_rates = rates.sum(axis=1)
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return times, total_rates, np.asarray(integrate(total_rates, times, axis=0), dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--output-root", type=Path, default=HERE / "publication")
    args = parser.parse_args()
    root = args.output_root.resolve()
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)

    source_dt = 0.025
    source = root / "source_avac_dt_0p025"
    source_times = write_synthetic_avac(source, source_dt)
    spatial_specs = (
        ("uniform_0p10", 0.10, 1),
        ("uniform_0p05", 0.05, 1),
        ("amr_0p10_level2", 0.10, 2),
    )
    spatial_rows: list[dict[str, object]] = []
    histories_written = False
    for name, dx, refinement in spatial_specs:
        case = root / name
        work = prepare_wave(case, dx, refinement=refinement)
        times, total_rates, ledger = converter_ledger(source, case, straight_faces(dx))
        if not histories_written:
            np.savetxt(
                results / "written_source_history.csv",
                np.column_stack((times, total_rates)), delimiter=",",
                header="time_s,volume_rate_m3_s,depth_momentum_x_rate_m4_s2,depth_momentum_y_rate_m4_s2",
                comments="",
            )
            histories_written = True
        run_solver("wave", work, cores=args.cores)
        frame_ids = sorted(
            int(path.name.replace("fort.t", "")) for path in work.glob("fort.t*")
            if path.name.replace("fort.t", "").isdigit()
        )
        initial = native_composite_integrals(work, frame_ids[0])
        final = native_composite_integrals(work, frame_ids[-1])
        delta = final - initial
        relative = (delta - ledger) / np.maximum(np.abs(ledger), 1.0e-15)
        spatial_rows.append({
            "case": name, "base_dx_m": dx, "amr_levels": refinement,
            "maximum_written_amr_level": maximum_written_amr_level(work, final_only=True),
            "source_volume_m3": ledger[0], "source_depth_momentum_x_m4_s": ledger[1],
            "source_depth_momentum_y_m4_s": ledger[2],
            "wave_volume_change_m3": delta[0], "wave_depth_momentum_x_change_m4_s": delta[1],
            "wave_depth_momentum_y_change_m4_s": delta[2],
            "relative_volume_closure": relative[0],
            "relative_momentum_x_closure": relative[1],
            "relative_momentum_y_closure": relative[2],
        })
    spatial = pd.DataFrame(spatial_rows)
    spatial.to_csv(results / "wave_closure.csv", index=False)

    temporal_rows: list[dict[str, float]] = []
    probe_case = root / "temporal_converter"
    prepare_wave(probe_case, 0.10)
    exact = exact_ledger(length=STRAIGHT_LENGTH, un=U_X, ux=U_X, uy=U_Y)
    for spacing in (0.25, 0.10, 0.05, 0.025):
        temporal_source = root / f"source_avac_dt_{str(spacing).replace('.', 'p')}"
        write_synthetic_avac(temporal_source, spacing)
        _, _, ledger = converter_ledger(temporal_source, probe_case, straight_faces(0.10))
        relative = np.abs((ledger - exact) / exact)
        temporal_rows.append({
            "source_spacing_s": spacing,
            "volume_relative_error": relative[0],
            "momentum_x_relative_error": relative[1],
            "momentum_y_relative_error": relative[2],
        })
    temporal = pd.DataFrame(temporal_rows)
    temporal.to_csv(results / "time_sampling_convergence.csv", index=False)

    orientation_rows: list[dict[str, float | str]] = []
    diag_source = root / "source_avac_diagonal"
    write_synthetic_avac(diag_source, source_dt, ux=0.020, uy=-0.020)
    for dx in (0.10, 0.05, 0.025):
        prepare_wave(probe_case, dx)
        faces, step_length = diagonal_faces(dx)
        _, _, ledger = converter_ledger(diag_source, probe_case, faces)
        exact_diag = exact_ledger(length=0.4, un=0.040, ux=0.020, uy=-0.020)
        # The stair-step boundary has 0.4 m of east-facing and 0.4 m of
        # south-facing shoreline.  Its total normal flux is equivalent to
        # un=0.02+0.02=0.04 over the 0.4 m projected length.
        relative = np.abs((ledger - exact_diag) / exact_diag)
        orientation_rows.append({
            "geometry": "diagonal_stair_step", "spacing_m": dx,
            "represented_face_length_m": step_length,
            "volume_relative_error": relative[0],
            "momentum_x_relative_error": relative[1],
            "momentum_y_relative_error": relative[2],
        })
    orientation = pd.DataFrame(orientation_rows)
    orientation.to_csv(results / "shoreline_orientation.csv", index=False)

    summary = {
        "case": "production AVAC-to-WAVE conservative shoreline source",
        "wave_solver": str(solver_executable("wave")),
        "wave_solver_sha256": sha256(solver_executable("wave")),
        "source_format": 2,
        "source_duration_s": T_FINAL,
        "source_spacing_s": source_dt,
        "prescribed_avac_depth_m": H_AVAC,
        "prescribed_peak_velocity_m_s": [U_X, U_Y],
        "initial_lake_depth_m": LAKE_DEPTH,
        "straight_shoreline_length_m": STRAIGHT_LENGTH,
        "exact_continuous_ledger": {
            "volume_m3": exact[0], "depth_momentum_x_m4_s": exact[1],
            "depth_momentum_y_m4_s": exact[2],
        },
        "maximum_absolute_wave_relative_closure": float(
            spatial[["relative_volume_closure", "relative_momentum_x_closure", "relative_momentum_y_closure"]]
            .abs().to_numpy().max()
        ),
        "finest_temporal_volume_relative_error": float(temporal.iloc[-1]["volume_relative_error"]),
        "finest_temporal_momentum_relative_error": float(temporal.iloc[-1]["momentum_x_relative_error"]),
        "maximum_diagonal_ledger_relative_error": float(
            orientation[["volume_relative_error", "momentum_x_relative_error", "momentum_y_relative_error"]]
            .abs().to_numpy().max()
        ),
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
