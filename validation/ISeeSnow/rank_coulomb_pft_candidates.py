#!/usr/bin/env python3
"""Rank CoulombOnly numerical candidates against the aligned ISeeSnow peers.

The selection rule is deliberately fixed before the candidate sweep:

* use peak-flow thickness (PFT) only;
* scale each candidate-to-peer RMSE by that peer's median RMSE to the other
  peers, so one intrinsically unusual peer cannot dominate the result;
* aggregate the seven scaled errors with a median;
* require the leading candidate to beat the runner-up for at least six of the
  seven peers and to remain first in all seven leave-one-peer-out rankings.

Support IoU and active-field correlation are deterministic secondary keys.
They are never blended into the primary score with fitted weights.  No raster
is shifted, clipped, padded, or resampled.  Candidate run summaries must also
pass the listed numerical-control and executable gates. Candidate PFT bytes,
the official target grid, and every included peer PFT are hashed in the report;
the gate does not independently reconstruct unlisted physical inputs. Mixed
CFL targets require an explicitly named robustness batch.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from compare_iseesnow import (  # noqa: E402
    ascii_grid,
    clean,
    output_pairs,
    pair_metrics,
    read_grid,
    same_grid,
)
from avac4qgis_validation.datasets import (  # noqa: E402
    ISEESNOW_URL,
    ISEESNOW_VERSION,
    ensure_iseesnow,
)


EXPECTED_PEERS = (
    "TITAN2Dv420",
    "com1DFA",
    "Gerris",
    "INRAEaval",
    "minVoellmyv2",
    "TRENT2D",
    "03CoulombOnly_faSavageHutterFoamGamma",
)
PFT_SUPPORT_THRESHOLD_M = 0.01
PAIRED_WINS_REQUIRED = 6
LOO_FIRSTS_REQUIRED = len(EXPECTED_PEERS)
FLOAT_TIE_ATOL = 1.0e-14
EXPECTED_STATE_REGULARIZATION_DEPTH_M = 0.05
EXPECTED_SPATIAL_ORDER = 2
EXPECTED_SIMULATION_CEILING_S = 1200.0
EXPECTED_REFINEMENT_LEVELS = 1
EXPECTED_FINEST_CELL_SIZE_M = 5.0
EXPECTED_SPEED_LIMIT_MPS = 1.0e99


@dataclass(frozen=True)
class Candidate:
    name: str
    results_root: Path
    pft_path: Path
    values: np.ndarray
    run_summary_path: Path
    run_summary: dict[str, Any]
    pft_sha256: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_candidate(value: str) -> tuple[str, Path]:
    """Parse one ``NAME=results-root`` command-line value."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"candidate {value!r} must have the form NAME=results-root"
        )
    name, raw_root = value.split("=", 1)
    name = name.strip()
    raw_root = raw_root.strip()
    if not name or not raw_root:
        raise argparse.ArgumentTypeError(
            f"candidate {value!r} must have a non-empty name and path"
        )
    return name, Path(raw_root).expanduser()


def candidate_pft_path(results_root: Path) -> Path:
    """Find the single AVAC CoulombOnly PFT below a candidate results root."""
    root = results_root.resolve()
    submissions = (root / "CoulombOnly" / "Submission", root / "Submission")
    for submission in submissions:
        if not submission.is_dir():
            continue
        paths = sorted(submission.glob("*_AVAC4QGIS_pft.asc"))
        if len(paths) == 1:
            return paths[0]
        if len(paths) > 1:
            raise RuntimeError(
                f"{submission} contains more than one AVAC4QGIS PFT: "
                + ", ".join(path.name for path in paths)
            )
    raise FileNotFoundError(
        f"no single CoulombOnly/Submission/*_AVAC4QGIS_pft.asc below {root}"
    )


def candidate_run_summary_path(results_root: Path) -> Path:
    """Find the run summary belonging to one candidate result root."""
    root = results_root.resolve()
    paths = (root / "CoulombOnly" / "run_summary.json", root / "run_summary.json")
    found = [path for path in paths if path.is_file()]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise RuntimeError(
            f"ambiguous candidate root {root}: both run summaries exist"
        )
    raise FileNotFoundError(f"no CoulombOnly/run_summary.json below {root}")


