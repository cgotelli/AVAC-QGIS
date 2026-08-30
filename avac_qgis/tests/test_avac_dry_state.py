"""Source contracts for the recovered PDF-era AVAC dry-state behavior."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AVAC = ROOT / "avac-main" / "src" / "AVAC"
GEOCLAW = (
    ROOT / "avac-main" / "clawpack-v5.14.0" / "geoclaw" / "src" / "2d" / "shallow"
)


def test_pdf_baseline_clears_momentum_at_geoclaw_dry_tolerance():
    b4step = (AVAC / "b4step2.f90").read_text(encoding="utf-8")
    source = (AVAC / "src2.f90").read_text(encoding="utf-8")
    riemann = (AVAC / "rpn2_geoclaw.f").read_text(encoding="utf-8")
    step2 = (GEOCLAW / "step2.f90").read_text(encoding="utf-8")

    assert "q(1,i,j) <= dry_tolerance" in b4step
    assert "dry_tolerance >= 1.d-8" not in b4step
    assert "0.02d0 * min(dx, dy)" in b4step
    assert "call regularized_velocity" in b4step
    assert "if (h <= dry_tolerance) then" in source
    assert "velocity_tolerance = 10.d0 * dry_tolerance" not in source
    assert "if (qr(1,i-1) <= drytol .and. ql(1,i) <= drytol)" in riemann


def test_avac_peak_velocity_uses_the_depth_aware_fgmax_implementation():
    makefile = (AVAC / "Makefile").read_text(encoding="utf-8")
    geoclaw_makefile = (GEOCLAW / "Makefile.geoclaw").read_text(encoding="utf-8")
    fgmax = (AVAC / "fgmax_values.f90").read_text(encoding="utf-8")

    assert "$(GEOLIB)/fgmax_values.f90" in makefile
    assert "./fgmax_values.f90" in makefile
    assert "$(GEOLIB)/fgmax_values.f90" in geoclaw_makefile
    assert "q(1,i,j) > velocity_depth" in fgmax
    assert "velocity_depth_threshold_rh" in fgmax
    assert "w = u*dzdx + v*dzdy" in fgmax
    assert "sqrt(u**2 + v**2 + w**2)" in fgmax
