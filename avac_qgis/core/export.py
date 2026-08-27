"""Small, QGIS-independent helpers for AVAC image/video export."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Sequence


def locate_ffmpeg(configured: str | Path | None = None) -> Path | None:
    """Return a usable external ffmpeg executable without bundling one."""
    candidate = Path(str(configured)).expanduser() if configured else None
    if candidate and candidate.is_file() and candidate.stat().st_mode & 0o111:
        return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def animation_frames(times: Sequence[float], every: int = 1) -> list[tuple[int, float]]:
    """Select one-based raster bands while retaining their real AVAC times."""
    if every < 1:
        raise ValueError("Animation frame step must be at least one.")
    if not times:
        raise ValueError("No AVAC temporal frames are available for animation export.")
    return [(band, float(time_seconds)) for band, time_seconds in enumerate(times, 1) if (band - 1) % every == 0]


def animation_provenance(
    source_run: str | Path, variable: str, frames: Sequence[tuple[int, float]], fps: int,
    extent: tuple[float, float, float, float], result_range: Sequence[float],
) -> dict[str, Any]:
    """Scientific sidecar metadata, deliberately separate from AVAC files."""
    return {
        "format": "AVAC-QGIS animation export v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "plugin_version": "0.1.0",
        "source_run": str(Path(source_run)),
        "variable": variable,
        "frame_bands": [band for band, _time in frames],
        "simulation_time_seconds": [time for _band, time in frames],
        "frames_per_second": int(fps),
        "extent": {"xmin": extent[0], "xmax": extent[1], "ymin": extent[2], "ymax": extent[3]},
        "result_range": [float(value) for value in result_range],
    }


def frame_filename(variable: str, band: int, time_seconds: float) -> str:
    """Stable filesystem-safe name retaining the actual AVAC simulation time."""
    # Simulation time is an elapsed scalar, never a QDateTime/clock value.
    safe_time = f"{float(time_seconds):.6f}".replace("-", "minus").replace(".", "p")
    return f"{variable}_frame_{int(band):04d}_t{safe_time}s.png"
