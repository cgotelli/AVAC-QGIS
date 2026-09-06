"""Compiled controller tests: synchronization work is not retry exhaustion."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
TICK = ROOT / "avac-main/clawpack-v5.14.0/geoclaw/src/2d/shallow/tick.f"


def test_controller_obeys_production_fixed_form_columns() -> None:
    for number, line in enumerate(TICK.read_text(encoding="utf-8").splitlines(), 1):
        if line[:1] in ("c", "C", "*", "!"):
            continue
        assert len(line.split("!", 1)[0].rstrip()) <= 72, (number, line)


def _routine(source: str, name: str) -> str:
    match = re.search(rf"(?im)^\s*(?:integer\s+function|subroutine)\s+{name}\b", source)
    assert match, name
    end = re.search(r"(?im)^\s*end\s*$", source[match.end():])
    assert end, name
    return source[match.start():match.end()+end.end()] + "\n"


def test_remaining_work_has_no_100_substep_abort() -> None:
    source = TICK.read_text(encoding="utf-8").lower()
    assert "too many dt reductions" not in source
    assert "more than 100 fine-level substeps" not in source
    assert "ntogo(level) .gt. 100" not in source
    assert "retries .ge. 20" in source
    helper = _routine(source, "checked_amr_substeps")
    guard = helper.index("steps .gt. dble(huge(checked_amr_substeps))")
    assert guard < helper.index("checked_amr_substeps = max(1,ceiling(steps))")
    assert ".not. ieee_is_finite(steps)" in helper[:guard]
    assert "trial_time+partition_dt .le. trial_time" in helper
    assert "huge(ntogo(level))-ntogo(level)" in source
    assert "ntogo(level) = max(1,int(rounded_substeps))" in source
    assert source.index("rounded_substeps .ge. dble(huge(ntogo(level)))") < source.index("int(rounded_substeps)")


@pytest.fixture(scope="module")
def compiled_controller(tmp_path_factory):
    compiler = shutil.which(os.environ.get("FC", "gfortran"))
    if not compiler and os.name == "nt":
        strawberry = Path("C:/Strawberry/c/bin/gfortran.exe")
        compiler = str(strawberry) if strawberry.is_file() else None
    if not compiler:
        pytest.skip("gfortran is required for the compiled controller tests")
    temp = tmp_path_factory.mktemp("amr-controller")
    source = TICK.read_text(encoding="utf-8")
    fixed = temp / "controller.f"
    fixed.write_text("\n".join(_routine(source, name) for name in (
        "checked_amr_substeps", "select_cfl_timestep", "cfl_retry_abort")), encoding="utf-8")
    modules = temp / "modules.f90"
    modules.write_text("""
module amr_module
  implicit none
  integer, parameter :: maxlv=10
  integer :: outunit=6, kratio(maxlv)=2
  real(8) :: cfl=.25d0, cflv1=.5d0, possk(maxlv)=.01d0
end module
module refinement_module
  logical :: varRefTime=.true.
end module
module probe_control
  integer :: mode=0, probes=0
end module
subroutine cfl_preflight(level,nvar,naux,cfl_trial,cfl_invalid)
  use amr_module
  use probe_control
  implicit none
  integer :: level,nvar,naux,cfl_invalid
  real(8) :: cfl_trial
  probes=probes+1
  cfl_invalid=0
  if (mode == 1) then
    cfl_trial=2d0
  else
    cfl_trial=400d0*possk(level)
  endif
end subroutine
""", encoding="utf-8")
    driver = temp / "driver.f90"
    driver.write_text("""