def read_run_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read run summary {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"run summary {path} is not a JSON object")
    return payload


def validated_candidate_pft(values: np.ndarray, name: str) -> np.ndarray:
    """Require a complete finite, non-negative candidate field before scoring."""
    field = np.asarray(values, dtype=float)
    invalid = ~np.isfinite(field)
    if np.any(invalid):
        raise RuntimeError(
            f"candidate {name!r} PFT contains {int(np.count_nonzero(invalid))} "
            "non-finite or nodata cell(s)"
        )
    negative = field < 0.0
    if np.any(negative):
        raise RuntimeError(
            f"candidate {name!r} PFT contains {int(np.count_nonzero(negative))} "
            "negative cell(s)"
        )
    return field


def official_peer_fields() -> tuple[Any, dict[str, np.ndarray], dict[str, Any]]:
    """Load exactly the seven official PFT rasters aligned to the input DEM."""
    case_root = ensure_iseesnow() / "data" / "CoulombOnly"
    target_path = case_root / "Inputs" / "DEM_CoulombOnly.asc"
    target = ascii_grid(target_path)
    peers: dict[str, np.ndarray] = {}
    peer_sources: dict[str, dict[str, str]] = {}
    for peer, pft_path, _pfv_path in output_pairs(
        case_root / "Outputs_CoulombOnly"
    )[0]:
        pft = read_grid(pft_path)
        aligned, _reason = same_grid(pft, target)
        if aligned:
            peers[peer] = clean(pft.values_north)
            peer_sources[peer] = {
                "path": str(pft_path.resolve()),
                "sha256": file_sha256(pft_path),
            }

    found = set(peers)
    expected = set(EXPECTED_PEERS)
    if found != expected:
        missing = sorted(expected - found)
        unexpected = sorted(found - expected)
        raise RuntimeError(
            "the aligned official peer set changed; "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )
    source_record = {
        "dataset_version": ISEESNOW_VERSION,
        "dataset_url": ISEESNOW_URL,
        "dataset_root": str(case_root.parents[1].resolve()),
        "target_grid": {
            "path": str(target_path.resolve()),
            "sha256": file_sha256(target_path),
        },
        "peer_pft_fields": [
            {"peer": name, **peer_sources[name]} for name in EXPECTED_PEERS
        ],
    }
    return target, {name: peers[name] for name in EXPECTED_PEERS}, source_record


