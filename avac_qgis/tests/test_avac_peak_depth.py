"""Source contracts for an accurate and practical AVAC peak-depth product."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETRUN = ROOT / "avac-main" / "src" / "AVAC" / "setrun.py"
FGMAX = (
    ROOT
    / "avac-main"
    / "clawpack-v5.14.0"
    / "geoclaw"
    / "src"
    / "2d"
    / "shallow"
    / "fgmax_frompatch.f90"
)
STEPGRID = (
    ROOT
    / "avac-main"
    / "clawpack-v5.14.0"
    / "geoclaw"
    / "src"
    / "2d"
    / "shallow"
    / "stepgrid.f"
)


def test_peak_depth_includes_initial_state_and_checks_every_solver_step():
    source = SETRUN.read_text(encoding="utf-8")

    assert "fg.tstart_max = 0." in source
    assert "fg.dt_check   = 0.0" in source
    assert "fg_zoom.tstart_max = 0." in source
    assert "fg_zoom.dt_check   = 0.0" in source


def test_zoom_outputs_require_actual_amr_refinement():
    source = SETRUN.read_text(encoding="utf-8")

    assert "use_zoom_output = bool(Refine['topo_refinement']) and int(Param['refinement']) > 1" in source
    # One condition each for the zoom region, FGmax grid, and FGout grid.
    assert source.count("if use_zoom_output:") == 3


def test_every_step_peak_tracking_skips_only_initialized_exactly_dry_patches():
    source = FGMAX.read_text(encoding="utf-8").lower()

    assert "maxval(q(1,1:mx,1:my)) <= 0.d0" in source
    assert "all(fg%levelmax(fg%klist(1:fg_klist_length,mythread)) > 0)" in source
    # A positive tolerance here could omit real shallow flow and corrupt the
    # maximum.  The optimization is deliberately restricted to exact dryness.
    assert "maxval(q(1,1:mx,1:my)) <= dry_tolerance" not in source


def test_fgmax_interpolation_is_not_serialized_across_all_patches():
    frompatch = FGMAX.read_text(encoding="utf-8").lower()
    stepgrid = STEPGRID.read_text(encoding="utf-8").lower()

    call_start = stepgrid.index("call fgmax_frompatch")
    surrounding = stepgrid[max(0, call_start - 300):call_start + 300]
    assert "critical (fixedgrids)" not in surrounding
    assert "critical (fgmaxcommit)" in frompatch
    assert frompatch.index("call fgmax_interpolate", frompatch.index("if (.not. interpolation_done)")) \
        < frompatch.index("!$omp critical (fgmaxcommit)", frompatch.index("only this commit"))
