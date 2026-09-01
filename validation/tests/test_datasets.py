from __future__ import annotations

from pathlib import Path

from avac4qgis_validation.datasets import (
    ISEESNOW_REQUIRED_FILES,
    iseesnow_dataset_complete,
)


def test_iseesnow_completeness_rejects_an_empty_data_tree(tmp_path: Path) -> None:
    (tmp_path / "data" / "IdealizedTopo").mkdir(parents=True)

    assert not iseesnow_dataset_complete(tmp_path)


def test_iseesnow_completeness_requires_every_benchmark_input(tmp_path: Path) -> None:
    for relative in ISEESNOW_REQUIRED_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    assert iseesnow_dataset_complete(tmp_path)

    (tmp_path / ISEESNOW_REQUIRED_FILES[-1]).unlink()
    assert not iseesnow_dataset_complete(tmp_path)
