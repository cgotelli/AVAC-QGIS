"""Lightweight diagnostics for a completed native AVAC solver run."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_MASS_LINE = re.compile(
    rf"time\s+t\s*=\s*({_FLOAT})\s*,\s*total\s+mass\s*=\s*({_FLOAT})"
    rf"\s+diff\s*=\s*({_FLOAT})",
    re.IGNORECASE,
)
_SOLVER_FAILURES = (
    "SOLUTION ERROR",
    "Error ***",
    "Too many dt reductions",
    "Stopping calculation",
    "set_fgout: ERROR",
    "ERROR reading hydraulic",
    "ERROR: hydraulic boundary",
    "ERROR: total-discharge boundary",
)


def solver_failure_reason(output: str) -> str | None:
    """Return the first known fatal solver diagnostic present in output."""
    return next((message for message in _SOLVER_FAILURES if message in output), None)


def parse_volume_history(text: str) -> list[tuple[float, float, float]]:
    """Parse GeoClaw's base-grid conservation checks from ``fort.amr``.

    AVAC's first conserved component is flow depth, so GeoClaw's historical
    ``total mass`` label is a computational-domain volume in cubic metres for
    projected metre-based grids.  Level 1 covers the whole domain exactly;
    its refluxed/averaged state therefore avoids counting overlapping AMR
    patches twice.
    """
    records: list[tuple[float, float, float]] = []
    for match in _MASS_LINE.finditer(text):
        records.append(tuple(float(value.replace("D", "E").replace("d", "e")) for value in match.groups()))
    return records


def write_volume_balance(
    output_directory: str | Path,
    *,
    warning_fraction: float = 1.0e-3,
) -> dict[str, Any] | None:
    """Write a volume ledger and return its summary.

    The escaped amount is a net estimate, ``max(V0 - V(t), 0)``.  It is not
    an accumulated face-flux integral: numerical conservation error is also
    present, so the plugin warns only above the configured relative tolerance
    (0.1 % by default).
    """
    output = Path(output_directory)
    source = output / "fort.amr"
    if not source.is_file():
        return None
    records = parse_volume_history(source.read_text(encoding="utf-8", errors="replace"))
    if not records:
        return None

    initial_volume = records[0][1]
    rows: list[tuple[float, float, float, float, float]] = []
    for time_s, volume, _reported_difference in records:
        change = volume - initial_volume
        escaped = max(-change, 0.0)
        fraction_percent = 100.0 * escaped / initial_volume if initial_volume > 0.0 else 0.0
        rows.append((time_s, volume, change, escaped, fraction_percent))

    ledger = output / "avac_volume_balance.csv"
    with ledger.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "simulation_time_s",
                "volume_in_domain_m3",
                "net_volume_change_m3",
                "escaped_volume_estimate_m3",
                "escaped_fraction_percent",
            )
        )
        writer.writerows((f"{value:.15g}" for value in row) for row in rows)

    final_time, final_volume, net_change, escaped_volume, escaped_percent = rows[-1]
    escaped_fraction = escaped_volume / initial_volume if initial_volume > 0.0 else 0.0
    summary: dict[str, Any] = {
        "format": 1,
        "basis": "GeoClaw level-1 conservation history; escaped volume is a net estimate",
        "warning_fraction": float(warning_fraction),
        "warning": bool(initial_volume > 0.0 and escaped_fraction > warning_fraction),
        "initial_volume_m3": initial_volume,
        "final_time_s": final_time,
        "final_volume_m3": final_volume,
        "net_volume_change_m3": net_change,
        "escaped_volume_estimate_m3": escaped_volume,
        "escaped_fraction_percent": escaped_percent,
        "minimum_volume_m3": min(row[1] for row in rows),
        "maximum_volume_m3": max(row[1] for row in rows),
        "samples": len(rows),
        "ledger": ledger.name,
    }
    summary_path = output / "avac_volume_balance.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    summary["ledger_path"] = str(ledger)
    return summary
