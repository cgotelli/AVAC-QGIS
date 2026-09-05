# CoulombOnly numerical investigation

## Decision

The reproducible CoulombOnly validation configuration is:

- second-order GeoClaw update on the supplied 5 m grid;
- `state_momentum_regularization_depth = 0.05 m`;
- Minmod wave limiter;
- target CFL 0.25; and
- the existing AVAC curvature contribution to normal stress, unchanged.

PFT is the selection variable. PFV is retained only as a secondary,
selection-independent audit, as requested, because it changes much less across
the limiter candidates. The
Minmod choice is local to the CoulombOnly validation driver; it does not change
the general AVAC4QGIS template default or either Voellmy ISeeSnow case.
Because the same seven PFT fields select and then score the limiter, those
agreement metrics are in-sample numerical-scheme evidence, not an independent
validation dataset.

Generated submissions, native frames, comparison plots, and ranking files are
kept outside Git. This note records the selection contract and the numerical
results needed to interpret those artifacts.

## What caused the original warning

The pre-investigation notebook result gained 5.4521% native volume and did not
reach its reported practical-rest criterion by 1200 s. That was a numerical
result, not a Windows or Jupyter execution failure.

The investigation separated four effects:

1. The second-order wet/dry correction had to limit one conservative set of
   face fluctuations before both the cell update and AMR flux registers used
   it. The conservative relimiter removes the level-one volume creation.
2. Shallow momentum regularization had been coupled to the PFV reporting depth
   and mesh spacing. It is now an explicit physical state depth of 0.05 m,
   independent of the output-only velocity diagnostic.
3. The standard second-order limiter materially changes PFT. It therefore had
   to be selected by a disclosed, fixed PFT comparison rather than by PFV or a
   single peer.
4. Curved-coordinate transport is distinct from the existing curvature
   correction to Coulomb normal load. Both were checked separately before any
   source-term change was considered.

## PFT limiter selection

All candidates used the same 1200 s ceiling, 5 m grid, second-order update,
0.05 m state depth, disabled practical speed cap, and one executable. No field
was shifted, clipped, padded, resampled, or normalized.

The primary score is the median, across the seven exactly aligned official
peer fields, of full-grid PFT RMSE divided by that peer's median RMSE to the
other peers. Lower is better. A winner must beat the runner-up for at least six
of seven peers and remain first in every leave-one-peer-out ranking. PFT support
IoU and active-field correlation are tie-breakers only; PFV is not loaded by
the ranking program.

| limiter | normalized PFT RMSE | median PFT RMSE (m) | leave-one-out firsts | rank |
|---|---:|---:|---:|---:|
| Minmod | 1.38794 | 0.33428 | 7/7 | 1 |
| van Leer | 1.52280 | 0.38357 | 0/7 | 2 |
| MC | 1.80689 | 0.47350 | 0/7 | 3 |
| Superbee | 2.38990 | 0.64248 | 0/7 | 4 |

Minmod beat each other candidate for all seven peer-specific RMSE comparisons.

At target CFL 0.25 the Minmod/van-Leer comparison gave the same decision:
Minmod scored 1.35978 versus 1.67927, won 7/7 peer comparisons, and remained
first in 7/7 leave-one-peer-out rankings. Both CFL 0.25 candidates were then
reproduced byte-for-byte with the final frozen executable used by the
provenance-gated ranking.

A three-level Minmod timestep study then used PFT as the requested primary
criterion. CFL 0.25 scored 1.35978, CFL 0.125 scored 1.36168, and CFL 0.5
scored 1.38794. The 0.25 result beat the converged-side 0.125 result for all
seven peers and remained first in every leave-one-peer-out ranking; it beat
0.5 for five of seven peers. Successive full-field PFT RMSE decreased from
0.04480 m (0.5 versus 0.25) to 0.02507 m (0.25 versus 0.125). CFL 0.125 cost
more than twice as much as 0.25 without improving the peer score. This selects
0.25 as the scientific baseline; 0.5 remains useful only as a faster smoke
setting.

The selected CFL 0.25 PFV peak was 102.042 m/s. The seven aligned peer peaks
span 90.528--114.19 m/s, so the selected result is not a PFV magnitude outlier.
Its active velocity support is 335,625 m2, below the peer range of
390,100--631,700 m2; the remaining PFV disagreement therefore includes a
compact-support difference even though the peak lies inside the peer envelope.

The selected PFT peak (6.029 m), integral proxy (767,878 m3), and active-field
pattern remain inside or near the peer envelope. Its support above 0.01 m
(348,950 m2) is 9.1% below the smallest aligned peer. Minmod makes the result
materially closer to the complete peer set; it does not erase this residual
compact-support difference.

## Conservation and practical rest

Native volume is summed over a non-overlapping AMR hierarchy. Motion uses the
terrain-tangent speed reconstructed from horizontal momentum and saved bed
slopes. A case reaches practical rest only if moving volume is at most 1% of
the initial release for at least three saved frames and never rebounds before
the verified 1200 s ceiling.

| target CFL | relative volume change | sustained below 1% from (s) | confirmed at (s) | moving volume at 1200 s |
|---:|---:|---:|---:|---:|
| 0.5 | +4.96e-10 | 640 | 660 | 173.95 m3 (0.2322%) |
| 0.25 | -4.61e-10 | 540 | 560 | 166.25 m3 (0.2219%) |
| 0.125 | +1.02e-10 | 710 | 730 | 189.42 m3 (0.2529%) |

