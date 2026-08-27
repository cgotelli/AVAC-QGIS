"""Read one AVAC fgout frame through QGIS Python and inspect temporal APIs."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QTimer

from avac_qgis.core.results import discover_results, geometry_from_axes, _load_fgmax, _load_fgout


ROOT = Path("/private/tmp/avac-task5-qgis.NgdDmB")


def check() -> None:
    try:
        results = discover_results(ROOT)
        time, x, y, depth = _load_fgout(results, results.frames[0].frame_id)
        fx, fy, max_depth, velocity, pressure = _load_fgmax(results)
        geometry = geometry_from_axes(x, y)
        print(f"RESULT_DISCOVERY frames={len(results.frames)} time_range={results.frames[0].time_seconds}:{results.frames[-1].time_seconds} crs={results.crs_authid}", flush=True)
        print(f"FGOUT_FRAME id={results.frames[0].frame_id} actual_time={time} shape={depth.shape} geometry={geometry}", flush=True)
        print(f"FGMAX shape={max_depth.shape} velocity_max={velocity.max()} pressure_max={pressure.max()} geometry={geometry_from_axes(fx, fy)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("RESULT_SMOKE_FAILURE\n" + traceback.format_exc(), flush=True)
    QCoreApplication.quit()


QTimer.singleShot(0, check)
