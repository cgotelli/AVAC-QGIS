# Curved-terrain transport and the Coulomb runout deficit

## Finding

The packaged baseline (`76844b9`, preserved by `ee0d98e`) loses terrain-tangent
velocity on the concave transition, placing its Coulomb deposit about 270 m
too far upstream. The physical curvature contribution to basal normal load
is not the error and remains unchanged. No friction parameter, release
condition, limiter, shallow-state depth, or runout threshold is fitted here.

At the end of the straight approach, AVAC and com1DFA have nearly identical
peak velocities (102.042 and 102.358 m/s). At map x=3400 m on the downstream
flat, their values are 60.224 and 75.867 m/s. The difference in Coulomb stopping
distance, `(75.867^2 - 60.224^2)/(2*0.4*9.81)`, is 271.3 m, matching the
270.0 m same-method runout difference. Lowering the runout thickness threshold
from 0.5 to 0.001 m extends the baseline only 15 m. Applying the same thalweg
measurement reproduces eight checked peer runouts within 1.1 m; all checked
matches lie within one 5 m grid cell (SaVal differs by 2.56 m).

A reduced material-point balance on the supplied approximately 400 m-radius,
34-degree transition predicts 74.924 m/s at x=3400 with tangent kinematics,
but 59.741 m/s when their geometric acceleration is omitted. This diagnostic
excludes finite-layer pressure, lateral spreading and unsteadiness; it is a
mechanistic cross-check, not an exact analytical solution of the avalanche.

