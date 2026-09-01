"""Preflight checks and controlled process environment for AVAC."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .runtime_assets import bundled_backend_directory, default_template_path, ensure_bundled_runtime
from .runtime import validate_runtime
from .workspace import validate_workspace


@dataclass(frozen=True)
class EnvironmentReport:
    """Result of checking the exact environment to be passed to AVAC."""

    environment: dict[str, str]
    claw_root: Path | None
    avac_dir: Path
    tools: dict[str, str | None]
    expected_fort_frames: int | None = None
    expected_fgout_frames: int | None = None
    details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    runtime_root: Path | None = None

    @property
    def ready(self) -> bool:
        return not self.errors

    def as_text(self) -> str:
        lines = [f"AVAC directory: {self.avac_dir}", f"CLAW: {self.environment.get('CLAW', '(not set)')}"]
        for name in ("make", "gfortran", "python"):
            lines.append(f"{name}: {self.tools.get(name) or 'not found'}")
        lines.append(f"FC: {self.environment.get('FC', '(not set; Makefile/compiler default)')}")
        lines.append(f"OMP_NUM_THREADS: {self.environment.get('OMP_NUM_THREADS', '(not set)')}")
        if self.expected_fort_frames is not None:
            lines.append(f"Expected fort.t frames: {self.expected_fort_frames}")
        if self.expected_fgout_frames is not None:
            lines.append(f"Expected fgout frames: {self.expected_fgout_frames}")
        lines.extend(self.details)
        if self.errors:
            lines.append("Preflight failures:")
            lines.extend(f"- {error}" for error in self.errors)
        return "\n".join(lines)


def default_avac_directory() -> Path:
    """Return automatically resolved plugin/development AVAC assets."""
    return bundled_backend_directory()


def default_clawpack_root() -> Path | None:
    """Locate a configured or conventional local Clawpack checkout."""
    configured = os.environ.get("AVAC_QGIS_CLAW_ROOT", "").strip()
    candidates = (
        Path(configured).expanduser() if configured else None,
        Path.home() / "Downloads" / "Lac_Clusaz" / "clawpack-v5.14.0",
    )
    return next(
        (path for path in candidates if path is not None and (path / "clawutil" / "src" / "Makefile.common").is_file()),
        None,
    )


def default_claw_python() -> Path | None:
    """Use an explicitly configured AVAC Python; do not assume a user home path."""
    configured = os.environ.get("AVAC_QGIS_CLAW_PYTHON", "").strip()
    candidate = Path(configured).expanduser() if configured else None
    return candidate if candidate is not None and candidate.is_file() else None


def available_cpu_cores() -> int:
    """Return the usable logical-CPU count for a local OpenMP process."""
    return max(1, int(os.cpu_count() or 1))


def _omp_thread_count(omp_threads: int | None) -> str:
    """Use an explicit UI choice, retaining legacy defaults when omitted."""
    if omp_threads is None:
        return os.environ.get("OMP_NUM_THREADS", "8")
    return str(max(1, int(omp_threads)))


def build_avac_environment(
    claw_root: str | Path | None,
    python_executable: str | Path | None = None,
    base: Mapping[str, str] | None = None,
    omp_threads: int | None = None,
) -> tuple[dict[str, str], Path | None]:
    """Build the explicit environment used for QProcess without sourcing shell files."""
    env = {str(key): str(value) for key, value in (os.environ if base is None else base).items()}
    selected = str(claw_root or "").strip()
    inherited = env.get("CLAW", "").strip()
    root_text = selected or inherited
    root = Path(root_text).expanduser().resolve() if root_text else None
    if root is not None:
        env["CLAW"] = str(root)
        existing_pythonpath = env.get("PYTHONPATH", "")
        pieces = [str(root), *[item for item in existing_pythonpath.split(os.pathsep) if item and item != str(root)]]
        env["PYTHONPATH"] = os.pathsep.join(pieces)

    # Finder-launched QGIS commonly has a short PATH. Retain the inherited
    # value and add only system locations; optional developer toolchains must
    # be selected explicitly rather than embedding a Homebrew installation.
    path_entries = [item for item in env.get("PATH", "").split(os.pathsep) if item]
    for directory in ("/usr/local/bin", "/usr/bin", "/bin"):
        if directory not in path_entries:
            path_entries.append(directory)
    env["PATH"] = os.pathsep.join(path_entries)
    if not env.get("FC"):
        compiler = _tool_path("gfortran", env)
        if compiler:
            env["FC"] = compiler
    # AVAC's Makefile uses eight OpenMP threads.  Set it explicitly because a
    # Finder-launched QGIS process does not inherit the terminal environment.
    if omp_threads is None:
        env.setdefault("OMP_NUM_THREADS", "8")
    else:
        env["OMP_NUM_THREADS"] = _omp_thread_count(omp_threads)
    selected_python = str(python_executable or "").strip()
    if selected_python:
        env["CLAW_PYTHON"] = str(Path(selected_python).expanduser())
    return env, root


def _expected_frames(configuration: Path) -> tuple[int | None, int | None]:
    """Read the existing AVAC frame count without modifying its YAML input."""
    try:
        text = configuration.read_text(encoding="utf-8")
    except OSError:
        return None, None
    match = re.search(r"(?m)^\s*nb_simul\s*:\s*(\d+)\s*(?:#.*)?$", text)
    if not match:
        return None, None
    outputs = int(match.group(1))
    # GeoClaw writes an initial fort frame (0) plus one for every simulation
    # output.  AVAC's fgout stream has one frame per simulation output.
    return outputs + 1, outputs


def _prepared_qinit_path(avac_path: Path) -> Path | None:
    """Resolve new binary and legacy text initial-condition inputs."""
    for name in ("init.avacbin", "init.xyz"):
        candidate = avac_path / name
        if candidate.is_file():
            return candidate
    return None


def _tool_path(name: str, env: Mapping[str, str]) -> str | None:
    return shutil.which(name, path=env.get("PATH"))


def _version(command: list[str], env: Mapping[str, str]) -> str | None:
    try:
        result = subprocess.run(command, env=dict(env), capture_output=True, text=True, timeout=5, check=False)
    except OSError:
        return None
    first_line = ((result.stdout or result.stderr).strip().splitlines() or [""])[0]
    return first_line or None


def check_environment(
    avac_dir: str | Path,
    claw_root: str | Path | None,
    python_executable: str | Path | None = None,
    omp_threads: int | None = None,
) -> EnvironmentReport:
    """Check the complete-case and tool requirements without changing any files."""
    avac_path = Path(avac_dir).expanduser().resolve()
    env, root = build_avac_environment(claw_root, python_executable, omp_threads=omp_threads)
    configured_python = env.get("CLAW_PYTHON", "").strip()
    tools = {
        "make": _tool_path("make", env),
        "gfortran": _tool_path("gfortran", env),
        # This is the interpreter run by the Makefile/runclaw, not merely the
        # first python3 visible on QGIS's PATH.
        "python": configured_python or _tool_path("python3", env),
    }
    details: list[str] = []
    errors: list[str] = []

    for name, path in tools.items():
        if path is None:
            errors.append(f"Required executable not found on the QProcess PATH: {name}")
    if tools["make"]:
        details.append(f"make version: {_version([tools['make'], '--version'], env) or 'unavailable'}")
    if tools["gfortran"]:
        details.append(f"gfortran version: {_version([tools['gfortran'], '--version'], env) or 'unavailable'}")

    required_sources = ("Makefile", "setrun.py", "setprob.f90", "src2.f90", "b4step2.f90", "rheology_module.f90", "fgmax_values.f90", "qinit_module.f90", "rpn2_geoclaw.f")
    if not avac_path.is_dir():
        errors.append(f"AVAC working directory does not exist: {avac_path}")
    else:
        missing_sources = [name for name in required_sources if not (avac_path / name).is_file()]
        if missing_sources:
            errors.append("Incomplete AVAC solver directory; missing: " + ", ".join(missing_sources))
        if not (avac_path / "AVAC_configuration.yaml").is_file():
            errors.append("Missing AVAC_configuration.yaml; this solver's setrun.py imports that exact filename.")
        else:
            try:
                configuration = (avac_path / "AVAC_configuration.yaml").read_text(encoding="utf-8")
            except OSError:
                configuration = ""
            if not re.search(r"(?m)^\s*topo_source\s*:\s*\S+", configuration):
                errors.append(
                    "AVAC_configuration.yaml has no file_names.topo_source; "
                    "the existing setrun.py will fail before the solver starts."
                )

        # The real-world setrun.py resolves terrain as ../Topo/<topofile> and
        # reads the qinit path written in qinit.data.  Do not create either here.
        topo_dir = avac_path.parent / "Topo"
        if not (topo_dir / "topography.asc").is_file():
            errors.append(f"Missing AVAC-ready terrain input: {topo_dir / 'topography.asc'}")
        if _prepared_qinit_path(avac_path) is None:
            errors.append(f"Missing AVAC-ready initial-condition input in: {avac_path}")

    if configured_python and not Path(configured_python).is_file():
        errors.append(f"Configured CLAW_PYTHON does not exist: {configured_python}")

    # The release-mask implementation deliberately uses Matplotlib's Path
    # semantics to remain numerically equivalent to the standalone AVAC GUI.
    try:
        from matplotlib.path import Path as _MplPath  # noqa: F401
    except ImportError:
        errors.append(
            "Matplotlib is required for AVAC release-mask compatibility; install it in QGIS's Python environment."
        )

    if root is None:
        errors.append("CLAW is not configured. Select a Clawpack root containing clawutil/src/Makefile.common.")
    else:
        expected = (root / "clawutil" / "src" / "Makefile.common", root / "geoclaw" / "src" / "2d" / "shallow" / "Makefile.geoclaw")
        missing = [str(path) for path in expected if not path.is_file()]
        if missing:
            errors.append("Configured CLAW root is not compatible with this Makefile: " + "; ".join(missing))
    expected_fort, expected_fgout = _expected_frames(avac_path / "AVAC_configuration.yaml")
    return EnvironmentReport(env, root, avac_path, tools, expected_fort, expected_fgout, details, errors)


def check_runtime_environment(avac_dir: str | Path, omp_threads: int | None = None) -> EnvironmentReport:
    """Preflight a prepared direct-runtime case without Make/compiler/CLAW."""
    avac_path = Path(avac_dir).expanduser().resolve()
    errors: list[str] = []
    configuration = avac_path / "AVAC_configuration.yaml"
    if not avac_path.is_dir():
        errors.append(f"Prepared AVAC directory does not exist: {avac_path}")
    if not configuration.is_file():
        errors.append("Missing AVAC_configuration.yaml; prepare the run again.")
    if _prepared_qinit_path(avac_path) is None:
        errors.append("Missing AVAC initial condition; prepare the run again.")
    if not (avac_path.parent / "Topo" / "topography.asc").is_file():
        errors.append("Missing AVAC terrain input; prepare the run again.")
    expected_fort, expected_fgout = _expected_frames(configuration)
    environment = {"OMP_NUM_THREADS": _omp_thread_count(omp_threads)}
    return EnvironmentReport(environment, None, avac_path, {"make": None, "gfortran": None, "python": None},
                             expected_fort, expected_fgout,
                             ["Execution mode: bundled native runtime (no Make/compiler/CLAW required)."], errors)


def check_packaged_environment(
    workspace: str | Path,
    template: str | Path | None = None,
    omp_threads: int | None = None,
) -> EnvironmentReport:
    """Return a report for the normal packaged workflow, never ``None``.

    This deliberately does not inspect Make, compilers, external Clawpack or
    external AVAC source trees. ``ensure_bundled_runtime`` installs/repairs and
    validates the signed-by-hash managed artifact before reporting readiness.
    """
    errors: list[str] = []
    runtime: Path | None = None
    details = ["Execution mode: packaged AVAC runtime (no Make/compiler/external CLAW required)."]
    try:
        workspace_path = validate_workspace(workspace)
        details.append(f"Working directory writable: {workspace_path}")
    except Exception as exc:  # noqa: BLE001
        workspace_path = Path(str(workspace or ".")).expanduser()
        errors.append(f"AVAC Working Directory is unavailable: {exc}")
    template_path = Path(template or default_template_path()).expanduser()
    if template_path.is_file():
        details.append(f"Built-in configuration template: {template_path}")
    else:
        errors.append(f"Built-in AVAC configuration template is unavailable: {template_path}")
    try:
        runtime = ensure_bundled_runtime()
        manifest = validate_runtime(runtime)
        details.extend((f"Managed runtime validated: {runtime}", "Bundled xgeoclaw and Clawpack hashes validated."))
        import importlib
        import sys
        claw_root = runtime / str(manifest["clawpack"]["root"])
        added = str(claw_root)
        if added not in sys.path:
            sys.path.insert(0, added)
        try:
            importlib.import_module("clawpack")
        except ImportError as exc:
            errors.append(f"Bundled Clawpack cannot be imported by QGIS Python: {exc}")
        for module in ("numpy", "matplotlib.path", "osgeo.gdal"):
            try:
                importlib.import_module(module)
            except ImportError as exc:
                errors.append(f"Required QGIS Python module is unavailable ({module}): {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Plugin-managed runtime is unavailable or invalid: {exc}")
    return EnvironmentReport({"OMP_NUM_THREADS": _omp_thread_count(omp_threads)}, None, workspace_path,
                             {"make": None, "gfortran": None, "python": None}, details=details, errors=errors,
                             runtime_root=runtime)
