# Terrain-precision validation checkpoint — 2026-09-05

The precision correction is integrated in the main source and plugin. The
experimental conservative flux correction remains separate; it is **not**
promoted merely because automated tests or individual peer comparisons pass.

## Changes in this checkpoint

- Preserve binary64 terrain elevations in the general plugin writer and shared
  validation writer. The standalone Coulomb verification writer delegates to
  that shared implementation.
- Preserve the existing release/initial-state serialization, geometry
  registration, nodata handling, friction coefficients, physical curvature,
  Minmod Coulomb limiter and separate 0.05/0.10 m numerical depth controls.
- Record generated terrain, binary initial state and native controls before
  each ISeeSnow run; reject changed inputs before publishing results. Require
  all 17 managed-backend control files as well as authenticate extra controls,
  so deleting a file and its manifest record cannot pass as a complete input set.
- Reauthenticate these generated-input records during article-figure
  generation. Historical runs without pre-run records are explicitly not
  assigned invented generated-input provenance. Existing full-duration,
  physical/numerical protocol and managed-runtime gates remain unchanged.

See [the implementation and regression contract](../../docs/TERRAIN_SERIALIZATION.md).

## Verification findings

Matched source controls below use the same full-precision inputs with the
AMR-only main executable `16cdba0f...` and experimental V1 `831f9835...`.
Physical/numerical controls are identical; auxiliary-count metadata differs
where V1 needs its third component.

| Control | Result |
|---|---|
| Uniform affine Coulomb, 6 s | All 61 native conserved fields and pre-existing auxiliaries, including ghosts, exactly match. |
| Kerswell horizontal-bed AMR, 10 s | All 41 native and 40 fixed-grid frames exactly match in physical fields. |
| Uniform WRR water, 5 s | All 101 native and 100 fixed-grid frames exactly match. |
| Original Coulomb AMR, 6 s | Both complete, but **not** an exact flat-state non-regression. |
| Original WRR AMR, 5 s | All 704 saved native/fixed-grid files exactly match; 101 native and 100 fixed-grid frames complete. |

The original Coulomb AMR run now completes with the precision correction.
Previously its lower-precision preparation stalled near 1.13 s. However, the
source comparison on the new inputs still changes the front RMSE from
1.330175 to 0.191368 m; the final front is 16.039063 versus 17.912187 m
(analytic 17.775987 m). Rear RMSE slightly worsens, and the filtered final
maximum speed rises from 0.001332 to 0.123667 m/s. The improved front is not
an all-metric or exact-state pass.

### Remaining AMR geometry mechanism

The native binary64 bed and physical patch geometries match between solvers.
The first saved positive level-three nonplanarity mask is at 1.0 s on an
intended affine plane; the first saved conserved-state difference is at 1.1 s.
The output interval does not identify the exact onset between saved frames.

A separate compiled probe reproduces the saved bed exactly using the frozen
terrain integrator and the same global-coordinate cell edges/nominal-area
normalization as `setaux`. It also reproduces the false mask. This is native
terrain-integration roundoff, not a changed DEM or proof that physical
curvature should be disabled. Actual-area normalization removes most but not
all flags. A constant-partition-integral normalization removes them in the
sampled patches, but remains a **diagnostic**, not a production change or a
validated general algorithm for multiple topofiles, incomplete coverage,
spherical grids and WAVE.

The compiled old source changes shallow momentum even at `dt=0` on the
affected saved front; the normalized/analytic plane removes this false-gate
effect. This demonstrates a mechanism without attributing the entire final
front difference to one observation.

The completed WRR AMR pair has front/rear RMSE 0.059859747 / 0.071935102 m,
zero accepted CFL violations and 141 identical rejected trials. The separate
same-solver comparison against its earlier 12-digit terrain slightly improves
front/rear errors but raises retries from 82 to 141 and slightly increases the
mass range. Greater terrain precision is not a guarantee of lower adaptive
workload. Runtime comparisons across different concurrent workloads are not
controlled performance benchmarks.

Reproducible integration and zero-duration source probes are documented in
`runout-investigation-76844b9/amr-precision-forensics/amr_terrain_integration_report.md`.
The integrator exactly reproduces all native bed bits and masks on 34 sampled
patches. Constant-partition normalization is not implemented in either
production source in this checkpoint.

## ISeeSnow: distinguish full results from short diagnostics

The official idealized/Coulomb terrain values are unchanged by the new text
precision; the repeated 120 s Coulomb runs reproduce every saved native frame
and both peak-field files from the earlier V1 probes exactly.

Halving Coulomb CFL from 0.25 to 0.125 still changes the full PFT field by
5.379% relative L2. Both give 3150.041 m runout and practical-rest onset /
confirmation at 80/100 s **through the 120 s diagnostic ceiling**. This is not
a convergence claim or a substitute for the new full-duration histories.

