"""Convert completed AVAC output into an internal WAVE shoreline inflow.

GeoClaw still solves on its required rectangular grid.  Coupling is instead
performed on the grid-aligned shoreline of the initially wet lake, so an
avalanche can enter a diagonal reservoir without first crossing an unrelated
outer edge of the calculation rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import yaml


@dataclass(frozen=True)
class WaveBoundarySummary:
    """Internal-inflow generation result retained with a Wave scenario."""

    times: tuple[float, ...]
    active_samples: int
    outside_avac_coverage_zeroed: int
    shoreline_faces: int = 0
    active_source_cells: int = 0
    injected_water_volume_m3: float = 0.0
    injected_depth_momentum_x_m4_s: float = 0.0
    injected_depth_momentum_y_m4_s: float = 0.0
    injected_water_momentum_x_kg_m_s: float = 0.0
    injected_water_momentum_y_kg_m_s: float = 0.0


def _finite_boundary_state(depth: np.ndarray, hu: np.ndarray, hv: np.ndarray, *, epsilon: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Replace samples outside AVAC coverage with a finite zero state.

    Retained as a small compatibility helper for older smoke tests and for the
    same missing-coverage policy used by the internal shoreline converter.
    """
    depth, hu, hv = (np.asarray(values, dtype=float).copy() for values in (depth, hu, hv))
    invalid = ~np.isfinite(depth) | ~np.isfinite(hu) | ~np.isfinite(hv)
    replaced = int(np.count_nonzero(invalid))
    depth[invalid] = 0.0
    hu[invalid] = 0.0
    hv[invalid] = 0.0
    stopped = (np.abs(hu) < epsilon) & (np.abs(hv) < epsilon)
    depth[stopped] = 0.0
    return depth, hu, hv, replaced


