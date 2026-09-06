# Voellmy near-dry source correction

Status: the reproduced Voellmy near-dry failure is corrected in this
candidate and does not recur in either 1200 s all-accepted-step audit.
The full Coulomb regression also preserves the V1 native fields exactly.
This is not general release
promotion, parameter calibration or a reporting-threshold change. The
earlier V1 instability warning remains valid for its archived runs/figures.

## Demonstrated defect and native producing step

The old `src2` caller discarded a zero from its exact frozen friction update
whenever the bed slope exceeded static yield. It retained the entire incoming
momentum, including the part that Voellmy turbulent drag should remove. Since
the drag coefficient is proportional to `1/h`, this can bypass the strongest
drag precisely in a near-dry layer. This is a caller-policy defect, not a
negative turbulent-drag coefficient or an instruction to remove curvature.

An observation-only build from frozen V1 (`831f9835...`) reproduces the
RealTopo startup. At cell (169400, 362395) m, the accepted step beginning at
0.01 s has duration 0.28996263635 s and incoming patch CFL 0.362855876:

| Stage | Vertical depth (m) | Horizontal speed (m/s) |
|---|---:|---:|
| Before flux | 0.000503091 | 4.6853 |
| After flux | 0.000156085 | 1744.362 |
| After terrain transport | 0.000156085 | 31778.257 |
| After basal source, old fallback | 0.000156085 | 31778.257 |

After terrain transport, the frozen scalar coefficients are approximately
`a=4.33504815`, `b=52.45960195`. The integrated source speed is zero, but
the old fallback preserves the incoming momentum. All 12 native artifacts
at 0, 10 and 20 s and all six rejected-trial records match the uninstrumented
V1 prefix exactly. The diagnostic ceiling is 20 s rather than 1200 s; output
cadence, terrain, release and physical/numerical controls are unchanged.
Thus the trace observes the actual production trajectory,
not a restart from rounded binary32 output or a different older solver.

There are three distinct operations here: fluxes create the first large
momentum/depth ratio, the extrapolated tangent transport amplifies it, and
the fallback keeps it despite the calculated drag. Fixing the last defect
does not establish that every intermediate split state is accurate or that
the complete spatial discretization has converged.

## General source/plugin change

[src2.f90](../../avac-main/src/AVAC/src2.f90) now honors a zero result for
Voellmy and cohesive Voellmy (`imodel_rh >= 2`) even on a super-yield bed.
Zero momentum needs no assigned direction. It is a transient source-substep
stop, not a declaration of permanent static equilibrium: the next Riemann
update still supplies bed/pressure driving.

The exact source formula, friction coefficients and altitude zones, physical
curvature/contact treatment, terrain transport, limiter selection, Coulomb
0.05 m and Voellmy 0.10 m controls, solver dry tolerance, PFV reporting depth,
and CFL protocol are unchanged. Pure Coulomb retains its prior stopping
compatibility path; water retains the existing Manning path. This applies to
all user cases using these constitutive laws, not a benchmark coordinate or
a fitted velocity cap.

That deliberate Coulomb compatibility scope has a limitation: the callers
do not have an exactly uniform Voellmy-to-Coulomb limit as `xi -> infinity`
on the inherited super-yield stopping branch. This work does not silently
approve that old pure-Coulomb policy or claim to fix it.

