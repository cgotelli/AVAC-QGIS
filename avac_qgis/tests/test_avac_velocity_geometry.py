"""Display-velocity and verified AVAC source contracts."""

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


def test_temporal_speed_ignores_unresolved_depths_below_five_centimetres():
    frame = _Frame()
    frame.h[0, 0] = 0.01
    frame.eta = frame.B + frame.h

    _, _, fields = _avac_frame_fields(frame, rho=300.0)

    assert fields["depth"][0, 0] == 0.01
    assert fields["velocity"][0, 0] == 0.0


def test_verified_avac_source_hashes_are_stable():
    expected = {
        "src2.f90": "fcb4766a64c7b06b257e65bfffa3efbcd6d53b4a2587e70b87ef2fdb5ae50233",
        "rheology_module.f90": "27e64add229292cafd94ae9832e25d0ce87045f9117d94981ec3451ca854d69d",
        "rpn2_geoclaw.f": "2f403b9f81b22d963906cbd509fe9594dd3334ad2f37d9cc7691570a4028d1e1",
        "b4step2.f90": "97d8607958b89511eca4a7e63904ad3636a2545d975b109b2829bb48d062d225",
        "fgmax_values.f90": "bc613f38f72d342dacae6a6188b178c43e6309c5c7b3325c3d8631588a8ae346",
        "Makefile": "9d41195d8733cde7f13871e84a1d9a529d40e78c2a940382a5f87e4d127ac31b",
    }
    for name, digest in expected.items():
        # Git may materialize CRLF working-tree files on Windows. The source
        # contract concerns the repository text, not platform line endings.
        normalized = (AVAC / name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        assert hashlib.sha256(normalized).hexdigest() == digest
