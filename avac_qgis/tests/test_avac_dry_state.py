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

    assert "q(1,i,j) <= dry_tolerance" in b4step
    assert "if (h <= dry_tolerance) then" in source
    assert "velocity_tolerance = 10.d0 * dry_tolerance" not in source
    assert "if (qr(1,i-1) <= drytol .and. ql(1,i) <= drytol)" in riemann


def test_avac_fgmax_is_a_diagnostic_only_replacement():
    makefile = (AVAC / "Makefile").read_text(encoding="utf-8")
    source = (AVAC / "fgmax_values.f90").read_text(encoding="utf-8")

    assert "$(GEOLIB)/fgmax_values.f90" in makefile
    assert "./fgmax_values.f90" in makefile
    assert "q(1,i,j) > velocity_depth" in source
    assert "transition_depth = 4.d0 * velocity_depth" in source
    assert "h4 + max(h4, transition_h4)" in source
    assert "sqrt(2.d0) * q(1,i,j) * q(2,i,j) / denominator" in source
    assert "w = u*dzdx + v*dzdy" in source
    assert "sqrt(u**2 + v**2 + w**2)" in source
    assert "intent(inout) :: q" not in source


def test_fgmax_velocity_desingularization_is_exact_above_transition():
    """The diagnostic formula must recover momentum/depth in resolved flow."""
    import math

    transition_depth = 0.20
    momentum = 3.75
    for depth in (transition_depth, 0.25, 2.0):
        h4 = depth**4
        denominator = math.sqrt(h4 + max(h4, transition_depth**4))
        diagnostic_velocity = math.sqrt(2.0) * depth * momentum / denominator
        assert math.isclose(diagnostic_velocity, momentum / depth, rel_tol=1e-14)
