from __future__ import annotations

import importlib
import json
import logging
import logging.config
import os
from pathlib import Path

import pytest


RUNTIME = importlib.import_module("avac4qgis_validation.runtime")


def test_clean_case_closes_only_file_handlers_inside_generated_folders(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case"
    wave = case / "Wave"
    wave.mkdir(parents=True)
    inside_log = wave / "pyclaw.log"
    outside_log = tmp_path / "application.log"
    inside_logger = logging.getLogger(f"test.clean_case.inside.{id(tmp_path)}")
    shared_logger = logging.getLogger(f"test.clean_case.shared.{id(tmp_path)}")
    outside_logger = logging.getLogger(f"test.clean_case.outside.{id(tmp_path)}")
    inside_handler = logging.FileHandler(inside_log)
    outside_handler = logging.FileHandler(outside_log)
    inside_logger.addHandler(inside_handler)
    shared_logger.addHandler(inside_handler)
    outside_logger.addHandler(outside_handler)
    try:
        RUNTIME.clean_case(case)

        assert inside_handler not in inside_logger.handlers
        assert inside_handler not in shared_logger.handlers
        assert inside_handler.stream is None
        assert (case / "Wave").is_dir()
        assert not inside_log.exists()
        assert outside_handler in outside_logger.handlers
        assert outside_handler.stream is not None
    finally:
        inside_logger.removeHandler(inside_handler)
        shared_logger.removeHandler(inside_handler)
        outside_logger.removeHandler(outside_handler)
        inside_handler.close()
        outside_handler.close()


def test_run_setrun_suppresses_pyclaw_import_file_logging(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    config = tmp_path / "pyclaw" / "log.config"
    config.parent.mkdir()
    config.write_text("unused\n", encoding="utf-8")
    (source / "setrun.py").write_text(
        "import logging.config\n"
        "class RunData:\n"
        "    def write(self):\n"
        f"        logging.config.fileConfig({str(config)!r})\n"
        "def setrun():\n"
        "    return RunData()\n",
        encoding="utf-8",
    )
    case = tmp_path / "case"
    (case / "Wave").mkdir(parents=True)
    calls: list[object] = []

    def fake_file_config(path, *args, **kwargs):
        calls.append(path)

    monkeypatch.setattr(RUNTIME, "runtime", lambda kind: source)
    monkeypatch.setattr(RUNTIME, "_activate_packaged_clawpack", lambda root: None)
    monkeypatch.setattr(logging.config, "fileConfig", fake_file_config)

    RUNTIME._run_setrun("wave", case, qinit=False)

    assert calls == []
    assert logging.config.fileConfig is fake_file_config


@pytest.mark.skipif(os.name == "nt", reason="Unix make invocation")
def test_unix_source_build_forces_the_executable_target(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "AVAC"
    source.mkdir()
    clawpack = tmp_path / "clawpack"
    clawpack.mkdir()
    (source / "Makefile").write_text("all:\n", encoding="utf-8")
    (source / "src2.f90").write_text("end\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, *, cwd, env, check):
        calls.append(command)
        assert cwd == source
        assert check is True
        (source / "xgeoclaw").write_bytes(b"test executable")

    monkeypatch.setattr(RUNTIME, "SOURCE_ROOTS", {"avac": source})
    monkeypatch.setattr(RUNTIME, "CLAWPACK_SOURCE", clawpack)
    monkeypatch.setattr(RUNTIME, "BUILD_STAMP_ROOT", tmp_path / "stamps")
    monkeypatch.setattr(RUNTIME, "_make_command", lambda: "make")
    monkeypatch.setattr(RUNTIME.subprocess, "run", fake_run)
    monkeypatch.setenv("FC", "gfortran")

    assert RUNTIME.build_solver("avac", cores=2) == source
    assert calls == [["make", "-B", ".exe"]]
    stamp = json.loads((tmp_path / "stamps" / "avac.json").read_text(encoding="utf-8"))
    assert stamp["solver_fingerprint"] == RUNTIME.solver_fingerprint("avac")
    assert stamp["executable_sha256"] == RUNTIME._sha256(source / "xgeoclaw")


@pytest.mark.skipif(os.name == "nt", reason="Unix make invocation")
def test_runtime_rebuilds_after_a_native_source_change(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "AVAC"
    source.mkdir()
    clawpack = tmp_path / "clawpack"
    clawpack.mkdir()
    (source / "Makefile").write_text("all:\n", encoding="utf-8")
    source_file = source / "src2.f90"
    source_file.write_text("end\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, *, cwd, env, check):
        calls.append(command)
        (source / "xgeoclaw").write_bytes(f"build-{len(calls)}".encode("ascii"))

    monkeypatch.setattr(RUNTIME, "SOURCE_ROOTS", {"avac": source})
    monkeypatch.setattr(RUNTIME, "CLAWPACK_SOURCE", clawpack)
    monkeypatch.setattr(RUNTIME, "BUILD_STAMP_ROOT", tmp_path / "stamps")
    monkeypatch.setattr(RUNTIME, "_make_command", lambda: "make")
    monkeypatch.setattr(RUNTIME.subprocess, "run", fake_run)
    monkeypatch.setenv("FC", "gfortran")

    assert RUNTIME.runtime("avac") == source
    assert calls == [["make", "-B", ".exe"]]
    assert RUNTIME.runtime("avac") == source
    assert len(calls) == 1

    source_file.write_text("! changed\nend\n", encoding="utf-8")
    assert RUNTIME.runtime("avac") == source
    assert calls == [["make", "-B", ".exe"], ["make", "-B", ".exe"]]


@pytest.mark.skipif(os.name == "nt", reason="Unix make invocation")
def test_runtime_rebuilds_after_a_vendored_geoclaw_change(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "AVAC"
    source.mkdir()
    clawpack = tmp_path / "clawpack"
    shared = clawpack / "geoclaw" / "src" / "2d" / "shallow"
    shared.mkdir(parents=True)
    (source / "Makefile").write_text("all:\n", encoding="utf-8")
    (source / "src2.f90").write_text("end\n", encoding="utf-8")
    shared_file = shared / "step2.f90"
    shared_file.write_text("end\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, *, cwd, env, check):
        calls.append(command)
        (source / "xgeoclaw").write_bytes(f"build-{len(calls)}".encode("ascii"))

    monkeypatch.setattr(RUNTIME, "SOURCE_ROOTS", {"avac": source})
    monkeypatch.setattr(RUNTIME, "CLAWPACK_SOURCE", clawpack)
    monkeypatch.setattr(RUNTIME, "BUILD_STAMP_ROOT", tmp_path / "stamps")
    monkeypatch.setattr(RUNTIME, "_make_command", lambda: "make")
    monkeypatch.setattr(RUNTIME.subprocess, "run", fake_run)
    monkeypatch.setenv("FC", "gfortran")

    assert RUNTIME.runtime("avac") == source
    assert len(calls) == 1
    shared_file.write_text("! changed\nend\n", encoding="utf-8")
    assert RUNTIME.runtime("avac") == source
    assert len(calls) == 2


def test_source_execution_does_not_require_a_packaged_runtime(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "setrun.py").write_text(
        "from pathlib import Path\n"
        "if __name__ == '__main__':\n"
        "    Path('claw.data').write_text('source setup\\n')\n",
        encoding="utf-8",
    )
    work = tmp_path / "Run" / "AVAC"
    topo = work.parent / "Topo"
    work.mkdir(parents=True)
    topo.mkdir()
    (work / "AVAC_configuration.yaml").write_text("{}\n", encoding="utf-8")
    (work / "init.xyz").write_text("0 0 1\n", encoding="utf-8")
    (topo / "topography.asc").write_text("test\n", encoding="utf-8")

    monkeypatch.setattr(RUNTIME, "runtime", lambda kind: source)

    output = RUNTIME.prepare_source_execution("avac", work)

    assert (output / "claw.data").read_text(encoding="utf-8") == "source setup\n"
    assert not (tmp_path / "runtime-manifest.json").exists()


def test_packaged_clawpack_activation_exposes_the_repository_plugin(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    clawpack = workspace / "clawpack"
    clawpack.mkdir(parents=True)
    monkeypatch.setattr(RUNTIME, "WORKSPACE", workspace)
    monkeypatch.setattr(RUNTIME, "CLAWPACK_SOURCE", clawpack)
    monkeypatch.setattr(
        RUNTIME.sys,
        "path",
        [entry for entry in RUNTIME.sys.path if entry != str(workspace)],
    )

    RUNTIME._activate_packaged_clawpack(clawpack)

    assert RUNTIME.sys.path[0] == str(clawpack)
    assert str(workspace) in RUNTIME.sys.path
