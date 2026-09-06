# Voellmy CFL-target refinement

Status: both 1200 s runs, independent native-field comparisons and
all-accepted-step audits are complete. The result is mixed: reducing the
CFL improves the real-terrain thin-layer pulse but is not uniformly better
for PFT or all velocities. No production source, plugin defaults, friction
parameters or curvature treatment changes in this experiment. A third CFL
level is recommended before a convergence-based default decision.

## Controlled experiment

This follows the [Voellmy source correction](VOELLMY_NEAR_DRY_STABILITY.md).
Compare its corrected CFL 0.50 cohort with CFL 0.25, using exactly the same
frozen executable `55a8c4baf0cc74d9a8ca4c582f361eb85ab01817b0d16b63e1c824611144f2e3`
and canonical runtime manifest
`26cb7b8f7805641da15cb72d29dc577c192ff1a3d45cfe24ed0a89201433c4bf`.
The earlier direct-interface static guard is present in both sides; this
is not a comparison against the unstable V1 executable.

Both IdealizedTopo and RealTopo retain the uniform 5 m grid, 1200 s horizon,
10 s saved outputs, second-order Van Leer, Voellmy depth control 0.10 m,
native dry tolerance 0.0001 m, single worker, no gauge and no AMR refinement.
The rejection ceiling remains CFL 1.0. The desired CFL, which controls the
variable timestep, is the only numerical setting changed: 0.50 to 0.25.
Prepared terrain, release and initial native states are byte-identical.

A dedicated comparison gate permits exactly that difference, including
configuration/template/plugin fields and both copies of every native
control file. Only the selected result-root paths may be relocated. It does
not waive general protocol checks or alter article/ranking acceptance pins.
Twenty-four positive/negative tests check that gate; thirteen existing CFL
diagnostic tests also pass. The full solver test suite is not rerun here.

All 2211 reused runtime records are rehashed without mismatches. The existing
source-matched Windows plugin is unchanged. Its previous QGIS functional
test remains historical evidence; this experiment is not a new plugin build
or installation. Coulomb and the flat verification cases are not rerun
because their source and controls are not changed.

## Actual temporal resolution and the original pulse

The controller's adaptive timesteps are not assumed to be exactly halved.
Native AMR1 mass timestamps independently show 195 versus 397 accepted
steps in the complete RealTopo 40-50 s interval: mean timestep 0.0512821
versus 0.0251889 s. Native timestamps are rounded, but interval endpoints
are fixed saved times; individual differences have a maximum rounding
uncertainty of 0.001 s in this interval.

The recorded horizontal-speed maxima in the 0.05-0.10 m band occur at the
same cell (168515, 363565) m and fall from 88.5193 to 36.5257 m/s. These
are global band records, not a complete local all-depth trajectory or a
matched-state replay: their times are 46.4064 and 46.5486 s and
vertical depths 0.0897617 and 0.0843225 m. The fine peak-producing timestep
is exactly recovered from consecutive binary64 observer endpoints as
0.02432517043 s; the old timestep is approximately 0.0504143 s with a
0.0005 s uncertainty from its rounded preceding endpoint.

The full-run fine maximum terrain-tangent speed within the 0.05-0.10 m band
is 47.6039 m/s at a different cell and time. It must not
be paired with the original cell as though it were that cell's tangent
response. Full-horizon maxima and field changes are reported below.

The large pulse reduction is evidence of substantial temporal sensitivity,
not convergence. Two CFL levels cannot establish a convergence rate or
exclude further change on refinement. PFT remains the primary peer metric;
filtered PFV is distinct from raw momentum/depth speed, and cannot bound
all wet native states. No physical coefficients are fitted to the peers.

The unchanged primary PFT score divides each candidate-to-peer RMSE by
that peer's median RMSE to the other peers, then takes the median of the
normalized errors. It is not the unnormalized median RMSE in metres.

## Completed idealized comparison

The individual native audits and dedicated one-change comparison gate pass.
All 121 saved native histories recompute exactly. The observation-only
run reproduces all 484 native artifacts and final PFT/PFV byte-for-byte.
It covers 9541 accepted source steps (4949 at CFL 0.50), 2874712841 interior
cell observations and 56156536 wet observations through 1200 s, with zero
non-finite states/speeds, negative depths or dry nonzero momentum.

| IdealizedTopo metric | CFL 0.50 | CFL 0.25 |
|---|---:|---:|
| Normalized median spatial PFT RMSE | 0.865517146 | 0.881405437 |
| Runout, PFT > 0.5 m (m) | 2310.05134 | 2305.08856 |
| Peak PFT (m) | 8.53216142 | 8.57759918 |
| Peak reported PFV (m/s) | 39.62553 | 39.611584 |
| All-step tangent maximum, 0.0001 < h < 0.05 m (m/s) | 18.009108 | 19.187221 |
| All-step tangent maximum, 0.05 <= h < 0.10 m (m/s) | 24.373036 | 25.790268 |
| Maximum reported accepted CFL | 0.59 | 0.31 |
| Rejected trials | 0 | 0 |
| Relative volume change | +1.6463e-9 | +7.7412e-10 |
| Sustained-rest confirmation, saved checks (s) | 590 | 620 |
| Final resolved moving volume (m3) | 70.0878642 | 109.8033100 |
| Final moving volume below 0.05 m (m3) | 146.477207 | 87.767141 |
| Final resolved maximum speed (m/s) | 0.361159 | 1.943018 |

