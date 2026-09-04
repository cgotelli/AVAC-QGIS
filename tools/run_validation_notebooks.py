#!/usr/bin/env python3
"""Execute the published validation notebooks serially and resumably.

The source notebooks are never modified.  The four manuscript-figure
notebooks normally rerun their producer simulations; this runner has already
executed those producers in the documented order, so it disables the reruns
in memory and still executes every figure cell.  Executed notebooks, the
ISeeSnow products, and the run manifest are kept outside the checkout.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
VALIDATION = REPOSITORY / "validation"
DEFAULT_OUTPUT_ROOT = REPOSITORY.parent / f"{REPOSITORY.name}-validation-runs"
FIGURE_RERUN_MARKER = "ENSURE_CURRENT_RESULTS = True"
PUBLICATION_AVAC_RUN_NAME = "publication_amr"
SWASHES_ROOT = VALIDATION / "vendor" / "SWASHES-1.05.01"
SWASHES_EXECUTABLE = SWASHES_ROOT / "bin" / (
    "swashes.exe" if os.name == "nt" else "swashes"
)
SWASHES_BUILD_STAMP = VALIDATION / ".solver-build-stamps" / "swashes.json"

# This is the authoritative order published in validation/README.md.  Producer
# notebooks immediately precede the figure notebooks that consume their data.
NOTEBOOKS = (
    "AVAC/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb",
    "AVAC/Kerswell_Coulomb/Kerswell_Coulomb.ipynb",
    "AVAC/Coulomb_sloping_bed/Coulomb_sloping_bed.ipynb",
    "AVAC/Curvature_normal_stress/Curvature_normal_stress.ipynb",
    "AVAC/Paper_figures/AVAC_verification_figures.ipynb",
    "WAVE/01_transcritical_shock/transcritical_shock.ipynb",
    "WAVE/02_macdonald_smooth_shock/macdonald_smooth_shock.ipynb",
    "WAVE/03_ritter_dry_dam_break/ritter_dry_dam_break.ipynb",
    "WAVE/04_thacker_planar_paraboloid/thacker_planar_paraboloid.ipynb",
    "WAVE/05_macdonald_pseudo2d_supercritical/pseudo2d_supercritical.ipynb",
    "WAVE/06_macdonald_pseudo2d_subcritical/pseudo2d_subcritical.ipynb",
    "WAVE/07_baines_flow_over_bump/Baines_flow_over_bump.ipynb",
    "WAVE/08_amr_parallel/AMR_OpenMP.ipynb",
    "WAVE/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb",
    "WAVE/Paper_figures/WAVE_verification_figures.ipynb",
    "COUPLING/Paper_figures/Coupling_verification.ipynb",
    "COUPLING/Paper_figures/Coupling_verification_figures.ipynb",
    "ISeeSnow/IdealizedTopo/IdealizedTopo.ipynb",
    "ISeeSnow/RealTopo/RealTopo.ipynb",
    "ISeeSnow/CoulombOnly/CoulombOnly.ipynb",
    "ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb",
)

FIGURE_NOTEBOOKS = frozenset(
    {
        "AVAC/Paper_figures/AVAC_verification_figures.ipynb",
        "WAVE/Paper_figures/WAVE_verification_figures.ipynb",
        "COUPLING/Paper_figures/Coupling_verification_figures.ipynb",
        "ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb",
    }
)

FIGURE_PREREQUISITES = {
    "AVAC/Paper_figures/AVAC_verification_figures.ipynb": NOTEBOOKS[0:4],
    "WAVE/Paper_figures/WAVE_verification_figures.ipynb": NOTEBOOKS[5:14],
    "COUPLING/Paper_figures/Coupling_verification_figures.ipynb": NOTEBOOKS[15:16],
    "ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb": NOTEBOOKS[17:20],
}

# These are the only tracked-worktree paths that published notebook execution
# is allowed to replace.  They are outputs, not execution inputs.  Most are
# currently untracked, but keeping the exact contract here prevents a future
# decision to publish them from making the live-input guard reject a valid run.
RUNTIME_GENERATED_REPOSITORY_FILES = frozenset(
    {
        "validation/AVAC/2008_WRR_sloping_bed/publication_amr/controls.json",
        "validation/AVAC/Coulomb_sloping_bed/publication_amr/controls.json",
        "validation/AVAC/Kerswell_Coulomb/publication_amr/controls.json",
        "validation/WAVE/2008_WRR_sloping_bed/controls.json",
        "docs/article/figures/avac_coulomb_verification.pdf",
        "docs/article/figures/avac_coulomb_verification.png",
        "docs/article/figures/avac_wrr_water_limit.pdf",
        "docs/article/figures/avac_wrr_water_limit.png",
        "docs/article/figures/avac_verification_run_summaries.json",
        "docs/article/figures/wave_analytical_verification.pdf",
        "docs/article/figures/wave_analytical_verification.png",
        "docs/article/figures/wave_analytical_verification.json",
        "docs/article/figures/wave_additional_benchmarks.pdf",
        "docs/article/figures/wave_additional_benchmarks.png",
        "docs/article/figures/wave_numerical_diagnostics.pdf",
        "docs/article/figures/wave_numerical_diagnostics.png",
        "docs/article/figures/wave_appendix_figures.json",
        "docs/article/figures/coupling_verification.pdf",
        "docs/article/figures/coupling_verification.png",
        "docs/article/figures/coupling_verification.json",
        "docs/article/figures/iseesnow_case_setup.pdf",
        "docs/article/figures/iseesnow_case_setup.png",
        "docs/article/figures/iseesnow_case_setup.json",
        "docs/article/figures/iseesnow_intercomparison.pdf",
        "docs/article/figures/iseesnow_intercomparison.png",
        "docs/article/figures/iseesnow_intercomparison.json",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def require_external(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if is_inside(resolved, REPOSITORY):
        raise ValueError(
            f"{label} must be outside the repository so generated validation "
            f"products cannot modify the checkout: {resolved}"
        )
    return resolved


def git_output(*arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {message}")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="replace").strip()


def git_input_pathspec() -> tuple[str, ...]:
    return (
        ".",
        *(
            f":(exclude){relative}"
            for relative in sorted(RUNTIME_GENERATED_REPOSITORY_FILES)
        ),
    )


def untracked_input_hashes() -> dict[str, str]:
    listed = git_output("ls-files", "--others", "--exclude-standard")
    assert isinstance(listed, str)
    result: dict[str, str] = {}
    for relative in listed.splitlines():
        normalized = Path(relative).as_posix()
        if normalized in RUNTIME_GENERATED_REPOSITORY_FILES:
            continue
        path = REPOSITORY / Path(relative)
        if path.is_file():
            result[normalized] = sha256_file(path)
    return result


def notebook_sources() -> dict[str, Path]:
    sources = {relative: VALIDATION / Path(relative) for relative in NOTEBOOKS}
    missing = [relative for relative, path in sources.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Published validation notebooks are missing:\n  " + "\n  ".join(missing)
        )
    discovered = {
        path.relative_to(VALIDATION).as_posix()
        for path in VALIDATION.rglob("*.ipynb")
    }
    unexpected = sorted(discovered - set(NOTEBOOKS))
    if unexpected:
        raise RuntimeError(
            "Validation contains notebooks absent from the authoritative run order:\n  "
            + "\n  ".join(unexpected)
        )
    return sources


def count_figure_markers(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        "".join(cell.get("source", [])).count(FIGURE_RERUN_MARKER)
        if isinstance(cell.get("source"), list)
        else str(cell.get("source", "")).count(FIGURE_RERUN_MARKER)
        for cell in payload.get("cells", [])
        if cell.get("cell_type") == "code"
    )


def validate_notebook_contract(sources: dict[str, Path]) -> None:
    unexpected: list[str] = []
    for relative, source in sources.items():
        count = count_figure_markers(source)
        expected = 1 if relative in FIGURE_NOTEBOOKS else 0
        if count != expected:
            unexpected.append(f"{relative}: expected {expected}, found {count}")
    if unexpected:
        raise RuntimeError(
            "Unexpected ENSURE_CURRENT_RESULTS markers; refusing an ambiguous run:\n  "
            + "\n  ".join(unexpected)
        )
    if set(FIGURE_PREREQUISITES) != set(FIGURE_NOTEBOOKS):
        raise RuntimeError("Every figure notebook must have one explicit dependency set")
    positions = {relative: index for index, relative in enumerate(NOTEBOOKS)}
    invalid_dependencies = [
        f"{figure} <- {prerequisite}"
        for figure, prerequisites in FIGURE_PREREQUISITES.items()
        for prerequisite in prerequisites
        if prerequisite not in sources or positions[prerequisite] >= positions[figure]
    ]
    if invalid_dependencies:
        raise RuntimeError(
            "Figure prerequisites must be published earlier in the run order:\n  "
            + "\n  ".join(invalid_dependencies)
        )


def base_identity(
    sources: dict[str, Path],
    *,
    kernel_name: str,
    iseesnow_results_root: Path | None,
) -> dict[str, Any]:
    input_pathspec = git_input_pathspec()
    diff = git_output(
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
        *input_pathspec,
        binary=True,
    )
    assert isinstance(diff, bytes)
    changed = git_output("diff", "--name-only", "HEAD", "--", *input_pathspec)
    assert isinstance(changed, str)
    return {
        "git_head": git_output("rev-parse", "HEAD"),
        "git_diff_sha256": sha256_bytes(diff),
        "git_diff_bytes": len(diff),
        "git_diff_files": [line for line in changed.splitlines() if line],
        "untracked_input_sha256": untracked_input_hashes(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "notebook_sha256": {
            relative: sha256_file(source) for relative, source in sources.items()
        },
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "kernel_name": kernel_name,
        "figure_prerequisite_reruns": False,
        "environment_policy": {
            "matplotlib_backend": "Agg",
            "makeflags_cleared": True,
            "venv_scripts_prepend": True,
            "avac_validation_run_name": PUBLICATION_AVAC_RUN_NAME,
        },
        "iseesnow_results": (
            {"mode": "explicit", "path": str(iseesnow_results_root)}
            if iseesnow_results_root is not None
            else {"mode": "inside_external_run"}
        ),
    }


def configure_process_environment(venv: Path) -> Path:
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    expected_python = scripts / ("python.exe" if os.name == "nt" else "python")
    if not expected_python.is_file():
        raise FileNotFoundError(f"Validation virtual environment is missing: {expected_python}")
    if Path(sys.executable).resolve() != expected_python.resolve():
        raise RuntimeError(
            "Run this tool with the repository validation interpreter:\n"
            f"  {expected_python} {Path(__file__).resolve()}"
        )
    current_path = os.environ.get("PATH", "")
    entries = [item for item in current_path.split(os.pathsep) if item]
    entries = [item for item in entries if Path(item).resolve() != scripts.resolve()]
    os.environ["PATH"] = os.pathsep.join([str(scripts), *entries])
    os.environ["MPLBACKEND"] = "Agg"
    for variable in ("MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS"):
        os.environ.pop(variable, None)
    os.environ["AVAC_VALIDATION_RUN_NAME"] = PUBLICATION_AVAC_RUN_NAME
    jupyter_data = venv / "share" / "jupyter"
    existing_jupyter_path = os.environ.get("JUPYTER_PATH", "")
    os.environ["JUPYTER_PATH"] = os.pathsep.join(
        [str(jupyter_data), *filter(None, existing_jupyter_path.split(os.pathsep))]
    )
    return expected_python


def validate_notebook_runtime(kernel_name: str, expected_python: Path) -> None:
    try:
        import ipykernel  # noqa: F401
        import nbformat  # noqa: F401
        from jupyter_client.kernelspec import KernelSpecManager
        from nbconvert.preprocessors import ExecutePreprocessor  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The validation environment needs nbformat, nbconvert, jupyter-client, "
            "and ipykernel before the matrix can run"
        ) from exc
    try:
        specification = KernelSpecManager().get_kernel_spec(kernel_name)
    except Exception as exc:
        raise RuntimeError(f"Jupyter kernel is unavailable: {kernel_name}") from exc
    command = Path(os.path.expandvars(specification.argv[0])).expanduser()
    if not command.is_absolute():
        located = shutil.which(str(command))
        if located is None:
            raise RuntimeError(
                f"Kernel {kernel_name!r} launches unavailable command {command!s}"
            )
        command = Path(located)
    if command.resolve() != expected_python.resolve():
        raise RuntimeError(
            f"Kernel {kernel_name!r} uses {command}, not validation Python "
            f"{expected_python}"
        )


def compiler_version(compiler: str) -> str:
    result = subprocess.run(
        [compiler, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    first_line = result.stdout.splitlines()[0].strip() if result.stdout else ""
    if result.returncode != 0 or not first_line:
        raise RuntimeError(f"Could not identify native compiler: {compiler}")
    return first_line


def swashes_source_inputs() -> tuple[Path, ...]:
    required = (SWASHES_ROOT / "Makefile", SWASHES_ROOT / "make_config")
    missing = [path for path in required if not path.is_file()]
    sources = sorted((SWASHES_ROOT / "Sources").rglob("*.cpp"))
    headers = sorted(
        path
        for path in (SWASHES_ROOT / "Headers").rglob("*")
        if path.is_file()
    )
    if missing or not sources or not headers:
        details = [*(str(path) for path in missing)]
        if not sources:
            details.append(str(SWASHES_ROOT / "Sources" / "*.cpp"))
        if not headers:
            details.append(str(SWASHES_ROOT / "Headers"))
        raise FileNotFoundError(
            "Pinned SWASHES build inputs are missing:\n  " + "\n  ".join(details)
        )
    return (*required, *sources, *headers)


def swashes_source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in swashes_source_inputs():
        relative = path.relative_to(SWASHES_ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def swashes_compiler() -> str:
    configured = os.environ.get("CXX")
    candidates = (
        (configured,) if configured else ()
    ) + ("g++-15", "g++-14", "g++-13", "g++-12", "g++", "clang++", "c++")
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = os.path.expandvars(candidate.strip().strip('"'))
        located = shutil.which(candidate)
        if located is None:
            explicit = Path(candidate).expanduser()
            located = str(explicit) if explicit.is_file() else None
        if located is not None:
            return str(Path(located).resolve())
        if configured:
            break
    requested = f" from CXX={configured!r}" if configured else ""
    raise RuntimeError(f"A C++ compiler is required to build SWASHES{requested}")


def swashes_compile_flags() -> tuple[str, ...]:
    configuration = SWASHES_ROOT / "make_config"
    for line in configuration.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("CPPFLAGS"):
            continue
        for operator in (":=", "?=", "="):
            name, separator, value = stripped.partition(operator)
            if separator and name.strip() == "CPPFLAGS":
                return tuple(shlex.split(value, posix=True))
    raise RuntimeError(f"SWASHES compile flags are missing from {configuration}")


def swashes_build_plan() -> dict[str, Any]:
    compiler = swashes_compiler()
    return {
        "source_fingerprint": swashes_source_fingerprint(),
        "compiler": compiler,
        "compiler_version": compiler_version(compiler),
        "platform": sys.platform,
    }


def stamped_swashes_identity(plan: dict[str, Any]) -> dict[str, Any] | None:
    stamp = read_manifest(SWASHES_BUILD_STAMP)
    if stamp is None or stamp.get("format") != 1 or stamp.get("kind") != "swashes":
        return None
    stable_fields = (
        "source_fingerprint",
        "compiler",
        "compiler_version",
        "platform",
    )
    if any(stamp.get(field) != plan[field] for field in stable_fields):
        return None
    if not SWASHES_EXECUTABLE.is_file():
        return None
    executable_sha = sha256_file(SWASHES_EXECUTABLE)
    if stamp.get("executable_sha256") != executable_sha:
        return None
    return {
        **plan,
        "executable": str(SWASHES_EXECUTABLE.resolve()),
        "executable_sha256": executable_sha,
    }


def current_swashes_identity() -> dict[str, Any]:
    plan = swashes_build_plan()
    current = stamped_swashes_identity(plan)
    if current is None:
        raise RuntimeError("SWASHES executable does not match its current source/build stamp")
    return current


def preflight_swashes() -> tuple[dict[str, Any], bool]:
    plan = swashes_build_plan()
    return plan, stamped_swashes_identity(plan) is not None


def write_swashes_stamp(record: dict[str, Any]) -> None:
    SWASHES_BUILD_STAMP.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": 1, "kind": "swashes", **record}
    temporary = SWASHES_BUILD_STAMP.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, SWASHES_BUILD_STAMP)


def ensure_current_swashes() -> dict[str, Any]:
    plan = swashes_build_plan()
    current = stamped_swashes_identity(plan)
    if current is not None:
        return current

    sources = [
        path for path in swashes_source_inputs() if path.suffix.lower() == ".cpp"
    ]
    SWASHES_EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    executable_suffix = ".tmp.exe" if os.name == "nt" else ".tmp"
    temporary = SWASHES_EXECUTABLE.parent / (
        f"swashes.runner-{os.getpid()}{executable_suffix}"
    )
    temporary.unlink(missing_ok=True)
    command = [
        plan["compiler"],
        *swashes_compile_flags(),
        f"-I{SWASHES_ROOT / 'Headers'}",
        *(str(source) for source in sources),
        "-o",
        str(temporary),
    ]
    try:
        subprocess.run(command, cwd=SWASHES_ROOT, check=True)
        if not temporary.is_file():
            raise RuntimeError(
                f"SWASHES build completed without creating {temporary}"
            )
        after = swashes_build_plan()
        stable_fields = (
            "source_fingerprint",
            "compiler",
            "compiler_version",
            "platform",
        )
        if any(after[field] != plan[field] for field in stable_fields):
            raise RuntimeError("SWASHES build inputs changed while it was compiling")
        os.replace(temporary, SWASHES_EXECUTABLE)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Could not build the pinned SWASHES generator: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    record = {
        **plan,
        "executable": str(SWASHES_EXECUTABLE.resolve()),
        "executable_sha256": sha256_file(SWASHES_EXECUTABLE),
    }
    write_swashes_stamp(record)
    return record


def current_solver_identity() -> dict[str, dict[str, Any]]:
    if str(VALIDATION) not in sys.path:
        sys.path.insert(0, str(VALIDATION))
    from avac4qgis_validation.runtime import (
        BUILD_STAMP_ROOT,
        SOURCE_ROOTS,
        _has_current_build,
        solver_fingerprint,
    )

    records: dict[str, dict[str, Any]] = {}
    executable_name = "xgeoclaw.exe" if os.name == "nt" else "xgeoclaw"
    for kind in ("avac", "wave"):
        executable = SOURCE_ROOTS[kind] / executable_name
        if not executable.is_file():
            raise FileNotFoundError(f"{kind.upper()} executable is missing: {executable}")
        if not _has_current_build(kind):
            raise RuntimeError(
                f"{kind.upper()} executable does not match its current source/build stamp"
            )
        stamp = json.loads(
            (BUILD_STAMP_ROOT / f"{kind}.json").read_text(encoding="utf-8")
        )
        compiler = str(stamp["compiler"])
        records[kind] = {
            "source_fingerprint": solver_fingerprint(kind),
            "executable": str(executable.resolve()),
            "executable_sha256": sha256_file(executable),
            "compiler": compiler,
            "compiler_version": compiler_version(compiler),
            "platform": str(stamp["platform"]),
        }
    return records


def prebuild_solvers() -> dict[str, dict[str, Any]]:
    if str(VALIDATION) not in sys.path:
        sys.path.insert(0, str(VALIDATION))
    from avac4qgis_validation.runtime import build_solver

    # The two solvers use common Clawpack object/module directories.  Their
    # builds must remain sequential even though notebook solver runs use
    # OpenMP internally.
    for kind in ("avac", "wave"):
        print(f"Prebuilding {kind.upper()} serially...", flush=True)
        build_solver(kind, cores=1)
    records = current_solver_identity()
    print("Ensuring SWASHES analytical generator serially...", flush=True)
    records["swashes"] = ensure_current_swashes()
    return records


def solver_identity_matches(saved: object) -> bool:
    if not isinstance(saved, dict):
        return False
    try:
        current = current_solver_identity()
        current["swashes"] = current_swashes_identity()
        stable_fields = (
            "source_fingerprint",
            "compiler",
            "compiler_version",
            "platform",
        )
        return all(
            all(current[kind].get(field) == saved[kind].get(field) for field in stable_fields)
            for kind in ("avac", "wave", "swashes")
        )
    except (
        AttributeError,
        FileNotFoundError,
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def assert_input_integrity(
    expected_base: dict[str, Any],
    expected_fingerprint: str,
    sources: dict[str, Path],
    *,
    kernel_name: str,
    explicit_iseesnow: Path | None,
    solvers: object,
) -> None:
    current = base_identity(
        sources,
        kernel_name=kernel_name,
        iseesnow_results_root=explicit_iseesnow,
    )
    current_fingerprint = canonical_fingerprint(current)
    if current_fingerprint != expected_fingerprint:
        changed_fields = sorted(
            key
            for key in set(expected_base) | set(current)
            if expected_base.get(key) != current.get(key)
        )
        notebook_changes = sorted(
            relative
            for relative in set(expected_base.get("notebook_sha256", {}))
            | set(current.get("notebook_sha256", {}))
            if expected_base.get("notebook_sha256", {}).get(relative)
            != current.get("notebook_sha256", {}).get(relative)
        )
        tracked_changes = sorted(
            set(expected_base.get("git_diff_files", ()))
            | set(current.get("git_diff_files", ()))
        )
        untracked_changes = sorted(
            relative
            for relative in set(expected_base.get("untracked_input_sha256", {}))
            | set(current.get("untracked_input_sha256", {}))
            if expected_base.get("untracked_input_sha256", {}).get(relative)
            != current.get("untracked_input_sha256", {}).get(relative)
        )
        details = f"changed identity fields: {', '.join(changed_fields)}"
        if notebook_changes:
            details += "; notebooks: " + ", ".join(notebook_changes)
        if tracked_changes:
            details += "; tracked worktree inputs: " + ", ".join(tracked_changes)
        if untracked_changes:
            details += "; untracked inputs: " + ", ".join(untracked_changes)
        raise RuntimeError(
            "Validation execution inputs changed after this matrix was identified; "
            f"{details}. Restore the original inputs or start a new matrix."
        )
    if not solver_identity_matches(solvers):
        raise RuntimeError(
            "AVAC, WAVE, or SWASHES build identity changed during the matrix; "
            "restore/rebuild the recorded inputs before resuming"
        )


def pin_solver_compiler(solvers: dict[str, dict[str, Any]]) -> None:
    compilers = {str(solvers[kind]["compiler"]) for kind in ("avac", "wave")}
    if len(compilers) != 1:
        raise RuntimeError(
            "AVAC and WAVE were built with different compilers; refusing a mixed matrix"
        )
    os.environ["FC"] = compilers.pop()


def read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def find_resumable_manifest(
    output_root: Path, fingerprint: str
) -> tuple[Path, dict[str, Any]] | None:
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for path in output_root.glob("matrix-*/manifest.json"):
        payload = read_manifest(path)
        if payload is None or payload.get("base_fingerprint") != fingerprint:
            continue
        candidates.append((path.stat().st_mtime, path, payload))
    for _modified, path, payload in sorted(
        candidates, key=lambda item: item[0], reverse=True
    ):
        if solver_identity_matches(payload.get("identity", {}).get("solvers")):
            return path, payload
    return None


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_utc"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def output_name(index: int, relative: str) -> str:
    stem = relative.removesuffix(".ipynb").replace("/", "__")
    return f"{index:02d}_{stem}.executed.ipynb"


def new_manifest(
    *,
    run_root: Path,
    base: dict[str, Any],
    base_fingerprint: str,
    solvers: dict[str, dict[str, Any]],
    run_fingerprint: str,
    iseesnow_results_root: Path,
) -> dict[str, Any]:
    executed_root = run_root / "executed-notebooks"
    stable_solver_fields = (
        "source_fingerprint",
        "compiler",
        "compiler_version",
        "platform",
    )
    stable_solvers = {
        kind: {field: record[field] for field in stable_solver_fields}
        for kind, record in solvers.items()
    }
    combined_solver_fingerprint = canonical_fingerprint(stable_solvers)
    entries: list[dict[str, Any]] = []
    for index, relative in enumerate(NOTEBOOKS, start=1):
        source_sha = base["notebook_sha256"][relative]
        entries.append(
            {
                "index": index,
                "source": relative,
                "source_sha256": source_sha,
                "solver_fingerprint": combined_solver_fingerprint,
                "execution_fingerprint": canonical_fingerprint(
                    {"notebook_sha256": source_sha, "solvers": stable_solvers}
                ),
                "prerequisites": list(FIGURE_PREREQUISITES.get(relative, ())),
                "figure_prerequisite_reruns_disabled": relative in FIGURE_NOTEBOOKS,
                "executed_notebook": str(
                    (executed_root / output_name(index, relative)).relative_to(run_root)
                ),
                "status": "pending",
                "attempts": 0,
            }
        )
    identity = dict(base)
    identity["solvers"] = solvers
    identity["iseesnow_results_root"] = str(iseesnow_results_root)
    return {
        "format": 1,
        "suite": "AVAC4QGIS published validation notebooks",
        "status": "pending",
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
        "repository": str(REPOSITORY),
        "run_root": str(run_root),
        "base_fingerprint": base_fingerprint,
        "run_fingerprint": run_fingerprint,
        "identity": identity,
        "solver_provenance_note": (
            "identity.solvers records the serial AVAC/WAVE prebuild and the "
            "source-matched SWASHES analytical generator. Each notebook records "
            "executable SHA-256 values before and after execution because ISeeSnow "
            "intentionally force-relinks AVAC from the same source."
        ),
        "notebooks": entries,
    }


def disable_figure_rerun(notebook: Any, relative: str) -> None:
    matches = 0
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        count = cell.source.count(FIGURE_RERUN_MARKER)
        if count:
            cell.source = cell.source.replace(
                FIGURE_RERUN_MARKER, "ENSURE_CURRENT_RESULTS = False"
            )
            matches += count
    if matches != 1:
        raise RuntimeError(
            f"Expected exactly one figure-rerun marker in {relative}; found {matches}"
        )


def passed_output_is_current(record: dict[str, Any], run_root: Path) -> bool:
    if record.get("status") != "passed":
        return False
    output = run_root / record["executed_notebook"]
    expected = record.get("executed_sha256")
    return output.is_file() and isinstance(expected, str) and sha256_file(output) == expected


def records_by_source(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record["source"]): record for record in manifest["notebooks"]}


def invalidate_dependents(manifest: dict[str, Any], producer: str) -> list[str]:
    invalidated: list[str] = []
    by_source = records_by_source(manifest)
    for figure, prerequisites in FIGURE_PREREQUISITES.items():
        if producer not in prerequisites:
            continue
        record = by_source[figure]
        if record.get("status") != "passed":
            continue
        record["status"] = "pending"
        record.pop("executed_sha256", None)
        record.pop("blocked_by", None)
        record.setdefault("invalidations", []).append(
            {"utc": utc_now(), "producer_rerun": producer}
        )
        invalidated.append(figure)
    return invalidated


def unavailable_prerequisites(
    record: dict[str, Any], manifest: dict[str, Any], run_root: Path
) -> list[str]:
    prerequisites = FIGURE_PREREQUISITES.get(str(record["source"]), ())
    by_source = records_by_source(manifest)
    return [
        prerequisite
        for prerequisite in prerequisites
        if not passed_output_is_current(by_source[prerequisite], run_root)
    ]


def executable_hashes(manifest: dict[str, Any]) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for kind, solver in manifest["identity"]["solvers"].items():
        executable = Path(solver["executable"])
        hashes[kind] = sha256_file(executable) if executable.is_file() else None
    return hashes


def execute_notebook(
    source: Path,
    relative: str,
    output: Path,
    *,
    kernel_name: str,
) -> None:
    import nbformat
    from nbconvert.preprocessors import ExecutePreprocessor

    notebook = nbformat.read(source, as_version=4)
    if relative in FIGURE_NOTEBOOKS:
        disable_figure_rerun(notebook, relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    processor = ExecutePreprocessor(
        timeout=None, kernel_name=kernel_name, allow_errors=False
    )
    try:
        processor.preprocess(
            notebook, resources={"metadata": {"path": str(source.parent)}}
        )
    finally:
        # A partial notebook contains the traceback from a failed cell and is
        # considerably more useful than console output alone.
        nbformat.write(notebook, output)


def execute_matrix(
    manifest_path: Path,
    manifest: dict[str, Any],
    sources: dict[str, Path],
    *,
    expected_base: dict[str, Any],
    base_fingerprint: str,
    explicit_iseesnow: Path | None,
    kernel_name: str,
    keep_going: bool,
) -> int:
    run_root = Path(manifest["run_root"])

    def check_integrity() -> None:
        try:
            assert_input_integrity(
                expected_base,
                base_fingerprint,
                sources,
                kernel_name=kernel_name,
                explicit_iseesnow=explicit_iseesnow,
                solvers=manifest["identity"]["solvers"],
            )
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["input_integrity_error"] = {
                "utc": utc_now(),
                "type": type(exc).__name__,
                "message": str(exc),
            }
            write_manifest(manifest_path, manifest)
            raise
        else:
            manifest.pop("input_integrity_error", None)

    manifest["status"] = "running"
    write_manifest(manifest_path, manifest)
    for record in manifest["notebooks"]:
        check_integrity()
        relative = record["source"]
        output = run_root / record["executed_notebook"]
        current_output = passed_output_is_current(record, run_root)
        if not current_output:
            invalidated = invalidate_dependents(manifest, relative)
            if invalidated:
                write_manifest(manifest_path, manifest)
                for dependent in invalidated:
                    print(
                        f"Invalidated dependent result {dependent}: "
                        f"{relative} will rerun",
                        flush=True,
                    )

        blockers = unavailable_prerequisites(record, manifest, run_root)
        if blockers:
            record["status"] = "blocked"
            record["blocked_by"] = blockers
            record.pop("executed_sha256", None)
            record["blocked_utc"] = utc_now()
            write_manifest(manifest_path, manifest)
            print(
                f"[{record['index']:02d}/{len(NOTEBOOKS)}] BLOCK {relative}: "
                + ", ".join(blockers),
                flush=True,
            )
            if not keep_going:
                manifest["status"] = "failed"
                write_manifest(manifest_path, manifest)
                return 1
            continue

        if current_output:
            print(
                f"[{record['index']:02d}/{len(NOTEBOOKS)}] PASS (resumed) {relative}",
                flush=True,
            )
            continue

        record["status"] = "running"
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["started_utc"] = utc_now()
        record.pop("completed_utc", None)
        record.pop("elapsed_seconds", None)
        record.pop("error", None)
        record.pop("executed_sha256", None)
        record.pop("blocked_by", None)
        record.pop("blocked_utc", None)
        record["solver_executable_sha256_before"] = executable_hashes(manifest)
        write_manifest(manifest_path, manifest)
        print(
            f"[{record['index']:02d}/{len(NOTEBOOKS)}] RUN  {relative}", flush=True
        )
        started = time.perf_counter()
        try:
            execute_notebook(
                sources[relative], relative, output, kernel_name=kernel_name
            )
        except KeyboardInterrupt as exc:
            record["status"] = "interrupted"
            manifest["status"] = "interrupted"
            if output.is_file():
                record["executed_sha256"] = sha256_file(output)
            record["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc()[-12000:],
            }
            print(
                f"[{record['index']:02d}/{len(NOTEBOOKS)}] INTERRUPT {relative}",
                flush=True,
            )
            raise
        except Exception as exc:
            record["status"] = "failed"
            if output.is_file():
                record["executed_sha256"] = sha256_file(output)
            record["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc()[-12000:],
            }
            print(
                f"[{record['index']:02d}/{len(NOTEBOOKS)}] FAIL {relative}: {exc}",
                flush=True,
            )
        else:
            record["status"] = "passed"
            record["executed_sha256"] = sha256_file(output)
            print(
                f"[{record['index']:02d}/{len(NOTEBOOKS)}] PASS {relative}",
                flush=True,
            )
        finally:
            record["completed_utc"] = utc_now()
            record["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            record["solver_executable_sha256_after"] = executable_hashes(manifest)
            write_manifest(manifest_path, manifest)
        if record["status"] == "failed" and not keep_going:
            manifest["status"] = "failed"
            write_manifest(manifest_path, manifest)
            return 1

    check_integrity()
    failures = sum(record["status"] != "passed" for record in manifest["notebooks"])
    manifest["status"] = "passed" if failures == 0 else "failed"
    write_manifest(manifest_path, manifest)
    return 0 if failures == 0 else 1


def print_notebook_list() -> None:
    for index, relative in enumerate(NOTEBOOKS, start=1):
        suffix = (
            " [figure: prerequisite reruns disabled in memory]"
            if relative in FIGURE_NOTEBOOKS
            else ""
        )
        print(f"{index:02d}. {relative}{suffix}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list",
        action="store_true",
        help="print the authoritative notebook order and exit",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs and print the execution plan without building or running",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"external parent for run directories (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--iseesnow-results-root",
        type=Path,
        help="external ISeeSnow result directory; default is inside this fingerprinted run",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=REPOSITORY / ".venv",
        help="validation virtual environment (default: repository .venv)",
    )
    parser.add_argument("--kernel-name", default="python3")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue after notebook failures (the default is fail-fast)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.list:
        print_notebook_list()
        return 0

    # The three AVAC producer notebooks expose this variable for isolated
    # exploratory runs, while the manuscript figure consumes publication_amr.
    # A complete published matrix must therefore pin the shared contract.
    os.environ["AVAC_VALIDATION_RUN_NAME"] = PUBLICATION_AVAC_RUN_NAME

    try:
        output_root = require_external(arguments.output_root, "--output-root")
        explicit_iseesnow = (
            require_external(arguments.iseesnow_results_root, "--iseesnow-results-root")
            if arguments.iseesnow_results_root is not None
            else None
        )
        sources = notebook_sources()
        validate_notebook_contract(sources)
        base = base_identity(
            sources,
            kernel_name=arguments.kernel_name,
            iseesnow_results_root=explicit_iseesnow,
        )
        base_fingerprint = canonical_fingerprint(base)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if arguments.dry_run:
        try:
            expected_python = configure_process_environment(
                arguments.venv.expanduser().resolve()
            )
            validate_notebook_runtime(arguments.kernel_name, expected_python)
            swashes_plan, swashes_current = preflight_swashes()
        except (OSError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print_notebook_list()
        print()
        print(f"Repository:        {REPOSITORY}")
        print(f"Output parent:     {output_root}")
        print(f"Virtual env:       {arguments.venv.expanduser().resolve()}")
        print(
            "ISeeSnow results:  "
            + (str(explicit_iseesnow) if explicit_iseesnow else "inside fingerprinted external run")
        )
        print(f"Base fingerprint:  {base_fingerprint}")
        print("Runtime preflight: passed")
        print(f"SWASHES compiler:  {swashes_plan['compiler']}")
        swashes_action = "reuse source-matched binary" if swashes_current else "rebuild"
        print(f"SWASHES action:    {swashes_action}")
        print("Would prebuild:    AVAC, then WAVE, then ensure SWASHES (serial)")
        failure_mode = "continue on failure" if arguments.keep_going else "fail-fast"
        print(f"Would execute:     21 notebooks (serial, {failure_mode})")
        return 0

    try:
        expected_python = configure_process_environment(
            arguments.venv.expanduser().resolve()
        )
        validate_notebook_runtime(arguments.kernel_name, expected_python)
        preflight_swashes()
        output_root.mkdir(parents=True, exist_ok=True)
        resumed = find_resumable_manifest(output_root, base_fingerprint)
        if resumed is not None:
            manifest_path, manifest = resumed
            run_root = manifest_path.parent
            iseesnow_results_root = Path(manifest["identity"]["iseesnow_results_root"])
            pin_solver_compiler(manifest["identity"]["solvers"])
            print(f"Resuming compatible matrix: {run_root}", flush=True)
        else:
            solvers = prebuild_solvers()
            pin_solver_compiler(solvers)
            identity_for_fingerprint = dict(base)
            identity_for_fingerprint["solvers"] = solvers
            run_fingerprint = canonical_fingerprint(identity_for_fingerprint)
            run_root = output_root / f"matrix-{run_fingerprint[:16]}"
            manifest_path = run_root / "manifest.json"
            iseesnow_results_root = explicit_iseesnow or run_root / "iseesnow-results"
            if manifest_path.exists():
                existing = read_manifest(manifest_path)
                if existing is None or existing.get("run_fingerprint") != run_fingerprint:
                    raise RuntimeError(
                        f"Run directory collision or invalid manifest: {run_root}"
                    )
                manifest = existing
            else:
                manifest = new_manifest(
                    run_root=run_root,
                    base=base,
                    base_fingerprint=base_fingerprint,
                    solvers=solvers,
                    run_fingerprint=run_fingerprint,
                    iseesnow_results_root=iseesnow_results_root,
                )
                write_manifest(manifest_path, manifest)
            print(f"Created matrix run: {run_root}", flush=True)
        os.environ["AVAC_ISEESNOW_RESULTS_ROOT"] = str(iseesnow_results_root)
        return execute_matrix(
            manifest_path,
            manifest,
            sources,
            expected_base=base,
            base_fingerprint=base_fingerprint,
            explicit_iseesnow=explicit_iseesnow,
            kernel_name=arguments.kernel_name,
            keep_going=arguments.keep_going,
        )
    except (
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
