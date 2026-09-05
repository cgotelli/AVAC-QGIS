"""Profile diagnostics preserve the authenticated raster and protocol contract."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ISeeSnow/paper_figures/make_coulomb_runout_diagnosis.py"
SPEC = importlib.util.spec_from_file_location("coulomb_runout_diagnosis", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIGURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIGURE)


def test_protocol_mismatch_is_not_opted_in_by_default():
    args = FIGURE.parse_args(["--baseline", "old", "--candidate", "new", "--output", "figure"])
    assert not args.allow_protocol_differences
    assert FIGURE.parse_args(["--baseline", "old", "--candidate", "new", "--output", "figure",
                              "--allow-protocol-differences"]).allow_protocol_differences


def test_build_report_reuses_cross_source_protocol_gate():
    args = SimpleNamespace(allow_protocol_differences=False)
    def refuse(actual_args, *unused):
        assert actual_args is args
        raise RuntimeError("Numerical protocol differs")
    source = SimpleNamespace(compare_case=refuse)
    paper = SimpleNamespace(validated_peer_table=lambda path: (None, {}))
    with pytest.raises(RuntimeError, match="Numerical protocol differs"):
        FIGURE.build_report(args, source, None, None, paper)


def test_profile_is_unshifted_cross_flow_maximum():
    field = np.array([[0, 3, 1, 0], [2, 0, 4, 1]])
    np.testing.assert_array_equal(FIGURE.cross_flow_profile(field), [2, 3, 4, 1])
    np.testing.assert_array_equal(field, [[0, 3, 1, 0], [2, 0, 4, 1]])


@pytest.mark.parametrize("field", [[[np.nan]], [[-1]], [1, 2]])
def test_invalid_submission_profile_is_rejected(field):
    with pytest.raises(RuntimeError, match="finite, non-negative two-dimensional"):
        FIGURE.cross_flow_profile(field)


def test_terrain_uses_north_row_order_and_original_elevations():
    grid = SimpleNamespace(x_centres=np.arange(3), y_centres=np.array([10, 11, 12]),
                           values_north=np.array([[90, 80, 70], [60, 50, 40], [30, 20, 10]]))
    bed, rows = FIGURE.terrain_profile(grid, np.array([[0, 12], [2, 10]]))
    np.testing.assert_array_equal(rows, [0, 1, 2])
    np.testing.assert_array_equal(bed, [90, 50, 10])


def test_nonmonotonic_path_is_not_silently_reordered():
    with pytest.raises(RuntimeError, match="strictly x-increasing"):
        FIGURE.terrain_profile(None, np.array([[1, 1], [0, 1]]))


def test_affine_terrain_has_no_invented_curved_transition():
    x = np.arange(20, dtype=float)
    assert FIGURE.concave_transition(x, 1000 - 0.5*x) is None


def test_concave_annotation_is_derived_from_dem_not_fitted_radius():
    x = np.arange(30, dtype=float)
    bed = np.where(x < 10, 20-x, np.where(x < 20, (20-x)**2/20 + 5, 5))
    interval = FIGURE.concave_transition(x, bed)
    assert interval is not None
    assert 8 <= interval[0] <= 11
    assert 18 <= interval[1] <= 21


def test_hash_is_checked_again_after_grid_read(tmp_path):
    path = tmp_path / "field.asc"
    path.write_bytes(b"original")
    record = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    def artifact(path, expected):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Artifact hash mismatch")
    def read_grid(path):
        path.write_bytes(b"changed while being read")
        return None
    with pytest.raises(RuntimeError, match="Artifact hash mismatch"):
        FIGURE.authenticated_grid(record, SimpleNamespace(artifact=artifact), SimpleNamespace(read_grid=read_grid))


@pytest.mark.parametrize("matched", [False, True])
def test_figure_visibly_labels_comparison_status_and_profile_limitations(tmp_path, monkeypatch, matched):
    runs = [{"label": label, "protocol": {"simulation_end_ceiling_seconds": seconds},
             "runout_by_threshold_m": {"0.5": 100}} for label, seconds in (
                 ("baseline", 1200), ("candidate", 1200 if matched else 120))]
    report = {
        "comparison": {"runs": runs, "matched_protocol": matched, "aligned_peer_count": 2},
        "x_m": [0, 1, 2], "display_x_limits_m": [0, 2],
        "profiles": {"runs": {label: {"pft": [1, 2, 0], "pfv": [3, 2, 0]}
                               for label in ("baseline", "candidate")}, "peers": {},
                     "peer_statistics": {var: {key: [1, 2, 0] for key in ("q1", "median", "q3")}
                                         for var in ("pft", "pfv")}},
        "terrain": {"elevation_m": [2, 1, 1], "concave_transition_x_m": [0, 1]},
    }
    real_close = FIGURE.plt.close
    monkeypatch.setattr(FIGURE.plt, "close", lambda *unused: None)
    monkeypatch.setattr(FIGURE.plt.Figure, "savefig", lambda *unused, **kwargs: None)
    FIGURE.render(report, tmp_path)
    figure = FIGURE.plt.gcf()
    text = "\n".join(item.get_text() for item in figure.texts)
    assert ("UNMATCHED DIAGNOSTIC" in text) is not matched
    assert ("Matched numerical/physical protocols" in text) is matched
    assert "not particle tracks or simultaneous states" in text
    real_close(figure)
