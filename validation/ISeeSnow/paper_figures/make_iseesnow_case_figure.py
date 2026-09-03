#!/usr/bin/env python3
"""Create an original three-case ISeeSnow setup figure from supplied inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LightSource
import numpy as np
import shapefile


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "validation"))

from avac4qgis_validation.plot_style import (  # noqa: E402
    PAPER_COLORS,
    apply_paper_style,
    figure_size,
)


CASES = (
    ("IdealizedTopo", "DEM_IdealizedTopo.asc", "release1HS.shp", "Voellmy idealized", r"$\mu=0.4$, $\xi=2000$ m s$^{-2}$"),
    ("RealTopo", "DEM_RealTopo.asc", "relWog.shp", "Voellmy real terrain", r"$\mu=0.2$, $\xi=2000$ m s$^{-2}$"),
    ("CoulombOnly", "DEM_CoulombOnly.asc", "release1HS.shp", "Coulomb idealized", r"$\mu=0.4$, no velocity drag"),
)


def read_ascii(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    header: dict[str, float] = {}
    with path.open(encoding="utf-8") as stream:
        for _ in range(6):
            key, value = stream.readline().split()[:2]
            header[key.lower()] = float(value)
        values = np.loadtxt(stream, dtype=float)
    cell = header["cellsize"]
    x0 = header.get("xllcenter", header.get("xllcorner", 0.0) + cell / 2.0)
    y0 = header.get("yllcenter", header.get("yllcorner", 0.0) + cell / 2.0)
    x = x0 + np.arange(int(header["ncols"])) * cell
    y = y0 + np.arange(int(header["nrows"])) * cell
    nodata = header.get("nodata_value", -9999.0)
    values = np.where(np.isclose(values, nodata), np.nan, values)
    return x, y, values


def release_rings(path: Path) -> list[np.ndarray]:
    rings: list[np.ndarray] = []
    for shape in shapefile.Reader(str(path)).shapes():
        points = np.asarray(shape.points, dtype=float)
        parts = list(shape.parts) + [len(points)]
        rings.extend(points[start:stop] for start, stop in zip(parts[:-1], parts[1:]))
    return rings


def main(results_root: Path = REPO / "validation" / "ISeeSnow") -> None:
    apply_paper_style()
    results_root = results_root.expanduser().resolve()
    cmap = LinearSegmentedColormap.from_list(
        "avac_terrain",
        ["#DDEBF7", "#B8D8C0", "#F4E4A6", "#F4B183", "#C77C6A"],
    )
    light = LightSource(azdeg=315, altdeg=35)
    hillshade_alpha = 0.24
    output = REPO / "docs" / "article" / "figures"
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=figure_size(2, aspect=0.42), constrained_layout=True)
    provenance: dict[str, object] = {}

    for label, axis, (folder, dem_name, release_name, title, parameters) in zip("abc", axes, CASES):
        inputs = results_root / folder / "Inputs"
        x, y, elevation_north = read_ascii(inputs / dem_name)
        elevation = np.flipud(elevation_north)
        x0, y0 = float(x[0]), float(y[0])
        x_km = (x - x0) / 1000.0
        y_km = (y - y0) / 1000.0
        finite = elevation[np.isfinite(elevation)]
        levels = np.linspace(float(np.percentile(finite, 2)), float(np.percentile(finite, 98)), 13)
        image = axis.contourf(
            x_km, y_km, elevation, levels=levels, cmap=cmap, extend="both", zorder=0,
        )
        # Retain the elevation palette and add only a semi-transparent relief
        # layer. Grid spacing is supplied in metres so illumination reflects
        # the physical DEM slopes rather than the plotted kilometre axes.
        cell_size = float(abs(x[1] - x[0]))
        shade_elevation = np.where(np.isfinite(elevation), elevation, np.nanmedian(elevation))
        hillshade = light.hillshade(
            shade_elevation, vert_exag=1.0, dx=cell_size, dy=cell_size,
        )
        hillshade = np.ma.masked_where(~np.isfinite(elevation), hillshade)
        axis.imshow(
            hillshade,
            extent=(float(x_km[0]), float(x_km[-1]), float(y_km[0]), float(y_km[-1])),
            origin="lower",
            cmap="gray",
            vmin=0.0,
            vmax=1.0,
            alpha=hillshade_alpha,
            interpolation="bilinear",
            aspect="auto",
            zorder=1,
        )
        axis.contour(x_km, y_km, elevation, levels=levels[::2], colors=PAPER_COLORS["ink"],
                     linewidths=0.35, alpha=0.60, zorder=2)
        for ring in release_rings(inputs / release_name):
            axis.fill((ring[:, 0] - x0) / 1000.0, (ring[:, 1] - y0) / 1000.0,
                      facecolor=PAPER_COLORS["red"], edgecolor=PAPER_COLORS["ink"],
                      linewidth=0.65, alpha=0.82, zorder=3)
        axis.set_title(f"{title}\n{parameters}")
        axis.set_xlabel("Local easting (km)")
        axis.set_ylabel("Local northing (km)")
        axis.set_aspect("equal")

        colorbar = fig.colorbar(image, ax=axis, location="bottom", shrink=0.80, pad=0.16,
                               ticks=np.linspace(levels[0], levels[-1], 5))
        colorbar.set_label("Elevation (m)")
        colorbar.ax.tick_params(labelsize=7.2)
        provenance[folder] = {
            "dem": str(inputs / dem_name),
            "release": str(inputs / release_name),
            "release_thickness_normal_m": 1.5,
            "parameters": parameters,
            "hillshade": {
                "azimuth_degrees": 315,
                "altitude_degrees": 35,
                "vertical_exaggeration": 1.0,
                "overlay_alpha": hillshade_alpha,
            },
        }

    for suffix in ("pdf", "png"):
        fig.savefig(output / f"iseesnow_case_setup.{suffix}")
    plt.close(fig)
    (output / "iseesnow_case_setup.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "cases": len(CASES)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=REPO / "validation" / "ISeeSnow",
        help="Directory containing the completed ISeeSnow case folders and their copied Inputs.",
    )
    main(parser.parse_args().results_root)
