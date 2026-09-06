"""Exercise WAVE setrun's patch limit and exact physical/output cell counts."""

import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest


SOURCE = Path(__file__).resolve().parents[2] / "avac-main" / "src" / "WAVE" / "setrun.py"


@pytest.fixture
def wave_namespace(monkeypatch):
    """Execute production setrun/helper without importing Clawpack's MPI stack."""
    rundata = SimpleNamespace(
        clawdata=SimpleNamespace(lower=[0., 0.], upper=[0., 0.], num_cells=[0, 0],
                                 bc_lower=[0, 0], bc_upper=[0, 0]),
        amrdata=SimpleNamespace(max1d=60),
        gaugedata=SimpleNamespace(gauges=[]),
        regiondata=SimpleNamespace(regions=[]),
        fgout_data=SimpleNamespace(fgout_grids=[]),
        new_UserData=lambda **_kwargs: SimpleNamespace(add_param=lambda *_args: None),
    )
    clawpack = ModuleType("clawpack")
    clawutil = ModuleType("clawpack.clawutil")
    data = ModuleType("clawpack.clawutil.data")
    data.ClawRunData = lambda *_args: rundata
    clawpack.clawutil = clawutil
    clawutil.data = data
    for name, module in (("clawpack", clawpack), ("clawpack.clawutil", clawutil),
                         ("clawpack.clawutil.data", data)):
        monkeypatch.setitem(sys.modules, name, module)
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_whole_cell_count", "setrun"}]
    assert len(functions) == 2
    namespace = {
        "setgeo": lambda value: value,
        "lake": {"xmin": 2667311., "xmax": 2673098., "ymin": 1169558., "ymax": 1173185.},
        "computation": {"cell_size": 1., "t_0": 0., "t_max": 150., "nb_simul": 150,
                        "cfl_target": .5, "cfl_max": 1., "max_iter": 100000,
                        "limiter": "vanleer", "boundary": "extrap", "refinement": 1},
        "output": {"output_format": "binary32"},
        "gauges": {"gauge_recording": False},
        "fgout_tools": SimpleNamespace(FGoutGrid=SimpleNamespace),
        "proj_dir": SOURCE.parent.parent,
        "np": np,
    }
    code = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(code, str(SOURCE), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("levels,expected", [(1, 250), (2, 60), (3, 60)])
def test_wave_patch_limit_preserves_resolution_output_and_amr(wave_namespace, levels, expected):
    wave_namespace["computation"]["refinement"] = levels
    result = wave_namespace["setrun"]()
    assert result.amrdata.max1d == expected
    assert result.amrdata.amr_levels_max == levels
    assert result.amrdata.refinement_ratios_x == [10, 5, 2]
    assert result.amrdata.refinement_ratios_y == [10, 5, 2]
    assert result.clawdata.lower == [2667311., 1169558.]
    assert result.clawdata.upper == [2673098., 1173185.]
    assert result.clawdata.num_cells == [5787, 3627]
    assert result.clawdata.num_ghost == 2
    assert result.clawdata.cfl_desired == .5
    assert result.clawdata.cfl_max == 1.
    fgout = result.fgout_data.fgout_grids[0]
    assert (fgout.nx, fgout.ny, fgout.nout) == (5787, 3627, 151)
    assert (fgout.x1, fgout.x2, fgout.y1, fgout.y2) == (2667311., 2673098., 1169558., 1173185.)


@pytest.mark.parametrize("levels", [1, 2, 3])
def test_fractional_spacing_preserves_solver_and_fgout_cells(wave_namespace, levels):
    # Decimal YAML bounds on the Swiss grid produce ratios just below whole
    # counts on both axes. Truncating used to lose a full row and column.
    bounds = {"xmin": 2667311.2, "xmax": 2667889.9,
              "ymin": 1169558.2, "ymax": 1169920.9}
    wave_namespace["lake"] = bounds
    wave_namespace["computation"].update(cell_size=.1, refinement=levels)
    assert int((bounds["xmax"] - bounds["xmin"]) / .1) == 5786
    assert int((bounds["ymax"] - bounds["ymin"]) / .1) == 3626
    helper = wave_namespace["_whole_cell_count"]
    calls = []

    def counted_cell_count(lower, upper, spacing, axis):
        calls.append(axis)
        return helper(lower, upper, spacing, axis)

    wave_namespace["_whole_cell_count"] = counted_cell_count
    result = wave_namespace["setrun"]()
    fgout = result.fgout_data.fgout_grids[0]
    assert calls == ["x", "y"]  # Compute once, reuse for solver and output.
    assert result.clawdata.num_cells == [5787, 3627]
    assert (fgout.nx, fgout.ny) == (5787, 3627)
    assert result.clawdata.lower == [bounds["xmin"], bounds["ymin"]]
    assert result.clawdata.upper == [bounds["xmax"], bounds["ymax"]]
    assert (fgout.x1, fgout.x2, fgout.y1, fgout.y2) == (
        bounds["xmin"], bounds["xmax"], bounds["ymin"], bounds["ymax"])
    assert result.amrdata.max1d == (250 if levels == 1 else 60)


@pytest.mark.parametrize("lower,upper,spacing,expected", [
    (0., 1., 1., 1),
    (.1, .3, .1, 2),  # Ratio rounds down.
    (.1, .1 + .1 * 2, .1, 2),  # Ratio rounds up.
    (2667311.2, 2667311.3, .1, 1),
    (-.3, -.1, .1, 2),
])
def test_whole_cell_count_accepts_positive_integral_spans(
        wave_namespace, lower, upper, spacing, expected):
    count = wave_namespace["_whole_cell_count"](lower, upper, spacing, "x")
    assert count == expected
    assert isinstance(count, int)


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("lower,upper,spacing", [
    (0., 1.05, .1),  # A genuinely fractional manually configured span.
    (0., 1.000001, .1),  # Outside the roundoff-only tolerance.
    (0., 0., .1),
    (1., 0., .1),
    (0., .05, .1),  # Less than one cell.
    (0., 1., 0.),
    (0., 1., -.1),
    (0., 1., float("nan")),
    (0., 1., float("inf")),
    (float("nan"), 1., .1),
    (0., float("inf"), .1),
    (float("-inf"), 1., .1),
    (-1e308, 1e308, .1),  # Overflowed span.
    (0., 1e308, 1e-308),  # Finite span/spacing but overflowed ratio.
])
def test_setrun_rejects_invalid_cell_counts(wave_namespace, axis, lower, upper, spacing):
    wave_namespace["lake"].update({f"{axis}min": lower, f"{axis}max": upper})
    wave_namespace["computation"]["cell_size"] = spacing
    # The unchanged other axis must be valid, including for tiny spacing.
    other_axis = "y" if axis == "x" else "x"
    wave_namespace["lake"].update({f"{other_axis}min": 0., f"{other_axis}max": spacing})
    with pytest.raises(ValueError, match=r"WAVE [xy]-domain"):
        wave_namespace["setrun"]()
