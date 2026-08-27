"""Pure numerical regressions for AVAC profile extraction."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import numpy as np

from avac_qgis.core.profiles import bilinear_sample, extract_profile, raster_spacing, sample_polyline_positions, write_profile_csv


def main() -> None:
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])
    values = y[:, None] * 10.0 + x[None, :]
    assert raster_spacing(x, y) == 1.0
    for coords, length in (([(0, 1), (2, 1)], 2.0), ([(1, 0), (1, 2)], 2.0), ([(0, 0), (1, 1), (2, 1)], 1 + 2**0.5)):
        distance, xq, yq = sample_polyline_positions(coords, spacing=0.6)
        assert distance[0] == 0 and np.isclose(distance[-1], length) and np.all(np.diff(distance) > 0)
        assert (xq[0], yq[0]) == tuple(coords[0]) and np.allclose((xq[-1], yq[-1]), coords[-1])
    # Matches the supplied profil.shp: a single-part PolyLine with a repeated
    # final vertex must sample as the same non-degenerate line.
    profil = [(965560.025847458, 6536375.762824026), (965893.4254486539, 6536163.74657278),
              (966694.5555583234, 6535686.30539631), (966694.5555583234, 6535686.30539631)]
    distance, xq, yq = sample_polyline_positions(profil, count=5)
    assert np.all(np.diff(distance) > 0)
    assert np.allclose((xq[-1], yq[-1]), profil[-1])
    assert np.allclose(bilinear_sample(x, y, values, np.array([0.5]), np.array([0.5])), [5.5])
    assert np.isnan(bilinear_sample(x, y, values, np.array([-0.1]), np.array([0.5]))[0])
    nodata = values.copy()
    nodata[0, 0] = np.nan
    assert np.isnan(bilinear_sample(x, y, nodata, np.array([0.5]), np.array([0.5]))[0])
    dataset = extract_profile([(0, 0), (2, 2)], x, y, values, "depth", "maximum result", spacing=1.0, profile_name="Diagonal")
    assert dataset.values.size == 4 and np.isclose(dataset.values[0], 0) and np.isclose(dataset.values[-1], 22)
    legacy = extract_profile([(0, 0), (2, 0)], x, y, values, "velocity", "maximum result", count=1000)
    assert legacy.values.size == 1000 and np.isclose(legacy.distance_m[-1], 2.0)
    snow_surface = extract_profile([(0, 0), (2, 0)], x, y, values, "snow_surface_elevation", "selected frame", count=3)
    water_surface = extract_profile([(0, 0), (2, 0)], x, y, values, "water_elevation", "selected frame", count=3)
    assert snow_surface.unit == "m" and water_surface.unit == "m"
    with tempfile.TemporaryDirectory() as directory:
        output = write_profile_csv(Path(directory) / "profile", dataset)
        rows = list(csv.reader(line for line in output.read_text(encoding="utf-8").splitlines() if not line.startswith("#")))
        assert rows[0] == ["distance_m", "x", "y", "depth_m"] and len(rows) == 5
    print("profile sampling/spacing/interpolation/CSV: PASS")


if __name__ == "__main__":
    main()
