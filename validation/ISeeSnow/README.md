# AVAC–ISeeSnow intercomparison

The three independent notebooks reproduce the official
[ISeeSnow 1.0](https://github.com/avaframe/ISeeSnow/tree/1.0) cases:
idealized Voellmy, real-topography Voellmy, and idealized Coulomb-only flow.
The official dataset is downloaded on first use and kept outside version
control.

Each notebook:

1. uses the supplied DEM, release polygon, 1.5 m normal release thickness, and
   prescribed friction parameters without calibration;
2. executes the current AVAC source and records its SHA-256;
3. writes peak flow thickness and velocity in the ISeeSnow standard format;
4. compares AVAC with grid-compatible submitted peer fields without shifting,
   clipping, padding, or resampling them.

For Coulomb, the validation driver exposes the shallow-state momentum
regularization as a physical depth (`--state-regularization-depth`, default
0.05 m) independently of the 0.05 m PFV reporting threshold. Voellmy retains
its established state update and ignores this Coulomb-only control. The native
mass history reports moving
volume in five AVAC vertical-depth bands and uses terrain-tangent speed
reconstructed from saved bed slopes. The first band audits raw motion from the
native dry tolerance to 0.05 m; it is not counted in the practical-rest test.
Practical rest is accepted only when the volume at or above 0.05 m moving
faster than 0.01 m/s stays below 1% of the initial release for at least three
saved frames and never rebounds before the verified integration ceiling.

For the second-order `CoulombOnly` comparison, Minmod was selected by PFT field
agreement with the complete set of exactly aligned peer grids; PFV is retained
as a secondary audit because it is comparatively insensitive to the limiter.
The PFT-based timestep study selects target CFL 0.25: it is closer to the
0.125 result than 0.5, beats 0.125 for all seven peer fields (and 0.5 for five),
and avoids the greater-than-twofold additional cost of 0.125. The two Voellmy
cases retain their prior target CFL 0.5.
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

Generated submissions, copied inputs, reports, plots, and raw solver results
are intentionally not committed. Historical formulation and wet--dry audits
are retained under the repository's `Archive/validation-development` folder
and are not required by the public notebooks. See the
[validation suite index](../README.md) for links, run order, and requirements.
