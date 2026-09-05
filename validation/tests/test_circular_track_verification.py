from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPOSITORY
    / "validation"
    / "AVAC"
    / "Curvature_normal_stress"
    / "run_circular_track_verification.py"
)


def test_circular_track_locks_planes_and_exposes_changing_basis(tmp_path: Path):
    output_root = tmp_path / "circular-track"
    environment = os.environ.copy()
    environment["MPLBACKEND"] = "Agg"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-root", str(output_root)],
        cwd=REPOSITORY,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    summary_path = output_root / "results" / "circular_track_summary.json"
    history_path = output_root / "results" / "circular_track_history.csv"
    figure_path = (
        output_root / "figures" / "circular_track_coordinate_verification.png"
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = {row["case"]: row for row in summary["cases"]}

    assert json.loads(completed.stdout) == summary
    assert set(cases) == {
        "flat_coulomb",
        "constant_slope_coulomb",
        "circular_zero_force",
        "circular_coulomb",
    }

    # A fixed basis is the non-negotiable control: both coordinate forms must
    # remain bit-for-bit identical on flat and constant-slope terrain.
    for name in ("flat_coulomb", "constant_slope_coulomb"):
        assert cases[name]["maximum_speed_difference_m_s"] == 0.0
        assert cases[name]["exit_speed_difference_m_s"] == 0.0

    # With no forces on a circular track, terrain speed is invariant.  The
    # reduced Cartesian reconstruction loses exactly the changing projection.
    zero_force = cases["circular_zero_force"]
    assert zero_force["terrain_following_exit_speed_m_s"] == pytest.approx(
        80.0, abs=2.0e-11
    )
    assert zero_force["reduced_cartesian_exit_speed_m_s"] == pytest.approx(
        80.0 * math.cos(math.radians(34.0)), abs=2.0e-9
    )

    curved_coulomb = cases["circular_coulomb"]
    assert curved_coulomb["exit_speed_difference_m_s"] > 10.0
    assert curved_coulomb["maximum_omitted_basis_acceleration_m_s2"] > 10.0
    assert (
        curved_coulomb["reduced_cartesian_travel_time_s"]
        > curved_coulomb["terrain_following_travel_time_s"]
    )

    expected_lines = 1 + 4 * 2 * summary["output_samples_per_formulation"]
    assert sum(1 for _ in history_path.open(encoding="utf-8")) == expected_lines
    assert figure_path.stat().st_size > 10_000
