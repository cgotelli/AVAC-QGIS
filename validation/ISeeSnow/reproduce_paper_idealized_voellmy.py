#!/usr/bin/env python3
"""Reproduce paper-style VoellmyIdealized maps with the AVAC4QGIS submission.

The figures follow the display conventions of egusphere-2025-6053 Fig. 2,
Fig. 3, and Fig. C2.  They are a transparent update, not a re-analysis of the
paper: every submitted raster is drawn at its native supplied coordinates and
no peer raster is resampled, shifted, clipped, or used to configure AVAC.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import shapefile

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parent
from avac4qgis_validation.datasets import ensure_iseesnow  # noqa: E402

BENCHMARK = ensure_iseesnow() / "data" / "IdealizedTopo"
sys.path.insert(0, str(ROOT))
from compare_iseesnow import Grid, clean, grid_extent, output_pairs, read_grid  # noqa: E402

OUTPUT = ROOT / "paper_figures" / "VoellmyIdealized"
PFT_CAP_M = 11.0
PFV_CAP_MPS = 42.0
DISPLAY_DRY = 0.01
CONTOUR_PFT_M = 0.5


MODEL_LABELS = {
    "TITAN2Dv420": "TITAN2D",
    "Gerris": "Gerris",
    "INRAEaval": "INRAEaval",
    "TRENT2D": "TRENT2D",
    "RAMMSUSER": "RAMMS::Avalanche",
    "avaflow": "r.avaflow",
    "com1DFA": "com1DFA",
    "minVoellmyv2": "minVoellmyv2",
    "samosat": "samosAT",
    "01IdealizedTopo_faSavageHutterFoamGamma": "faSavageHutterFoam",
    "flo2d": "FLO-2D",
    "MoT-Voellmy": "MoT-Voellmy",
    "AVAC4QGIS": "AVAC4QGIS",
}
MODEL_ORDER = (
    "com1DFA", "Gerris", "minVoellmyv2", "MoT-Voellmy", "avaflow",
    "RAMMSUSER", "samosat", "TITAN2Dv420", "TRENT2D",
    "01IdealizedTopo_faSavageHutterFoamGamma", "flo2d", "INRAEaval", "AVAC4QGIS",
)


def release_boundary(path: Path) -> list[np.ndarray]:
    shapes: list[np.ndarray] = []
    for shape in shapefile.Reader(str(path)).shapes():
        payload = shape.__geo_interface__
        polygons = [payload["coordinates"]] if payload["type"] == "Polygon" else payload.get("coordinates", [])
        shapes.extend(np.asarray(polygon[0], dtype=float) for polygon in polygons if polygon)
    if not shapes:
        raise ValueError("Release polygon has no exterior ring.")
    return shapes


def model_key(name: str) -> str:
    for key in MODEL_LABELS:
        if key.lower() in name.lower():
            return key
    raise ValueError(f"No paper display name configured for submitted model: {name}")


def gathered_fields() -> dict[str, dict[str, Grid]]:
    output = BENCHMARK / "Outputs_IdealizedTopo"
    fields: dict[str, dict[str, Grid]] = {}
    pairs, missing = output_pairs(output)
    if missing:
        raise ValueError(f"ISeeSnow IdealizedTopo has unmatched peak fields: {missing}")
    for name, pft, pfv in pairs:
        key = model_key(name)
        fields[key] = {"pft": read_grid(pft), "pfv": read_grid(pfv)}

    # The MoT-Voellmy submission predates the standardized pft/pfv suffixes.
    fields["MoT-Voellmy"] = {
        "pft": read_grid(output / "1HS_01_curv91s_MoT-Voellmy_h_max.asc"),
        "pfv": read_grid(output / "1HS_01_curv91s_MoT-Voellmy_s_max.asc"),
    }
    submission = ROOT / "IdealizedTopo" / "Submission"
    fields["AVAC4QGIS"] = {
        "pft": read_grid(next(submission.glob("*_AVAC4QGIS_pft.asc"))),
        "pfv": read_grid(next(submission.glob("*_AVAC4QGIS_pfv.asc"))),
    }
    missing_models = [key for key in MODEL_ORDER if key not in fields]
    if missing_models:
        raise ValueError(f"Missing source fields for: {', '.join(missing_models)}")
    return fields


def north_coordinates(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    return np.meshgrid(grid.x_centres, grid.y_centres[::-1])


def masked_field(grid: Grid, cap: float) -> np.ma.MaskedArray:
    values = np.asarray(grid.values_north, dtype=float)
    return np.ma.masked_where(~np.isfinite(values) | (values <= DISPLAY_DRY), values)


def panel_axis(axis, grid: Grid, values: np.ndarray, boundary: list[np.ndarray], *, cap: float, cmap, title: str, pft_for_outline: Grid | None = None):
    image = axis.imshow(
        np.ma.minimum(masked_field(grid, cap), cap), origin="upper", extent=grid_extent(grid),
        interpolation="none", cmap=cmap, vmin=DISPLAY_DRY, vmax=cap,
    )
    xx, yy = north_coordinates(grid)
    # The paper indicates values above the cap with a distinct over-range
    # colour. Hatch-free color keeps the panel readable at 5 m resolution.
    over = np.isfinite(values) & (values > cap)
    if np.any(over):
        axis.contourf(xx, yy, over.astype(float), levels=[0.5, 1.5], colors=["#24a148"], alpha=0.9)
    if pft_for_outline is not None:
        px, py = north_coordinates(pft_for_outline)
        pvalues = clean(pft_for_outline.values_north)
        if np.nanmax(pvalues) >= DISPLAY_DRY:
            axis.contour(px, py, pvalues, levels=[DISPLAY_DRY], colors=["#d62728"], linewidths=0.55)
    for ring in boundary:
        axis.plot(ring[:, 0], ring[:, 1], color="black", linewidth=0.55)
    axis.set_title(title, fontsize=8.3, fontweight="bold" if title == "AVAC4QGIS" else "normal")
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])
    return image


def figure_panels(fields: dict[str, dict[str, Grid]], boundary: list[np.ndarray], variable: str, path: Path) -> None:
    cap = PFT_CAP_M if variable == "pft" else PFV_CAP_MPS
    cmap = plt.colormaps["viridis"].copy()
    cmap.set_bad("white")
    title = "Peak flow thickness" if variable == "pft" else "Peak flow velocity"
    unit = "m (normal to terrain)" if variable == "pft" else "m/s"
    figure, axes = plt.subplots(4, 4, figsize=(13.5, 9.6), layout="constrained")
    image = None
    for index, key in enumerate(MODEL_ORDER):
        axis = axes.flat[index]
        item = fields[key]
        image = panel_axis(
            axis, item[variable], item[variable].values_north, boundary, cap=cap, cmap=cmap,
            title=MODEL_LABELS[key], pft_for_outline=item["pft"] if variable == "pfv" else None,
        )
    for axis in axes.flat[len(MODEL_ORDER):]:
        axis.axis("off")
    assert image is not None
    colorbar = figure.colorbar(image, ax=axes.flat[:len(MODEL_ORDER)], location="bottom", shrink=0.62, pad=0.025, extend="max")
    colorbar.set_label(f"{title} [{unit}]")
    extra = " Values above 11 m are green." if variable == "pft" else " Red contours: PFT = 0.01 m; values above 42 m/s are green."
    figure.suptitle(
        f"VoellmyIdealized - {title} fields, ISeeSnow paper-style update (AVAC4QGIS added).\n"
        f"Values <= {DISPLAY_DRY:g} are masked; every raster is displayed on its submitted native grid.{extra}",
        fontsize=12,
    )
    figure.savefig(path, dpi=240)
    plt.close(figure)


def figure_contours(fields: dict[str, dict[str, Grid]], boundary: list[np.ndarray], path: Path) -> None:
    target = fields["AVAC4QGIS"]["pft"]
    figure, axis = plt.subplots(figsize=(11.5, 4.8), layout="constrained")
    colors = plt.colormaps["tab20"](np.linspace(0, 1, len(MODEL_ORDER)))
    handles, labels = [], []
    for color, key in zip(colors, MODEL_ORDER):
        grid = fields[key]["pft"]
        values = clean(grid.values_north)
        if not np.any(values >= CONTOUR_PFT_M):
            continue
        xx, yy = north_coordinates(grid)
        contour = axis.contour(xx, yy, values, levels=[CONTOUR_PFT_M], colors=[color], linewidths=2.0 if key == "AVAC4QGIS" else 0.95)
        handles.append(contour.legend_elements()[0][0])
        labels.append(MODEL_LABELS[key])
    for ring in boundary:
        axis.plot(ring[:, 0], ring[:, 1], color="black", linewidth=1.0, label="release polygon")
    axis.set_xlim(grid_extent(target)[:2]); axis.set_ylim(grid_extent(target)[2:])
    axis.set_aspect("equal")
    axis.set_xlabel("Local easting [m]")
    axis.set_ylabel("Local northing [m]")
    axis.set_title("VoellmyIdealized - 0.5 m peak-flow-thickness contours (paper Fig. 3 style)")
    handles.append(plt.Line2D([], [], color="black", linewidth=1.0)); labels.append("release polygon")
    axis.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4, fontsize=8, frameon=False)
    axis.text(0.01, 0.02, "Contours use every submitted grid directly; no resampling or spatial adjustment.", transform=axis.transAxes, fontsize=8, va="bottom")
    figure.savefig(path, dpi=240, bbox_inches="tight")
    plt.close(figure)


def write_report(fields: dict[str, dict[str, Grid]], paths: list[Path]) -> None:
    rows = []
    for key in MODEL_ORDER:
        item = fields[key]
        pft, pfv = clean(item["pft"].values_north), clean(item["pfv"].values_north)
        rows.append({
            "model": MODEL_LABELS[key],
            "pft_source": str(item["pft"].path), "pfv_source": str(item["pfv"].path),
            "pft_shape": list(item["pft"].values_north.shape), "pfv_shape": list(item["pfv"].values_north.shape),
            "pft_peak_m": float(np.max(pft)), "pfv_peak_mps": float(np.max(pfv)),
        })
    (OUTPUT / "source_manifest.json").write_text(json.dumps({
        "purpose": "Paper-style VoellmyIdealized figures with AVAC4QGIS added",
        "display_rules": {
            "pft_cap_m": PFT_CAP_M, "pfv_cap_mps": PFV_CAP_MPS,
            "mask_below_or_equal": DISPLAY_DRY, "pft_contour_m": CONTOUR_PFT_M,
            "resampling": "none", "spatial_adjustment": "none",
        },
        "figures": [str(path.name) for path in paths], "fields": rows,
    }, indent=2) + "\n", encoding="utf-8")
    report = [
        "# VoellmyIdealized paper-style figures with AVAC4QGIS", "",
        "These figures update the display conventions of Figure 2, Figure 3, and Appendix Figure C2 in `egusphere-2025-6053.pdf` using the ISeeSnow result files delivered with this repository and the AVAC4QGIS submission.", "",
        "## Method", "",
        "- The AVAC4QGIS PFT is the submitted normal-to-terrain peak thickness; PFV is the submitted peak speed.",
        "- Every peer raster is read and drawn at its submitted native grid coordinates. No field is resampled, shifted, clipped, padded, or used to configure AVAC.",
        "- The PFT panels cap display at 11 m and mask values at or below 0.01 m. The PFV panels cap display at 42 m/s, mask values at or below 0.01 m/s, and show the corresponding PFT = 0.01 m contour in red. Values above a display cap appear green.",
        "- The contour figure uses PFT = 0.5 m. It is an overlay rather than a calculation of the paper's thalweg-based runout metrics.", "",
        "## Files", "",
    ]
    report.extend([f"- [{path.name}]({path.name})" for path in paths])
    report.extend(["", "## Source audit", "", "| model | PFT grid | PFV grid | PFT peak [m] | PFV peak [m/s] |", "| --- | --- | --- | ---: | ---: |"])
    for row in rows:
        report.append(f"| {row['model']} | {row['pft_shape']} | {row['pfv_shape']} | {row['pft_peak_m']:.5g} | {row['pfv_peak_mps']:.5g} |")
    (OUTPUT / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fields = gathered_fields()
    boundary = release_boundary(BENCHMARK / "Inputs" / "release1HS.shp")
    paths = [
        OUTPUT / "Figure_2_style_VoellmyIdealized_PFT_with_AVAC4QGIS.png",
        OUTPUT / "Figure_3_style_VoellmyIdealized_PFT_0p5m_contours_with_AVAC4QGIS.png",
        OUTPUT / "Figure_C2_style_VoellmyIdealized_PFV_with_AVAC4QGIS.png",
    ]
    figure_panels(fields, boundary, "pft", paths[0])
    figure_contours(fields, boundary, paths[1])
    figure_panels(fields, boundary, "pfv", paths[2])
    write_report(fields, paths)
    print("\n".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
