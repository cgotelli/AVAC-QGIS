"""Event-time sentinels/zero-time semantics for derived static products."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from avac_qgis.core.results import ResultDiscovery, _load_fgmax


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    rows = np.array([
        [0, 0, 0, 0, 1, 2, 0, 3, -1],
        [1, 0, 0, 0, 1, 2, 5, -9999, 8],
        [0, 1, 0, 0, 1, 2, -1e99, 7, 9],
        [1, 1, 0, 0, 1, 2, 10, 11, 12],
    ])
    path = root / "fgmax0001.txt"; np.savetxt(path, rows)
    discovery = ResultDiscovery(root, root, root, "EPSG:2154", 300, "binary32", 1, 1, path, (), ())
    _x, _y, fields = _load_fgmax(discovery)
    assert fields["time_max_depth"][0, 0] == 0.0
    assert np.isnan(fields["time_max_depth"][1, 0])
    assert np.isnan(fields["time_max_velocity"][0, 1])
    assert np.isnan(fields["arrival_time"][0, 0])
    valid = fields["arrival_time"][np.isfinite(fields["arrival_time"])]
    assert valid.min() == 8 and valid.max() == 12
print("event-time zero/NoData range semantics: PASS")