The primary PFT error worsens by 1.84%, with all nine aligned spatial-peer
comparisons worsening. Runout changes by approximately one grid cell.
The two complete PFT fields differ by 0.0204522 m RMSE and up to 1.61704 m
locally. Shallow-band maxima increase modestly, while the bulk peak is
almost unchanged. This is not an across-the-board improvement from reducing
the timestep. The existing practical-rest threshold is 1% resolved moving
volume, sustained through subsequent saved checks; it is not literal rest
of every wet cell.

## Completed real-terrain field comparison

All 121 saved native histories and the one-control-difference gate pass.
The observer also reproduces all 484 native artifacts and actual PFT/PFV
byte-for-byte. It covers 11089 accepted source steps (5473 at CFL 0.50),
3015653550 interior cell observations and 327361408 wet observations
through 1200 s. All non-finite-state/speed, negative-depth and dry nonzero
momentum counters are zero. Counters are 64-bit; the cell totals exceeding
2^31 are not truncated.

| RealTopo metric | CFL 0.50 | CFL 0.25 |
|---|---:|---:|
| Normalized median spatial PFT RMSE | 0.907803281 | 0.894032191 |
| Unnormalized median peer PFT RMSE (m) | 0.445144346 | 0.445547686 |
| Runout, PFT > 0.5 m (m) | 2097.12447 | 2086.83777 |
| Peak PFT (m) | 21.0366978 | 21.1243499 |
| Peak reported PFV (m/s) | 67.664786 | 69.870558 |
| All-step tangent maximum, 0.0001 < h < 0.05 m (m/s) | 73.906669 | 26.275170 |
| All-step tangent maximum, 0.05 <= h < 0.10 m (m/s) | 90.971601 | 47.603853 |
| All-step tangent maximum, h >= 0.50 m (m/s) | 67.664786 | 69.870558 |
| Maximum reported accepted CFL | 0.72 | 0.33 |
| Rejected trials | 0 | 0 |
| Relative volume change | +6.0960e-10 | +4.7925e-10 |
| Sustained-rest confirmation, saved checks (s) | 520 | 610 |
| Final resolved moving volume (m3) | 231.349059 | 321.048401 |
| Final moving volume below 0.05 m (m3) | 677.194301 | 554.885632 |
| Final resolved maximum speed (m/s) | 2.831520 | 2.179737 |

The primary normalized PFT score improves 1.52%; five of eight peer
comparisons improve. INRAEaval, TRENT2D and faSavageHutterFoamGamma worsen.
The unnormalized median peer RMSE changes slightly in the opposite direction:
the two medians rank differently normalized peer errors and are not the same
statistic. Neither metric is redefined to favour this experiment.

Runout shortens by 10.29 m (about two cells), while peak reported velocity
increases 3.26%. Complete PFT fields differ by 0.0709899 m RMSE and up to
2.28975 m locally. Thus the lower raw thin-layer pulse does not imply lower
PFV, identical deposition or uniformly better agreement with peers.

## Recommendation

Keep production source and equation-specific defaults unchanged for now.
The full-field results are mixed and the original raw pulse remains strongly
timestep-sensitive. Add a third matched target, CFL 0.125, on the same 5 m
grid and both Voellmy cases before making a convergence-based default
decision. Compare successive field changes, all-step raw speeds, PFT peer
scores, runout, mass and saved rest checks. Do not select a timestep merely
because discretization error happens to improve a peer score.

These two levels cannot establish a convergence order, and a third level
may still show non-asymptotic behaviour. Keep the physical parameters and
curvature intact. Once temporal sensitivity is understood, proceed with
the separate disclosed 5 m / 2.5 m spatial study and the existing AMR/static
interface gates. No commit, push or release promotion is part of this test.

## Reproducible evidence

External workspace root:
`AVAC-QGIS-validation-runs/iseesnow-investigation/voellmy-cfl-refinement-20260906/`.

- `README.md`: exact experiment design, unchanged runtime/package identity.
- `cfl-diagnostics-tests.xml`: existing diagnostic/provenance test results.
- `morphology/compare_cfl_refinement.py`: one-parameter comparison gate.
- `morphology/test_cfl_refinement_gate.py`: positive and rejection controls.
- `morphology/comparisons/all/cfl_refinement_comparison.md`: complete
  PFT-primary two-case comparison, with field/input/control hashes in JSON.
- `morphology/full_cfl_sensitivity.md`: combined saved-field and every-step
  evidence, with each observer bound to the correct production cohort.
- `regression/`: native input preflight, frozen observer provenance and
  completed full-duration byte parity/all-step coverage and speed bands.
- `physics/timestep_refinement_design_review.md`: actual timestep and
  co-temporal pulse analysis, with explicit precision and sampling limits.
- `physics/accepted_timestep_audit_final.json`: complete native/observer
  endpoint and step-count checks, not the retained provisional snapshot.
- `figures/voellmy_cfl_refinement.pdf`: separately labelled peer-comparison
  overview, with caption and JSON provenance alongside it. Both plotted
  runs use the corrected solver; neither is the older unstable V1 cohort.

Production results are under sibling `vn-cfl25-1200`; observation-only runs
are under `vn-cfl25-audit`. Prior cohorts and figures remain unchanged.
The separate AMR/static-interface acceptance and QGIS shutdown issues are
not resolved or waived by this uniform-grid timestep experiment.
