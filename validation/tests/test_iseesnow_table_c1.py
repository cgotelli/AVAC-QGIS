from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "validation" / "ISeeSnow" / "paper_figures" / "iseesnow_table_c1_core.csv"


def test_table_c1_contains_the_complete_core_group() -> None:
    with TABLE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    models = {row["model"] for row in rows}
    counts = Counter(row["case"] for row in rows)

    assert len(models) == 11
    assert counts == {
        "IdealizedTopo": 11,
        "RealTopo": 10,
        "CoulombOnly": 11,
    }
    assert "TITAN2D" in models
    assert not any(
        row["case"] == "RealTopo" and row["model"] == "TITAN2D"
        for row in rows
    )