RealTopo 120 s results at CFL 0.5 still contain 153 late retries, but the new
saved thin-band states do **not** reproduce the old 888 m/s observation.
CFL 0.25 has no late retries through 120 s, yet begins retrying later in the
full run. Neither accepted CFL nor a short clean prefix proves convergence.

Completed full 1200 s main and V1 cohorts, plus a separate finer-CFL Voellmy
check, are assessed with exactly aligned spatial peers (9/8/8); scalar Table C1
comparisons use their distinct 11/10/11 populations. Current completed
IdealizedTopo results show a V1 PFT score regression from 0.967689 to
1.013786 (+4.76%), unchanged runout and earlier practical rest. Only 1/9
individual peer PFT errors improves. This is a reason to keep V1 experimental,
not hide the less favorable case behind the Coulomb result.

All three main-source runs have now completed 1200 s and passed the original
article provenance/protocol gate with the trusted main runtime. Main
IdealizedTopo and Coulomb PFT/PFV fields reproduce the previous full-suite
results exactly. RealTopo PFT score changes only from 0.966457 to 0.966167;
its global PFV changes from 82.794 to 81.545 m/s, so this is not byte identity
or a guarantee that every local velocity is unchanged.

The completed full-duration Coulomb comparison retains an 8.04% aggregate
PFT-score improvement with V1 (0.991161 to 0.911514; 6/8 individual peer RMSEs
improve). Runout is 3130.041 versus 3150.041 m; the Table C1 median is
3144.30 m. Practical-rest onset/confirmation changes from 620/640 to 80/100 s,
verified through the complete 1200 s history. However, peak PFT rises from
5.441 to 7.220 m, the terminal crest is high relative to the local peer median,
and median support IoU worsens from about 0.841 to 0.813. Global PFV rises from
102.126 to 110.965 m/s. These less favorable outcomes remain visible.

The full IdealizedTopo CFL-halving check does not rescue the V1 default:
PFT score worsens further to 1.023854, about 5.8% above main. Retrying decreases
from 1811 to 502 trials, but the finer run fails its retrospective
practical-rest test owing to late reactivation. Lower CFL is not a substitute
for validating the numerical formulation.
Its saved near-dry audit still reaches 2315.413 m/s at 1150 s and vertical
depth 0.000101883008 m: CFL halving does not eliminate the accepted-state
failure.

Fresh full-duration figures (PNG, PDF and provenance JSON) are in
`p17-figures-main/iseesnow_intercomparison.*`,
`p17-figures-v1/iseesnow_intercomparison.*` and
`p17-coulomb-1200-figure/coulomb_runout_diagnosis.*`. The Coulomb figure
explicitly labels the flux correction experimental, not an accepted release.
The full V1 RealTopo run improves aggregate PFT score from 0.966167 to
0.936822 (3.04%; 7/8 individual peer RMSEs improve). Runout changes from
2093.886 to 2097.124 m and reported PFV from 81.545 to 67.657 m/s. Neither
run reaches practical rest. V1 has 4280 rejected trials (maximum trial CFL
26978.26), accepted CFL no greater than 1.0, and zero recorded accepted CFL
violations. Relative volume change is 4.108e-10.

**An accepted-state failure prevents promotion independently of those
scores.** At saved time 370 s, V1 RealTopo contains a near-dry cell at
(168355, 364105) m with vertical depth 0.000113499744 m and terrain-tangent
speed 75845.697 m/s. An independent direct native read confirms
`(h, hu, hv) = (0.00011349974374752492, -0.04968072101473808, -8.248089790344238)`;
the horizontal speed alone is 72671.877 m/s. This is a saved accepted state,
not a rejected trial. It lies below the 0.05 m reported-PFV depth threshold,
so it does not contradict the reported 67.657 m/s PFV. Main's largest speed
over the corresponding sub-0.05 m band in all 121 saved frames is 5.002 m/s.
These are saved-frame observations, not maxima over every accepted step;
the full peak-field PFV does not supply co-temporal depth at its own maximum.
Evidence: `p17-full-authentication/*RealTopo-speed-bands.json`.

The expanded 121-frame audit also finds 7077.080 m/s in V1 IdealizedTopo at
350 s, vertical depth 0.000108713713 m; main's maximum in that same depth
band is 9.079 m/s. Coulomb's sub-0.05 m maxima are 75.738 m/s on main and
118.217 m/s on V1. No comparable thousand-metre-per-second Coulomb state was
found among its saved frames, but that does not certify all-step stability
or remove its independently measured timestep sensitivity.

The frozen source's reported CFL is based on incoming normal Riemann wave
speeds; it is not a final-state check after flux, positivity and source
updates. This explains why the observations are compatible, not which
suboperator produced the bad state. A post-update CFL check alone is not a
demonstrated cure: an arbitrarily small timestep can accommodate an
unphysical speed. The exact source references, independent native read and
whole-step rollback requirements are documented in
`p17-full-authentication/accepted_shallow_state_cfl_scope.md`.

