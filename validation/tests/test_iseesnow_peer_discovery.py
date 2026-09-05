"""Native peak filenames must neither omit nor double-weight a peer model."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest


VALIDATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VALIDATION))
SPEC = importlib.util.spec_from_file_location(
    "compare_iseesnow_peer_discovery", VALIDATION / "ISeeSnow" / "compare_iseesnow.py"
)
assert SPEC is not None and SPEC.loader is not None
COMPARISON = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COMPARISON
# Pair discovery is independent of downloading the official benchmark.
with patch("avac4qgis_validation.datasets.ensure_iseesnow", return_value=Path("unused")):
    SPEC.loader.exec_module(COMPARISON)


def write_grid(path: Path, values: str = "1.5 2.0\n3.0 4.0\n") -> bytes:
    payload = (
        "ncols 2\nnrows 2\nxllcenter 1000\nyllcenter -5000\n"
        "cellsize 5\nNODATA_value -9999\n" + values
    ).encode()
    path.write_bytes(payload)
    return payload


@pytest.mark.parametrize("prefix", [
    "1HS_01_curv91s_MoT-Voellmy",
    "Wog_02_curv151s_MoT-Voellmy",
    "1HS_03_curv76s_MoT-Voellmy",
])
def test_native_peak_pairs_preserve_coordinates_and_values(tmp_path: Path, prefix: str) -> None:
    pft = tmp_path / f"{prefix}_h_max.asc"
    pfv = tmp_path / f"{prefix}_s_max.asc"
    before = {pft: write_grid(pft), pfv: write_grid(pfv, "10 20\n30 40\n")}

    pairs, exclusions = COMPARISON.output_pairs(tmp_path)

    assert pairs == [("MoT-Voellmy", pft, pfv)]
    assert exclusions == []
    thickness = COMPARISON.read_grid(pairs[0][1])
    speed = COMPARISON.read_grid(pairs[0][2])
    np.testing.assert_array_equal(thickness.values_north, [[1.5, 2.0], [3.0, 4.0]])
    np.testing.assert_array_equal(speed.values_north, [[10, 20], [30, 40]])
    np.testing.assert_array_equal(thickness.x_centres, [1000, 1005])
    np.testing.assert_array_equal(thickness.y_centres, [-5000, -4995])
    assert COMPARISON.same_grid(thickness, speed) == (True, "")
    assert {path: path.read_bytes() for path in before} == before


def test_standard_export_supersedes_alternate_export_for_same_model(tmp_path: Path) -> None:
    standard_pft = tmp_path / "release_null_MoT-Voellmy_pft.asc"
    standard_pfv = tmp_path / "release_null_MoT-Voellmy_pfv.asc"
    for path in (standard_pft, standard_pfv,
                 tmp_path / "release_native_MoT-Voellmy_h_max.asc",
                 tmp_path / "release_native_MoT-Voellmy_s_max.asc"):
        write_grid(path)

    pairs, exclusions = COMPARISON.output_pairs(tmp_path)

    assert pairs == [("MoT-Voellmy", standard_pft, standard_pfv)]
    assert len(exclusions) == 1
    assert "already has a paired export" in exclusions[0]["reason"]


def test_unpaired_native_thickness_is_reported(tmp_path: Path) -> None:
    write_grid(tmp_path / "release_Model_h_max.asc")

    pairs, exclusions = COMPARISON.output_pairs(tmp_path)

    assert pairs == []
    assert exclusions[0]["model"] == "Model"
    assert exclusions[0]["reason"] == "h_max exists but matching s_max is absent"


def test_native_names_do_not_bypass_grid_validation(tmp_path: Path) -> None:
    pft = tmp_path / "release_Model_h_max.asc"
    pfv = tmp_path / "release_Model_s_max.asc"
    write_grid(pft)
    write_grid(pfv)
    pfv.write_text(pfv.read_text().replace("xllcenter 1000", "xllcenter 1002.5"))

    pairs, _ = COMPARISON.output_pairs(tmp_path)

    assert len(pairs) == 1
    assert COMPARISON.same_grid(
        COMPARISON.read_grid(pairs[0][1]), COMPARISON.read_grid(pairs[0][2])
    ) == (False, "X cell centres differ")
