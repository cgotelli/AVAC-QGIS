#!/usr/bin/env python3
"""Create the three-case ISeeSnow scalar intercomparison figure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import shapefile


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "validation"))

from avac4qgis_validation.plot_style import (  # noqa: E402
    MODEL_COLORS,
    PAPER_COLORS,
    apply_paper_style,
    figure_size,
)


CASES = (
    ("IdealizedTopo", "Idealized Voellmy"),
    ("RealTopo", "Real-terrain Voellmy"),
    ("CoulombOnly", "Idealized Coulomb"),
)
METRICS = (
    ("runout_length_m", 1.0e-3, "Runout length (km)"),
    ("pft_peak_m", 1.0, "Peak flow thickness (m)"),
    ("pfv_peak_mps", 1.0, r"Peak flow velocity (m s$^{-1}$)"),
)


def read_ascii(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    header: dict[str, float] = {}
    with path.open(encoding="utf-8") as stream:
        for _ in range(6):
            key, value = stream.readline().split()[:2]
            header[key.lower()] = float(value)
        values_north = np.loadtxt(stream, dtype=float)
    cell = float(header["cellsize"])
    x0 = float(header.get("xllcenter", header.get("xllcorner", 0.0) + cell / 2.0))
    y0 = float(header.get("yllcenter", header.get("yllcorner", 0.0) + cell / 2.0))
    x = x0 + np.arange(int(header["ncols"])) * cell
    y = y0 + np.arange(int(header["nrows"])) * cell
    nodata = float(header.get("nodata_value", -9999.0))
    values_north[np.isclose(values_north, nodata)] = 0.0
    return x, y, values_north


def read_path(path: Path) -> np.ndarray:
    reader = shapefile.Reader(str(path))
    lines = [np.asarray(shape.points, dtype=float) for shape in reader.shapes() if len(shape.points) >= 2]
    if len(lines) != 1:
        raise ValueError(f"Expected one ISeeSnow thalweg in {path}, found {len(lines)}")
    return lines[0]


def along_path_coordinate(points: np.ndarray, path: np.ndarray) -> np.ndarray:
    """Project map points onto a polyline and return curvilinear distance."""
    starts, vectors = path[:-1], np.diff(path, axis=0)
    lengths = np.linalg.norm(vectors, axis=1)
    valid = lengths > 0.0
    starts, vectors, lengths = starts[valid], vectors[valid], lengths[valid]
    cumulative = np.concatenate(([0.0], np.cumsum(lengths[:-1])))
    projected = np.empty(points.shape[0], dtype=float)
    for start in range(0, points.shape[0], 4096):
        values = points[start:start + 4096]
        relative = values[:, None, :] - starts[None, :, :]
        fraction = np.sum(relative * vectors[None, :, :], axis=2) / lengths[None, :] ** 2
        fraction = np.clip(fraction, 0.0, 1.0)
        closest = starts[None, :, :] + fraction[:, :, None] * vectors[None, :, :]
        distance2 = np.sum((values[:, None, :] - closest) ** 2, axis=2)
        segment = np.argmin(distance2, axis=1)
        projected[start:start + values.shape[0]] = (
            cumulative[segment] + fraction[np.arange(values.shape[0]), segment] * lengths[segment]
        )
    return projected


def avac_runout(case: str, results_root: Path, threshold_m: float = 0.5) -> float:
    submission = results_root / case / "Submission"
    pft_path = next(submission.glob("*_AVAC4QGIS_pft.asc"))
    x, y, values_north = read_ascii(pft_path)
    active_rows, active_columns = np.nonzero(values_north > threshold_m)
    if active_rows.size == 0:
        return 0.0
    points = np.column_stack((x[active_columns], y[::-1][active_rows]))
    path = (
        REPO / "validation" / "_data" / "ISeeSnow" / "data" / case
        / "Inputs" / "LINES" / "path_aimec.shp"
    )
    return float(np.max(along_path_coordinate(points, read_path(path))))


def main(
    output: Path,
    stem: str,
    avac_label: str,
    results_root: Path,
    comparison_root: Path | None = None,
    comparison_label: str = "Before correction",
) -> None:
    apply_paper_style()
    root = results_root.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    fields = pd.read_csv(root / "field_summary.csv")
    comparison_root = comparison_root.expanduser().resolve() if comparison_root is not None else None
    comparison_fields = (
        pd.read_csv(comparison_root / "field_summary.csv")
        if comparison_root is not None else None
    )
    table_c1_path = Path(__file__).with_name("iseesnow_table_c1_core.csv")
    table_c1 = pd.read_csv(table_c1_path)

    fig, axes = plt.subplots(3, 3, figsize=figure_size(2, aspect=0.88), squeeze=False)
    rng = np.random.default_rng(4127)
    provenance: dict[str, object] = {
        "avac_field_source": str(root / "field_summary.csv"),
        "peer_scalar_source": str(table_c1_path),
        "peer_group": "ISeeSnow Table C1 core group",
        "runout_definition": "furthest thalweg coordinate with PFT > 0.5 m",
        "cases": {},
    }

    for row, (case, row_label) in enumerate(CASES):
        case_info: dict[str, object] = {}
        avac_fields = fields[(fields["case"] == case) & (fields["model"] == "AVAC4QGIS")]
        avac_values = {
            "runout_length_m": avac_runout(case, root),
            "pft_peak_m": float(avac_fields[avac_fields["variable"] == "pft"]["peak"].iloc[0]),
            "pfv_peak_mps": float(avac_fields[avac_fields["variable"] == "pfv"]["peak"].iloc[0]),
        }
        comparison_values = None
        if comparison_root is not None and comparison_fields is not None:
            old_fields = comparison_fields[
                (comparison_fields["case"] == case)
                & (comparison_fields["model"] == "AVAC4QGIS")
            ]
            comparison_values = {
                "runout_length_m": avac_runout(case, comparison_root),
                "pft_peak_m": float(old_fields[old_fields["variable"] == "pft"]["peak"].iloc[0]),
                "pfv_peak_mps": float(old_fields[old_fields["variable"] == "pfv"]["peak"].iloc[0]),
            }
        peers = table_c1[table_c1["case"] == case]
        for col, (field, scale, title) in enumerate(METRICS):
            ax = axes[row, col]
            peer_values = peers[field].to_numpy(float) * scale
            avac_value = avac_values[field] * scale
            q1, median, q3 = np.quantile(peer_values, [0.25, 0.5, 0.75])

            jitter = rng.uniform(-0.075, 0.075, peer_values.size)
            ax.fill_between([-0.18, 0.18], q1, q3, color=MODEL_COLORS["wave"], alpha=0.25, zorder=1)
            ax.hlines(median, -0.18, 0.18, color=MODEL_COLORS["wave"], linewidth=2.2, zorder=2)
            ax.scatter(jitter, peer_values, color=MODEL_COLORS["wave"], edgecolor="white", linewidth=0.6, zorder=3)
            avac_x = 2.0 if comparison_values is not None else 1.0
            ax.scatter([avac_x], [avac_value], color=MODEL_COLORS["avac"], marker="D", s=44,
                       edgecolor="white", linewidth=0.7, zorder=4)
            if comparison_values is not None:
                comparison_value = comparison_values[field] * scale
                ax.scatter([1.0], [comparison_value], color=PAPER_COLORS["green"], marker="o", s=42,
                           edgecolor="white", linewidth=0.7, zorder=4)
                ax.set_xlim(-0.45, 2.45)
                ax.set_xticks([0, 1, 2], ["Peers", "Before", "After"])
            else:
                ax.set_xlim(-0.40, 1.40)
                ax.set_xticks([0, 1], ["Peers", "AVAC"])
            if row == 0:
                ax.set_title(title)
            if col == 0:
                ax.set_ylabel(row_label)
            panel = chr(ord("a") + row * 3 + col)
            ax.text(0.02, 0.96, f"({panel})", transform=ax.transAxes,
                    ha="left", va="top", fontweight="bold")
            case_info[field] = {
                "peer_count": int(peer_values.size),
                "peer_q1": float(q1),
                "peer_median": float(median),
                "peer_q3": float(q3),
                "avac": avac_value,
            }
            if comparison_values is not None:
                case_info[field]["comparison"] = comparison_values[field] * scale
        provenance["cases"][case] = case_info

    handles = [
        Line2D([], [], marker="o", linestyle="None", color=MODEL_COLORS["wave"], label="ISeeSnow core models"),
        Patch(facecolor=MODEL_COLORS["wave"], alpha=0.25, edgecolor="none", label="Peer interquartile range"),
        Line2D([], [], color=MODEL_COLORS["wave"], linewidth=2.2, label="Peer median"),
        Line2D([], [], marker="D", linestyle="None", color=MODEL_COLORS["avac"], label=avac_label),
    ]
    if comparison_root is not None:
        handles.insert(
            -1,
            Line2D([], [], marker="o", linestyle="None", color=PAPER_COLORS["green"], label=comparison_label),
        )
    fig.legend(handles=handles, loc="outside lower center", ncol=4)
    fig.subplots_adjust(bottom=0.13, hspace=0.33, wspace=0.30)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"{stem}.{suffix}")
    plt.close(fig)
    provenance["avac_label"] = avac_label
    provenance["comparison_root"] = str(comparison_root) if comparison_root is not None else None
    provenance["comparison_label"] = comparison_label if comparison_root is not None else None
    (output / f"{stem}.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "docs" / "article" / "figures",
        help="Directory for the PDF, PNG, and provenance JSON.",
    )
    parser.add_argument(
        "--stem",
        default="iseesnow_intercomparison",
        help="Shared filename stem for the figure outputs.",
    )
    parser.add_argument(
        "--avac-label",
        default="AVAC4QGIS",
        help="Legend label for the AVAC marker.",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=REPO / "validation" / "ISeeSnow",
        help="Directory containing the three completed AVAC case folders and field_summary.csv.",
    )
    parser.add_argument(
        "--comparison-root",
        type=Path,
        help="Optional preserved result directory to show beside the current AVAC values.",
    )
    parser.add_argument(
        "--comparison-label",
        default="Before correction",
        help="Legend label for values read from --comparison-root.",
    )
    arguments = parser.parse_args()
    main(
        arguments.output,
        arguments.stem,
        arguments.avac_label,
        arguments.results_root,
        arguments.comparison_root,
        arguments.comparison_label,
    )
