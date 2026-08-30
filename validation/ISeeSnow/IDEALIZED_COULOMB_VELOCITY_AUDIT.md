# Idealized Coulomb peak-velocity audit

> **Historical audit, superseded on 29 August 2026.** This report correctly
> diagnoses the earlier wet--dry numerical spike, but its final 115.034 m/s
> result predates the Cartesian steep-slope correction. The current Coulomb
> result is 106.443 m/s. See
> [`VOELLMY_FORMULATION_AUDIT.md`](VOELLMY_FORMULATION_AUDIT.md) for the
> formulation audit and the three final notebook reruns.

This development record is deliberately separate from the manuscript. It
documents why the AVAC4QGIS peak velocity in the ISeeSnow idealized
Coulomb-only case was re-examined and how the corrected result was obtained.

## Finding

The original extreme value was numerical, not a prediction of the Coulomb
rheology. A full current-source rerun before the correction recorded an fgmax
peak of 37,199 m s-1 at 60.686 s, while the saved native solution frames had
maximum speeds of order 18 m s-1. The event occurred between the 10 s saved
states at a moving wet--dry margin, where a very small cell-average depth was
used as the denominator in `hu/h`.

Two implementation details contributed:

1. AVAC reconstructed velocity from raw momentum divided by depth in its
   Riemann and source paths, without a smooth wet--dry desingularization.
2. The conservative positivity relimiter present in GeoClaw's second-order
   update was disabled by a hard-coded setting.

## Correction

AVAC now uses the Kurganov--Petrova velocity desingularization consistently in
the Riemann solver, the pre-step state update, and the rheology source update.
At the 5 m ISeeSnow resolution its transition depth is 0.10 m. The formula is
exactly `momentum/depth` at and above that depth and smoothly reduces momentum
only in the unresolved wet--dry fringe. The GeoClaw positivity relimiter is
enabled at compile time for AVAC only. WAVE retains the upstream GeoClaw
setting.

The native AVAC peak diagnostic also now records velocity only where vertical
depth exceeds 0.05 m. This is a minimum depth for interpreting a cell-average
velocity, consistent with the model-specific thresholds documented by the
ISeeSnow protocol. It is not a velocity cap. The ISeeSnow runs retain a solver
speed limit of 1e99 m s-1, so no practical clipping occurs.

## Sensitivity and corrected full run

An instrumented intermediate run with a 0.05 m desingularization transition
still produced 170.340 m s-1 at 33.665 s in a cell only 0.05095 m deep. Raising
the transition to 0.10 m, which is 2% of the 5 m cell spacing, removed that
threshold-edge event without tuning to any peer result.

The corrected 1200 s notebook run gives:

- peak PFV: 115.0343 m s-1 at 37.7422 s;
- peak location: (3225 m, -4250 m);
- largest depth attained at that cell: 5.525 m;
- nearest saved state at 40.336 s: depth 1.886 m and speed 101.709 m s-1;
- relative native-volume change at 1200 s: +0.3634%;
- practical-rest criterion: not reached by 1200 s.

The corrected peak is 0.74% above the largest retained peer value of
114.190 m s-1 and is therefore at the edge of the ISeeSnow ensemble. The high
resolved velocity is physically consistent with this end-member benchmark:
the flow descends roughly 1500 m with Coulomb resistance but no
velocity-dependent Voellmy drag. A residual 1.30% of release volume remains
mobile at the common 1200 s ceiling, mostly as material draining the steep
part of the idealized chute; this is disclosed rather than classified as a
stopped deposit.
