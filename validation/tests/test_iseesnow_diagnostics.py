from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"
sys.path.insert(0, str(VALIDATION))
SPEC = importlib.util.spec_from_file_location(
    "run_iseesnow_avac", VALIDATION / "ISeeSnow" / "run_iseesnow_avac.py"
)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)


def test_benchmark_domain_edges_and_results_share_supplied_cell_centres(tmp_path: Path) -> None:
    grid = DRIVER.EsriGrid(
        tmp_path / "dem.asc", 3, 2, 10.0, -5.0, 5.0, -9999.0,
        np.zeros((2, 3), dtype=float),
    )
    configuration_path = tmp_path / "AVAC_configuration.yaml"
    configuration_path.write_text("dem_extent: {}\n", encoding="utf-8")

    DRIVER.set_benchmark_computational_extent(configuration_path, grid)

    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    assert configuration["dem_extent"] == {
        "xmin": 7.5, "xmax": 22.5, "ymin": -7.5, "ymax": 2.5,
        "nbx": 3, "nby": 2, "cell_size": 5.0,
    }
    assert configuration["result_grid"] == {
        "xllcenter": 10.0, "yllcenter": -5.0,
        "ncols": 3, "nrows": 2, "cell_size": 5.0,
    }


def test_normal_pft_preserves_internal_south_to_north_orientation() -> None:
    peak = np.array([[1.0, 2.0], [3.0, 4.0]])
    initial = np.array([[5.0, 0.0], [0.0, 0.0]])
    cosine = np.array([[1.0, 0.5], [0.25, 0.125]])

    result = DRIVER.normal_peak_thickness(peak, initial, cosine)

    np.testing.assert_allclose(result, [[5.0, 1.0], [0.75, 0.5]])


def test_normal_release_depth_uses_fractional_cell_coverage() -> None:
    dem = DRIVER.EsriGrid(
        Path("flat.asc"), 2, 2, 0.0, 0.0, 5.0, -9999.0,
        np.zeros((2, 2), dtype=float),
    )
    coverage = np.array([[1.0, 0.5], [0.25, 0.0]])

    vertical_depth, cosine = DRIVER.normal_depth_to_vertical(dem, coverage)

    np.testing.assert_allclose(cosine, np.ones((2, 2)))
    np.testing.assert_allclose(
        vertical_depth,
        DRIVER.NORMAL_RELEASE_THICKNESS_M * coverage,
    )