program driver
  use, intrinsic :: ieee_arithmetic
  use amr_module
  use probe_control
  implicit none
  integer :: checked_amr_substeps,n,ntogo(maxlv),level
  real(8) :: interval,limit,clock,tlevel(maxlv)
  logical :: variable
  character(40) :: scenario
  call get_command_argument(1,scenario)
  interval=1d0
  limit=1d0/103d0
  clock=0d0
  select case(trim(scenario))
  case('103')
    n=checked_amr_substeps(103d0,1d0,2,clock)
    if(n /= 103) stop 2
  case('near_landing')
    n=checked_amr_substeps(1d-12,3d-13,2,4.837d0)
    if(n /= 4) stop 2
    if(4.837d0+1d-12/n<=4.837d0) stop 2
  case('small_ratio')
    n=checked_amr_substeps(.01d0,1d0,2,clock)
    if(n /= 1) stop 2
  case('large')
    n=checked_amr_substeps(interval,1d-6,2,clock)
    if(n /= 1000000) stop 2
  case('zero_interval')
    n=checked_amr_substeps(0d0,limit,2,clock)
    stop 3
  case('zero_limit')
    n=checked_amr_substeps(interval,0d0,2,clock)
    stop 3
  case('nan')
    n=checked_amr_substeps(interval,ieee_value(limit,ieee_quiet_nan),2,clock)
    stop 3
  case('infinite')
    n=checked_amr_substeps(ieee_value(interval,ieee_positive_inf),limit,2,clock)
    stop 3
  case('overflow')
    n=checked_amr_substeps(interval,1d-15,2,clock)
    stop 3
  case('stall')
    n=checked_amr_substeps(interval,.5d0,2,1d16)
    stop 3
  case default
    ntogo=100
    tlevel=0d0
    tlevel(1)=1d0
    possk=.01d0
    level=2
    variable=.true.
    if(trim(scenario)=='retry_limit') then
      mode=1
      level=1
      tlevel=0d0
    endif
    if(trim(scenario)=='fixed') variable=.false.
    if(trim(scenario)=='increment_overflow') ntogo(2)=huge(n)
    if(trim(scenario)=='accepted_stall') then
      level=1
      tlevel=1d16
    endif
    call select_cfl_timestep(level,4,2,ntogo,tlevel,variable)
    if(trim(scenario)/='fine_retry') stop 3
    if(ntogo(2)/=1600 .or. probes/=2) stop 2
    if(abs(possk(2)-.000625d0)>1d-16) stop 2
    if(abs(possk(2)*ntogo(2)-1d0)>1d-15) stop 2
    n=ntogo(2)
  end select
  print *, 'PASS',n
end program
""", encoding="utf-8")
    executable = temp / ("controller.exe" if os.name == "nt" else "controller")
    env = os.environ.copy()
    env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
    completed = subprocess.run([compiler, "-O0", "-fcheck=all",
                                str(modules), str(fixed), str(driver), "-o", str(executable)],
                               cwd=temp, env=env, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return executable, env


@pytest.mark.parametrize("scenario", ["103", "large", "fine_retry", "near_landing", "small_ratio"])
def test_valid_large_subcycling_preserves_landing(compiled_controller, scenario):
    executable, env = compiled_controller
    result = subprocess.run([str(executable), scenario], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


@pytest.mark.parametrize("scenario,reason", [
    ("zero_interval", "invalid AMR substep interval or limit"),
    ("zero_limit", "invalid AMR substep interval or limit"),
    ("nan", "invalid AMR substep interval or limit"),
    ("infinite", "invalid AMR substep interval or limit"),
    ("overflow", "AMR substep count exceeds integer range"),
    ("stall", "AMR substeps cannot advance time"),
    ("accepted_stall", "timestep cannot advance time"),
    ("increment_overflow", "AMR substep increment overflows"),
    ("retry_limit", "more than 20 rejected CFL trials"),
    ("fixed", "fixed timestep exceeds cfl_max"),
])
def test_true_invalid_or_nonprogress_states_fail_cleanly(compiled_controller, scenario, reason):
    executable, env = compiled_controller
    result = subprocess.run([str(executable), scenario], env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert reason in result.stdout
    assert "PASS" not in result.stdout