The flow-parallel geometric source and Voellmy drag remain those described
in the [Hergarten and Robl formulation](https://nhess.copernicus.org/articles/15/671/2015/),
with the existing separate terrain-basis transport. No model closure is
retuned to improve a peer score.

## Compiled tests and frozen executable

The new [production source tests](../tests/test_voellmy_source_stopping.py)
compile the actual `src2` and rheology module. They cover both Voellmy laws,
altitude zones, cohesion, just-wet depths, very large incoming speed, source
subdivision, non-stopping and uphill correction, zero-duration identity,
and the unchanged Coulomb/water branches.

- Frozen old source: 14 failing stopping tests and 10 passing controls.
- Corrected source: all 24 pass.
- Broader selected suite: 589 pass, 5 skip, 1 deselected, with one existing
  source-acceptance-pin failure for the separate static-interface experiment.
  Its Riemann hash has not been updated to conceal that unaccepted change.

Frozen candidate runtime: `vn-rt-stop`, executable SHA-256
`55a8c4baf0cc74d9a8ca4c582f361eb85ab01817b0d16b63e1c824611144f2e3`.
Canonical manifest SHA-256:
`26cb7b8f7805641da15cb72d29dc577c192ff1a3d45cfe24ed0a89201433c4bf`.
All 2211 manifest files are authenticated. Against the preceding direct-head
runtime `8a646f61...`, only `src2.f90` and the executable copies change;
the backend, numerical controls, libraries and other compiled sources match.
The runtime includes its Windows DLL dependencies and licenses for automatic
plugin-managed installation.

Comparisons against the older full-duration `831f9835...` V1 cohort must
disclose the preceding, separate direct-head static guard as well as this
Voellmy change. Native controls against `8a646f61...` isolate the new change.

## Completed native preservation and plugin checks

Matched controls against the preceding direct-head runtime isolate this
Voellmy source change. All prepared terrain/release and numerical controls
match. Uniform sloping Coulomb (6 s, 61 native frames) and uniform WRR water
(5 s, 101 frames) preserve all native fields, including ghost cells,
bit-for-bit. Kerswell horizontal-bed AMR (10 s, 41 frames) has a maximum
depth difference of 1.150745e-15 m; its terrain and curvature mask are exact.
Every reported analytical error, final boundary, mass statistic and CFL
history is identical in all three pairs. Kerswell is a roundoff-scale
preservation result, not literal bitwise identity. The distinct original
sloping Coulomb AMR protocol is not rerun by these controls.

The Windows ZIP `2a0a78ad...` passes release validation and a new normal-dock
Voellmy workflow in QGIS 3.40.11 with a fresh isolated runtime directory.
Both AVAC and WAVE install automatically; the managed Clawpack import and
all runtime manifest records are authenticated. The 7 s Voellmy test writes
all four native/fixed-grid frames with native exit code zero. No compiler,
Python package or DLL is installed manually, and the normal user profile
is untouched. The existing offscreen QGIS native crash occurs after the
functional PASS; this is not a clean application-exit claim.

## Full-duration ISeeSnow evidence

The two corrected Voellmy runs have completed 1200 s. All 121 saved states
have independently recomputed native histories, and both cases pass strict
input, protocol, runtime and peer-provenance checks without an override.
The full Coulomb run and both Voellmy all-step audits are also complete.
Successful incoming-wave CFL checks, filtered PFV, or saved outputs alone
are not sufficient evidence about unsaved post-source transients.

| Case | V1 PFT error score | Corrected PFT error score | Spatial peer agreement | Runout, both runs (m) | V1 / corrected rejected trials |
|---|---:|---:|---:|---:|---:|
| IdealizedTopo | 1.01378568 | 0.865517146 | 9 / 9 improved | 2310.05134 | 1811 / 0 |
| RealTopo | 0.936821743 | 0.907803281 | 6 / 8 improved | 2097.12447 | 4280 / 0 |
| CoulombOnly | 0.911514348 | 0.911514348 | 8 / 8 unchanged | 3150.04063 | 0 / 0 |

The PFT score is normalized median spatial RMSE, lower is better. RealTopo
agreement with FLO2D and MoT is slightly worse; improvement in the median
is not an assertion that every peer improves. PFV peaks are nearly unchanged
(39.6563 to 39.6255 m/s and 67.6569 to 67.6648 m/s). Relative volume changes
are +1.6463e-9 and +6.0960e-10. The existing practical-rest criterion is
confirmed at 590 and 520 s and remains satisfied at subsequent saved 10 s
checks through 1200 s. It does
not mean zero velocity everywhere: resolved moving volume at 1200 s is
70.09 and 231.35 m3, with a further 146.48 and 677.19 m3 moving below 0.05 m.

CoulombOnly preserves all 484 saved native a/t/q/b artifacts through 1200 s,
plus its final PFT and PFV, byte-for-byte against V1. Its peak PFT remains
7.21983 m, PFV 110.96495 m/s, and runout 3150.04063 m. Practical rest is
confirmed at the saved 100 s check and subsequent saved checks through
1200 s. Relative volume change is -6.43377e-10; resolved moving volume is
zero at 1200 s, with 0.22310 m3 still moving below 0.05 m. Its native thin
motion has not been suppressed by imposing Voellmy's stopping policy.
The separate 0-120 s pair is also byte-exact against the immediately
preceding direct-head runtime, isolating the present source correction.

For each case the observation-only build reproduces all 484 native artifacts,
PFT/PFV, controls and rejection logs exactly. Counts equal the native
patch/cell counts times the accepted steps; actual source coverage ends at
1200 s. Across both audits, negative depths, non-finite states/speeds and
dry nonzero momentum are all absent.

| Case | Accepted source-step starts | Patch calls | Interior cell observations | Wet cell observations |
|---|---:|---:|---:|---:|
| IdealizedTopo | 4949 | 1266944 | 1491138649 | 29270547 |
| RealTopo | 5473 | 1401088 | 1488382350 | 162454615 |

The old saved-state maxima and new all-step maxima have different sampling
scope: the new check also includes the states between 10 s outputs.

| Case | V1 saved near-dry tangent maximum (m/s) | Corrected all-step near-dry tangent maximum (m/s) | Simultaneous vertical depth (m) | Time (s) |
|---|---:|---:|---:|---:|
| IdealizedTopo | 7077.08 | 18.0091 | 0.0497836 | 51.6014 |
| RealTopo | 75845.70 | 73.9067 | 0.0369247 | 44.8617 |

Here near-dry means native dry tolerance < h < 0.05 m. The RealTopo maximum
over **all** wet depths is 90.9716 m/s at h=0.0897617 m and t=46.4064 s;
its horizontal speed is 88.5193 m/s. This remaining thin-layer transient is
not hidden by reporting only the 67.6648 m/s PFV or the 19.0946 m/s saved
near-dry maximum. It is a useful target for the next timestep-convergence
check, not evidence of the former thousand-to-tens-of-thousands m/s failure.

These audits use **unfiltered** momentum/depth velocities. The unchanged PFV
diagnostic excludes vertical depth at or below 0.05 m and desingularizes
velocity below 0.20 m. Its peak is therefore not a bound on all wet native
states. The tangent metric uses native binary64 central bed derivatives;
horizontal maxima are recorded separately and are geometry-independent.
The all-step audit concerns accepted post-source states, not a bound on
provisional flux/geometry states or a temporal/spatial convergence proof.

External reproducible evidence is under
`AVAC-QGIS-validation-runs/iseesnow-investigation/voellmy-near-dry-20260906/`:

- `physics/voellmy_source_stopping_review.md`: source-only derivation,
  synthetic red/green evidence and compatibility limits.
- `regression/real-startup20-audit-v2/stage_audit.md`: authenticated producing
  step and observation-only source/build provenance.
- `runtime/source_parity.json`: complete packaged source/runtime identity.
- `physics/native_preservation.md`: completed, matched flat controls.
- `plugin/QGIS_WORKFLOW.json`: actual fresh-profile functional test, source
  identities and the separate native QGIS shutdown caveat.
- `morphology/near_dry_evidence.md`: prior full-duration saved-state context.
- `morphology/corrected_full1200_comparison.md`: completed corrected-case
  native histories, spatial peer scores, runout, conservation and rest.
- `regression/IdealizedTopo-all-steps/all_steps_audit.md`: authenticated
  all-accepted-step coverage and unfiltered depth-band speed maxima.
- `regression/RealTopo-all-steps/all_steps_audit.md`: the equivalent complete
  real-terrain audit, including its larger between-output thin-layer peak.

Existing article figures and full-run outputs are preserved as historical
evidence. The corrected overview is a separate `figures/iseesnow_voellmy_fix_candidate.pdf`
under the evidence directory, with the new candidate and prior unstable
Voellmy research baseline explicitly distinguished. It is not substituted
under an old label or runtime identity.

## Decision and next validation step

The source defect is fixed and the specific old Voellmy warning is resolved
for this authenticated candidate cohort. Neither clean incoming-wave CFL
logs nor filtered PFV alone was used to reach that conclusion. All-accepted-
step observations establish that the old extreme committed-state failure
does not recur in these runs; they do not establish global stability for
arbitrary inputs or accuracy of every provisional split state.

Keep the candidate isolated while the separate static-interface flat-state
acceptance gate, sloping-bed AMR terrain integration and offscreen QGIS
shutdown issue remain open. The subsequent matched
[CFL-target refinement](VOELLMY_CFL_REFINEMENT.md) is now complete: it keeps
terrain/release and physical parameters fixed and retains the all-step raw
velocity audit and PFT/runout metrics. Its mixed outcome motivates a third
CFL level before deciding defaults, followed by a disclosed uniform-grid
5 m / 2.5 m comparison before further transport or constitutive changes.
Keep the underlying terrain/release interpolants fixed or disclose their
changes, so input-discretization differences are not mistaken for solver
mesh convergence.
