#!/usr/bin/env python3
"""Compare AVAC4QGIS ISeeSnow submissions with the supplied peer outputs.

This is deliberately a *same-grid* comparison. It never shifts, clips, pads,
or resamples another model's submission. A peer raster is included only where
its dimensions, cell size, and cell-centre coordinates equal the supplied
ISeeSnow input grid exactly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
import rasterio

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parent
from avac4qgis_validation.datasets import ensure_iseesnow  # noqa: E402

BENCHMARK = ensure_iseesnow() / "data"
CASES = ("IdealizedTopo", "RealTopo", "CoulombOnly")


@dataclass(frozen=True)
class Grid:
    path: Path
    values_north: np.ndarray
    x_centres: np.ndarray
    y_centres: np.ndarray
    cell_size: float


def ascii_grid(path: Path) -> Grid:
    header: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        for _ in range(6):
            key, value = handle.readline().split()[:2]
            header[key.lower()] = float(value)
    values = np.atleast_2d(np.loadtxt(path, skiprows=6, dtype=float))
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    if values.shape != (nrows, ncols):
        raise ValueError(f"declared shape {(nrows, ncols)} differs from {values.shape}")
    cell = float(header["cellsize"])
    x0 = float(header.get("xllcenter", header.get("xllcorner", 0.0) + cell / 2.0))
    y0 = float(header.get("yllcenter", header.get("yllcorner", 0.0) + cell / 2.0))
    nodata = header.get("nodata_value", math.nan)
    if np.isfinite(nodata):
        values[np.isclose(values, nodata)] = np.nan
    return Grid(path, values, x0 + np.arange(ncols) * cell, y0 + np.arange(nrows) * cell, cell)


def gdal_grid(path: Path) -> Grid:
    with rasterio.open(path) as dataset:
        transform = dataset.transform
        if transform.b != 0.0 or transform.d != 0.0 or transform.a <= 0.0 or transform.e >= 0.0:
            raise ValueError("requires a north-up, square-pixel raster")
        values = np.asarray(dataset.read(1), dtype=float)
        nodata = dataset.nodata
        width, height = dataset.width, dataset.height
    if not np.isclose(transform.a, -transform.e):
        raise ValueError("requires a north-up, square-pixel raster")
    if nodata is not None and np.isfinite(nodata):
        values[np.isclose(values, nodata)] = np.nan
    cell = float(transform.a)
    x = float(transform.c) + (0.5 + np.arange(width)) * cell
    # The first stored row is north. y_centres remains south-to-north for
    # coordinate checks, while values retains north-to-south order.
    y_top = float(transform.f) + 0.5 * float(transform.e)
    y = y_top + np.arange(height - 1, -1, -1) * float(transform.e)
    return Grid(path, values, x, y, cell)


def read_grid(path: Path) -> Grid:
    # One supplied MPM peer submission is an ESRI ASCII file without a suffix.
    # Detect the text header instead of excluding it merely for that filename.
    try:
        return ascii_grid(path)
    except (OSError, ValueError, UnicodeDecodeError):
        return gdal_grid(path)


def same_grid(candidate: Grid, target: Grid) -> tuple[bool, str]:
    if candidate.values_north.shape != target.values_north.shape:
        return False, f"shape {candidate.values_north.shape}, expected {target.values_north.shape}"
    if not np.isclose(candidate.cell_size, target.cell_size, rtol=0.0, atol=1e-8):
        return False, f"cell size {candidate.cell_size:g}, expected {target.cell_size:g}"
    if not np.allclose(candidate.x_centres, target.x_centres, rtol=0.0, atol=1e-8):
        return False, "X cell centres differ"
    if not np.allclose(candidate.y_centres, target.y_centres, rtol=0.0, atol=1e-8):
        return False, "Y cell centres differ"
    return True, ""


def model_name(stem: str) -> str:
    match = re.search(r"_null_(.+)$", stem, flags=re.IGNORECASE)
    return match.group(1) if match else stem.rsplit("_", 1)[-1]


def output_pairs(output_dir: Path) -> tuple[list[tuple[str, Path, Path]], list[dict[str, str]]]:
    pairs: list[tuple[str, Path, Path]] = []
    exclusions: list[dict[str, str]] = []
    files = set(output_dir.glob("*_pft")) | set(output_dir.glob("*_pft.asc")) | set(output_dir.glob("*_pft.tif")) | set(output_dir.glob("*_pft.tiff"))
    for pft in sorted(files):
        suffix = pft.suffix
        name_without_suffix = pft.name[:-len(suffix)] if suffix else pft.name
        stem = re.sub(r"_pft$", "", name_without_suffix, flags=re.IGNORECASE)
        alternatives = [pft.with_name(f"{stem}_pfv{extension}") for extension in ("", ".asc", ".tif", ".tiff")]
        pfv = next((item for item in alternatives if item.is_file()), None)
        if pfv is None:
            exclusions.append({"case": output_dir.parent.name, "model": model_name(stem), "reason": "pft exists but matching pfv is absent"})
        else:
            pairs.append((model_name(stem), pft, pfv))
    return pairs, exclusions


def clean(values: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(values) & (values > 0.0), values, 0.0)


def scalar_metrics(values: np.ndarray, cell: float, variable: str) -> dict[str, float]:
    field = clean(values)
    threshold = 0.01 if variable == "pft" else 1.0
    return {
        "peak": float(np.max(field)),
        "positive_area_m2": float(np.count_nonzero(field > threshold) * cell * cell),
        "field_integral": float(np.sum(field) * cell * cell),
    }


def avac_speed_limit(case_dir: Path) -> float | None:
    """Read the packaged GeoClaw runtime's solver-level speed limit."""
    path = case_dir / "Run" / "AVAC" / "_output" / "geoclaw.data"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=: speed_limit" in line:
            try:
                return float(line.split("=:", 1)[0].strip())
            except ValueError:
                return None
    return None


