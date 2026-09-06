# Coulomb terminal deposit investigation

Status: experimental investigation, not an accepted release. Preserve the
Minmod default, 0.05 m Coulomb depth control, prescribed friction and physical
curvature. The objective is a defensible deposition prediction, not reduction
of a scalar peak by fitting parameters or clipping the solution.

## What the full-duration fields establish

The authenticated 1200 s V1 Coulomb run has peak normal thickness 7.219827 m
at map coordinates (4105, -4250) m, reached at 69.253952 s. Its final thickness
there is 7.189417 m (99.58% retained) with exactly zero momentum. The mound
forms during approximately 60--80 s; it is not a late-growing numerical spike.
Its connected half-peak footprint has a 70 by 165 m bounding box on the
5 m grid. Main's final maximum is 5.146349 m; its time-maximum PFT is 5.441116 m.

The saved terminal-face audit covers all 121 frames and both horizontal
directions. No wet-wet adjacent free-surface increment in the checked terminal
window exceeds the Coulomb slope 0.4. The largest final longitudinal and
transverse slopes in V1 are 0.229954 and 0.134546. The bed is flat there.
This does not exclude an event between saves, but it does not support the
claim that the final mound is held above its static repose condition.

Substantially more material reaches the V1 terminal deposit. Final cells
thicker than 0.5 m hold 98.44% of the initial volume, versus 78.33% on main;
the corresponding fractions above 2 m are 84.54% and 51.48%. These are native
final-volume measurements, not integrals of peak-over-time PFT fields.

## Compare individual crests, not only a pointwise median

The eight exactly aligned peers have their own foreland PFT maxima at
different positions. Using the common, fixed foreland x >= 3500 m (all y):

| Model | Own foreland peak PFT (m) | Map x of peak (m) |
|---|---:|---:|
| TITAN2D | 3.279 | 3865 |
| faSavageHutterFoam | 5.259 | 3925 |
| Gerris | 5.829 | 4210 |
| com1DFA | 5.860 | 4120 |
| INRAEaval | 6.377 | 4600 |
| minVoellmyv2 | 7.082 | 4100 |
| TRENT2D | 7.228 | 4160 |
| MoT-Voellmy | 9.972 | 3990 |
| Experimental V1 | 7.220 | 4105 |

V1 is above six of eight peers, slightly above their upper quartile, but
inside their 3.279--9.972 m range and close to minVoellmy/TRENT. A pointwise
median profile is lower partly because those individual crests do not align.
No fields have been translated, resampled or excluded to improve this result.
The peer submissions are PFT, not final-deposit histories; they cannot supply
an observed final deposit or establish a unique correct crest height.

