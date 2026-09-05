"""Contracts and an opt-in integration test for whole-level CFL retry.

The integration test is intentionally opt-in because it executes the native
solver.  Set ``AVAC_CFL_RETRY_SOLVER`` to a built AVAC ``xgeoclaw`` binary to
run it; the ordinary Python test suite still exercises all source contracts.
"""

from __future__ import annotations

from collections import Counter
import importlib
import os
from pathlib import Path
import re
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"
GEOCLAW = (
    ROOT
    / "avac-main"
    / "clawpack-v5.14.0"
    / "geoclaw"
    / "src"
    / "2d"
    / "shallow"
)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VALIDATION))
RUNTIME = importlib.import_module("avac4qgis_validation.runtime")

ARTIFACTS = ("fort.b0002", "fgout0001.b0002", "fgmax0001.txt")
REJECTED_TRIAL = re.compile(
    r"AMRCLAW:\s*rejected CFL trial level\s+(?P<level>\d+)\s+"
    r"CFL\s*=\s*(?P<cfl>[+\-0-9.DEde]+)\s+"
    r"cfl_max\s*=\s*(?P<cfl_max>[+\-0-9.DEde]+)\s+"
    r"dt\s*=\s*(?P<dt>[+\-0-9.DEde]+)\s+"
    r"retry dt\s*=\s*(?P<retry_dt>[+\-0-9.DEde]+)\s+"
    r"t\s*=\s*(?P<time>[+\-0-9.DEde]+)",
    re.IGNORECASE,
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _subroutine(source: str, name: str) -> str:
    """Return one fixed-form Fortran routine without leaking into the next."""
    match = re.search(rf"(?im)^\s*subroutine\s+{re.escape(name)}\b", source)
    if match is None:
        raise AssertionError(f"Missing subroutine {name}")
    following = re.search(r"(?im)^\s*subroutine\s+[a-z0-9_]+\b", source[match.end():])
    stop = len(source) if following is None else match.end() + following.start()
    return source[match.start():stop]


def _code(source: str) -> str:
    """Discard prose comments so side-effect assertions inspect code only."""
    lines: list[str] = []
    for line in source.splitlines():
        if line and line[0] in "cC*":
            continue
        if line.lstrip().startswith("!") and not line.lstrip().startswith("!$omp"):
            continue
        lines.append(line.lower())
    return "\n".join(lines)


def _fortran_float(value: str) -> float:
    return float(value.replace("d", "e").replace("D", "E"))


def test_tick_prepares_and_selects_cfl_before_committing_a_step() -> None:
    tick = _code(_subroutine(_source(GEOCLAW / "tick.f"), "tick"))

    prepare = tick.index("call prepare_advanc")
    select = tick.index("call select_cfl_timestep")
    nextout = tick.index("nextout = nextout + 1")
    nextchk = tick.index("nextchk = nextchk + 1")
    advance = tick.index("call advanc_prepared")
    ntogo = tick.index("ntogo(level)  = ntogo(level) - 1")
    tlevel = tick.index("tlevel(level) = tlevel(level) + possk(level)")
    icheck = tick.index("icheck(level) = icheck(level) + 1")

    assert prepare < select < nextout < advance < ntogo
    assert select < nextchk < advance
    assert advance < tlevel
    assert advance < icheck
    assert tick.count("nextout = nextout + 1") == 1
    assert tick.count("nextchk = nextchk + 1") == 1
    assert "dumpout = .false." in tick[select:advance]
    assert "dumpchk = .false." in tick[select:advance]


def test_retry_rechecks_the_whole_level_and_preserves_parent_landing() -> None:
    selector = _code(
        _subroutine(_source(GEOCLAW / "tick.f"), "select_cfl_timestep")
    )

    target = selector.index("target_cfl = dmin1(cfl,0.9d0*cflv1)")
    preflight = selector.index("call cfl_preflight")
    accepted = selector.index("if (cfl_trial .le. cflv1) return")
    assert target < preflight < accepted
    assert ".not. ieee_is_finite(cfl)" in selector[:preflight]
    assert "if (.not. vtime) then" in selector
    assert "if (retries .ge. 20) then" in selector
    assert "new_dt = old_dt*target_cfl/cfl_trial" in selector
    assert "go to 700" in selector

    assert "remaining = tlevel(level-1) - tlevel(level)" in selector
    assert "steps_required = remaining/new_dt" in selector
    assert "new_ntogo = ceiling(steps_required)" in selector
    assert "new_ntogo = max(new_ntogo,ntogo(level)+1)" in selector
    assert "new_ntogo .gt. 100" in selector
    assert "new_dt = remaining/dble(new_ntogo)" in selector
    assert "new_dt .ge. old_dt" in selector
    # Seventeen printed significant digits let an IEEE double round-trip into
    # a direct-start run, which is how the integration test proves rollback.
    assert selector.count("d25.17") >= 5


def test_preflight_uses_private_scratch_and_a_whole_level_maximum() -> None:
    source = _source(GEOCLAW / "advanc.f")
    prepare = _code(_subroutine(source, "prepare_advanc"))
    whole_level = _code(_subroutine(source, "cfl_preflight"))
    patch = _code(_subroutine(source, "par_cfl_preflight"))

    assert prepare.index("call bound") < prepare.index("call saveqc")
    assert prepare.index("call saveqc") < prepare.index("call topo_update")
    assert "reduction(max:cfl_trial)" in whole_level.replace(" ", "")
    assert "do j = 1, numgrids(level)" in whole_level
    assert "call par_cfl_preflight" in whole_level
    assert "cfl_trial = dmax1(cfl_trial,cfl_patch)" in whole_level
    assert "cfl_patch = huge(1.d0)" in whole_level

    for allocation in ("qwork", "auxwork", "fm", "fp", "gm", "gp"):
        assert allocation in patch
    assert "allocate(qwork(nvar,mitot,mjtot))" in patch
    assert "allocate(auxwork(max(1,naux),mitot,mjtot))" in patch
    assert "qwork(m,ii,jj) = alloc(locnew+idx-1)" in patch
    assert "auxwork(m,ii,jj) = alloc(locaux+idx-1)" in patch
    before_step = patch.index("call b4step2")
    step = patch.index("call step2")
    assert before_step < step
    assert ".true.)" in patch[before_step:step]


def test_preflight_cannot_commit_observations_fluxes_or_patch_time() -> None:
    source = _source(GEOCLAW / "advanc.f")
    patch = _code(_subroutine(source, "par_cfl_preflight"))
    accepted = _code(_subroutine(source, "par_advanc"))

    forbidden = (
        "call saveqc",
        "call qad",
        "call update_gauges",
        "call fgmax_frompatch",
        "call fgout_interp",
        "call stepgrid",
        "call src2",
        "call fluxsv",
        "call fluxad",
        "rnode(timemult,mptr)  =",
        "cflmax =",
        "cfl_level =",
    )
    for operation in forbidden:
        assert operation not in patch

    for operation in (
        "call qad",
        "call update_gauges",
        "call stepgrid",
        "call fluxsv",
        "call fluxad",
        "rnode(timemult,mptr)  =",
    ):
        assert operation in accepted


def _prepare_boundary_impulse(root: Path, initial_dt: float) -> Path:
    work = RUNTIME.prepare_avac_hydraulic_case(
        root,
        xlower=0.0,
        xupper=4.0,
        ylower=0.0,
        yupper=0.2,
        dx=0.05,
        t_final=0.01,
        nout=2,
        bed=lambda x, y: np.zeros_like(x),
        depth=lambda x, y: np.full_like(x, 0.1),
        boundary_west="user",
        boundary_east="wall",
        boundary_south="wall",
        boundary_north="wall",
        hydraulic_boundaries={1: (3, 0.1, 5.0)},
        limiter="minmod",
        max1d=60,
    )
    for label, value in (
        ("amr_levels_max", "2"),
        ("refinement_ratios_x", "2"),
        ("refinement_ratios_y", "2"),
        ("refinement_ratios_t", "2"),
        ("flag_richardson", "F"),
        ("flag2refine", "F"),
    ):
        RUNTIME._replace_data_value(work / "amr.data", label, value)
    (work / "regions.data").write_text(
        "########################################################\n"
        "### Validation-controlled forced AMR regions          ###\n"
        "########################################################\n\n"
        "1                    =: num_regions\n"
        "2 2 0.0 0.01 0.0 4.0 0.0 0.2\n",
        encoding="utf-8",
    )
    RUNTIME._replace_data_value(
        work / "claw.data", "dt_initial", format(initial_dt, ".17g")
    )
    return work


def _audit_completed_case(work: Path) -> None:
    stdout = (work / "solver.log").read_text(encoding="utf-8")
    fort_amr = (work / "fort.amr").read_text(encoding="utf-8")
    assert "is larger than input cfl_max" not in stdout + fort_amr
    maximum = re.search(
        r"maximum Courant number seen\s*=\s*([0-9.]+)", fort_amr
    )
    assert maximum is not None
    assert float(maximum.group(1)) <= 0.5
    assert float((work / "fort.t0002").read_text().split()[0]) == pytest.approx(0.01)
    levels = Counter(
        int(value)
        for value in re.findall(
            r"^\s*(\d+)\s+AMR_level\s*$",
            (work / "fort.q0002").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    assert levels == {1: 2, 2: 4}
    # The generated fixed grid writes its configured two frames (initial and
    # final); the AMR solution itself additionally has fort frame zero.
    assert len(list(work.glob("fgout0001.t*"))) == 2
    for artifact in ARTIFACTS:
        assert (work / artifact).is_file()


def test_boundary_impulse_retry_is_transactional_and_thread_deterministic(
    tmp_path: Path,
) -> None:
    configured = os.environ.get("AVAC_CFL_RETRY_SOLVER")
    if not configured:
        pytest.skip("set AVAC_CFL_RETRY_SOLVER to run the native integration test")
    solver = Path(configured).expanduser().resolve()
    if not solver.is_file():
        pytest.fail(f"AVAC_CFL_RETRY_SOLVER does not exist: {solver}")

    retry_one = _prepare_boundary_impulse(tmp_path / "retry-one", 0.0025)
    retry_four = _prepare_boundary_impulse(tmp_path / "retry-four", 0.0025)
    RUNTIME.run_solver("avac", retry_one, cores=1, executable_override=solver)
    RUNTIME.run_solver("avac", retry_four, cores=4, executable_override=solver)

    one_stdout = (retry_one / "solver.log").read_text(encoding="utf-8")
    four_stdout = (retry_four / "solver.log").read_text(encoding="utf-8")
    one_trials = list(REJECTED_TRIAL.finditer(one_stdout))
    four_trials = list(REJECTED_TRIAL.finditer(four_stdout))
    assert len(one_trials) == len(four_trials) == 1
    trial = one_trials[0].groupdict()
    assert int(trial["level"]) == 1
    assert _fortran_float(trial["cfl"]) > _fortran_float(trial["cfl_max"])
    retry_dt = _fortran_float(trial["retry_dt"])
    assert 0.0 < retry_dt < _fortran_float(trial["dt"])
    assert one_trials[0].group(0) == four_trials[0].group(0)
    assert (retry_one / "fort.amr").read_text().count(
        "AMRCLAW: rejected CFL trial"
    ) == 1
    assert (retry_four / "fort.amr").read_text().count(
        "AMRCLAW: rejected CFL trial"
    ) == 1

    direct = _prepare_boundary_impulse(tmp_path / "direct", retry_dt)
    RUNTIME.run_solver("avac", direct, cores=1, executable_override=solver)
    assert "AMRCLAW: rejected CFL trial" not in (
        direct / "solver.log"
    ).read_text(encoding="utf-8")

    for work in (retry_one, retry_four, direct):
        _audit_completed_case(work)
    for artifact in ARTIFACTS:
        rejected_bytes = (retry_one / artifact).read_bytes()
        assert (retry_four / artifact).read_bytes() == rejected_bytes
        # The direct run starts at the exact full-precision retry dt.  Exact
        # identity proves that the discarded oversized probe did not alter
        # the final state, fixed-grid frame, or peak-field artifact.
        assert (direct / artifact).read_bytes() == rejected_bytes
