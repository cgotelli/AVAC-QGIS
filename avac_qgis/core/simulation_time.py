"""AVAC elapsed simulation-time helpers.

AVAC times are scalar seconds, never civil dates.  QGIS temporal ranges are
only an internal band-selection mechanism and must not be used for display or
serialization.
"""

from __future__ import annotations

from datetime import timedelta
import math

from .time_utils import parse_iso_datetime


def format_simulation_seconds(seconds: float) -> str:
    """Format an elapsed AVAC time without timezone/date conversion."""
    value = float(seconds)
    return f"{value:.9f}".rstrip("0").rstrip(".") + " s"


def simulation_seconds_for_band(times: list[float], band: int) -> float:
    """Return the manifest time for QGIS's one-based raster band."""
    if band < 1 or band > len(times):
        raise ValueError(f"Temporal band {band} is outside the AVAC time axis.")
    return float(times[band - 1])


def temporal_band_records(origin_iso: str, times: list[float]) -> list[dict[str, float | int | str]]:
    """Build unique, millisecond-aligned QGIS intervals for simulation frames.

    QGIS requires civil datetimes for its Temporal Controller.  AVAC remains
    authoritative in elapsed seconds; these records are only an automatic
    display mapping anchored to the real local run-preparation time.
    """
    values = [float(value) for value in times]
    if not values:
        raise ValueError("Temporal result has no frame times.")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Temporal frame times must be finite.")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError("Temporal frame times must be strictly increasing.")
    origin = parse_iso_datetime(origin_iso)
    records: list[dict[str, float | int | str]] = []
    for index, start_seconds in enumerate(values):
        if index + 1 < len(values):
            end_seconds = values[index + 1]
        else:
            step = values[-1] - values[-2] if len(values) > 1 else 0.001
            end_seconds = start_seconds + max(0.001, step)
        # QDateTime and the controller operate at millisecond resolution.
        start_ms, end_ms = round(start_seconds * 1000), round(end_seconds * 1000)
        if end_ms <= start_ms:
            end_ms = start_ms + 1
        records.append({
            "band": index + 1,
            "simulation_time_seconds": start_seconds,
            "start_iso": (origin + timedelta(milliseconds=start_ms)).isoformat(),
            "end_iso": (origin + timedelta(milliseconds=end_ms)).isoformat(),
        })
    return records
