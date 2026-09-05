#!/usr/bin/env python3
"""Authenticated Coulomb downstream peak-field profiles, without fitted shifts.

The cross-source comparison supplies the provenance and protocol gates. This
figure is a scientific diagnostic, not a replacement for article certification
or the stricter same-source limiter selection. Raster fields are never shifted
or resampled. Only the reference thalweg is interpolated to DEM column centres
to select the nearest DEM row for the displayed terrain profile.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO = Path(__file__).resolve().parents[3]
CASE = "CoulombOnly"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--allow-protocol-differences", action="store_true",
                        help="allow explicitly labelled unmatched diagnostics, never final equivalence")
    return parser.parse_args(argv)


def modules() -> tuple[Any, Any, Any, Any]:
    for relative in ("", "validation", "validation/ISeeSnow", "validation/ISeeSnow/paper_figures"):
        sys.path.insert(0, str(REPO / relative))
    return tuple(importlib.import_module(name) for name in (
        "compare_source_runs", "compare_iseesnow", "rank_coulomb_pft_candidates", "make_iseesnow_figures"))


def authenticated_grid(record: dict, source: Any, comparison: Any) -> Any:
    """Reopen a previously authenticated field with before/after identity checks."""
    path = Path(record["path"])
    source.artifact(path, record["sha256"])
    grid = comparison.read_grid(path)
    source.artifact(path, record["sha256"])
    return grid


def cross_flow_profile(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or not np.all(np.isfinite(values)) or np.any(values < 0):
        raise RuntimeError("Peak profiles require a finite, non-negative two-dimensional field")
    return values.max(axis=0)


def terrain_profile(grid: Any, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sample supplied terrain at nearest row to its strictly x-increasing path."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or np.any(np.diff(points[:, 0]) <= 0):
        raise RuntimeError("Coulomb downstream profiles require a strictly x-increasing thalweg")
    x = np.asarray(grid.x_centres, dtype=float)
    path_y = np.interp(x, points[:, 0], points[:, 1])
    rows = np.abs(np.asarray(grid.y_centres)[::-1, None] - path_y).argmin(axis=0)
    bed = np.asarray(grid.values_north)[rows, np.arange(x.size)]
    if not np.all(np.isfinite(bed)):
        raise RuntimeError("The sampled reference terrain contains nodata")
    return bed, rows


def concave_transition(x: np.ndarray, bed: np.ndarray) -> list[float] | None:
    """Locate the longest resolved concave, descending DEM segment; no track fit.

    The relative derivative tolerance rejects rounding noise only. This display
    annotation does not affect profiles, runouts, scores, or model parameters.
    """
    if len(x) < 3:
        return None
    slope = np.gradient(bed, x)
    curvature = np.gradient(slope, x)
    tolerance = max(1e-10, 1e-3 * float(np.max(np.abs(curvature))))
    active = np.flatnonzero((curvature > tolerance) & (slope < -1e-4))
    if not active.size:
        return None
    groups = np.split(active, np.flatnonzero(np.diff(active) > 1) + 1)
    selected = max(groups, key=lambda group: (x[group[-1]] - x[group[0]], x[group[-1]]))
    return [float(x[selected[0]]), float(x[selected[-1]])]


def build_report(args: Any, source: Any, comparison: Any, ranking: Any, paper: Any) -> dict:
    table, table_record = paper.validated_peer_table(
        REPO / "validation/ISeeSnow/paper_figures/iseesnow_table_c1_core.csv")
    case = source.compare_case(args, CASE, comparison, ranking, paper, table)
    source.validate_source_cohorts([case])
    dem = authenticated_grid(case["official_dem"], source, comparison)
    thalweg = paper.validated_thalweg(CASE)
    if thalweg["artifacts"] != case["thalweg"]["artifacts"]:
        raise RuntimeError("Reference thalweg changed during profile preparation")
    bed, rows = terrain_profile(dem, thalweg["_points"])
    x = np.asarray(dem.x_centres)
    profiles = {"runs": {}, "peers": {}, "peer_statistics": {}}
    for run in case["runs"]:
        profiles["runs"][run["label"]] = {
            variable: cross_flow_profile(authenticated_grid(run["provenance"][variable], source, comparison).values_north)
            for variable in ("pft", "pfv")}
    for record in case["aligned_peer_artifacts"]:
        profiles["peers"][record["model"]] = {
            variable: cross_flow_profile(comparison.clean(authenticated_grid(record[variable], source, comparison).values_north))
            for variable in ("pft", "pfv")}
    if not profiles["peers"]:
        raise RuntimeError("No aligned peer profiles are available")
    for variable in ("pft", "pfv"):
        population = np.stack([fields[variable] for fields in profiles["peers"].values()])
        quartiles = np.quantile(population, [0.25, 0.5, 0.75], axis=0)
        profiles["peer_statistics"][variable] = dict(zip(("q1", "median", "q3"), quartiles))
    transition = concave_transition(x, bed)
    support = np.stack([fields["pft"] > 0.5 for collection in (profiles["runs"], profiles["peers"])
                        for fields in collection.values()]).any(axis=0)
    active = np.flatnonzero(support)
    start = transition[0] - 150.0 if transition else float(x[0])
    end = float(x[active[-1]] + 100.0) if active.size else float(x[-1])
    focus = [max(float(x[0]), start), min(float(x[-1]), max(end, start + 300.0))]
    # Lists are intentional: the companion stores every plotted source profile.
    profiles = {section: {name: {variable: values.tolist() for variable, values in fields.items()}
                          for name, fields in entries.items()} for section, entries in profiles.items()}
    return source.serializable({
        "title": "CoulombOnly downstream peak-field diagnostic",
        "script": source.artifact(Path(__file__)),
        "helpers": [source.artifact(Path(module.__file__)) for module in (source, comparison, ranking, paper)],
        "comparison": case, "table_c1_artifact": table_record,
        "profile_definition": "maximum over every cross-flow raster row of the time-maximum PFT/PFV at each map-x cell centre",
        "limitation": "Cross-flow maxima can occur at different rows and times; curves are not material trajectories or simultaneous states. No field is shifted or resampled.",
        "peer_population": "Same exactly aligned discovered raster peers on both sides; distinct from Table C1 scalar population. Existing peer nodata/negative cleaning is retained.",
        "x_m": x.tolist(), "profiles": profiles,
        "terrain": {"elevation_m": bed.tolist(), "sampled_north_row": rows.tolist(),
                    "method": "reference-thalweg y interpolated at DEM x centres; nearest original DEM row, no elevation interpolation or fitted radius",
                    "concave_transition_x_m": transition,
                    "annotation_rule": "longest descending positive-curvature segment; slope < -1e-4, curvature > max(1e-10, 0.001*max(abs(curvature)))"},
        "display_x_limits_m": focus,
        "sources": ["https://doi.org/10.5194/egusphere-2025-6053",
                    "https://nhess.copernicus.org/articles/15/671/2015/"],
    })


def render(report: dict, output: Path) -> list[Path]:
    case = report["comparison"]
    x = np.asarray(report["x_m"])
    profiles = report["profiles"]
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.2), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.90, top=0.81, bottom=0.18, hspace=0.14)
    for axis, variable, title in zip(axes, ("pfv", "pft"), ("(a) Peak flow velocity", "(b) Peak flow thickness")):
        stats = profiles["peer_statistics"][variable]
        axis.fill_between(x, stats["q1"], stats["q3"], color="#88a6b5", alpha=0.35, label="Aligned-peer IQR")
        axis.plot(x, stats["median"], color="#476a7c", lw=1.8, label="Aligned-peer median")
        if "com1DFA" in profiles["peers"]:
            axis.plot(x, profiles["peers"]["com1DFA"][variable], color="#267b57", ls="--", lw=1.5, label="com1DFA")
        for run, color in zip(case["runs"], ("#222222", "#d05a18")):
            seconds = run["protocol"]["simulation_end_ceiling_seconds"]
            name = "Baseline" if run["label"] == "baseline" else "Candidate"
            axis.plot(x, profiles["runs"][run["label"]][variable], color=color, lw=2.2, label=f"{name} ({seconds:g} s)")
        if report["terrain"]["concave_transition_x_m"]:
            axis.axvspan(*report["terrain"]["concave_transition_x_m"], color="#b5a88e", alpha=0.15, zorder=0)
        axis.set_title(title, loc="left", fontsize=11)
        axis.set_ylabel("Cross-flow max PFV (m/s)" if variable == "pfv" else "Cross-flow max PFT (m)")
        axis.set_ylim(bottom=0)
        axis.grid(alpha=0.18)
        axis.spines[["top", "right"]].set_visible(False)
    terrain_axis = axes[0].twinx()
    terrain_axis.plot(x, report["terrain"]["elevation_m"], color="#887b65", ls=":", lw=1.4, label="Supplied DEM at reference path")
    terrain_axis.set_ylabel("Reference-path bed elevation (m)", color="#887b65", fontsize=9)
    terrain_axis.tick_params(axis="y", colors="#887b65", labelsize=9)
    terrain_axis.spines["top"].set_visible(False)
    focus = (x >= report["display_x_limits_m"][0]) & (x <= report["display_x_limits_m"][1])
    z = np.asarray(report["terrain"]["elevation_m"])[focus]
    terrain_axis.set_ylim(float(z.min()) - 0.1 * max(1, float(np.ptp(z))), float(z.max()) + 0.2 * max(1, float(np.ptp(z))))
    axes[1].axhline(0.5, color="#777777", ls=":", lw=1)
    axes[1].set(xlabel="Map x (m) — not thalweg runout distance", xlim=report["display_x_limits_m"])
    handles, labels = axes[0].get_legend_handles_labels()
    extra_handles, extra_labels = terrain_axis.get_legend_handles_labels()
    fig.legend(handles + extra_handles, labels + extra_labels, loc="upper center", bbox_to_anchor=(0.5, 0.925), ncol=3, fontsize=9, frameon=False)
    matched = case["matched_protocol"]
    status = "Matched numerical/physical protocols" if matched else "UNMATCHED DIAGNOSTIC — numerical/physical protocols differ"
    fig.suptitle("CoulombOnly: transition velocity and downstream deposit", fontsize=14, y=0.985)
    fig.text(0.5, 0.951, status, ha="center", fontsize=10, color="#333333" if matched else "#a32f22")
    runouts = "; ".join(f"{run['label']} {run['runout_by_threshold_m']['0.5']:.1f} m" for run in case["runs"])
    footer = (f"Thalweg runout at PFT > 0.5 m: {runouts}.  Aligned spatial peers: {case['aligned_peer_count']}.\n"
              "Peak-field cross-flow envelopes are not particle tracks or simultaneous states. Shading marks the DEM-derived concave bend.\n"
              "PFT panel dotted line: 0.5 m runout threshold. Peer median/IQR use every aligned peer; full profiles and hashes are in the JSON.")
    if not matched:
        footer += "\nDifferent run ceilings/controls do not isolate the source correction or establish final deposition/rest."
    fig.text(0.5, 0.055, footer, ha="center", va="center", fontsize=8.5, linespacing=1.5)
    paths = [output / f"coulomb_runout_diagnosis.{extension}" for extension in ("png", "pdf")]
    for path in paths:
        fig.savefig(path, dpi=200)
    plt.close(fig)
    return paths


def main() -> None:
    args = parse_args()
    for key in ("baseline", "candidate", "output"):
        setattr(args, key, getattr(args, key).resolve())
    report = build_report(args, *modules())
    args.output.mkdir(parents=True, exist_ok=True)
    paths = render(report, args.output)
    destination = args.output / "coulomb_runout_diagnosis.json"
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for path in [*paths, destination]:
        print(path)


if __name__ == "__main__":
    main()