def pair_metrics(avac: np.ndarray, peer: np.ndarray, cell: float, variable: str) -> dict[str, float]:
    left, right = clean(avac), clean(peer)
    difference = left - right
    threshold = 0.01 if variable == "pft" else 1.0
    support_left, support_right = left > threshold, right > threshold
    union = np.count_nonzero(support_left | support_right)
    intersection = np.count_nonzero(support_left & support_right)
    active = support_left | support_right
    if np.count_nonzero(active) > 1 and np.std(left[active]) > 0.0 and np.std(right[active]) > 0.0:
        correlation = float(np.corrcoef(left[active], right[active])[0, 1])
    else:
        correlation = math.nan
    return {
        "mae": float(np.mean(np.abs(difference))),
        "rmse": float(np.sqrt(np.mean(difference**2))),
        "support_iou": float(intersection / union) if union else 1.0,
        "active_correlation": correlation,
        "avac_peak": float(np.max(left)),
        "peer_peak": float(np.max(right)),
        "avac_positive_area_m2": float(np.count_nonzero(support_left) * cell * cell),
        "peer_positive_area_m2": float(np.count_nonzero(support_right) * cell * cell),
        "avac_field_integral": float(np.sum(left) * cell * cell),
        "peer_field_integral": float(np.sum(right) * cell * cell),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({field for row in rows for field in row}) if rows else ["case", "model", "reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def table(rows: list[dict[str, object]], fields: list[str]) -> list[str]:
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows:
        values = []
        for field in fields:
            value = row.get(field, "")
            values.append(f"{value:.5g}" if isinstance(value, float) else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def grid_extent(grid: Grid) -> tuple[float, float, float, float]:
    half = grid.cell_size / 2.0
    return (
        float(grid.x_centres[0] - half), float(grid.x_centres[-1] + half),
        float(grid.y_centres[0] - half), float(grid.y_centres[-1] + half),
    )


def finite_max(*fields: np.ndarray) -> float:
    values = [float(np.nanmax(np.where(np.isfinite(field), field, np.nan))) for field in fields if np.any(np.isfinite(field))]
    maximum = max(values, default=0.0)
    return maximum if maximum > 0.0 else 1.0


def comparison_display_max(avac: np.ndarray, peers: np.ndarray) -> tuple[float, float]:
    """Return an honest but readable map limit and the uncapped maximum.

    An isolated velocity outlier must remain visible in metrics and the report,
    but allowing one value to set the full color range can make every other
    value indistinguishable from zero. Only the visualization is capped, at no
    less than the largest peer value and the AVAC 99th percentile of positive
    cells. Ordinary fields retain their full range.
    """
    raw_max = finite_max(avac, peers)
    positive = avac[np.isfinite(avac) & (avac > 0.0)]
    avac_robust = float(np.percentile(positive, 99.0)) if positive.size else 0.0
    peer_max = finite_max(peers)
    candidate = max(avac_robust, peer_max)
    if candidate > 0.0 and raw_max > 10.0 * candidate:
        return candidate, raw_max
    return raw_max, raw_max


def fgmax_peak_velocity_audit(case_dir: Path, dem: Grid) -> dict[str, float] | None:
    """Audit the native velocity maximum without classifying it a priori."""
    path = case_dir / "Run" / "AVAC" / "_output" / "fgmax0001.txt"
    if not path.is_file():
        return None
    values = np.atleast_2d(np.loadtxt(path, dtype=float))
    if values.shape[1] < 8:
        return None
    index = int(np.nanargmax(values[:, 5]))
    x_peak, y_peak = float(values[index, 0]), float(values[index, 1])
    terrain = np.flipud(np.asarray(dem.values_north, dtype=float))
    if np.any(~np.isfinite(terrain)):
        terrain = np.where(np.isfinite(terrain), terrain, float(np.nanmean(terrain)))
    dz_dy, dz_dx = np.gradient(terrain, dem.cell_size)
    column = int(np.argmin(np.abs(dem.x_centres - x_peak)))
    row = int(np.argmin(np.abs(dem.y_centres - y_peak)))
    slope = np.degrees(np.arctan(np.hypot(dz_dx[row, column], dz_dy[row, column])))
    return {
        "fgmax_peak_velocity_mps": float(values[index, 5]),
        "fgmax_peak_velocity_time_s": float(values[index, 7]),
        "fgmax_peak_velocity_x_m": x_peak,
        "fgmax_peak_velocity_y_m": y_peak,
        "maximum_depth_at_peak_cell_m": float(values[index, 4]),
        "local_dem_slope_degrees": float(slope),
        "kinetic_head_at_peak_m": float(values[index, 5] ** 2 / (2.0 * 9.81)),
    }


def map_axis(axis: plt.Axes, values: np.ndarray, grid: Grid, title: str, *, cmap: str, vmin: float, vmax: float, label: str) -> None:
    image = axis.imshow(
        values, origin="upper", extent=grid_extent(grid), interpolation="none",
        cmap=cmap, vmin=vmin, vmax=vmax,
    )
    axis.set_title(title)
    axis.set_xlabel("Easting [m]")
    axis.set_ylabel("Northing [m]")
    axis.set_aspect("equal")
    axis.figure.colorbar(image, ax=axis, shrink=0.76, label=label)


def write_case_pngs(case: str, target: Grid, avac: dict[str, Grid], peers: dict[str, dict[str, Grid]], output: Path) -> list[Path]:
    """Write direct AVAC-versus-peer ensemble maps and scalar comparisons.

    Every displayed peer field has already passed ``same_grid``.  The peer
    reference is the cell-wise median and its interquartile range; it is a
    display-only summary, not an input to AVAC or to the reported metrics.
    """
    if not peers:
        return []
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    units = {"pft": "Peak normal thickness [m]", "pfv": "Peak velocity [m/s]"}
    pretty = {"pft": "peak flow thickness", "pfv": "peak flow velocity"}
    for variable in ("pft", "pfv"):
        peer_stack = np.stack([clean(item[variable].values_north) for item in peers.values()])
        peer_median = np.median(peer_stack, axis=0)
        peer_iqr = np.percentile(peer_stack, 75.0, axis=0) - np.percentile(peer_stack, 25.0, axis=0)
        avac_field = clean(avac[variable].values_north)
        difference = avac_field - peer_median
        shared_max, raw_max = comparison_display_max(avac_field, peer_stack)
        difference_max, raw_difference_max = comparison_display_max(
            np.abs(difference), np.abs(peer_stack - peer_median)
        )
        spread_max = finite_max(peer_iqr)
        figure, axes = plt.subplots(1, 4, figsize=(20, 5.4), layout="constrained")
        map_axis(axes[0], avac_field, target, "AVAC4QGIS", cmap="viridis", vmin=0.0, vmax=shared_max, label=units[variable])
        map_axis(axes[1], peer_median, target, f"Peer median (n={len(peers)})", cmap="viridis", vmin=0.0, vmax=shared_max, label=units[variable])
        map_axis(axes[2], difference, target, "AVAC4QGIS − peer median", cmap="coolwarm", vmin=-difference_max, vmax=difference_max, label=f"Difference [{units[variable].split('[')[-1]}")
        map_axis(axes[3], peer_iqr, target, "Peer interquartile range", cmap="magma", vmin=0.0, vmax=spread_max, label=units[variable])
        cap_note = ""
        if shared_max < raw_max or difference_max < raw_difference_max:
            cap_note = (
                f"\nDisplay capped at {shared_max:.4g} {units[variable].split('[')[-1].rstrip(']')}; "
                f"raw AVAC maximum = {raw_max:.6g}. Raw values and metrics are unchanged."
            )
        figure.suptitle(
            f"{case}: {pretty[variable]} comparison on the supplied ISeeSnow grid{cap_note}",
            fontsize=13,
        )
        path = output / f"{case}_{variable}_peer_comparison.png"
        figure.savefig(path, dpi=180)
        plt.close(figure)
        written.append(path)

    names = ["AVAC4QGIS", *peers]
    metrics: dict[str, dict[str, list[float]]] = {"pft": {"peak": [], "area": []}, "pfv": {"peak": [], "area": []}}
    all_fields = {"AVAC4QGIS": avac, **peers}
    for variable in ("pft", "pfv"):
        for model in names:
            measure = scalar_metrics(all_fields[model][variable].values_north, target.cell_size, variable)
            metrics[variable]["peak"].append(measure["peak"])
            metrics[variable]["area"].append(measure["positive_area_m2"] / 1.0e6)
    figure, axes = plt.subplots(2, 2, figsize=(14, 8), layout="constrained")
    x = np.arange(len(names))
    color = ["#1f77b4", *["#8c8c8c"] * len(peers)]
    for row, variable in enumerate(("pft", "pfv")):
        axes[row, 0].bar(x, metrics[variable]["peak"], color=color)
        axes[row, 0].set_title(f"{variable.upper()} peak")
        axes[row, 0].set_ylabel("m" if variable == "pft" else "m/s")
        positive_peaks = [value for value in metrics[variable]["peak"] if value > 0.0]
        if positive_peaks and max(positive_peaks) / min(positive_peaks) > 50.0:
            axes[row, 0].set_yscale("log")
            axes[row, 0].set_title(f"{variable.upper()} peak (log scale; raw values)")
        axes[row, 1].bar(x, metrics[variable]["area"], color=color)
        axes[row, 1].set_title(f"{variable.upper()} positive area")
        axes[row, 1].set_ylabel("km²")
        for axis in axes[row]:
            axis.set_xticks(x, names, rotation=40, ha="right")
            axis.grid(axis="y", alpha=0.25)
    figure.suptitle(f"{case}: AVAC4QGIS and supplied comparable peer outputs", fontsize=13)
    path = output / f"{case}_scalar_peer_comparison.png"
    figure.savefig(path, dpi=180)
    plt.close(figure)
    written.append(path)
    return written


def main(cases: tuple[str, ...] = CASES) -> None:
    comparison_rows: list[dict[str, object]] = []
    scalar_rows: list[dict[str, object]] = []
    exclusions: list[dict[str, str]] = []
    report = [
        "# AVAC4QGIS ISeeSnow peer comparison", "",
        "This is a direct comparison with the official ISeeSnow 1.0 model outputs. "
        "No reference output was used to configure AVAC, and no raster was shifted, clipped, "
        "padded, or resampled. All metrics use the complete supplied 5 m grid.", "",
        "`pft` is peak flow thickness normal to terrain. `pfv` is peak flow velocity. "
        "The field integral is a grid-cell sum (not an independently reconstructed volume).", "",
        "## Velocity formulation audited in this rerun", "",
        "AVAC stores vertical depth and horizontal map-grid momentum. The submitted PFV is "
        "the physical terrain-tangent magnitude sqrt(u^2 + v^2 + (u*Bx + v*By)^2), evaluated "
        "inside the native fgmax routine at every solver step. This is consistent with the "
        "terrain-tangent speed used by the slope-corrected Voellmy law and avoids reconstructing "
        "a vector direction from an already maximized scalar field.", "",
        "The velocity diagnostic requires a local depth above 0.05 m, an explicit "
        "cell-average velocity threshold of the type documented by the ISeeSnow protocol. "
        "No physical velocity ceiling or post-processing clipping is used.", "",
    ]
    speed_cap_rows: list[dict[str, object]] = []
    run_diagnostic_rows: list[dict[str, object]] = []
    velocity_audit_rows: list[dict[str, object]] = []
    peak_outlier_rows: list[dict[str, object]] = []
    plot_paths: list[Path] = []
    plot_directory = ROOT / "plots"
    for case in cases:
        case_dir = ROOT / case
        input_dem = next((case_dir / "Inputs").glob("DEM_*.asc"))
        target = read_grid(input_dem)
        submission = case_dir / "Submission"
        avac_pft = next(submission.glob("*_AVAC4QGIS_pft.asc"))
        avac_pfv = next(submission.glob("*_AVAC4QGIS_pfv.asc"))
        avac = {"pft": read_grid(avac_pft), "pfv": read_grid(avac_pfv)}
        for variable, item in avac.items():
            matches, reason = same_grid(item, target)
            if not matches:
                raise RuntimeError(f"AVAC submission {item.path}: {reason}")
            scalar_rows.append({"case": case, "model": "AVAC4QGIS", "variable": variable, **scalar_metrics(item.values_north, target.cell_size, variable)})
        velocity_audit = fgmax_peak_velocity_audit(case_dir, target)
        if velocity_audit is not None:
            velocity_audit_rows.append({"case": case, **velocity_audit})
        speed_limit = avac_speed_limit(case_dir)
        if speed_limit is not None:
            speed_cap_rows.append({
                "case": case, "runtime_speed_limit_mps": speed_limit,
                "submitted_pfv_cells_equal_limit": int(np.count_nonzero(np.isclose(clean(avac["pfv"].values_north), speed_limit))),
            })
        summary_path = case_dir / "run_summary.json"
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                initial_volume = float(summary["initial_volume_m3"])
                final_volume = float(summary["final_volume_m3"])
                run_diagnostic_rows.append({
                    "case": case,
                    "initial_volume_m3": initial_volume,
                    "final_volume_m3": final_volume,
                    "relative_volume_change": (final_volume - initial_volume) / initial_volume if initial_volume else math.nan,
                    "practical_rest_time_s": summary.get("flow_stopped_at_seconds") or "not reached",
                    "simulation_ceiling_s": summary.get("simulation_end_ceiling_seconds", ""),
                    "spatial_order": summary.get("spatial_order", ""),
                    "limiter": summary.get("limiter", ""),
                    "cfl_target": summary.get("cfl_target", ""),
                    "speed_limit_mps": summary.get("speed_limit_mps", ""),
                    "plugin_version": summary.get("plugin_version", ""),
                    "solver_sha256": summary.get("solver_sha256", ""),
                })
            except (OSError, ValueError, KeyError, TypeError) as exc:
                exclusions.append({"case": case, "model": "AVAC4QGIS", "reason": f"invalid run summary: {exc}"})
        output_dir = BENCHMARK / case / f"Outputs_{case}"
        pairs, missing = output_pairs(output_dir)
        exclusions.extend(missing)
        used_models: list[str] = []
        comparable_peers: dict[str, dict[str, Grid]] = {}
        for model, pft_path, pfv_path in pairs:
            peer = {"pft": read_grid(pft_path), "pfv": read_grid(pfv_path)}
            invalid = []
            for variable, item in peer.items():
                matches, reason = same_grid(item, target)
                if not matches:
                    invalid.append(f"{variable}: {reason}")
            if invalid:
                exclusions.append({"case": case, "model": model, "reason": "; ".join(invalid)})
                continue
            used_models.append(model)
            comparable_peers[model] = peer
            for variable, item in peer.items():
                scalar_rows.append({"case": case, "model": model, "variable": variable, **scalar_metrics(item.values_north, target.cell_size, variable)})
                comparison_rows.append({"case": case, "peer_model": model, "variable": variable, **pair_metrics(avac[variable].values_north, item.values_north, target.cell_size, variable)})
        if comparable_peers:
            for variable in ("pft", "pfv"):
                avac_peak = float(np.nanmax(clean(avac[variable].values_north)))
                peer_peak = max(
                    float(np.nanmax(clean(item[variable].values_north)))
                    for item in comparable_peers.values()
                )
                if peer_peak > 0.0 and avac_peak > 10.0 * peer_peak:
                    row: dict[str, object] = {
                        "case": case, "variable": variable,
                        "avac_raw_peak": avac_peak,
                        "maximum_comparable_peer_peak": peer_peak,
                        "ratio": avac_peak / peer_peak,
                    }
                    if variable == "pfv":
                        row.update(velocity_audit or {})
                    peak_outlier_rows.append(row)
        plot_paths.extend(write_case_pngs(case, target, avac, comparable_peers, plot_directory))
        report.extend([f"## {case}", "", f"Comparable peer submissions: {len(used_models)} — {', '.join(used_models) if used_models else 'none'}.", ""])
        case_rows = [row for row in comparison_rows if row["case"] == case]
        report.extend(table(case_rows, ["peer_model", "variable", "mae", "rmse", "support_iou", "active_correlation", "avac_peak", "peer_peak"]))
        report.append("")
    orders = {row.get("spatial_order") for row in run_diagnostic_rows}
    if orders == {1}:
        numerical_description = (
            "This rerun uses GeoClaw's first-order Godunov update (`spatial_order = 1`) as a conservative dry-front setting. "
            "No output raster was normalized, rescaled, shifted, clipped, padded, or matched to a peer result; the native mass histories below record the resulting solver behavior."
        )
    elif orders == {2}:
        numerical_description = (
            "This rerun uses GeoClaw's second-order update (`spatial_order = 2`) at the user's request. "
            "The AVAC dry-state update zeros momentum at and below the configured dry tolerance. "
            "The native mass histories below disclose the measured volume change and no result field was normalized, rescaled, shifted, clipped, padded, or matched to a peer result."
        )
    else:
        numerical_description = (
            "The completed cases use mixed or unavailable spatial-order settings; inspect the native mass diagnostics for each case. "
            "No result field was normalized, rescaled, shifted, clipped, padded, or matched to a peer result."
        )
    report.extend([
        "## Numerical configuration of this rerun", "", numerical_description, "",
        "## AVAC runtime speed limit", "",
        "`speed_limit` is applied by the compiled GeoClaw solver, not by post-processing. For this rerun it is set to `1.0e99 m/s`, so no practical velocity clipping occurs. "
        "The count should therefore be zero; it is retained as an auditable check of the data used for each comparison.", "",
    ])
    report.extend(table(speed_cap_rows, ["case", "runtime_speed_limit_mps", "submitted_pfv_cells_equal_limit"]))
    report.append("")
    report.extend([
        "## Native peak-velocity audit", "",
        "The raw fgmax occurrence is reported for every case. `maximum_depth_at_peak_cell_m` "
        "is the maximum depth attained at the same grid cell over the run, not necessarily the "
        "instantaneous depth at the velocity-peak time. A substantial value rules out a location "
        "that remained only a dry-tolerance film throughout the calculation.", "",
    ])
    report.extend(table(velocity_audit_rows, [
        "case", "fgmax_peak_velocity_mps", "fgmax_peak_velocity_time_s",
        "fgmax_peak_velocity_x_m", "fgmax_peak_velocity_y_m",
        "maximum_depth_at_peak_cell_m", "local_dem_slope_degrees",
        "kinetic_head_at_peak_m",
    ]))
    report.append("")
    report.extend([
        "## Native mass and completion diagnostics", "",
        "Volumes are summed from native level-one GeoClaw state cells, rather than from interpolated map outputs. "
        "The practical rest time requires moving volume at or below 1% of the initial release for three consecutive 10 s outputs; it is not inferred from a single residual cell's speed.", "",
    ])
    report.extend(table(run_diagnostic_rows, [
        "case", "initial_volume_m3", "final_volume_m3", "relative_volume_change",
        "practical_rest_time_s", "simulation_ceiling_s", "spatial_order", "limiter", "cfl_target", "speed_limit_mps",
        "plugin_version", "solver_sha256",
    ]))
    report.append("")
    report.extend([
        "## Raw peak outlier audit", "",
        "This audit is based on the unmodified submitted fields. A listed peak is more than ten times the largest exactly aligned peer peak. "
        "Figures may cap only their color scale so the peer fields remain visible; CSV values, raster values, and numerical metrics are never clipped.", "",
    ])
    if peak_outlier_rows:
        report.extend(table(peak_outlier_rows, [
            "case", "variable", "avac_raw_peak", "maximum_comparable_peer_peak", "ratio",
            "fgmax_peak_velocity_time_s", "fgmax_peak_velocity_x_m", "fgmax_peak_velocity_y_m",
        ]))
        report.extend(["", "Any listed event must be classified from its raw peak depth, location, and time before it is interpreted as a numerical dry-front value."])
    else:
        report.append("None.")
    report.append("")
    write_csv(ROOT / "peer_field_comparison.csv", comparison_rows)
    write_csv(ROOT / "field_summary.csv", scalar_rows)
    write_csv(ROOT / "comparison_exclusions.csv", exclusions)
    write_csv(ROOT / "avac_runtime_speed_limit.csv", speed_cap_rows)
    write_csv(ROOT / "avac_run_diagnostics.csv", run_diagnostic_rows)
    write_csv(ROOT / "peak_velocity_audit.csv", velocity_audit_rows)
    report.extend(["## PNG comparisons", ""])
    if plot_paths:
        report.extend([f"- [{path.name}]({path.relative_to(ROOT).as_posix()})" for path in plot_paths])
    else:
        report.append("No comparable peer grids were available for plotting.")
    report.append("")
    report.extend(["## Excluded supplied outputs", ""])
    report.extend(table(exclusions, ["case", "model", "reason"]) if exclusions else ["None."])
    report.append("")
    (ROOT / "comparison_report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"comparisons": len(comparison_rows), "exclusions": len(exclusions)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    arguments = parser.parse_args()
    selected = CASES if arguments.case == "all" else (arguments.case,)
    main(selected)
