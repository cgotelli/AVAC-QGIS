from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


RUNTIME = importlib.import_module("avac4qgis_validation.runtime")


@pytest.mark.skipif(os.name == "nt", reason="Unix make invocation")
def test_unix_source_build_forces_the_executable_target(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "AVAC"
    source.mkdir()
    calls: list[list[str]] = []

    def fake_run(command, *, cwd, env, check):
        calls.append(command)
        assert cwd == source
        assert check is True
        (source / "xgeoclaw").write_bytes(b"test executable")

    monkeypatch.setattr(RUNTIME, "SOURCE_ROOTS", {"avac": source})
    monkeypatch.setattr(RUNTIME, "_make_command", lambda: "make")
    monkeypatch.setattr(RUNTIME.subprocess, "run", fake_run)
    monkeypatch.setenv("FC", "gfortran")

    assert RUNTIME.build_solver("avac", cores=2) == source
    assert calls == [["make", "-B", ".exe"]]


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
    monkeypatch.setattr(RUNTIME, "_activate_packaged_clawpack", lambda source_root: None)

    output = RUNTIME.prepare_source_execution("avac", work)

    assert (output / "claw.data").read_text(encoding="utf-8") == "source setup\n"
    assert not (tmp_path / "runtime-manifest.json").exists()
