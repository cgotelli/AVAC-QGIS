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


def test_recovered_pdf_baseline_source_hashes_are_stable():
    expected = {
        "src2.f90": "249fe780c2329490ccf9ade4c6554695602bfc680c77770627a66e9a1c1d27ed",
        "rheology_module.f90": "1c913b4a0b8f8b86c529eed927d37bb40ef58bc46048fc912de69039a271d1c0",
        "b4step2.f90": "ac2829b0ea8b2c4b6e44e0acc32a61c2ba7256767b85cbdf8e7961d5c0aad2e8",
        "Makefile": "ea519f819761ae7b6690e1a31016ab08a05961ff4f3af90ff68bac84f7b14714",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((AVAC / name).read_bytes()).hexdigest() == digest