The mass changes are relative fractions and are at numerical roundoff for the
single-level benchmark grid. Residual motion is reported in the vertical-depth
bands `(dry tolerance, 0.05)`, `[0.05, 0.10)`, `[0.10, 0.20)`, `[0.20, 0.50)`,
and `>= 0.50 m`. The first band uses raw momentum/depth terrain-tangent speed
to expose motion inside the regularization range; it is deliberately excluded
from practical rest, which retains the 0.05 m minimum depth used for PFV.

## Curvature audit

The compiled AVAC rheology source still matches its closed frozen-cell Coulomb
solutions for planar, concave-circular, and convex-circular normal loads; the
largest measured speed error is approximately `3.1e-15 m/s`. Positive concave
curvature increases the normal load and friction, while negative convex
curvature decreases them subject to the existing contact condition. No
coefficient or sign in that production term was changed.

A separate material-point diagnostic follows a circular transition from a
34-degree slope to horizontal. It compares constrained terrain-following speed
with the speed reconstructed from AVAC's reduced horizontal Cartesian state:

| track | terrain-following exit (m/s) | reduced Cartesian exit (m/s) | gap (m/s) |
|---|---:|---:|---:|
| flat Coulomb control | 27.2588 | 27.2588 | 0 |
| constant-slope Coulomb control | 42.3440 | 42.3440 | 0 |
| circular, zero force | 80.0000 | 66.3230 | 13.6770 |
| circular, Coulomb | 78.1097 | 63.5789 | 14.5308 |

The plane controls are bit-for-bit identical. On the circle, the reduced state
omits the acceleration associated with rotation of the terrain-tangent basis;
the maximum isolated omitted term is 14.659 m/s2. This isolates a plausible
changing-basis mechanism consistent with a velocity discrepancy on curved
slopes while the curvature correction remains useful for normal stress. The
point diagnostic excludes depth, pressure, and full PDE transport, so it does
not by itself attribute the ISeeSnow peer mismatch or justify inserting a new
production source term.

## Flat-surface regression lock

Both quasi-1D drivers deliberately use the documented two-ghost compatibility
path, with the new five-ghost f-wave relimiter disabled. For the completed
Kerswell control, this locks the historical analytical verification output;
for the constant-slope case, it isolates the same path for a paired common-stop
diagnostic. Neither check is evidence that the production five-ghost relimiter
is bitwise invariant on every affine grid.

A fresh run with the final frozen executable retained the Kerswell front,
rear, final-speed, and initial-mass metrics exactly. The front RMSE remained
0.147534 m, rear RMSE 0.003112 m, final maximum speed 0.000781 m/s, and volume-
per-unit-width range 0.000615 m2. All front/rear/speed entries in the complete
40-row boundary report are identical; 18 volume-per-unit-width entries and the
derived range differ by at most `1.78e-15 m2`. The raw fields are numerically,
but not byte-for-byte,
invariant: differences begin only in 14 late-time cells at the arrested
advancing fringe, with maximum depth and velocity differences of `2.43e-17 m`
and `1.26e-18 m/s`. Those values are machine-roundoff scale and many orders
below every diagnostic threshold; the stricter byte-identity claim is
therefore intentionally not made.

In the paired constant-slope check, both the old and current executables stop
near 2.430 s with `Too many dt reductions` instead of reaching the configured
6 s; their fields through that common stop agreed. The driver now rejects that
zero-exit stop and also validates the complete output cadence during
post-processing, so partial fields cannot be presented as completed 6 s
metrics. This is a pre-existing solver issue, not a change caused by the
curved-terrain regularization or limiter selection. The Kerswell driver now
applies the same complete-cadence rule.

## Refinement status

The two-level, 2.5 m AMR run at target CFL 0.5 reduced the old volume creation
to -0.0562%, but it emitted 42 late level-two CFL warnings (maximum 1.644).
Lowering the target CFL to 0.25 removed every CFL>1 warning and reduced the
volume loss by 75.1%, to -0.0140%. It reached sustained practical rest at
1160 s, confirmed at 1180 s, with 0.5587% of the initial volume still moving.

That stability improvement did not produce PFT convergence. The AMR peer score
worsened from 1.5106 at CFL 0.5 to 1.5706 at CFL 0.25, median peer RMSE worsened
from 0.3690 m to 0.3862 m, and matching-CFL AMR-versus-5 m RMSE increased from
0.0952 m to 0.1066 m. The 2.5 m results are therefore stress tests, not clean
grid-convergence evidence and not a reason to replace the supplied 5 m grid.

## Reproduction entry points

Run a candidate without replacing publication artifacts:

```powershell
python validation/ISeeSnow/run_iseesnow_avac.py --case CoulombOnly --workers 1 `
  --spatial-order 2 --simulation-end 1200 --output-interval 10 `
  --state-regularization-depth 0.05 --limiter minmod --cfl-target 0.25 `
  --results-root C:\path\to\candidate-results
```

Rank two or more completed candidates:

```powershell
python validation/ISeeSnow/rank_coulomb_pft_candidates.py `
  minmod=C:\path\to\minmod vanleer=C:\path\to\vanleer `
  --output C:\path\to\ranking
```

Run the curvature-coordinate diagnostic:

```powershell
python validation/AVAC/Curvature_normal_stress/run_circular_track_verification.py `
  --output-root C:\path\to\curvature-audit
```
