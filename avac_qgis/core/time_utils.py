"""Local civil-time helpers for user-visible AVAC run records.

Scientific simulation times remain elapsed seconds.  These helpers are only
for filenames, directory identifiers, provenance timestamps, and the civil
datetime axis QGIS requires for temporal navigation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


TEMPORAL_ORIGIN_FIELD = "temporal_origin_iso"


def local_now() -> datetime:
    """Return the current local time with an explicit UTC offset."""
    return datetime.now().astimezone()


def local_now_iso() -> str:
    """Return an unambiguous ISO-8601 local timestamp."""
    return local_now().isoformat()


def local_run_stamp() -> str:
    """Return the local wall-clock component used in run directory names."""
    return local_now().strftime("%Y%m%d_%H%M%S")


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO timestamp, treating an old naive value as local time."""
    text = str(value).strip()
    if not text:
        raise ValueError("Timestamp is empty.")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def localize_iso_datetime(value: str) -> str:
    """Normalize an existing aware timestamp to the machine's local zone."""
    return parse_iso_datetime(value).astimezone().isoformat()


def local_timestamp_for_file(path: str | Path) -> str:
    """Return a local ISO timestamp from a file's modification time."""
    return datetime.fromtimestamp(Path(path).stat().st_mtime).astimezone().isoformat()


def temporal_origin_iso(metadata: dict, marker_path: str | Path) -> str:
    """Return a stable local civil origin for a simulation's QGIS time axis.

    ``temporal_origin_iso`` is deliberately independent from ``updated_at``:
    a result reload, cancellation, or Wave preparation must never move an
    already-established simulation along the QGIS temporal axis.  Older run
    markers have no explicit origin, so their creation time remains the
    compatible fallback.
    """
    for key in (TEMPORAL_ORIGIN_FIELD, "created_at", "updated_at"):
        value = str(metadata.get(key) or "").strip()
        if value:
            try:
                return localize_iso_datetime(value)
            except ValueError:
                pass
    return local_timestamp_for_file(marker_path)


def display_local_datetime(value: str) -> str:
    """Format either new local or historical UTC metadata for the UI."""
    try:
        return parse_iso_datetime(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError):
        return str(value).strip()