The finer RealTopo check also completes all 1200 s with independently
recomputed native history and authenticated controls. At CFL 0.25 its PFT
score is 0.911508, 2.70% lower than V1 at CFL 0.5, with runout 2088.550 m and
reported PFV 69.865 m/s. It still has no practical rest and increases retries
from 4280 to 4950 (maximum rejected CFL 1233.806); recorded accepted CFL
remains at most 1.0 and relative volume change is -6.858e-11. More importantly,
it retains an accepted saved near-dry speed of 13982.008 m/s at 500 s,
vertical depth 0.000129728520 m. Halving the target CFL reduces the observed
extreme but does not remove the failure.

All eight full-duration runs are complete: three main, three default V1 and
the two separately labelled finer-CFL Voellmy diagnostics. No diagnostic
replaces the default-CFL article protocol. The full same-source CFL audit,
its limitations and a saved thin-band versus depth-filtered velocity figure
are in `p17-full-cfl-diagnostic/full_cfl_diagnostic.md`. The default matched
peer comparison and figure companion are in
`p17-full-comparison/full_suite_companion.md`.

## Windows delivery and evidence

The final automated selection gives 526 passed / 5 skipped / 1 deselected
in the candidate checkout. Main gives 438 passed / 5 skipped / 1 deselected
and one existing notebook-output-policy failure: the user's saved notebook
results were deliberately preserved. The selection excludes the established
Windows-incompatible session module, the optional lake-depth module and the
pre-existing WAVE partially intersected shoreline-mask test. The latter was
also reproduced independently on main and does not call a terrain writer.
All 28 focused serialization, native-classifier and grid-reader tests pass;
the strengthened generated-input/figure-authentication module passes all
41 tests in each checkout. The broader candidate selection explicitly puts
that checkout's root and `validation` directory on `PYTHONPATH`: the reused
main virtual environment otherwise selects its editable main package in one
notebook-path test. No production change was needed for that test invocation.
These code tests do not replace the scientific gates above.

The corrected main plugin ZIP and separate experimental ZIP passed release
validation and isolated QGIS 3.40.11 normal-workflow tests. Both automatically
install AVAC/WAVE runtimes and dependencies; no manual dependency installation
or normal-profile modification was required. The known offscreen QGIS native
shutdown issue recurred **after** functional PASS, so this is not a clean
application-exit claim.

External evidence is under
`AVAC-QGIS-validation-runs/iseesnow-investigation/`:

- `p17-plugin-main/`, `p17-plugin-v1/`: exact ZIPs and source parity.
- `p17-staged-input-audit/`: input equivalence and full-precision roundtrip.
- `runout-investigation-76844b9/p17-flat-suite/`: native verification results.
- `p17-real-cfl-audit/`: independently authenticated RealTopo short-CFL audit.
- `runout-physics-audit/p17-coulomb-precision/`: Coulomb short-CFL evidence.
- `p17-main-1200/`, `p17-v1-1200/`, `p17-r025-1200/`: frozen full-run cohorts.
- `p17-full-authentication/`: full histories and exact runtime/input checks.

Existing accepted article figures and the user's executed notebooks are
preserved. New figures are generated separately with explicit main versus
experimental labels.

## Decision and next step

Keep the general terrain-serialization and input-authentication corrections
in source and plugin preparation. Do not promote the experimental flux
operator to the shared solver on the strength of Coulomb's better aggregate
PFT score: IdealizedTopo regresses, RealTopo has an unphysical accepted
near-dry state, and the original Coulomb AMR flat-state gate remains
unsatisfied. Preserve the existing Voellmy formulation while evaluating
Coulomb-specific changes separately.

The next isolated change should address terrain-quadrature conditioning and
consistent integration weights, without retuning the curvature tolerance,
friction or benchmark inputs. Validate constant and affine beds (including
oblique slopes and large datums), curved cell averages, multiple/overlapping
topofiles, partial/nodata coverage and relevant spherical/time-dependent
paths. Then repeat the original Coulomb AMR control, water/WAVE and
lake-at-rest/conservation regressions before matched full-duration curved
comparisons. Promotion also needs PFT-first peer evidence, full rest/mass
histories, velocity with co-temporal depth where needed, and timestep
sensitivity rather than accepted CFL alone. Coulomb and Voellmy policy
decisions must remain separate; no friction or physical curvature change is
justified by the current evidence.

Before any experimental Voellmy promotion, independently reproduce the
affected front stage by stage (normal/high-order/transverse fluxes, positivity,
terrain transport and constitutive source) and compare full versus subdivided
steps. Do not add a speed cap or discard a thin layer to hide this failure.
Any eventual full-update accept/retry scheme must also defer or restore
observations and AMR bookkeeping, not only the conserved state array.
