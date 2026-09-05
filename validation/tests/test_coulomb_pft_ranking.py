from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "validation" / "ISeeSnow" / "rank_coulomb_pft_candidates.py"
SPEC = importlib.util.spec_from_file_location("rank_coulomb_pft_candidates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RANKING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RANKING
SPEC.loader.exec_module(RANKING)


def _valid_summary(**updates: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "case": "CoulombOnly",
        "state_momentum_regularization_depth_m": 0.05,
        "spatial_order": 2,
        "simulation_end_ceiling_seconds": 1200.0,
        "refinement_levels": 1,
        "finest_effective_cell_size_m": 5.0,
        "speed_limit_mps": 1.0e99,
        "solver_sha256": "a" * 64,
        "setrun_backend_sha256": "b" * 64,
        "submission_pft_sha256": "c" * 64,
        "limiter": "vanleer",
        "cfl_target": 0.5,
    }
    summary.update(updates)
    return summary


def _candidate(name: str, **summary_updates: object):
    return RANKING.Candidate(
        name,
        Path(name),
        Path(f"{name}.asc"),
        np.ones((2, 2), dtype=float),
        Path(f"{name}.json"),
        _valid_summary(**summary_updates),
        "c" * 64,
    )


def _peer_rows(left: list[float], right: list[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for peer, left_rmse, right_rmse in zip(
        RANKING.EXPECTED_PEERS, left, right, strict=True
    ):
        rows.extend(
            (
                {"candidate": "left", "peer": peer, "rmse_m": left_rmse},
                {"candidate": "right", "peer": peer, "rmse_m": right_rmse},
            )
        )
    return rows


def _ranking() -> list[dict[str, object]]:
    return [
        {"candidate": "left", "normalized_median_rmse": 1.0},
        {"candidate": "right", "normalized_median_rmse": 2.0},
    ]


def _loo(firsts: list[str]) -> list[dict[str, object]]:
    return [
        {"held_out_peer": peer, "first_candidate": first, "scores": {}}
        for peer, first in zip(RANKING.EXPECTED_PEERS, firsts, strict=True)
    ]


def test_decision_requires_six_paired_wins_and_all_leave_one_out_firsts() -> None:
    peer_rows = _peer_rows([1.0] * 7, [2.0] * 7)
    loo_rows = _loo(["left"] * 7)

    decision = RANKING.selection_decision(_ranking(), peer_rows, loo_rows)

    assert decision["status"] == "selected"
    assert decision["candidate"] == "left"
    assert decision["leader_paired_wins"] == 7
    assert decision["leader_loo_firsts"] == 7


def test_decision_refuses_a_primary_leader_without_peer_consensus() -> None:
    # The aggregate ranking can lead while only five individual peers agree.
    peer_rows = _peer_rows(
        [1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 3.0],
        [2.0, 2.0, 2.0, 2.0, 2.0, 1.0, 1.0],
    )

    decision = RANKING.selection_decision(
        _ranking(), peer_rows, _loo(["left"] * 7)
    )

    assert decision["status"] == "no_decision"
    assert decision["candidate"] is None
    assert decision["leader_paired_wins"] == 5


def test_decision_refuses_a_leave_one_out_ranking_flip() -> None:
    peer_rows = _peer_rows([1.0] * 7, [2.0] * 7)
    firsts = ["left"] * 6 + ["right"]

    decision = RANKING.selection_decision(
        _ranking(), peer_rows, _loo(firsts)
    )

    assert decision["status"] == "no_decision"
    assert decision["leader_loo_firsts"] == 6


def test_full_report_prefers_the_candidate_nearest_peer_consensus() -> None:
    random = np.random.default_rng(4)
    base = np.zeros((12, 12), dtype=float)
    base[3:9, 2:10] = np.linspace(0.1, 3.0, 48).reshape(6, 8)
    peers = {
        name: np.maximum(
            0.0,
            np.roll(base, (index % 3 - 1, index // 3 - 1), axis=(0, 1))
            * (1.0 + 0.03 * (index - 3))
            + random.normal(0.0, 0.01, base.shape),
        )
        for index, name in enumerate(RANKING.EXPECTED_PEERS)
    }
    candidates = [
        RANKING.Candidate(
            "near",
            Path("near"),
            Path("near.asc"),
            np.median(np.stack(list(peers.values())), axis=0),
            Path("near.json"),
            _valid_summary(limiter="minmod"),
        ),
        RANKING.Candidate(
            "far",
            Path("far"),
            Path("far.asc"),
            np.flipud(base) * 1.8,
            Path("far.json"),
            _valid_summary(limiter="vanleer"),
        ),
    ]

    report = RANKING.build_report(candidates, peers, 5.0)

    assert [row["candidate"] for row in report["ranking"]] == ["near", "far"]
    assert report["decision"]["status"] == "selected"
    assert report["decision"]["candidate"] == "near"
    assert report["decision"]["leader_paired_wins"] == 7
    assert report["decision"]["leader_loo_firsts"] == 7


def test_provenance_accepts_only_the_fixed_experiment_and_common_solver() -> None:
    provenance = RANKING.validate_candidate_provenance(
        [_candidate("minmod", limiter="minmod"), _candidate("vanleer")]
    )

    assert provenance["status"] == "passed"
    assert provenance["common_solver_sha256"] == "a" * 64
    assert provenance["common_setrun_backend_sha256"] == "b" * 64
    assert provenance["cfl_policy"] == "common_cfl"
    assert provenance["cfl_targets"] == [0.5]


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("state_momentum_regularization_depth_m", 0.1),
        ("spatial_order", 1),
        ("simulation_end_ceiling_seconds", 120.0),
        ("refinement_levels", 2),
        ("finest_effective_cell_size_m", 2.5),
        ("speed_limit_mps", 100.0),
    ],
)
def test_provenance_rejects_any_changed_fixed_control(
    key: str, bad_value: float
) -> None:
    with pytest.raises(RuntimeError, match=key):
        RANKING.validate_candidate_provenance(
            [_candidate("bad", **{key: bad_value}), _candidate("control")]
        )


def test_provenance_rejects_wrong_case_or_mixed_solver_hashes() -> None:
    with pytest.raises(RuntimeError, match="expected 'CoulombOnly'"):
        RANKING.validate_candidate_provenance(
            [_candidate("bad", case="IdealizedTopo"), _candidate("control")]
        )


def test_provenance_rejects_mixed_backend_or_mismatched_pft_hash() -> None:
    with pytest.raises(RuntimeError, match="share one setrun backend SHA-256"):
        RANKING.validate_candidate_provenance(
            [
                _candidate("left"),
                _candidate("right", setrun_backend_sha256="d" * 64),
            ]
        )
    with pytest.raises(RuntimeError, match="PFT bytes do not match"):
        RANKING.validate_candidate_provenance(
            [
                _candidate("left", submission_pft_sha256="d" * 64),
                _candidate("right"),
            ]
        )
    with pytest.raises(RuntimeError, match="share one solver SHA-256"):
        RANKING.validate_candidate_provenance(
            [
                _candidate("left"),
                _candidate("right", solver_sha256="b" * 64),
            ]
        )


def test_mixed_cfl_requires_and_records_a_named_robustness_batch() -> None:
    candidates = [_candidate("cfl050", cfl_target=0.5), _candidate("cfl025", cfl_target=0.25)]

    with pytest.raises(RuntimeError, match="--cfl-robustness-batch"):
        RANKING.validate_candidate_provenance(candidates)

    provenance = RANKING.validate_candidate_provenance(
        candidates, "vanleer-cfl-sensitivity"
    )
    assert provenance["cfl_policy"] == "explicit_named_robustness_batch"
    assert provenance["cfl_robustness_batch"] == "vanleer-cfl-sensitivity"
    assert provenance["cfl_targets"] == [0.25, 0.5]


def test_outputs_record_the_decision_in_csv_json_and_markdown(tmp_path: Path) -> None:
    provenance_row = {
        "candidate": "synthetic",
        "run_summary_path": "synthetic.json",
        **_valid_summary(),
    }
    report = {
        "ranking": [
            {
                field: "" for field in RANKING.RANKING_FIELDS
            }
        ],
        "leave_one_out": [],
        "pairwise": [],
        "decision": {
            "status": "no_decision",
            "reason": "synthetic gate failure",
        },
        "provenance": {
            "status": "passed",
            "common_solver_sha256": "a" * 64,
            "common_setrun_backend_sha256": "b" * 64,
            "cfl_policy": "common_cfl",
            "candidates": [provenance_row],
        },
    }
    report["ranking"][0].update(
        {
            "rank": 1,
            "candidate": "synthetic",
            "normalized_median_rmse": 1.25,
            "median_rmse_m": 0.4,
            "median_support_iou": 0.7,
            "median_active_correlation": 0.6,
            "loo_first_count": 0,
            "case": "CoulombOnly",
            "limiter": "vanleer",
            "cfl_target": 0.5,
            "state_momentum_regularization_depth_m": 0.05,
            "spatial_order": 2,
            "simulation_end_ceiling_seconds": 1200.0,
            "refinement_levels": 1,
            "finest_effective_cell_size_m": 5.0,
            "speed_limit_mps": 1.0e99,
            "solver_sha256": "a" * 64,
            "provenance_status": "passed",
            "cfl_policy": "common_cfl",
        }
    )

    paths = RANKING.write_outputs(report, tmp_path)

    assert set(paths) == {"csv", "json", "markdown"}
    csv_text = paths["csv"].read_text(encoding="utf-8")
    assert "synthetic" in csv_text
    assert "state_momentum_regularization_depth_m" in csv_text
    assert "common_cfl" in csv_text
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "no_decision"
    assert payload["provenance"]["common_solver_sha256"] == "a" * 64
    assert payload["provenance"]["common_setrun_backend_sha256"] == "b" * 64
    assert payload["published_artifacts"]["completion_marker"] == paths["json"].name
    assert payload["published_artifacts"]["csv"]["sha256"] == hashlib.sha256(
        paths["csv"].read_bytes()
    ).hexdigest()
    assert payload["published_artifacts"]["markdown"]["sha256"] == hashlib.sha256(
        paths["markdown"].read_bytes()
    ).hexdigest()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "PFV is not loaded or scored" in markdown
    assert "synthetic gate failure" in markdown
    assert "Common solver SHA-256" in markdown


def test_file_hash_records_the_exact_candidate_bytes(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate_pft.asc"
    candidate.write_bytes(b"fixed PFT bytes\n")

    assert RANKING.file_sha256(candidate) == (
        "550b2565ea68717508d9d1c6cc96e45920ed9b55f3fc11a"
        "3da30e7c51610c37e"
    )


@pytest.mark.parametrize("bad", (float("nan"), float("inf"), -1.0e-12))
def test_candidate_pft_rejects_invalid_values_instead_of_cleaning(
    bad: float,
) -> None:
    values = np.ones((2, 2), dtype=float)
    values[0, 0] = bad

    with pytest.raises(RuntimeError, match="candidate 'bad' PFT contains"):
        RANKING.validated_candidate_pft(values, "bad")