def load_candidates(
    specifications: Iterable[tuple[str, Path]], target: Any
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for name, results_root in specifications:
        if name in seen:
            raise ValueError(f"duplicate candidate name: {name!r}")
        seen.add(name)
        pft_path = candidate_pft_path(results_root)
        run_summary_path = candidate_run_summary_path(results_root)
        run_summary = read_run_summary(run_summary_path)
        grid = read_grid(pft_path)
        aligned, reason = same_grid(grid, target)
        if not aligned:
            raise RuntimeError(f"candidate {name!r} is not on the official grid: {reason}")
        candidates.append(
            Candidate(
                name=name,
                results_root=results_root.resolve(),
                pft_path=pft_path.resolve(),
                values=validated_candidate_pft(grid.values_north, name),
                run_summary_path=run_summary_path.resolve(),
                run_summary=run_summary,
                pft_sha256=file_sha256(pft_path),
            )
        )
    if len(candidates) < 2:
        raise ValueError("at least two candidates are required for selection")
    return candidates


def _required_number(
    candidate: Candidate, key: str, expected: float
) -> float:
    value = candidate.run_summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(
            f"candidate {candidate.name!r} run summary lacks numeric {key!r}"
        )
    numeric = float(value)
    if not np.isfinite(numeric) or numeric != expected:
        raise RuntimeError(
            f"candidate {candidate.name!r} has {key}={value!r}; expected exactly {expected!r}"
        )
    return numeric


def validate_candidate_provenance(
    candidates: list[Candidate],
    cfl_robustness_batch: str | None = None,
) -> dict[str, Any]:
    """Enforce the fixed numerical experiment before comparing any fields."""
    hashes: set[str] = set()
    backend_hashes: set[str] = set()
    cfl_values: list[float] = []
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        summary = candidate.run_summary
        if summary.get("case") != "CoulombOnly":
            raise RuntimeError(
                f"candidate {candidate.name!r} has case={summary.get('case')!r}; "
                "expected 'CoulombOnly'"
            )
        state_depth = _required_number(
            candidate,
            "state_momentum_regularization_depth_m",
            EXPECTED_STATE_REGULARIZATION_DEPTH_M,
        )
        spatial_order = _required_number(
            candidate, "spatial_order", float(EXPECTED_SPATIAL_ORDER)
        )
        ceiling = _required_number(
            candidate,
            "simulation_end_ceiling_seconds",
            EXPECTED_SIMULATION_CEILING_S,
        )
        refinement = _required_number(
            candidate, "refinement_levels", float(EXPECTED_REFINEMENT_LEVELS)
        )
        finest_cell = _required_number(
            candidate,
            "finest_effective_cell_size_m",
            EXPECTED_FINEST_CELL_SIZE_M,
        )
        speed_limit = _required_number(
            candidate, "speed_limit_mps", EXPECTED_SPEED_LIMIT_MPS
        )

        solver_hash = summary.get("solver_sha256")
        if not isinstance(solver_hash, str) or re.fullmatch(
            r"[0-9a-fA-F]{64}", solver_hash
        ) is None:
            raise RuntimeError(
                f"candidate {candidate.name!r} has invalid solver_sha256={solver_hash!r}"
            )
        solver_hash = solver_hash.lower()
        hashes.add(solver_hash)

        backend_hash = summary.get("setrun_backend_sha256")
        if not isinstance(backend_hash, str) or re.fullmatch(
            r"[0-9a-fA-F]{64}", backend_hash
        ) is None:
            raise RuntimeError(
                f"candidate {candidate.name!r} has invalid "
                f"setrun_backend_sha256={backend_hash!r}"
            )
        backend_hash = backend_hash.lower()
        backend_hashes.add(backend_hash)

        recorded_pft_hash = summary.get("submission_pft_sha256")
        if not isinstance(recorded_pft_hash, str) or re.fullmatch(
            r"[0-9a-fA-F]{64}", recorded_pft_hash
        ) is None:
            raise RuntimeError(
                f"candidate {candidate.name!r} has invalid "
                f"submission_pft_sha256={recorded_pft_hash!r}"
            )
        recorded_pft_hash = recorded_pft_hash.lower()
        if recorded_pft_hash != candidate.pft_sha256.lower():
            raise RuntimeError(
                f"candidate {candidate.name!r} PFT bytes do not match its "
                "run-summary hash"
            )

        cfl = summary.get("cfl_target")
        if (
            isinstance(cfl, bool)
            or not isinstance(cfl, (int, float))
            or not np.isfinite(float(cfl))
            or not 0.0 < float(cfl) <= 1.0
        ):
            raise RuntimeError(
                f"candidate {candidate.name!r} has invalid cfl_target={cfl!r}"
            )
        cfl = float(cfl)
        cfl_values.append(cfl)

        limiter = summary.get("limiter")
        if not isinstance(limiter, str) or not limiter.strip():
            raise RuntimeError(
                f"candidate {candidate.name!r} has invalid limiter={limiter!r}"
            )
        rows.append(
            {
                "candidate": candidate.name,
                "run_summary_path": str(candidate.run_summary_path),
                "case": "CoulombOnly",
                "state_momentum_regularization_depth_m": state_depth,
                "spatial_order": int(spatial_order),
                "simulation_end_ceiling_seconds": ceiling,
                "refinement_levels": int(refinement),
                "finest_effective_cell_size_m": finest_cell,
                "speed_limit_mps": speed_limit,
                "solver_sha256": solver_hash,
                "setrun_backend_sha256": backend_hash,
                "submission_pft_sha256": recorded_pft_hash,
                "limiter": limiter,
                "cfl_target": cfl,
            }
        )

    if len(hashes) != 1:
        raise RuntimeError(
            "all candidates must share one solver SHA-256; found "
            + ", ".join(sorted(hashes))
        )
    if len(backend_hashes) != 1:
        raise RuntimeError(
            "all candidates must share one setrun backend SHA-256; found "
            + ", ".join(sorted(backend_hashes))
        )
    distinct_cfl = sorted(set(cfl_values))
    batch = cfl_robustness_batch.strip() if cfl_robustness_batch else None
    if len(distinct_cfl) > 1 and not batch:
        raise RuntimeError(
            "candidate CFL targets differ; pass --cfl-robustness-batch LABEL "
            "only for a deliberately named CFL robustness comparison"
        )

    return {
        "status": "passed",
        "scope": (
            "listed numerical controls, common executable/backend hashes, and "
            "a run-summary hash matching each candidate PFT; official raster "
            "hashes are recorded separately"
        ),
        "fixed_controls": {
            "case": "CoulombOnly",
            "state_momentum_regularization_depth_m": EXPECTED_STATE_REGULARIZATION_DEPTH_M,
            "spatial_order": EXPECTED_SPATIAL_ORDER,
            "simulation_end_ceiling_seconds": EXPECTED_SIMULATION_CEILING_S,
            "refinement_levels": EXPECTED_REFINEMENT_LEVELS,
            "finest_effective_cell_size_m": EXPECTED_FINEST_CELL_SIZE_M,
            "speed_limit_mps": EXPECTED_SPEED_LIMIT_MPS,
        },
        "common_solver_sha256": next(iter(hashes)),
        "common_setrun_backend_sha256": next(iter(backend_hashes)),
        "cfl_policy": (
            "explicit_named_robustness_batch"
            if len(distinct_cfl) > 1
            else "common_cfl"
        ),
        "cfl_robustness_batch": batch,
        "cfl_targets": distinct_cfl,
        "candidates": rows,
    }


def pft_metrics(left: np.ndarray, right: np.ndarray, cell_size: float) -> dict[str, float]:
    metrics = pair_metrics(left, right, cell_size, "pft")
    return {
        "rmse_m": float(metrics["rmse"]),
        "mae_m": float(metrics["mae"]),
        "support_iou": float(metrics["support_iou"]),
        "active_correlation": float(metrics["active_correlation"]),
    }


def peer_difficulty(
    peers: dict[str, np.ndarray], cell_size: float
) -> dict[str, dict[str, float]]:
    """Return each peer's median disagreement with every other peer."""
    result: dict[str, dict[str, float]] = {}
    for name, field in peers.items():
        comparisons = [
            pft_metrics(field, other, cell_size)
            for other_name, other in peers.items()
            if other_name != name
        ]
        if not comparisons:
            raise ValueError("peer difficulty needs at least two peers")
        result[name] = {
            "rmse_m": float(np.median([row["rmse_m"] for row in comparisons])),
            "mae_m": float(np.median([row["mae_m"] for row in comparisons])),
            "support_disagreement": float(
                np.median([1.0 - row["support_iou"] for row in comparisons])
            ),
            "pattern_disagreement": float(
                np.median([1.0 - row["active_correlation"] for row in comparisons])
            ),
        }
    for peer, metrics in result.items():
        for metric, value in metrics.items():
            if not np.isfinite(value) or value <= 0.0:
                raise RuntimeError(
                    f"peer difficulty {metric} for {peer!r} is not positive and finite: {value}"
                )
    return result


def candidate_rows(
    candidates: list[Candidate],
    peers: dict[str, np.ndarray],
    cell_size: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    difficulty = peer_difficulty(peers, cell_size)
    peer_median = np.median(np.stack(list(peers.values())), axis=0)
    summaries: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for candidate in candidates:
        rows: list[dict[str, Any]] = []
        for peer, peer_field in peers.items():
            metrics = pft_metrics(candidate.values, peer_field, cell_size)
            row = {
                "candidate": candidate.name,
                "peer": peer,
                **metrics,
                "normalized_rmse": metrics["rmse_m"] / difficulty[peer]["rmse_m"],
                "normalized_mae": metrics["mae_m"] / difficulty[peer]["mae_m"],
                "normalized_support_disagreement": (
                    (1.0 - metrics["support_iou"])
                    / difficulty[peer]["support_disagreement"]
                ),
                "normalized_pattern_disagreement": (
                    (1.0 - metrics["active_correlation"])
                    / difficulty[peer]["pattern_disagreement"]
                ),
            }
            rows.append(row)
            details.append(row)

        support = candidate.values > PFT_SUPPORT_THRESHOLD_M
        summaries.append(
            {
                "candidate": candidate.name,
                "results_root": str(candidate.results_root),
                "pft_path": str(candidate.pft_path),
                "pft_sha256": candidate.pft_sha256,
                "run_summary_path": str(candidate.run_summary_path),
                "case": candidate.run_summary.get("case"),
                "state_momentum_regularization_depth_m": candidate.run_summary.get(
                    "state_momentum_regularization_depth_m"
                ),
                "spatial_order": candidate.run_summary.get("spatial_order"),
                "simulation_end_ceiling_seconds": candidate.run_summary.get(
                    "simulation_end_ceiling_seconds"
                ),
                "refinement_levels": candidate.run_summary.get("refinement_levels"),
                "finest_effective_cell_size_m": candidate.run_summary.get(
                    "finest_effective_cell_size_m"
                ),
                "speed_limit_mps": candidate.run_summary.get("speed_limit_mps"),
                "solver_sha256": candidate.run_summary.get("solver_sha256"),
                "setrun_backend_sha256": candidate.run_summary.get(
                    "setrun_backend_sha256"
                ),
                "submission_pft_sha256": candidate.run_summary.get(
                    "submission_pft_sha256"
                ),
                "limiter": candidate.run_summary.get("limiter"),
                "cfl_target": candidate.run_summary.get("cfl_target"),
                "normalized_median_rmse": float(
                    np.median([row["normalized_rmse"] for row in rows])
                ),
                "median_rmse_m": float(np.median([row["rmse_m"] for row in rows])),
                "mean_rmse_m": float(np.mean([row["rmse_m"] for row in rows])),
                "maximum_rmse_m": float(np.max([row["rmse_m"] for row in rows])),
                "rmse_to_cellwise_peer_median_m": float(
                    np.sqrt(np.mean((candidate.values - peer_median) ** 2))
                ),
                "normalized_median_mae": float(
                    np.median([row["normalized_mae"] for row in rows])
                ),
                "median_mae_m": float(np.median([row["mae_m"] for row in rows])),
                "normalized_median_support_disagreement": float(
                    np.median(
                        [row["normalized_support_disagreement"] for row in rows]
                    )
                ),
                "median_support_iou": float(
                    np.median([row["support_iou"] for row in rows])
                ),
                "normalized_median_pattern_disagreement": float(
                    np.median(
                        [row["normalized_pattern_disagreement"] for row in rows]
                    )
                ),
                "median_active_correlation": float(
                    np.median([row["active_correlation"] for row in rows])
                ),
                "pft_peak_m": float(np.max(candidate.values)),
                "pft_integral_m3": float(np.sum(candidate.values) * cell_size**2),
                "pft_support_area_m2": float(np.count_nonzero(support) * cell_size**2),
            }
        )
    return summaries, details


def ranking_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    """PFT RMSE first; secondary PFT metrics only break an exact tie."""
    return (
        float(row["normalized_median_rmse"]),
        float(row["normalized_median_support_disagreement"]),
        float(row["normalized_median_pattern_disagreement"]),
        str(row["candidate"]),
    )


def leave_one_out_rankings(
    candidates: list[Candidate],
    peers: dict[str, np.ndarray],
    cell_size: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for held_out in peers:
        subset = {name: field for name, field in peers.items() if name != held_out}
        summaries, _details = candidate_rows(candidates, subset, cell_size)
        ranking = sorted(summaries, key=ranking_key)
        rows.append(
            {
                "held_out_peer": held_out,
                "first_candidate": ranking[0]["candidate"],
                "scores": {
                    row["candidate"]: row["normalized_median_rmse"]
                    for row in ranking
                },
            }
        )
    return rows


def paired_comparisons(
    candidate_names: list[str], peer_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_candidate = {
        candidate: {
            row["peer"]: float(row["rmse_m"])
            for row in peer_rows
            if row["candidate"] == candidate
        }
        for candidate in candidate_names
    }
    comparisons: list[dict[str, Any]] = []
    for index, left in enumerate(candidate_names):
        for right in candidate_names[index + 1 :]:
            left_wins = right_wins = ties = 0
            per_peer: dict[str, str] = {}
            for peer in EXPECTED_PEERS:
                delta = by_candidate[left][peer] - by_candidate[right][peer]
                if math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=FLOAT_TIE_ATOL):
                    ties += 1
                    per_peer[peer] = "tie"
                elif delta < 0.0:
                    left_wins += 1
                    per_peer[peer] = left
                else:
                    right_wins += 1
                    per_peer[peer] = right
            comparisons.append(
                {
                    "left": left,
                    "right": right,
                    "left_wins": left_wins,
                    "right_wins": right_wins,
                    "ties": ties,
                    "per_peer_winner": per_peer,
                }
            )
    return comparisons


def selection_decision(
    ranking: list[dict[str, Any]],
    peer_rows: list[dict[str, Any]],
    loo_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    leader = str(ranking[0]["candidate"])
    runner_up = str(ranking[1]["candidate"])
    leader_rmse = {
        row["peer"]: float(row["rmse_m"])
        for row in peer_rows
        if row["candidate"] == leader
    }
    runner_rmse = {
        row["peer"]: float(row["rmse_m"])
        for row in peer_rows
        if row["candidate"] == runner_up
    }
    wins = losses = ties = 0
    for peer in EXPECTED_PEERS:
        delta = leader_rmse[peer] - runner_rmse[peer]
        if math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=FLOAT_TIE_ATOL):
            ties += 1
        elif delta < 0.0:
            wins += 1
        else:
            losses += 1
    loo_firsts = sum(row["first_candidate"] == leader for row in loo_rows)
    passed = wins >= PAIRED_WINS_REQUIRED and loo_firsts == LOO_FIRSTS_REQUIRED
    return {
        "status": "selected" if passed else "no_decision",
        "candidate": leader if passed else None,
        "primary_leader": leader,
        "runner_up": runner_up,
        "leader_paired_wins": wins,
        "leader_paired_losses": losses,
        "paired_ties": ties,
        "paired_wins_required": PAIRED_WINS_REQUIRED,
        "leader_loo_firsts": loo_firsts,
        "loo_firsts_required": LOO_FIRSTS_REQUIRED,
        "reason": (
            f"{leader} passed both preregistered robustness gates"
            if passed
            else (
                f"{leader} led the primary score but did not pass both gates: "
                f"paired wins {wins}/{len(EXPECTED_PEERS)} "
                f"(required {PAIRED_WINS_REQUIRED}); leave-one-out firsts "
                f"{loo_firsts}/{LOO_FIRSTS_REQUIRED}"
            )
        ),
    }


def build_report(
    candidates: list[Candidate], peers: dict[str, np.ndarray], cell_size: float
) -> dict[str, Any]:
    summaries, peer_rows = candidate_rows(candidates, peers, cell_size)
    ranking = sorted(summaries, key=ranking_key)
    for index, row in enumerate(ranking, start=1):
        row["rank"] = index
    loo_rows = leave_one_out_rankings(candidates, peers, cell_size)
    pairwise = paired_comparisons(
        [str(row["candidate"]) for row in ranking], peer_rows
    )
    decision = selection_decision(ranking, peer_rows, loo_rows)
    loo_counts = {
        candidate.name: sum(
            row["first_candidate"] == candidate.name for row in loo_rows
        )
        for candidate in candidates
    }
    for row in ranking:
        row["loo_first_count"] = loo_counts[str(row["candidate"])]
        row["decision_status"] = (
            decision["status"]
            if row["candidate"] == decision["primary_leader"]
            else ""
        )
        if row["candidate"] == decision["primary_leader"]:
            row["paired_wins_vs_runner_up"] = decision["leader_paired_wins"]
            row["paired_losses_vs_runner_up"] = decision["leader_paired_losses"]
            row["paired_ties_vs_runner_up"] = decision["paired_ties"]
        else:
            row["paired_wins_vs_runner_up"] = ""
            row["paired_losses_vs_runner_up"] = ""
            row["paired_ties_vs_runner_up"] = ""
    return {
        "criterion": {
            "variable": "pft",
            "primary": (
                "median over peers of candidate-to-peer RMSE divided by that "
                "peer's median RMSE to every other included peer"
            ),
            "secondary_keys": [
                "normalized median PFT support disagreement (1-IoU)",
                "normalized median PFT active-pattern disagreement (1-correlation)",
            ],
            "secondary_use": "exact primary-score ties only",
            "paired_wins_required": PAIRED_WINS_REQUIRED,
            "leave_one_out_firsts_required": LOO_FIRSTS_REQUIRED,
            "support_threshold_m": PFT_SUPPORT_THRESHOLD_M,
            "raster_operations": "complete official grid; no shift, clip, pad, or resample",
        },
        "peers": list(EXPECTED_PEERS),
        "ranking": ranking,
        "candidate_peer_metrics": peer_rows,
        "leave_one_out": loo_rows,
        "pairwise": pairwise,
        "decision": decision,
    }


RANKING_FIELDS = (
    "rank",
    "candidate",
    "case",
    "limiter",
    "cfl_target",
    "state_momentum_regularization_depth_m",
    "spatial_order",
    "simulation_end_ceiling_seconds",
    "refinement_levels",
    "finest_effective_cell_size_m",
    "speed_limit_mps",
    "solver_sha256",
    "setrun_backend_sha256",
    "submission_pft_sha256",
    "provenance_status",
    "cfl_policy",
    "cfl_robustness_batch",
    "normalized_median_rmse",
    "median_rmse_m",
    "mean_rmse_m",
    "maximum_rmse_m",
    "rmse_to_cellwise_peer_median_m",
    "normalized_median_mae",
    "median_mae_m",
    "normalized_median_support_disagreement",
    "median_support_iou",
    "normalized_median_pattern_disagreement",
    "median_active_correlation",
    "pft_peak_m",
    "pft_integral_m3",
    "pft_support_area_m2",
    "loo_first_count",
    "paired_wins_vs_runner_up",
    "paired_losses_vs_runner_up",
    "paired_ties_vs_runner_up",
    "decision_status",
    "results_root",
    "pft_path",
    "pft_sha256",
    "run_summary_path",
)


def markdown_report(report: dict[str, Any]) -> str:
    provenance = report["provenance"]
    lines = [
        "# CoulombOnly PFT candidate ranking",
        "",
        "Primary score: median peer-difficulty-normalized full-grid PFT RMSE. "
        "Lower is better. Support and pattern scores are PFT-only secondary keys; "
        "PFV is not loaded or scored.",
        "",
        "## Provenance gate",
        "",
        f"Status: **{provenance['status']}**. Common solver SHA-256: "
        f"`{provenance['common_solver_sha256']}`. CFL policy: "
        f"`{provenance['cfl_policy']}`.",
        f"Common setrun backend SHA-256: "
        f"`{provenance['common_setrun_backend_sha256']}`.",
        "",
        "Gate scope: " + provenance.get("scope", "legacy report") + ".",
        "",
        "| candidate | limiter | CFL | state depth (m) | order | ceiling (s) | level | finest cell (m) | speed limit (m/s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in provenance["candidates"]:
        lines.append(
            f"| {row['candidate']} | {row['limiter']} | {row['cfl_target']:.8g} | "
            f"{row['state_momentum_regularization_depth_m']:.8g} | "
            f"{row['spatial_order']} | {row['simulation_end_ceiling_seconds']:.8g} | "
            f"{row['refinement_levels']} | {row['finest_effective_cell_size_m']:.8g} | "
            f"{row['speed_limit_mps']:.8g} |"
        )
    lines.extend(["", "Candidate PFT byte identities:", ""])
    for row in report["ranking"]:
        lines.append(
            f"- {row['candidate']}: `{row.get('pft_sha256', 'not recorded')}` "
            f"(`{row.get('pft_path', '')}`)"
        )
    official = report.get("official_inputs")
    if official:
        target = official["target_grid"]
        lines.extend(
            [
                "",
                "## Hashed comparison inputs",
                "",
                f"Pinned dataset: ISeeSnow {official['dataset_version']} "
                f"(`{official['dataset_url']}`).",
                "",
                f"Target grid SHA-256: `{target['sha256']}` (`{target['path']}`).",
                "",
                "| peer | PFT SHA-256 | path |",
                "|---|---|---|",
            ]
        )
        for source in official["peer_pft_fields"]:
            lines.append(
                f"| {source['peer']} | `{source['sha256']}` | "
                f"`{source['path']}` |"
            )
    lines.extend(
        [
        "",
        "## Ranking",
        "",
        "| rank | candidate | normalized RMSE | median RMSE (m) | median IoU | median correlation | LOO firsts |",
        "|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["ranking"]:
        lines.append(
            f"| {row['rank']} | {row['candidate']} | "
            f"{row['normalized_median_rmse']:.8g} | {row['median_rmse_m']:.8g} | "
            f"{row['median_support_iou']:.8g} | "
            f"{row['median_active_correlation']:.8g} | "
            f"{row['loo_first_count']}/{LOO_FIRSTS_REQUIRED} |"
        )

    decision = report["decision"]
    lines.extend(
        [
            "",
            "## Preregistered decision",
            "",
            f"Status: **{decision['status']}**.",
            "",
            decision["reason"] + ".",
            "",
            "## Leave-one-peer-out leaders",
            "",
            "| held-out peer | first candidate | normalized median RMSE |",
            "|---|---|---:|",
        ]
    )
    for row in report["leave_one_out"]:
        first = row["first_candidate"]
        lines.append(
            f"| {row['held_out_peer']} | {first} | {row['scores'][first]:.8g} |"
        )

    lines.extend(
        [
            "",
            "## Paired peer wins",
            "",
            "| left | right | left wins | right wins | ties |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in report["pairwise"]:
        lines.append(
            f"| {row['left']} | {row['right']} | {row['left_wins']} | "
            f"{row['right_wins']} | {row['ties']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": output / "coulomb_pft_candidate_ranking.csv",
        "json": output / "coulomb_pft_candidate_ranking.json",
        "markdown": output / "coulomb_pft_candidate_ranking.md",
    }
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=RANKING_FIELDS)
    writer.writeheader()
    writer.writerows(
        {field: row.get(field, "") for field in RANKING_FIELDS}
        for row in report["ranking"]
    )
    csv_text = csv_buffer.getvalue()
    markdown_text = markdown_report(report)
    report["published_artifacts"] = {
        "completion_marker": paths["json"].name,
        "csv": {
            "name": paths["csv"].name,
            "sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        },
        "markdown": {
            "name": paths["markdown"].name,
            "sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        },
    }
    serialized_json = json.dumps(report, indent=2, allow_nan=False) + "\n"
    pending = {
        kind: path.with_name(f".{path.name}.pending")
        for kind, path in paths.items()
    }
    for path in pending.values():
        path.unlink(missing_ok=True)
    with pending["csv"].open("w", newline="", encoding="utf-8") as stream:
        stream.write(csv_text)
    with pending["markdown"].open("w", newline="", encoding="utf-8") as stream:
        stream.write(markdown_text)
    with pending["json"].open("w", newline="", encoding="utf-8") as stream:
        stream.write(serialized_json)
    # JSON is the completion marker and carries the hashes of both companion
    # files, so an interrupted three-file replacement is detectable.
    for kind in ("csv", "markdown", "json"):
        os.replace(pending[kind], paths[kind])
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "candidates",
        nargs="+",
        type=parse_candidate,
        metavar="NAME=RESULTS_ROOT",
        help="candidate label and result root containing CoulombOnly/Submission",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory for CSV, JSON, and Markdown ranking files",
    )
    parser.add_argument(
        "--cfl-robustness-batch",
        metavar="LABEL",
        help=(
            "explicitly name a deliberate robustness batch when candidate "
            "CFL targets differ; mixed CFL is rejected without this option"
        ),
    )
    args = parser.parse_args()

    target, peers, official_inputs = official_peer_fields()
    candidates = load_candidates(args.candidates, target)
    provenance = validate_candidate_provenance(
        candidates, args.cfl_robustness_batch
    )
    report = build_report(candidates, peers, float(target.cell_size))
    report["provenance"] = provenance
    for row in report["ranking"]:
        row["provenance_status"] = provenance["status"]
        row["cfl_policy"] = provenance["cfl_policy"]
        row["cfl_robustness_batch"] = provenance["cfl_robustness_batch"] or ""
    report["official_inputs"] = official_inputs
    paths = write_outputs(report, args.output.resolve())
    decision = report["decision"]
    print(decision["reason"] + ".")
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
