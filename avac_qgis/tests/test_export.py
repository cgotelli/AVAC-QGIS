"""Fast regression tests for AVAC export selection and provenance."""

from __future__ import annotations

from avac_qgis.core.export import animation_frames, animation_provenance, frame_filename


def main() -> None:
    frames = animation_frames([0.0, 2.3333333, 4.6666667, 7.0])
    assert frames == [(1, 0.0), (2, 2.3333333), (3, 4.6666667), (4, 7.0)]
    assert animation_frames([0.0, 2.3333333, 4.6666667, 7.0], 2) == [(1, 0.0), (3, 4.6666667)]
    try:
        animation_frames([0.0], 0)
    except ValueError:
        pass
    else:
        raise AssertionError("zero frame step accepted")
    metadata = animation_provenance("/tmp/run", "velocity", frames, 10, (1, 2, 3, 4), (0, 12.5))
    assert metadata["frame_bands"] == [1, 2, 3, 4]
    assert metadata["simulation_time_seconds"][-1] == 7.0
    assert metadata["result_range"] == [0.0, 12.5]
    assert frame_filename("depth", 2, 1.25) == "depth_frame_0002_t1p250000s.png"
    print("export dynamic-times/subsampling/provenance: PASS")


if __name__ == "__main__":
    main()