def _source_rates(
    faces: np.ndarray,
    depth: np.ndarray,
    hu: np.ndarray,
    hv: np.ndarray,
    *,
    damping: float,
    cell_size: float,
    epsilon: float,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Return target cells and conservative total ``Q, Q*u, Q*v`` rates.

    ``faces`` columns are target x/y, face x/y, inward normal x/y and face
    length.  AVAC momentum dotted with the inward normal is a volume flux per
    unit shoreline length.  Multiplication by face length and the existing
    snow/water density ratio gives a water-volume rate.  Momentum is injected
    with the sampled AVAC velocity.  The rates deliberately remain integrated
    quantities rather than being divided by a base-grid cell area: the WAVE
    solver divides by the area of the AMR cell that receives each point source,
    so refinement cannot change the injected mass or momentum.
    """
    faces = np.asarray(faces, dtype=float)
    if faces.ndim != 2 or faces.shape[1] != 7:
        raise ValueError("Wave shoreline-face file must contain seven numeric columns.")
    sample_count = len(faces)
    vectors: list[np.ndarray] = []
    for name, values in (("depth", depth), ("x-momentum", hu), ("y-momentum", hv)):
        vector = np.asarray(values, dtype=float)
        # A one-face shoreline is a valid (if unusual) synthetic case.  Turn
        # its scalar sample into a one-value vector, but reject a scalar for a
        # multi-face shoreline with an actionable error instead of allowing
        # ``len() of unsized object`` to escape from NumPy.
        if vector.ndim == 0:
            vector = vector.reshape(1)
        vector = vector.reshape(-1)
        if vector.size != sample_count:
            raise ValueError(
                f"AVAC shoreline {name} samples ({vector.size}) do not match "
                f"the {sample_count} prepared shoreline faces."
            )
        vectors.append(vector)
    depth, hu, hv = vectors
    invalid = ~np.isfinite(depth) | ~np.isfinite(hu) | ~np.isfinite(hv)
    replaced = int(np.count_nonzero(invalid))
    normal_flux = hu * faces[:, 4] + hv * faces[:, 5]
    active = (~invalid) & (depth > epsilon) & (normal_flux > epsilon)
    rates_by_cell: dict[tuple[float, float], np.ndarray] = {}
    if not np.isfinite(cell_size) or float(cell_size) <= 0.0:
        raise ValueError("Wave cell size must be finite and positive.")
    for index in np.flatnonzero(active):
        water_rate = float(damping) * normal_flux[index] * faces[index, 6]
        velocity_x = hu[index] / depth[index]
        velocity_y = hv[index] / depth[index]
        rate = np.array((water_rate, water_rate * velocity_x, water_rate * velocity_y), dtype=float)
        key = (float(faces[index, 0]), float(faces[index, 1]))
        rates_by_cell[key] = rates_by_cell.get(key, np.zeros(3, dtype=float)) + rate
    if not rates_by_cell:
        return np.empty((0, 2), dtype=float), np.empty((0, 3), dtype=float), int(np.count_nonzero(active)), replaced
    cells = np.asarray(sorted(rates_by_cell), dtype=float)
    rates = np.vstack([rates_by_cell[(float(x), float(y))] for x, y in cells])
    return cells, rates, int(np.count_nonzero(active)), replaced


def _write_internal_inflow(path: Path, times: np.ndarray, cells: np.ndarray, rates: np.ndarray) -> None:
    """Write conservative point rates in format version 2.

    Version 2 stores total ``Q, Q*u, Q*v`` rates.  The Fortran reader retains
    version-1 compatibility but new scenarios must use the AMR-independent
    conservative convention.
    """
    times = np.asarray(times, dtype=float)
    cells = np.asarray(cells, dtype=float)
    rates = np.asarray(rates, dtype=float)
    if rates.shape != (times.size, cells.shape[0], 3):
        raise ValueError("Internal Wave inflow array has inconsistent dimensions.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("2\n")
        handle.write(f"{times.size} {cells.shape[0]}\n")
        handle.write(" ".join(f"{value:.17g}" for value in times) + "\n")
        for cell_index, (x, y) in enumerate(cells):
            handle.write(f"{x:.17g} {y:.17g}\n")
            for time_index in range(times.size):
                handle.write(" ".join(f"{value:.17g}" for value in rates[time_index, cell_index]) + "\n")


def _integrated_source_ledger(
    times: np.ndarray,
    rates: np.ndarray,
    *,
    water_density: float,
) -> tuple[float, float, float, float, float]:
    """Integrate conservative mass and momentum sources over AVAC time.

    The three source columns are total ``Q, Q*u, Q*v`` rates.  Their time
    integrals are water volume and the two depth-momentum integrals.  The
    latter become physical water momentum after multiplication by density.
    Keeping this ledger beside every scenario makes it directly auditable
    that coupling supplies both mass and horizontal momentum.
    """
    time_values = np.asarray(times, dtype=float).reshape(-1)
    source_rates = np.asarray(rates, dtype=float)
    if source_rates.ndim != 3 or source_rates.shape[0] != time_values.size or source_rates.shape[2] != 3:
        raise ValueError("Internal Wave source ledger has inconsistent dimensions.")
    density = float(water_density)
    if not np.isfinite(density) or density <= 0.0:
        raise ValueError("Water density must be finite and positive.")
    total_rates = source_rates.sum(axis=1)
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    integrated = np.asarray(integrate(total_rates, time_values, axis=0), dtype=float)
    return (
        float(integrated[0]), float(integrated[1]), float(integrated[2]),
        float(density * integrated[1]), float(density * integrated[2]),
    )


def _interpolate_patch_component(state, component: int, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Linearly sample one GeoClaw patch without importing SciPy.

    ``clawpack.visclaw.gridtools`` delegates this operation to
    ``scipy.interpolate.RegularGridInterpolator``.  SciPy is not supplied by
    all QGIS distributions, while the WAVE coupling needs only this small,
    regular-grid operation.  The padded edge values and 0.501-cell extent
    deliberately match VisClaw's ``grid_eval_2d`` behaviour.
    """
    values = np.asarray(state.q[component], dtype=float)
    if values.ndim != 2 or min(values.shape) < 2:
        raise ValueError("AVAC frame has an invalid two-dimensional conserved-component grid.")
    grid_x, grid_y = state.grid.c_centers
    x_centres = np.asarray(grid_x[:, 0], dtype=float)
    y_centres = np.asarray(grid_y[0, :], dtype=float)
    dx, dy = float(x_centres[1] - x_centres[0]), float(y_centres[1] - y_centres[0])
    if not (np.isfinite(dx) and np.isfinite(dy) and dx > 0.0 and dy > 0.0):
        raise ValueError("AVAC frame grid centres must be finite and increasing.")
    padded = np.pad(values, 1, mode="edge")
    x_axis = np.concatenate(([x_centres[0] - 0.501 * dx], x_centres, [x_centres[-1] + 0.501 * dx]))
    y_axis = np.concatenate(([y_centres[0] - 0.501 * dy], y_centres, [y_centres[-1] + 0.501 * dy]))
    x0, y0, xmax, ymax = x_axis[0], y_axis[0], x_axis[-1], y_axis[-1]
    result = np.full(x.shape, np.nan, dtype=float)
    covered = (x >= x0) & (x <= xmax) & (y >= y0) & (y <= ymax)
    if not np.any(covered):
        return result
    x_values, y_values = x[covered], y[covered]
    x_index = np.clip(np.searchsorted(x_axis, x_values, side="right") - 1, 0, padded.shape[0] - 2)
    y_index = np.clip(np.searchsorted(y_axis, y_values, side="right") - 1, 0, padded.shape[1] - 2)
    x_weight = (x_values - x_axis[x_index]) / (x_axis[x_index + 1] - x_axis[x_index])
    y_weight = (y_values - y_axis[y_index]) / (y_axis[y_index + 1] - y_axis[y_index])
    result[covered] = (
        (1.0 - x_weight) * (1.0 - y_weight) * padded[x_index, y_index]
        + x_weight * (1.0 - y_weight) * padded[x_index + 1, y_index]
        + (1.0 - x_weight) * y_weight * padded[x_index, y_index + 1]
        + x_weight * y_weight * padded[x_index + 1, y_index + 1]
    )
    return result


def _sample_conserved_components(solution, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample h, hu and hv on all AMR patches without a SciPy dependency."""
    if not solution.states or any(np.asarray(state.q).ndim < 3 or np.asarray(state.q).shape[0] < 3 for state in solution.states):
        raise ValueError("AVAC frame does not contain depth and two momentum components.")
    x, y = np.asarray(x, dtype=float).reshape(-1), np.asarray(y, dtype=float).reshape(-1)
    if x.shape != y.shape:
        raise ValueError("AVAC shoreline sample coordinates must have matching shapes.")
    sampled = [np.full(x.shape, np.nan, dtype=float) for _ in range(3)]
    # Clawpack orders states from coarse to fine.  Later finite patch samples
    # replace earlier ones, exactly as VisClaw's grid_output_2d does.
    for state in solution.states:
        for component, values in enumerate(sampled):
            interpolated = _interpolate_patch_component(state, component, x, y)
            finite = np.isfinite(interpolated)
            values[finite] = interpolated[finite]
    return tuple(sampled)


def create_boundary_conditions(
    avac_root: str | Path,
    wave_root: str | Path,
    claw_source: str | Path,
    *,
    damping: float = .3,
    samples: int = 100,
    epsilon: float = 1e-6,
) -> WaveBoundarySummary:
    """Sample AVAC on the prepared lake shoreline and write internal sources.

    The legacy ``samples`` argument remains accepted for API compatibility but
    no longer controls the coupling resolution: shoreline faces follow the
    WAVE grid exactly.
    """
    del samples
    avac_root = Path(avac_root).resolve()
    wave_root = Path(wave_root).resolve()
    claw_source = Path(claw_source).resolve()
    output = avac_root / "AVAC" / "_output"
    if not any(output.glob("fort.q*")):
        raise ValueError("Completed AVAC source contains no fort.q frames for Wave coupling.")
    if not (claw_source / "clawpack" / "__init__.py").is_file():
        raise ValueError("Wave runtime is missing its validated Clawpack reader.")
    if str(claw_source) not in sys.path:
        sys.path.insert(0, str(claw_source))
    from clawpack.pyclaw.solution import Solution

    config = yaml.safe_load((wave_root / "impulse_configuration.yaml").read_text(encoding="utf-8"))
    if config.get("computation", {}).get("mode") != "internal_shoreline":
        raise ValueError("Prepared Wave scenario does not use internal shoreline coupling.")
    cell_size = float(config["computation"]["cell_size"])
    face_path = wave_root / str(config.get("coupling", {}).get("shoreline_faces", "CL/shoreline_faces.txt"))
    if not face_path.is_file():
        raise ValueError("Prepared Wave scenario is missing its shoreline-face definition.")
    faces = np.loadtxt(face_path, comments="#", ndmin=2)
    if faces.shape[1] != 7:
        raise ValueError("Prepared shoreline-face definition must contain seven columns.")

    avac_cfg = yaml.safe_load((avac_root / "AVAC" / "AVAC_configuration.yaml").read_text(encoding="utf-8"))
    fmt = avac_cfg.get("output", {}).get("output_format", "binary32")
    frames = sorted(
        int(path.name.replace("fort.q", ""))
        for path in output.glob("fort.q*")
        if path.name.replace("fort.q", "").isdigit()
    )
    if len(frames) < 2:
        raise ValueError("Wave coupling requires at least two numbered AVAC fort.q frames.")

    face_x, face_y = faces[:, 2], faces[:, 3]
    times: list[float] = []
    per_time: list[tuple[np.ndarray, np.ndarray]] = []
    all_cells: set[tuple[float, float]] = set()
    active_samples = 0
    replaced_samples = 0
    active_faces = np.zeros(len(faces), dtype=bool)
    for frame in frames:
        solution = Solution(frame, path=output, file_format=fmt)
        # Sample each conserved component independently.  ``grid_output_2d``
        # initializes its output with the shape of the requested points.  If
        # no AMR patch overlaps those points, a multi-component callback such
        # as ``lambda q: q`` therefore returns that 1-D placeholder rather
        # than a (components, points) array.  Indexing it produced scalar
        # samples and the Mauvoisin ``len() of unsized object`` failure.
        # Integer component callbacks preserve a point-sized vector both with
        # and without AVAC coverage, so uncovered early frames are correctly
        # converted to zero inflow by ``_source_rates``.
        h, hu, hv = _sample_conserved_components(solution, face_x, face_y)
        cells, rates, active, replaced = _source_rates(
            faces, h, hu, hv, damping=float(damping), cell_size=cell_size, epsilon=epsilon,
        )
        normal_flux = hu * faces[:, 4] + hv * faces[:, 5]
        active_faces |= np.isfinite(h) & np.isfinite(hu) & np.isfinite(hv) & (h > epsilon) & (normal_flux > epsilon)
        times.append(float(solution.t))
        active_samples += active
        replaced_samples += replaced
        mapping = {(float(x), float(y)): rate for (x, y), rate in zip(cells, rates)}
        per_time.append((cells, rates))
        all_cells.update(mapping)

    time_values = np.asarray(times, dtype=float)
    if not np.all(np.isfinite(time_values)) or np.any(np.diff(time_values) <= 0.0):
        raise ValueError("AVAC frame times for Wave coupling must be finite and strictly increasing.")
    if replaced_samples == len(faces) * len(frames):
        raise ValueError(
            "The prepared Wave shoreline is outside AVAC coverage in every output frame. "
            "Select an AVAC run for the same case and coordinate reference system."
        )
    ordered_cells = np.asarray(sorted(all_cells), dtype=float) if all_cells else np.empty((0, 2), dtype=float)
    cell_lookup = {(float(x), float(y)): index for index, (x, y) in enumerate(ordered_cells)}
    source_rates = np.zeros((len(times), len(ordered_cells), 3), dtype=float)
    for time_index, (cells, rates) in enumerate(per_time):
        for cell, rate in zip(cells, rates):
            source_rates[time_index, cell_lookup[(float(cell[0]), float(cell[1]))]] = rate

    coupling_dir = wave_root / "CL"
    coupling_dir.mkdir(exist_ok=True)
    for prior in coupling_dir.glob("*.npy"):
        prior.unlink()
    legacy_times = coupling_dir / "times.txt"
    if legacy_times.exists():
        legacy_times.unlink()
    inflow_path = wave_root / str(config.get("coupling", {}).get("inflow", "CL/internal_inflow.data"))
    _write_internal_inflow(inflow_path, time_values, ordered_cells, source_rates)
    np.savetxt(
        coupling_dir / "active_shoreline_faces.txt", faces[active_faces], fmt="%.12g",
        header="target_x target_y face_x face_y normal_into_lake_x normal_into_lake_y face_length",
    )
    water_density = float(config.get("rheology", {}).get("rho", 1000.0))
    injected_volume, momentum_x, momentum_y, physical_momentum_x, physical_momentum_y = _integrated_source_ledger(
        time_values, source_rates, water_density=water_density,
    )
    summary_data = {
        "source_avac_run": str(avac_root),
        "mode": "internal_shoreline",
        "source_format": 2,
        "frames": len(frames),
        "damping": float(damping),
        "shoreline_faces": int(len(faces)),
        "active_shoreline_faces": int(np.count_nonzero(active_faces)),
        "active_source_cells": int(len(ordered_cells)),
        "active_inflow_samples": int(active_samples),
        "outside_avac_coverage_zeroed": int(replaced_samples),
        "injected_water_volume_m3": injected_volume,
        "injected_depth_momentum_x_m4_s": momentum_x,
        "injected_depth_momentum_y_m4_s": momentum_y,
        "water_density_kg_m3": water_density,
        "injected_water_momentum_x_kg_m_s": physical_momentum_x,
        "injected_water_momentum_y_kg_m_s": physical_momentum_y,
    }
    (coupling_dir / "summary_config.yaml").write_text(yaml.safe_dump(summary_data, sort_keys=False), encoding="utf-8")
    return WaveBoundarySummary(
        times=tuple(times),
        active_samples=active_samples,
        outside_avac_coverage_zeroed=replaced_samples,
        shoreline_faces=int(len(faces)),
        active_source_cells=int(len(ordered_cells)),
        injected_water_volume_m3=injected_volume,
        injected_depth_momentum_x_m4_s=momentum_x,
        injected_depth_momentum_y_m4_s=momentum_y,
        injected_water_momentum_x_kg_m_s=physical_momentum_x,
        injected_water_momentum_y_kg_m_s=physical_momentum_y,
    )