This limitation is consistent with the
[ISeeSnow study](https://egusphere.copernicus.org/preprints/2026/egusphere-2025-6053/),
which compares peak fields and reports substantial Coulomb runout-zone
variability. The local peer comparison remains useful, but is not ground truth.

## A real, separate static-interface defect

Compiled tests using the actual augmented Riemann solver reveal that the old
centred/minmod/span checks can suppress an unsupported plateau step. For
resting flat-bed cell averages h_L = 3 m, h_R = 6 m, dx = 5 m and mu = 0.4:

```text
pressure jump / rho = g * h_average * |h_R - h_L| = 132.435
available interface static resistance / rho = mu * g * h_average * dx = 88.29
```

The old guard produces zero waves even though the force ratio is 1.5. The
candidate additionally requires the actual adjacent head jump to satisfy the
existing interface yield bound. Other static checks, cohesion strength,
friction coefficients, water equations and physical curvature are unchanged.
The condition also excludes alternating-cell false equilibria without fitting
a velocity or curvature tolerance.

Implementation: [rpn2_geoclaw.f](../../avac-main/src/AVAC/rpn2_geoclaw.f).
The new [coupled regression tests](../tests/test_static_interface_balance.py)
exercise actual pre-step kernels, Riemann/transverse solvers, conservative flux
update and source ordering, not a sentinel for the Riemann solve. Synthetic
red/green evidence justifies this general correction, but is not proof that
it caused the observed Coulomb crest.

## Controlled transport comparison

The completed 120 s first-order control uses the same frozen V1 executable,
backend, exact terrain, initial state, friction, depth control and CFL 0.25.
The only native-control change is spatial order 2 to 1. All 13 native
mass/motion rows are independently recomputed.

| Metric | Second-order Minmod | First-order diagnostic |
|---|---:|---:|
| Peak PFT (m) | 7.219827 | 6.909329 |
| Final retained maximum at 120 s (m) | 7.189417 | 6.727306 |
| Runout, existing 0.5 m PFT criterion (m) | 3150.041 | 3155.041 |
| Normalized median PFT peer error (lower is better) | 0.911514 | 0.915736 |
| Median raw PFT peer RMSE (m) | 0.243247 | 0.265468 |
| Peak PFV (m/s) | 110.964950 | 103.901780 |

The first-order result lowers the scalar crest, but slightly worsens the
primary normalized score (0.463%) and increases the raw median error by
9.14%. Its PFT field differs by 28.56% in relative L2; its connected
half-peak footprint changes from 70 by 165 to 95 by 105 m. Both short runs
meet the practical-rest onset/confirmation criterion at 80/100 s through
their 120 s ceiling, with no rejected trials. This is a substantial
transport-discretization effect, not evidence of a more accurate solution.
Do not select first order solely to reduce peak thickness; retain the
second-order Minmod default.

An early inspection reported a 6.16 m first-order local patch peak at 100 s.
The whole-domain stitched analysis supersedes that local observation; the
global retained maximum is the 6.727306 m value above at 120 s.

## Matched static-guard control and flat regressions

The separately labelled 120 s Coulomb run of the new direct-head guard has
the same backend, prepared terrain, initial state and launch controls as
the frozen V1 second-order control. All 13 saved native frames (52 binary,
auxiliary, geometry and time artifacts), the accumulated maximum-field
file, and the PFT/PFV submission files are byte-identical. Independently
recomputed native mass and motion histories agree as well. The retained
crest remains 7.189417 m, with the same 80/100 s practical-rest onset and
confirmation and maximum accepted CFL 0.96 (target 0.25; acceptance limit
1.0).

Thus the demonstrated static-interface defect does **not** explain this
deposit's formation in the checked trajectory. This is not a new 1200 s
run or a claim of identity at every internal timestep. The original
full-duration publication data remain unchanged.

Matched native flat controls give:

| Control | Saved frames | Field preservation | Maximum depth difference (m) |
|---|---:|---|---:|
| Uniform sloping Coulomb, 6 s | 61 | Not exact | 0.005685 |
| Horizontal Kerswell AMR, 10 s | 41 | Not exact | 0.003112 |
| Uniform WRR water, 5 s | 101 | Exact, including 100 fixed-grid frames | 0 |

The two granular final fronts are unchanged, but analytical error changes
are mixed. The Coulomb mass range increases from 0.00017194 to 0.00036291
m2/m; Kerswell's final rear moves one fine cell (0.0025 m) farther from
theory even though its moving exact-state rear RMSE improves. Terrain and
curvature-mask fields are identical. CFL maxima and rejected-trial counts
are unchanged in all three controls.

The strict unchanged-flat-state gate is therefore **not passed**. The
general guard correction and its source-matched plugin remain isolated
experimental artifacts, not a promoted deposit-peak improvement. These
controls also do not replace a complete ISeeSnow regression for that
changed solver.

## Evidence and implementation status

External workspace evidence is under
`AVAC-QGIS-validation-runs/iseesnow-investigation/deposit-peak-20260905/`:

- `morphology/coulomb_deposit_morphology.md`, PNG/PDF and JSON: full-duration
  retained-deposit morphology, own-peak peers and saved-face audit.
- `physics/static_deposit_balance_review.md`: derivation and actual compiled
  false-equilibrium controls.
- `regression/coupled-head-guard-v1/`: coupled frozen-old/current evidence.
- `physics/flat-regressions/face_guard_flat_controls.md`: completed matched
  flat native controls, with full input and field authentication in JSON.
- `morphology/o1-control/`: spatial-order sensitivity comparison.
- `plugin/`: source-matched experimental Windows bundle, runtime and licenses.

The new candidate's 40 actual coupled tests pass. The broader selection
gives 565 passed, 5 skipped, 1 deselected and one deliberate source-acceptance
pin failure for the changed Riemann source. That acceptance hash is not
silently updated: implementation tests do not confer scientific acceptance.
The licensed experimental Windows ZIP passes release validation and contains
the exact tested solver, backend and managed dependencies. It is not
promoted, and no new QGIS GUI-workflow pass is claimed for this checkpoint.

The prior V1 Voellmy near-dry failures and the AMR terrain-integration issue
remain independent release gates; this focused deposit work does not resolve
or waive them.

Subsequent work: [Voellmy near-dry source correction](VOELLMY_NEAR_DRY_STABILITY.md)
identifies a separate discarded-drag defect and documents corrected
full-duration, all-accepted-step evidence. That new candidate has its own
source/runtime identity; it does not retroactively clear the V1 runs or
waive the flat-state and AMR gates documented here.

## Decision and next experiment

Keep the user's preferred V1 result as the research baseline, with
second-order Minmod, the 0.05 m Coulomb control, prescribed friction and
physical curvature unchanged. The present evidence does not justify
forcing its terminal crest downward or promoting the new static guard as
a crest fix.

The next useful test is matched spatial convergence of arrival, spreading
and deposition on uniform 5 m and 2.5 m grids, with a finer grid only if
necessary. Keep AMR disabled for this first comparison so its known
terrain-integration defect is not mixed into the deposition experiment.
Use the same physical terrain and release definition, explicitly quantify
any input-discretization differences, keep the CFL protocol consistent,
and compare on a disclosed common grid without shifting peer fields.
Track the retained crest and footprint as well as the primary PFT error,
runout, native mass, raw thin-flow motion and sustained practical rest.
This separates a grid-dependent concentration from a stable consequence
of the model before changing its constitutive or geometric closure.
