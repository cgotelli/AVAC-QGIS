# AVAC–ISeeSnow intercomparison

The [2026-09-05 precision checkpoint](PRECISION_VALIDATION_20260905.md)
records the general source/plugin terrain fix, matched native regressions,
full-duration peer comparisons, and the reasons the flux correction remains
experimental.

The [Coulomb deposit-peak investigation](COULOMB_DEPOSIT_PEAK.md) separates
retained-deposit morphology from peak-over-time peer fields, tests spatial
order and a general static-interface correction, and records why neither
change is promoted as a peak reduction. Second-order Minmod is retained.

The [Voellmy near-dry source correction](VOELLMY_NEAR_DRY_STABILITY.md)
documents a reproduced drag-cancellation defect, its general source/plugin
fix and the full-duration acceptance checks. Historical V1 instability
warnings remain attached to the runs that produced them.

The [Voellmy CFL refinement](VOELLMY_CFL_REFINEMENT.md) compares the same
corrected solver at CFL targets 0.50 and 0.25. Both full-duration all-step
audits pass, but PFT and thin-layer velocity changes are mixed; defaults
remain unchanged pending a third timestep level.

The three independent notebooks reproduce the official
[ISeeSnow 1.0](https://github.com/avaframe/ISeeSnow/tree/1.0) cases:
idealized Voellmy, real-topography Voellmy, and idealized Coulomb-only flow.
The official dataset is downloaded on first use and kept outside version
control.

The general curved-terrain velocity transport correction and its regression
contract are described in
[`COULOMB_RUNOUT_TRANSPORT.md`](COULOMB_RUNOUT_TRANSPORT.md). It preserves
basal curvature friction and affine-bed behavior. Spatial peer discovery now
also includes native MoT-Voellmy `h_max`/`s_max` exports, giving 9/8/8 aligned
peers; the seven-peer limiter scores below describe the earlier selection.

Each notebook:

1. uses the supplied DEM, release polygon, 1.5 m normal release thickness, and
   prescribed friction parameters without calibration;
2. executes the current AVAC source and records its SHA-256;
3. writes peak flow thickness and velocity in the ISeeSnow standard format;
4. compares AVAC with grid-compatible submitted peer fields without shifting,
   clipping, padding, or resampling them.

The validation driver treats the constitutive equations separately. Coulomb
uses `--state-regularization-depth` (default 0.05 m), while Voellmy and
cohesive Voellmy use `--voellmy-state-regularization-depth` (default 0.10 m).
These legacy option names now specify shallow correction-flux depth scales,
independent of the 0.05 m PFV reporting threshold. The conservative normal and
transverse high-order corrections share a bounded taper on locally non-planar
terrain; stored cell-average momentum is no longer projected once per step.
Flat/affine beds and water retain their previous flux path. No friction,
curvature force, or peer parameter is retuned. See
[`SOURCE_TIMESTEP_STABILIZATION.md`](SOURCE_TIMESTEP_STABILIZATION.md) for the
method, regression evidence and limitations.
The native mass history reports moving
volume in five AVAC vertical-depth bands and uses terrain-tangent speed
reconstructed from saved bed slopes. The first band audits raw motion from the
native dry tolerance to 0.05 m; it is not counted in the practical-rest test.
Practical rest is accepted only when the volume at or above 0.05 m moving
faster than 0.01 m/s stays below 1% of the initial release for at least three
saved frames and never rebounds before the verified integration ceiling.

For the second-order `CoulombOnly` comparison, Minmod was selected by PFT field
agreement with the then-discovered seven exactly aligned peer grids; PFV is retained
as a secondary audit because it is comparatively insensitive to the limiter.
The PFT-based timestep study selects target CFL 0.25: it is closer to the
0.125 result than 0.5, beats 0.125 for all seven peer fields (and 0.5 for five),
and avoids the greater-than-twofold additional cost of 0.125. The two Voellmy
cases retain their prior target CFL 0.5.
Those results are historical: native MoT-Voellmy files named `*_h_max.asc`
and `*_s_max.asc` were previously omitted by filename discovery. They are now
included without changing their values or coordinates. The current aligned
spatial populations are 9/8/8 for IdealizedTopo/RealTopo/CoulombOnly; the two
Voellmy populations include FLO-2D, whereas Table C1 scalar statistics remain
core-group only. The Coulomb ranking population is versioned as
`aligned-eight-including-native-mot-v2`. Selection now requires at least seven
of eight paired wins and all eight leave-one-peer-out firsts, retaining the
all-but-one consensus rule. Scores must be recomputed for both alternatives
on this same eight-peer population; historical seven-peer scores are not
numerically interchangeable. This discovery correction does not retune Minmod
or alter the same-executable, backend, numerical-control or CFL gates.
That peer comparison is an explicitly disclosed, in-sample numerical-scheme
selection, not independent validation. `IdealizedTopo` and `RealTopo` retain
their prior van Leer default and were not part of this limiter sweep. An
explicit `--limiter` value overrides the default for every selected case.
The completed quasi-1D Kerswell horizontal-bed verification result is locked
through its explicit two-ghost compatibility path. The constant-slope case
uses the same path but is rejected because of its pre-existing early stop,
rather than presented as a completed result. Both checks remain separate from
curved-terrain diagnostics under `../AVAC/Curvature_normal_stress`; the
Kerswell lock is not a claim of bitwise identity for every production
five-ghost affine-grid run.

The selection rule, four-limiter results, timestep and AMR checks, curvature
finding, and flat-surface regression lock are summarized in
[`COULOMB_ONLY_INVESTIGATION.md`](COULOMB_ONLY_INVESTIGATION.md).

For regression comparison between different solver versions, run:

```text
python validation/ISeeSnow/compare_source_runs.py --baseline PATH_TO_BASELINE_RESULTS --candidate PATH_TO_CANDIDATE_RESULTS --output PATH_TO_COMPARISON
```

The comparison checks recorded executable, backend, submission and complete
official-input hashes and compares generated release fields and physical and
numerical controls. Each labelled suite must use one executable/backend pair.
Both alternatives are scored against the exact same discovered aligned peers.
PFT is primary; per-peer PFV, runout and conservation/rest diagnostics are
reported separately. Different durations or controls are rejected by default;
`--allow-protocol-differences` produces an explicitly unmatched diagnostic for
preliminary investigations. Direct file-hash authentication supports both
current-source and explicit source-snapshot/packaged runs; it does not replace
the article figure's independent packaged-runtime certification.

Generated submissions, copied inputs, reports, plots, and raw solver results
are intentionally not committed. Historical formulation and wet--dry audits
are retained under the repository's `Archive/validation-development` folder
and are not required by the public notebooks. See the
[validation suite index](../README.md) for links, run order, and requirements.

The managed solver now applies CFL acceptance to an entire AMR level before
the physical update. It prepares the level once in the legacy
`bound`--`saveqc`--`topo_update` order, evaluates every sibling patch on
scratch state, and either accepts the common timestep or repartitions the
remaining level interval and repeats the preflight. The accepted physical
advance and its observations, flux registers, and output bookkeeping run
exactly once. This is a pre-step acceptance procedure, not a post-step
rollback. Coulomb retains its selected target CFL 0.25 and Voellmy its target
CFL 0.5; the supported bundled configurations disable Richardson flagging.

The scratch preflight uses the normal Riemann wave speeds and the same signed,
capacity-aware CFL reduction as the physical flux routine. Flux corrections,
limiters, transverse solves, and flux accumulation occur after that reduction
and are therefore not repeated merely to decide whether a trial timestep is
acceptable. This is implemented in the shared GeoClaw integration source that
is compiled into both packaged AVAC and WAVE executables, so it applies to all
plugin-created cases rather than to these validation drivers only.

A forced two-level regression rejected CFL `1.2995227220576577`, retried with
`dt = 0.00048094580371044085`, and kept the maximum accepted CFL at `0.50`.
One- and four-thread runs and direct replay produced bitwise-identical output
artifacts. A safe `dt = 2e-4` control was also bitwise identical between the
pre-change and current solvers. Publication runs still reject any legacy
accepted-step CFL warning.

The optimized packaged solver retained the same three Kerswell rejection
decisions and byte-identical native and FGout solution/time files relative to
the original transactional implementation. The final packaged Kerswell run
was 15.6% faster than that implementation. Twenty-second curved-terrain smoke
runs also reproduced the established Coulomb/Minmod and Voellmy/van-Leer PFT,
PFV, mass-history, and state-frame hashes exactly, with no accepted CFL
violation. A packaged WAVE forced-retry run likewise reproduced every native
and FGout solution/time file exactly across one-thread retry, four-thread
retry, and direct-start executions. The Windows release validator opens both
embedded runtime archives and verifies their complete manifested solver,
library, backend, and Clawpack payloads before a plugin ZIP can pass.

The Windows plugin package includes the compiled AVAC and WAVE solvers and
their runtime dependencies. The plugin installs its managed runtime
automatically, so users do not need to install a compiler, Python package, or
solver dependency manually.

On Windows, keep `--results-root` short: the runner rejects a generated
topography path longer than the vendored GeoClaw `character(150)` field before
Fortran can silently truncate it.
