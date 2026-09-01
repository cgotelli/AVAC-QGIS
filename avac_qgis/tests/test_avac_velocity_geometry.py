"""Display-velocity and recovered PDF-era AVAC source contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from avac_qgis.core.results import _avac_frame_fields


ROOT = Path(__file__).resolve().parents[2]
AVAC = ROOT / "avac-main" / "src" / "AVAC"


class _Frame:
    def __init__(self) -> None:
        self.x = np.array([0.0, 1.0, 2.0, 3.0])
        self.y = np.array([0.0, 1.0, 2.0])
        x_grid, _ = np.meshgrid(self.x, self.y)
        self.h = np.ones((3, 4))
        self.u = np.full((3, 4), 2.0)
        self.v = np.zeros((3, 4))
        self.B = x_grid.copy()  # 45-degree slope: dB/dx = 1
        self.eta = self.B + self.h


def test_temporal_speed_is_the_terrain_tangent_magnitude():
    _, _, fields = _avac_frame_fields(_Frame(), rho=300.0)

    assert np.allclose(fields["velocity"], 2.0 * np.sqrt(2.0))


def test_accepted_physics_sources_are_stable():
    """Diagnostic-output changes must not silently alter accepted physics."""
    expected = {
        "b4step2.f90": "ac2829b0ea8b2c4b6e44e0acc32a61c2ba7256767b85cbdf8e7961d5c0aad2e8",
        "rpn2_geoclaw.f": "fc2c151a131d64b1a85a71a18d437f8064ff4898fbe59665fd251100acc7bcb7",
    }
    for name, digest in expected.items():
        # Git may materialize CRLF working-tree files on Windows. The source
        # contract concerns the repository text, not platform line endings.
        normalized = (AVAC / name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        assert hashlib.sha256(normalized).hexdigest() == digest


def test_cohesive_interface_arrest_uses_terrain_normal_depth():
    source = (AVAC / "rpn2_geoclaw.f").read_text(encoding="utf-8")

    # Wet-left/dry-right, dry-left/wet-right, and wet/wet transitions all use
    # h_normal*cos(phi) = h_vertical*cos(phi)^2 in the cohesive yield balance.
    assert "dx_n/(hL*costh_n**2)" in source
    assert "dx_n/(hR*costh_n**2)" in source
    assert "dx_n/(h_avg_n*costh_n**2)" in source
    assert source.count("imodel_rh .eq. 3 .and. rho_rh .gt. 0.d0") == 3
