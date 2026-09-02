from __future__ import annotations

import csv
import json

from avac_qgis.core.run_diagnostics import (
    parse_volume_history,
    solver_failure_reason,
    write_volume_balance,
)


def test_parse_volume_history_accepts_fortran_exponents() -> None:
    records = parse_volume_history(
        "time t =  0.00000D+00,  total mass =  0.200000000000000E+03  diff =  0.0000E+00\n"
        "time t =  0.10000E+01,  total mass =  0.180000000000000E+03  diff = -0.2000E+02\n"
    )
    assert records == [(0.0, 200.0, 0.0), (1.0, 180.0, -20.0)]


def test_write_volume_balance_reports_material_outside_domain(tmp_path) -> None:
    (tmp_path / "fort.amr").write_text(
        "time t = 0.0, total mass = 200.0 diff = 0.0\n"
        "time t = 1.0, total mass = 180.0 diff = -20.0\n",
        encoding="utf-8",
    )
    summary = write_volume_balance(tmp_path)
    assert summary is not None
    assert summary["warning"] is True
    assert summary["escaped_volume_estimate_m3"] == 20.0
    assert summary["escaped_fraction_percent"] == 10.0
    assert json.loads((tmp_path / "avac_volume_balance.json").read_text())["warning"] is True
    with (tmp_path / "avac_volume_balance.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows[-1] == ["1", "180", "-20", "20", "10"]


def test_small_conservation_residual_does_not_trigger_outflow_warning(tmp_path) -> None:
    (tmp_path / "fort.amr").write_text(
        "time t = 0, total mass = 1000 diff = 0\n"
        "time t = 1, total mass = 999.5 diff = -0.5\n",
        encoding="utf-8",
    )
    summary = write_volume_balance(tmp_path)
    assert summary is not None
    assert summary["warning"] is False


def test_fatal_fortran_stop_is_detected_even_without_nonzero_exit() -> None:
    assert solver_failure_reason("**** Too many dt reductions ****") == "Too many dt reductions"
    assert solver_failure_reason("normal completion") is None
