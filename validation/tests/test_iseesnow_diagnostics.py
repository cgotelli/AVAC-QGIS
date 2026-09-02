from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VALIDATION))

from avac_qgis.core.preprocessing import QINIT_BINARY_HEADER, QINIT_BINARY_MAGIC
from avac4qgis_validation.notebook import validation_case

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


def test_iseesnow_initial_condition_keeps_the_active_binary_qinit_contract(tmp_path: Path) -> None:
    dem = DRIVER.EsriGrid(
        tmp_path / "dem.asc", 3, 2, 10.0, -5.0, 5.0, -9999.0,
        np.zeros((2, 3), dtype=float),
    )
    raster = DRIVER.benchmark_raster(dem, crs_authid="")
    coverage = np.array([[1.0, 0.5, 0.0], [0.25, 0.0, 1.0]])
    destination = tmp_path / "init.avacbin"

    vertical_depth, cosine_slope = DRIVER.write_iseesnow_initial_condition(
        destination, raster, dem, coverage,
    )

    payload = destination.read_bytes()
    assert payload.startswith(QINIT_BINARY_MAGIC)
    magic, ncols, nrows, components, reserved, xlow, yhigh, dx, dy = QINIT_BINARY_HEADER.unpack_from(payload)
    assert (magic, ncols, nrows, components, reserved) == (QINIT_BINARY_MAGIC, 3, 2, 1, 0)
    assert (xlow, yhigh, dx, dy) == (10.0, 0.0, 5.0, 5.0)
    np.testing.assert_allclose(cosine_slope, np.ones((2, 3)))
    np.testing.assert_allclose(vertical_depth, DRIVER.NORMAL_RELEASE_THICKNESS_M * coverage)
    np.testing.assert_allclose(
        np.frombuffer(payload, dtype="<f8", offset=QINIT_BINARY_HEADER.size),
        np.flipud(vertical_depth).ravel(),
    )


def test_iseesnow_figure_notebook_uses_the_case_sensitive_published_path(tmp_path: Path) -> None:
    build_spec = importlib.util.spec_from_file_location("build_iseesnow_notebooks", VALIDATION / "build_notebooks.py")
    assert build_spec is not None and build_spec.loader is not None
    builder = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(builder)
    builder.ROOT = tmp_path

    builder.iseesnow_notebooks()

    notebook_path = tmp_path / "ISeeSnow" / "paper_figures" / "ISeeSnow_intercomparison_figures.ipynb"
    assert notebook_path.is_file()
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "validation_case('ISeeSnow', 'paper_figures')" in code
    assert validation_case("ISeeSnow", "paper_figures").path == VALIDATION / "ISeeSnow" / "paper_figures"


def test_iseesnow_requires_two_fixed_grid_output_frames(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least two fixed-grid output frames"):
        DRIVER.configure_template(
            "IdealizedTopo", tmp_path,
            simulation_end_s=0.1,
            output_interval_s=0.1,
        )


def test_iseesnow_preserves_the_requested_fixed_grid_cadence() -> None:
    assert DRIVER.fixed_grid_output_frame_count(1200.0, 10.0) == 120
    with pytest.raises(ValueError, match="exact multiple"):
        DRIVER.fixed_grid_output_frame_count(0.25, 0.1)


def test_iseesnow_rebuilds_current_source_once_per_driver_process(
    tmp_path: Path, monkeypatch,
) -> None:
    """A pre-existing executable must not silently bypass the latest source."""
    source = tmp_path / "AVAC"
    source.mkdir()
    executable = source / ("xgeoclaw.exe" if DRIVER.os.name == "nt" else "xgeoclaw")
    executable.write_text("test executable", encoding="utf-8")
    calls: list[str] = []

    def build(kind: str) -> Path:
        calls.append(kind)
        return source

    monkeypatch.setattr(DRIVER, "build_solver", build)
    DRIVER.current_source_solver.cache_clear()
    try:
        assert DRIVER.current_source_solver() == executable
        assert DRIVER.current_source_solver() == executable
        assert calls == ["avac"]
    finally:
        DRIVER.current_source_solver.cache_clear()
