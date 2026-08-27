"""Fast non-QGIS checks for isolated run-tree materialization and protection."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from avac_qgis.core.run_project import RUNTIME_RUN_MANIFEST, SOLVER_MANIFEST, materialize_runtime_tree, materialize_solver_tree, validate_prepared_run


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    backend = root / "backend"
    backend.mkdir()
    for name in SOLVER_MANIFEST:
        (backend / name).write_text(name, encoding="utf-8")
    (backend / "xgeoclaw").write_text("transient", encoding="utf-8")
    run = root / "run"
    avac = materialize_solver_tree(run, backend, {"plugin": "test"})
    assert set(path.name for path in avac.iterdir()) == set(SOLVER_MANIFEST)
    assert not (avac / "xgeoclaw").exists()
    assert validate_prepared_run(avac, require_ready=False)["status"] == "materializing"
    # A cancelled run remains identifiable/reopenable for inspection, but is
    # never mistaken for an unmarked arbitrary backend.
    marker = run / ".avac_qgis_run.json"
    marker.write_text(marker.read_text(encoding="utf-8").replace('"materializing"', '"cancelled"'), encoding="utf-8")
    assert validate_prepared_run(avac, require_ready=False)["status"] == "cancelled"
    try:
        validate_prepared_run(backend)
    except ValueError:
        pass
    else:
        raise AssertionError("unmarked backend was accepted")
    runtime_backend = root / "runtime-backend"
    runtime_backend.mkdir()
    (runtime_backend / "setrun.py").write_text("runtime backend", encoding="utf-8")
    runtime_run = root / "runtime-run"
    runtime_avac = materialize_runtime_tree(runtime_run, runtime_backend, {"plugin": "test"})
    runtime_marker = validate_prepared_run(runtime_avac, require_ready=False)
    assert set(path.name for path in runtime_avac.iterdir()) == set(RUNTIME_RUN_MANIFEST)
    assert runtime_marker["execution_mode"] == "bundled_runtime"
print("run project materialization/protection: PASS")
