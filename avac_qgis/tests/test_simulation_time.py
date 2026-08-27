"""Timezone-independent AVAC elapsed-time formatting regression."""

from __future__ import annotations

import os
import time

from avac_qgis.core.export import animation_frames, frame_filename
from avac_qgis.core.simulation_time import format_simulation_seconds, simulation_seconds_for_band, temporal_band_records


def main() -> None:
    # Changing process TZ must never change scientific elapsed seconds.
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Zurich"
        if hasattr(time, "tzset"):
            time.tzset()
        times = [0.0, 2.3333333, 4.6666667, 7.0]
        assert [format_simulation_seconds(value) for value in times] == ["0 s", "2.3333333 s", "4.6666667 s", "7 s"]
        assert simulation_seconds_for_band(times, 3) == 4.6666667
        assert frame_filename("depth", 3, simulation_seconds_for_band(times, 3)) == "depth_frame_0003_t4p666667s.png"
        assert [time for _band, time in animation_frames(times)] == times
        records = temporal_band_records("2026-08-14T16:00:00+02:00", times)
        assert [record["band"] for record in records] == [1, 2, 3, 4]
        assert [record["simulation_time_seconds"] for record in records] == times
        assert len({record["start_iso"] for record in records}) == len(times)
        assert records[0]["start_iso"] == "2026-08-14T16:00:00+02:00"
        assert records[1]["start_iso"] == "2026-08-14T16:00:02.333000+02:00"
        assert records[-1]["end_iso"] == "2026-08-14T16:00:09.333000+02:00"
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()
    print("simulation elapsed seconds are timezone-independent: PASS")


if __name__ == "__main__":
    main()