The underlying Cartesian approximation and changing-slope velocity problem
are discussed by [Hergarten and Robl (2015), section 4](https://nhess.copernicus.org/articles/15/671/2015/)
and the [ISeeSnow intercomparison, sections 5.1 and 5.2](https://doi.org/10.5194/egusphere-2025-6053).

## General source correction

For terrain `z = B(x,y)` and horizontal velocity vector `u`, motion constrained
to the surface includes

```text
a_geometry = -grad(B) * (u^T Hess(B) u) / (1 + |grad(B)|^2).
```

The solver now completes its conservative Cartesian flux update by minimally
rotating the provisional terrain-tangent velocity between material departure
and arrival bed normals. The departure gradient is reconstructed with the
local Hessian and the accepted timestep. The finite rotation preserves
tangent kinetic energy between those planes and includes lateral turning.
This local isometry does not imply global conservation of numerical kinetic
energy: the incoming post-flux state already mixes Eulerian contributions.
It avoids the pole of an independently frozen quadratic acceleration update;
it is not an empirical speed cap or an extra basal-friction coefficient.

This is a first-order material-geometry reconstruction within the existing
split solver, not a claim of second-order temporal accuracy or a complete
terrain-following reformulation of gravity and pressure. Timestep and mesh
sensitivity must therefore remain separate audits.

The operation is compiled into the production AVAC source and the Windows
plugin runtime, and applies to Coulomb, Voellmy and cohesive Voellmy cases,
independently of friction switches and friction-depth limits. Water mode is
unchanged. Genuine neighboring terrain is retained across internal patch
interfaces and periodic boundaries. Only exterior physical ghost closures
are excluded, with quadratic continuation where needed. One physically
resolved sample implies extrusion, two resolve a first derivative (and a
mixed derivative if both directions have two), and three or more resolve
the corresponding pure second derivative. A narrow numerical patch inside a
larger domain still uses its valid neighboring samples.

Affine terrain is an exact no-op, including oblique slopes and roundoff in
large stored elevations. Depth and mass are not modified. The existing
curvature normal-load term, static yield, Minmod Coulomb default, 0.05 m
Coulomb regularization, and separate Voellmy policy remain unchanged.

## Verification contract

The compiled tests exercise the actual Fortran helper and `src2`, not a
Python reimplementation. They cover affine identity, rest, tangent energy,
reverse transport, horizontal rotation covariance, the geodesic differential
limit, nearly opposing finite normals, hostile ghost closures, narrow curved
strips, friction independence, quadratic patch edges and vertical-datum
invariance. The separate frozen basal-source analytical tests are retained;
that constitutive law must not include geometric transport a second time.

The final Windows development test run passed 361 tests, with five skips and
one GDAL-dependent shoreline test deselected. Two modules were excluded from
that collection: the GDAL-only lake-depth module and the POSIX-only process
group test. The exact shoreline function and lake-depth test then passed in
QGIS's bundled Python/GDAL environment, without installing dependencies.
The POSIX process-group test is not a Windows verification. Forty-two compiled
geometry/`src2` tests passed as part of the native source checks.

Full-solver controls compare the complete Kerswell flat-bed run, a paired
uniform sloping-bed run, the WRR water limit, and all three ISeeSnow cases.
Kerswell (10 s, AMR3) and the uniform WRR water control (5 s) are byte-identical
to baseline in every saved native and fixed-grid field. The uniform Coulomb
slope control (6 s) preserves all front/rear analytical metrics; maximum saved
depth and raw velocity differences are 1.86e-10 m and 2.72e-7 m/s. These small
differences establish non-regression, not improvement of the existing coarse
uniform Coulomb front position (12.065 m versus the analytical 17.776 m,
an underprediction of about 5.711 m).

The historical AMR constant-slope early stop remains a known limitation. The
WRR publication AMR protocol also stops early with `Too many dt reductions`:
baseline and an initial transport build produced identical fields through the
same incomplete interval (about 4.837 s). Neither is a completed verification.
The completed uniform controls are non-regression checks, not replacements
for those publication accuracy studies. No accepted-CFL violations occurred
in the completed controls; their accepted/rejected-step histories are unchanged.

The geometry helper has explicit internal/periodic patch-interface tests, but
the complete curved solver is not proven AMR-invariant. The `07654535` build
reported here still has a shallow momentum projection with a patch-based
nonplanarity classifier and a per-step factor independent of dt. The later
[source/timestep investigation](SOURCE_TIMESTEP_STABILIZATION.md) replaces
that projection in a separately evaluated candidate. Its results must not be
silently substituted for the accepted build below. Source splitting, shallow
regularization and AMR subcycling still require whole-solver checks; this
ISeeSnow comparison is single-level, not a curved-AMR certification.

## Peer population correction

The spatial reader also recognizes official `*_h_max.asc`/`*_s_max.asc`
exports. This restores the previously omitted, exactly aligned MoT-Voellmy
submission. Its depth is terrain-normal and its speed terrain-tangent, as
documented in [Issler (2025), page 7](https://ngi.brage.unit.no/ngi-xmlui/bitstream/handle/11250/3189654/20230100-06-TN.pdf?isAllowed=y&sequence=1)
and the [AvaFrame MoT interface](https://docs.avaframe.org/en/latest/_modules/com9MoTVoellmy/com9MoTVoellmy.html).
Existing conventional exports take precedence over an alternate export of
the same model, avoiding double weighting. No peer grid or value is altered.

Spatial populations become 9/8/8 for IdealizedTopo/RealTopo/CoulombOnly;
published Table C1 scalar populations remain 11/10/11. These are distinct
populations, and the spatial Voellmy populations include FLO-2D. Historical
seven-peer limiter scores remain historical; every before/after comparison
of the source correction must use the same expanded peer set on both sides.
Minmod remains the selected policy; this investigation does not repeat its
in-sample selection or claim new independent validation.

## Completed packaged results

Both source versions completed all three 1200 s cases, with 121 outputs,
identical official physical inputs and numerical controls, and zero accepted
CFL violations or rejected trials. Final Coulomb runout is 3130.041 m versus
2874.999 m before and the published scalar peer median 3144.300 m. Its PFT
normalized full-field score improves from 1.200518 to 0.991161 (17.44%), against
the same eight aligned peers, with seven of eight individual errors reduced.
The downstream PFV at x=3200, 3300 and 3400 m is 94.686, 83.826 and 75.523 m/s,
versus com1DFA's 94.963, 84.036 and 75.867 m/s. Coulomb practical rest is
sustained from 620 s and confirmed at 640 s without later rebound.

IdealizedTopo and RealTopo primary PFT scores improve by 10.21% and 12.00%.
Their PFV field scores are essentially unchanged and 15.07% better,
respectively, but RealTopo's maximum PFV increases to a timestep-sensitive
82.794 m/s. Both Voellmy cases remain active at 1200 s, as in the baseline.
All corrected relative volume changes have magnitude at most 1.01e-9.

This is not universal agreement: Coulomb maximum PFT falls to 5.441 m versus
the scalar peer median 5.990 m, and its downstream cross-flow peak-thickness
plateau remains roughly twice the aligned peer median. Some individual
RealTopo peer errors worsen. The source correction is justified and improves
the chosen full-field metric, but does not certify a converged velocity field,
perfect deposit shape or completed publication-AMR verification.

The [article comparison](../../docs/article/iseesnow_comparison.md) contains
the final before/after figure, detailed transition profiles, regression
metrics, timestep caveats and exact package/source/input identities. Preliminary
120 s transport builds are not substituted for these final results.

## Timestep audit of the frozen production candidate

These sensitivity runs use the same final executable (`07654535`), 5 m mesh,
120 s ceiling and official physical inputs. Complete prepared YAML and native
input comparisons isolate `cfl_desired`; paired gauge changes are authenticated
by repeated byte-identical PFT/PFV fields. PFT remains the primary metric.

| Case | Target CFL | PFT normalized median RMSE | Peak PFV (m/s) | Runout (m) |
| --- | ---: | ---: | ---: | ---: |
| CoulombOnly | 0.25 | 0.991214 | 102.126 | 3130.041 |
| CoulombOnly | 0.125 | 1.067111 | 102.283 | 3125.041 |
| RealTopo | 0.5 | 0.907994 | 82.794 | 2093.315 |
| RealTopo | 0.25 | 0.915941 | 69.786 | 2086.838 |
| RealTopo | 0.125 | 0.914392 | 71.775 | 2086.267 |

For Coulomb, halving the timestep changes runout by one cell and worsens PFT
RMSE against all eight peers (aggregate score +7.66%). Minmod, the 0.05 m
regularization depth and target CFL 0.25 are retained without retuning friction.

For RealTopo, the successive whole-grid PFT differences contract from
0.07650 to 0.03666 m RMSE, and PFV differences from 0.60959 to 0.29413 m/s.
This is a useful convergence trend. However, the original coarse-run hotspot
falls from 82.794 to 43.913 and 44.196 m/s: the default-CFL velocity pulses are
not converged. The coarse peak occurs at simultaneous vertical depth 1.317 m
with positive contact load, so it cannot be dismissed as a dry-cell artifact.
The global maximum moves to another cell on refinement, with sensitive peak
timing. Smaller CFL changes the primary PFT score by less than 0.9% and does
not monotonically improve peer agreement. No default is changed on that basis.

These are whole-scheme timestep tests, not isolated tests of the new geometric
term, and 120 s scores must not be interchanged with full 1200 s deposition
scores. Peer agreement and numerical convergence are separate questions.

## Windows plugin delivery

The corrected production AVAC executable is included in the assembled Windows
plugin ZIP and was exercised through the normal QGIS dock in a fresh profile.
AVAC and unchanged WAVE runtimes and managed Clawpack installed automatically;
the short AVAC simulation completed with solver exit code 0 and all four native
and four fixed-grid outputs. No dependency was installed manually in that
profile. The exact same AVAC executable was used for the regression suite.

The offscreen QGIS harness emits an access violation during application
teardown after functional success. This was also reproduced with the previous
certified package; the functional result is not a claim of clean application
shutdown. The package and canonical runtime hashes are recorded in
[`docs/article/iseesnow_comparison.md`](../../docs/article/iseesnow_comparison.md).
