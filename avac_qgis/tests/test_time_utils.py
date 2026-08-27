from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from avac_qgis.core import time_utils
from avac_qgis.core.run_project import materialize_runtime_tree, update_run_status
from avac_qgis.core.wave_project import _new_wave_root
from avac_qgis.core.workspace import create_run_root


def test_user_visible_run_times_use_local_civil_time(monkeypatch, tmp_path):
    fixed = datetime(2026, 8, 14, 16, 37, 42, 125000, tzinfo=timezone(timedelta(hours=2)))
    monkeypatch.setattr(time_utils, "local_now", lambda: fixed)

    workspace = tmp_path / "workspace"
    run_id, run_root = create_run_root(workspace)
    assert run_id == "run_20260814_163742"
    assert _new_wave_root(workspace).name == "wave_20260814_163742"

    backend = tmp_path / "runtime"
    backend.mkdir(); (backend / "setrun.py").write_text("fixture", encoding="utf-8")
    avac = materialize_runtime_tree(run_root, backend, {"plugin": "test"})
    marker = json.loads((run_root / ".avac_qgis_run.json").read_text(encoding="utf-8"))
    assert marker["created_at"] == "2026-08-14T16:37:42.125000+02:00"
    assert marker["temporal_origin_iso"] == "2026-08-14T16:37:42.125000+02:00"
    update_run_status(avac, "prepared")
    marker = json.loads((run_root / ".avac_qgis_run.json").read_text(encoding="utf-8"))
    assert marker["updated_at"] == "2026-08-14T16:37:42.125000+02:00"
    assert marker["temporal_origin_iso"] == "2026-08-14T16:37:42.125000+02:00"


def test_historical_utc_metadata_is_rendered_as_local_time(monkeypatch):
    class Parsed:
        def astimezone(self):
            return datetime(2026, 8, 14, 16, 37, 42, tzinfo=timezone(timedelta(hours=2)))

    monkeypatch.setattr(time_utils, "parse_iso_datetime", lambda _value: Parsed())
    assert time_utils.display_local_datetime("2026-08-14T14:37:42+00:00").startswith("2026-08-14 16:37:42")
