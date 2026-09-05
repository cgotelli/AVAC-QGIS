#!/usr/bin/env python3
"""Compare two ISeeSnow source builds without weakening limiter-ranking gates.

This is an explicitly cross-source diagnostic. PFT is the primary comparison;
PFV is an independent audit. Every reported AVAC field must match its saved run
summary, both native executables/backends must still match their recorded
hashes, and each input must match the official benchmark. No field is shifted,
resampled, normalized, or clipped. The ordinary limiter-ranking CLI is neither
invoked nor modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np


DEFAULT_REPO = Path(__file__).resolve().parents[2]
PROTOCOL_KEYS = (
    "simulation_end_ceiling_seconds", "native_state_output_interval_seconds",
    "fixed_grid_output_interval_seconds", "fixed_grid_output_frame_count",
    "spatial_order", "limiter", "native_dry_tolerance_m",
    "practical_rest_minimum_depth_m", "state_momentum_regularization_depth_m",
    "coulomb_state_momentum_regularization_depth_m",
    "voellmy_state_momentum_regularization_depth_m", "cfl_target", "cfl_max",
    "refinement_levels", "refinement_ratio", "finest_effective_cell_size_m",
    "speed_limit_mps", "diagnostic_gauge",
)
DIAGNOSTIC_KEYS = (
    "wall_seconds", "cpu_seconds", "initial_volume_m3", "final_volume_m3",
    "relative_volume_change", "practical_rest_sustained_from_seconds",
    "flow_stopped_at_seconds", "flow_rest_confirmed_by_ceiling",
    "final_max_speed_mps", "final_moving_volume_by_vertical_depth_band_m3",
    "maximum_courant_number", "accepted_cfl_violation_count",
    "rejected_cfl_trial_count", "maximum_rejected_courant_number",
    "first_rejected_cfl_trial", "maximum_amr_level",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    if expected is not None and (
        not isinstance(expected, str) or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected.lower())
    ):
        raise RuntimeError(f"Invalid recorded SHA-256 for {path}")
    actual = sha256(path)
    if expected is not None and actual != expected.lower():
        raise RuntimeError(f"Artifact hash mismatch: {path}: {actual} != {expected}")
    return {"path": str(path), "sha256": actual}


def serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def validate_source_cohorts(cases: list[dict[str, Any]]) -> None:
    """Each labelled suite must originate from one executable/backend pair."""
    for label in ("baseline", "candidate"):
        identities = {
            (run["provenance"]["solver"]["sha256"], run["provenance"]["backend"]["sha256"])
            for case in cases for run in case["runs"] if run["label"] == label
        }
        if len(identities) != 1:
            raise RuntimeError(f"{label} suite mixes executable/backend identities")


def compare_protocols(runs: list[dict[str, Any]], allow_differences: bool = False) -> dict[str, Any]:
    differences = {
        key: {run["label"]: run["protocol"][key] for run in runs}
        for key in PROTOCOL_KEYS if runs[0]["protocol"][key] != runs[1]["protocol"][key]
    }
    for key in runs[0]["physical_protocol"]:
        if runs[0]["physical_protocol"][key] != runs[1]["physical_protocol"][key]:
            differences[f"physical.{key}"] = {
                run["label"]: run["physical_protocol"][key] for run in runs
            }
    for name in runs[0]["provenance"]["generated_initial_fields"]:
        hashes = {run["label"]: run["provenance"]["generated_initial_fields"][name]["sha256"] for run in runs}
        if hashes["baseline"] != hashes["candidate"]:
            differences[f"initial_field.{name}"] = hashes
    if differences and not allow_differences:
        raise RuntimeError(f"Numerical protocol differs: {differences}; use --allow-protocol-differences for an explicitly unmatched diagnostic")
    return differences


def load_run(root: Path, case: str, label: str, target: Any,
             official_inputs: Path, comparison: Any, paper: Any) -> dict[str, Any]:
    case_root = root / case
    summary_path = case_root / "run_summary.json"
    summary_record = artifact(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    required = set(PROTOCOL_KEYS) | {
        "case", "execution_mode", "solver", "solver_sha256", "setrun_backend",
        "setrun_backend_sha256", "submission_pft_sha256", "submission_pfv_sha256",
        "official_input_manifest", "native_mass_history", "maximum_courant_number",
        "accepted_cfl_violation_count", "plugin_case", "configuration",
    }
    missing = sorted(required - summary.keys())
    if missing:
        raise RuntimeError(f"{label}/{case} run summary lacks required fields: {missing}")
    unset = [key for key in PROTOCOL_KEYS if key != "diagnostic_gauge" and summary[key] is None]
    if unset:
        raise RuntimeError(f"{label}/{case} has unset numerical controls: {unset}")
    for key in ("solver_sha256", "setrun_backend_sha256", "submission_pft_sha256", "submission_pfv_sha256"):
        if not isinstance(summary[key], str) or not summary[key]:
            raise RuntimeError(f"{label}/{case} lacks recorded {key}")
    if summary.get("case") != case:
        raise RuntimeError(f"Wrong case in {summary_path}")
    if summary["execution_mode"] not in {"current_source", "explicit_solver_source_snapshot"}:
        raise RuntimeError(f"Unsupported execution mode in {summary_path}: {summary['execution_mode']!r}")
    if summary.get("accepted_cfl_violation_count") != 0:
        raise RuntimeError(f"{label}/{case} does not certify zero accepted CFL violations")
    if not math.isfinite(float(summary["maximum_courant_number"])) or not math.isfinite(float(summary["cfl_max"])):
        raise RuntimeError(f"{label}/{case} lacks finite CFL diagnostics")
    if not 0 <= summary["maximum_courant_number"] <= summary["cfl_max"]:
        raise RuntimeError(f"{label}/{case} maximum CFL exceeds its acceptance ceiling")

    provenance: dict[str, Any] = {
        "run_summary": summary_record,
        "execution_mode": summary.get("execution_mode"),
        "validation_scope": "recorded executable/backend/input/submission hashes; not independent package or article certification",
        "solver": artifact(Path(summary["solver"]), summary["solver_sha256"]),
        "backend": artifact(Path(summary["setrun_backend"]), summary["setrun_backend_sha256"]),
        "official_input_manifest": [],
    }
    records = summary.get("official_input_manifest", [])
    if not records:
        raise RuntimeError(f"{label}/{case} lacks its official input manifest")
    if any(not isinstance(record, dict) or not all(record.get(key) for key in ("name", "path", "sha256")) for record in records):
        raise RuntimeError(f"{label}/{case} has an incomplete official input record")
    official_names = {path.name for path in official_inputs.iterdir() if path.is_file()}
    names = [record["name"] for record in records]
    if len(set(names)) != len(names) or set(names) != official_names:
        raise RuntimeError(f"{label}/{case} official input manifest is incomplete, duplicated or unexpected")
    for record in records:
        supplied = Path(record["path"]).resolve()
        if not supplied.is_relative_to(case_root.resolve()):
            raise RuntimeError(f"Input is not contained within {case_root}: {supplied}")
        local_record = artifact(supplied, record["sha256"])
        original = artifact(official_inputs / record["name"], record["sha256"])
        provenance["official_input_manifest"].append({**local_record, "official_path": original["path"]})

    fields = {}
    for variable in ("pft", "pfv"):
        path = paper.unique_submission_path(root, case, variable)
        if not path.resolve().is_relative_to(case_root.resolve()):
            raise RuntimeError(f"Submission is not contained within {case_root}: {path}")
        expected = summary[f"submission_{variable}_sha256"]
        record = artifact(path, expected)
        grid = comparison.read_grid(path)
        matches, reason = comparison.same_grid(grid, target)
        if not matches:
            raise RuntimeError(f"{label}/{case}/{variable} grid mismatch: {reason}")
        values = np.asarray(grid.values_north, dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise RuntimeError(f"{label}/{case}/{variable} has non-finite, nodata or negative values")
        artifact(path, expected)
        fields[variable] = {
            **record, "_values_north": values,
            "_x": grid.x_centres, "_y": grid.y_centres,
        }
        provenance[variable] = record
    mass_history = Path(summary["native_mass_history"])
    if not mass_history.resolve().is_relative_to(case_root.resolve()):
        raise RuntimeError(f"Mass history is not contained within {case_root}: {mass_history}")
    provenance["native_mass_history"] = artifact(mass_history)
    for key in ("plugin_case", "configuration"):
        path = Path(summary[key]).resolve()
        if not path.is_relative_to(case_root.resolve()):
            raise RuntimeError(f"{key} is not contained within {case_root}: {path}")
        provenance[key] = artifact(path)
    config_path = case_root / "Run/AVAC/AVAC_configuration.yaml"
    provenance["prepared_configuration"] = artifact(config_path)
    config = paper.yaml.safe_load(config_path.read_text(encoding="utf-8"))
    physical_protocol = {key: config[key] for key in ("rheology", "release", "dem_extent")}
    initial_fields = {}
    for name in ("initial_depth_normal.asc", "initial_depth_vertical.asc"):
        initial_fields[name] = artifact(case_root / name)
    provenance["generated_initial_fields"] = initial_fields
    artifact(summary_path, summary_record["sha256"])
    return {
        "label": label, "root": str(root), "provenance": provenance,
        "protocol": {key: summary.get(key) for key in PROTOCOL_KEYS},
        "physical_protocol": physical_protocol,
        "diagnostics": {key: summary.get(key) for key in DIAGNOSTIC_KEYS},
        "_summary": summary, "_fields": fields,
    }


def load_peers(case: str, target: Any, comparison: Any) -> tuple[dict, list, list]:
    pairs, excluded = comparison.output_pairs(comparison.BENCHMARK / case / f"Outputs_{case}")
    peers = {}
    records = []
    for name, pft_path, pfv_path in pairs:
        if name in peers:
            raise RuntimeError(f"Duplicate aligned peer model: {name}")
        paths = {"pft": pft_path, "pfv": pfv_path}
        identities = {variable: artifact(path) for variable, path in paths.items()}
        grids = {variable: comparison.read_grid(path) for variable, path in paths.items()}
        for variable, path in paths.items():
            artifact(path, identities[variable]["sha256"])
        reasons = []
        for variable, grid in grids.items():
            matches, reason = comparison.same_grid(grid, target)
            if not matches:
                reasons.append(f"{variable}: {reason}")
        if reasons:
            excluded.append({"case": case, "model": name, "reason": "; ".join(reasons)})
            continue
        peers[name] = {variable: comparison.clean(grid.values_north) for variable, grid in grids.items()}
        records.append({"model": name, **identities})
    return peers, records, excluded


def compare_case(args: Any, case: str, comparison: Any, ranking: Any,
                 paper: Any, peer_table: Any) -> dict[str, Any]:
    official_inputs = comparison.BENCHMARK / case / "Inputs"
    dem_paths = list(official_inputs.glob("DEM_*.asc"))
    if len(dem_paths) != 1:
        raise RuntimeError(f"Expected one official DEM for {case}")
    target = comparison.read_grid(dem_paths[0])
    thalweg = paper.validated_thalweg(case)
    runs = [load_run(root, case, label, target, official_inputs, comparison, paper)
            for root, label in ((args.baseline, "baseline"), (args.candidate, "candidate"))]
    protocol_differences = compare_protocols(runs, args.allow_protocol_differences)
    peers, peer_records, excluded = load_peers(case, target, comparison)
    pft_peers = {name: fields["pft"] for name, fields in peers.items()}
    candidates = [ranking.Candidate(
        name=run["label"], results_root=Path(run["root"]),
        pft_path=Path(run["_fields"]["pft"]["path"]),
        values=run["_fields"]["pft"]["_values_north"],
        run_summary_path=Path(run["provenance"]["run_summary"]["path"]),
        run_summary=run["_summary"], pft_sha256=run["_fields"]["pft"]["sha256"],
    ) for run in runs]
    # Pure scoring helpers are valid across source builds. The strict public
    # limiter-provenance gate remains unchanged and is not called here.
    scores, pft_details = ranking.candidate_rows(candidates, pft_peers, target.cell_size)
    for run, score in zip(runs, scores):
        run["pft_score"] = score
        run["scalars"] = {
            variable: comparison.scalar_metrics(field["_values_north"], target.cell_size, variable)
            for variable, field in run["_fields"].items()
        }
        run["runout_by_threshold_m"] = {
            f"{threshold:g}": paper.runout_from_validated_field(run["_fields"]["pft"], thalweg, threshold)
            for threshold in (0.01, 0.05, 0.1, 0.5, 1.0)
        }
    direct = {}
    for variable in ("pft", "pfv"):
        baseline = runs[0]["_fields"][variable]["_values_north"]
        candidate = runs[1]["_fields"][variable]["_values_north"]
        direct[variable] = {
            **comparison.pair_metrics(candidate, baseline, target.cell_size, variable),
            "max_absolute_difference": float(np.max(np.abs(candidate - baseline))),
            "identical_values": bool(np.array_equal(candidate, baseline)),
            "identical_file_bytes": runs[0]["_fields"][variable]["sha256"] == runs[1]["_fields"][variable]["sha256"],
        }
    pfv_details = [{"candidate": run["label"], "peer": name,
                    **comparison.pair_metrics(run["_fields"]["pfv"]["_values_north"], fields["pfv"], target.cell_size, "pfv")}
                   for run in runs for name, fields in peers.items()]
    scalar_peers = peer_table.loc[peer_table["case"] == case]
    scalar_stats = {key: paper.peer_statistics(scalar_peers[key].to_numpy(dtype=float))
                    for key in ("runout_length_m", "pft_peak_m", "pfv_peak_mps")}
    comparisons_by_peer = {label: {row["peer"]: row for row in pft_details if row["candidate"] == label}
                           for label in ("baseline", "candidate")}
    improved = [name for name in peers
                if comparisons_by_peer["candidate"][name]["rmse_m"] < comparisons_by_peer["baseline"][name]["rmse_m"]]
    for run in runs:
        del run["_fields"]
        del run["_summary"]
    return {
        "case": case, "official_dem": artifact(dem_paths[0]),
        "thalweg": {key: value for key, value in thalweg.items() if not key.startswith("_")},
        "matched_protocol": not protocol_differences, "protocol_differences": protocol_differences,
        "comparison_status": "matched_protocol_diagnostic" if not protocol_differences else "unmatched_diagnostic_only",
        "runs": runs, "candidate_minus_baseline_fields": direct,
        "aligned_peer_count": len(peers), "aligned_peer_artifacts": peer_records,
        "excluded_peer_fields": excluded, "pft_per_peer": pft_details,
        "candidate_pft_improved_peers": improved, "pfv_per_peer": pfv_details,
        "table_c1_scalar_peer_statistics": scalar_stats,
    }


def value(item: Any) -> str:
    if item is None:
        return "not reached / not recorded"
    if isinstance(item, float):
        return f"{item:.9g}"
    return str(item)


def markdown(report: dict[str, Any]) -> str:
    lines = ["# ISeeSnow cross-source regression comparison", "",
             "This diagnostic permits explicitly identified different source builds. PFT is primary; PFV is a secondary audit. It does not change or satisfy the separate same-executable limiter-selection gate.", "",
             "PFT score is the median of candidate-to-peer full-grid RMSE divided by each peer's median RMSE to the other peers. Spatial comparisons retain exactly aligned rasters only, with the established peer nodata/negative-value treatment. AVAC fields must be finite and non-negative; no raster is resampled or shifted.", "",
             "Runout is the existing article definition: the furthest thalweg coordinate reached by PFT > 0.5 m. Other thresholds are diagnostic. Scalar Table C1 peers and spatial raster peers are distinct populations."]
    for case in report["cases"]:
        baseline, candidate = case["runs"]
        lines += ["", f"## {case['case']}", "",
                  f"Matched numerical protocol: **{case['matched_protocol']}**. Aligned spatial peers: {case['aligned_peer_count']}. Candidate improves PFT RMSE against {len(case['candidate_pft_improved_peers'])}/{case['aligned_peer_count']} peers.", ""]
        if case["protocol_differences"]:
            lines += ["Protocol differences: `" + json.dumps(case["protocol_differences"]) + "`. These runs do not isolate a source change.", ""]
        lines += ["| Metric | Baseline | Candidate |", "| --- | ---: | ---: |"]
        items = [("PFT normalized median RMSE", "pft_score", "normalized_median_rmse"),
                 ("PFT median peer RMSE (m)", "pft_score", "median_rmse_m"),
                 ("PFT median support IoU", "pft_score", "median_support_iou"),
                 ("Runout, PFT > 0.5 m (m)", "runout_by_threshold_m", "0.5")]
        items += [(key, "diagnostics", key) for key in DIAGNOSTIC_KEYS
                  if key not in {"final_moving_volume_by_vertical_depth_band_m3", "first_rejected_cfl_trial"}]
        for label, section, key in items:
            lines.append(f"| {label} | {value(baseline[section].get(key))} | {value(candidate[section].get(key))} |")
        for variable in ("pft", "pfv"):
            for key in ("peak", "positive_area_m2", "field_integral"):
                lines.append(f"| {variable.upper()} {key} | {value(baseline['scalars'][variable][key])} | {value(candidate['scalars'][variable][key])} |")
        lines += ["", "Candidate versus baseline full-field differences:", "",
                  "| Variable | RMSE | Max absolute difference | Support IoU | Identical bytes |",
                  "| --- | ---: | ---: | ---: | --- |"]
        for variable, row in case["candidate_minus_baseline_fields"].items():
            lines.append(f"| {variable.upper()} | {value(row['rmse'])} | {value(row['max_absolute_difference'])} | {value(row['support_iou'])} | {row['identical_file_bytes']} |")
        lines += ["", "| Peer | Baseline PFT normalized RMSE | Candidate PFT normalized RMSE |", "| --- | ---: | ---: |"]
        details = {label: {row["peer"]: row for row in case["pft_per_peer"] if row["candidate"] == label}
                   for label in ("baseline", "candidate")}
        for peer in details["baseline"]:
            lines.append(f"| {peer} | {value(details['baseline'][peer]['normalized_rmse'])} | {value(details['candidate'][peer]['normalized_rmse'])} |")
        lines += ["", "Source and field SHA-256 identities:", ""]
        for run in case["runs"]:
            lines += [f"- {run['label']}: solver `{run['provenance']['solver']['sha256']}`; backend `{run['provenance']['backend']['sha256']}`.",
                      f"  PFT `{run['provenance']['pft']['sha256']}`; PFV `{run['provenance']['pfv']['sha256']}`."]
    lines += ["", "The JSON companion records complete source/input/geometry provenance, runout-threshold sensitivity, Table C1 scalar peer statistics, per-peer PFV results, numerical controls, and rest diagnostics.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--case", choices=("all", "CoulombOnly", "IdealizedTopo", "RealTopo"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-protocol-differences", action="store_true",
                        help="explicitly allow and flag unmatched diagnostic controls/durations")
    args = parser.parse_args()
    for key in ("repo", "baseline", "candidate", "output"):
        setattr(args, key, getattr(args, key).resolve())
    for relative in ("", "validation", "validation/ISeeSnow", "validation/ISeeSnow/paper_figures"):
        sys.path.insert(0, str(args.repo / relative))
    comparison = importlib.import_module("compare_iseesnow")
    ranking = importlib.import_module("rank_coulomb_pft_candidates")
    paper = importlib.import_module("make_iseesnow_figures")
    table, table_record = paper.validated_peer_table(args.repo / "validation/ISeeSnow/paper_figures/iseesnow_table_c1_core.csv")
    cases = list(comparison.CASES) if args.case == "all" else [args.case]
    report = {
        "diagnostic": "cross-source comparison; differing authenticated source hashes permitted",
        "script": artifact(Path(__file__)),
        "scoring_helpers": [artifact(Path(module.__file__)) for module in (comparison, ranking, paper)],
        "baseline_root": str(args.baseline), "candidate_root": str(args.candidate),
        "table_c1_artifact": table_record,
        "primary_metric": "median peer-difficulty-normalized full-grid PFT RMSE",
        "runout_definition": "furthest thalweg coordinate with PFT > 0.5 m",
        "cases": [compare_case(args, case, comparison, ranking, paper, table) for case in cases],
    }
    report = serializable(report)
    validate_source_cohorts(report["cases"])
    args.output.mkdir(parents=True, exist_ok=True)
    json_path = args.output / "cross_source_comparison.json"
    md_path = args.output / "cross_source_comparison.md"
    json_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    print(json_path)
    print(md_path)
    for case in report["cases"]:
        print(case["case"], [(run["label"], run["pft_score"]["normalized_median_rmse"],
                             run["runout_by_threshold_m"]["0.5"]) for run in case["runs"]])


if __name__ == "__main__":
    main()
