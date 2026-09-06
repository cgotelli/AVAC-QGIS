# Source/timestep stabilization investigation

This is the pre-precision investigation record. The later
[terrain-precision checkpoint](PRECISION_VALIDATION_20260905.md) supersedes
the pending writer fix, incomplete native controls and automated-test counts
below. Both general writers now preserve binary64 terrain; the original
Coulomb AMR run completes, but a separate native terrain-integration roundoff
mechanism still prevents an exact flat-state non-regression claim. Historical
source hashes, rounded-terrain observations and short-run results below are
retained as such, not reassigned to the later full-duration cohorts.

Status: candidate implementation under evaluation; not a new accepted article
result or permission to push. The previous accepted source is `97e1ce1`, with
frozen executable `07654535`. All physical benchmark inputs, Coulomb Minmod,
Voellmy van Leer, and the independent 0.05/0.10 m depth controls are retained.

## Demonstrated defects and mechanism

The previous source projected shallow cell-average momentum after every
accepted step by

`R(h) = sqrt(2) (h/h_e)^2 / sqrt(1 + (h/h_e)^4)` for `h < h_e`.

There was no timestep factor. At `h/h_e=0.5`, one application retains 0.343
of momentum, two retain 0.118, and even `dt=0` changes the state. Six compiled
source tests reproduce this for Coulomb, Voellmy and cohesive Voellmy. The
force-free subcycling test uses motion along the straight axis of a
transversely curved surface, so the damping cannot be physical curvature.

Deleting the projection alone is unsafe. A matched RealTopo 60 s diagnostic
raises the hotspot peak from 82.794 to 149.310 m/s; the corresponding order-one
control gives 41.657 m/s but also changes PFT through diffusion.

An observation-only native stage trace and a private same-state order-one
shadow calculation identify the high-order interface correction more directly:
at time 52.42326 s, raw post-flux speed is 55.234 m/s for the shadow first-order
update and 84.005 m/s for the actual second-order update. The nearly dry south
interface contributes an extra horizontal momentum vector approximately
(-22.701, +26.914) m2/s with only -0.000012 m extra depth. On the next step
that momentum correction nearly disappears. Curvature transport adds only
0.226 m/s and basal friction removes 1.437 m/s on the peak-producing step;
the accepted reported peak is 82.794 m/s, not the provisional 84.005 m/s.

All seven native solution frames and the complete native gauge prefix match
the uninstrumented executable exactly. Trace/shadow hooks are diagnostic only
and are not included in the production candidate.

The Kurganov–Petrova shallow-velocity desingularization is described at flux
evaluation points, with momentum reconstructed there; this does not justify
repeatedly projecting stored cell averages after a source update. See the
[authors' paper, equations 3.24–3.25](https://people.tamu.edu/~gpetrova/KPSV.pdf).
The candidate below is a proposed stabilization, not a claimed theorem from
that paper.

## Candidate v1: conservative correction-flux taper

An AVAC-local `flux2fw.f` overrides the shared GeoClaw routine. At a shallow
curved-terrain interface, the complete high-order correction vector `cqxx`
receives one factor `R(min(h_left,h_right))`. The same corrected vector enters
both the normal flux and its transverse split. All three conserved components
share the factor. First-order fluctuations and increment-wave transverse
transport are unchanged. The conservative update still multiplies these
fluxes by `dt/dx`; there is no additional per-step cell-average damping.

`b4step2` refreshes a full two-dimensional nonplanarity mask in transient
`aux(3)`. Genuine internal/periodic ghost terrain is used. Only physical
exterior terrain is excluded; narrow physical domains and tile boundaries
have compiled regression tests. Water keeps two auxiliaries and its original
flux path. Flat/affine granular terrain gets factor one. Basal curvature,
gravity, friction, cohesion, contact handling and terrain transport are not
retuned.

Saved YAML keys containing `state_momentum_regularization_depth` remain
readable, but their numerical role changes to flux stabilization. The plugin
labels the controls "shallow flux depth" and keeps the separate 0.05 m Coulomb
and 0.10 m Voellmy defaults. They are not PFV reporting thresholds.

## Independent AMR controller correction

The inherited `ntogo > 100` abort counts remaining synchronization steps, not
rejected CFL trials. A still-water test with legitimate temporal refinement
ratio 103 aborts under `07654535` despite fine-grid CFL 0.000385 and zero
rejections. The corrected controller completes ratios 103 and 1000; ratio-two
outputs are byte-identical before and after.

The replacement checks finite positive timesteps, integer overflow and
floating-point time progress. It preserves the separate limit of 20 rejected
CFL trials and exact parent-step synchronization. Removing the arbitrary cap
does not by itself cure expensive thin-film subcycling or establish completion
of the original publication AMR tests.

## Current short-horizon evidence and limitations

All rows below are 120 s diagnostics, not final 1200 s article comparisons.
Scores use exactly aligned spatial peers, without parameter tuning, shifts
or resampling; lower normalized PFT score is better.

| Case / CFL | Previous PFT score | v1 PFT score | Runout change |
| --- | ---: | ---: | ---: |
| IdealizedTopo / 0.5 | 0.885739 | 0.893459 | 0 m |
| RealTopo / 0.5 | 0.907994 | 0.908531 | +3.809 m |
| RealTopo / 0.25 | 0.915941 | 0.917759 | 0 m |
| RealTopo / 0.125 | 0.914392 | 0.910829 | see matched report |
| CoulombOnly / 0.25 | 0.991214 | 0.911514 | +20 m |
| CoulombOnly / 0.125 | 1.067111 | 0.898873 | +25 m |

Coulomb v1 reaches practical rest from 80 s, confirmed at 100 s through this
120 s ceiling; its PFT peak rises from 5.441 to 7.220 m. Its matched half-step
check is complete: runout remains 3150.041 m and rest remains at 80/100 s.
The smaller-target peak is 6.819 m; the full PFT field differs by 5.38% relative
L2, so a single halving does not establish timestep convergence. Relative to
the previous source at each matched target, aggregate PFT score improves
8.04% at 0.25 and 15.77% at 0.125. This is not uniformly improved agreement
with every peer or a final-horizon result.

The resolved RealTopo hotspot is greatly reduced without materially changing
PFT. However, v1 at CFL 0.5 develops a different near-dry problem: 159 late
retries after 60 s, and a saved 120 s cell has raw horizontal speed 888 m/s at
depth 0.0001039 m. This is not the resolved reported hotspot. At CFL 0.25 there
are only two early retries and no late ones. Zero accepted-CFL violations is
therefore not sufficient to call v1 robust or timestep-converged.

The direct `hu/h` evaluation in first-order fluxes remains under investigation.
An additional private-flux-state desingularization was tested separately as
v2, and is not selected. It reduces the late near-dry growth but has a higher
global PFV (84.086 m/s, simultaneous depth at that cell not measured), slightly
worse PFT score than v1, and changes the leading-order shallow flux rather
than only its high-order correction. Its composite flux Jacobian can have a
wave speed approaching 2.618 times the speed used by its pressureless base
Riemann probe near the depth threshold. Matching implementation and preflight
does not prove that CFL estimate sufficient. The 320 passing compiled tests
do not override these scientific limitations.

Raw runs, exact executable/backend/input hashes, causal traces and independent
peer reports are retained outside Git under the validation-runs investigation
directory. The accepted 1200 s figures are not overwritten by these probes.

## Integration checkpoint

The proven AMR controller correction is integrated separately on the main
validation branch. The flux/source changes remain on the local
`avac-source-timestep-candidate` worktree/branch pending the physical checks.

The combined candidate passes 465 automated tests (5 skipped, 1 explicitly
deselected platform/GDAL test). Kerswell through 10 s and the uniform WRR water
control through 5 s preserve every conserved native field, original auxiliary
value and analytical metric. The original WRR AMR protocol now completes 5 s
with the AMR-only fix; its entire pre-failure output prefix is unchanged.

The uniform affine Coulomb control is not a non-regression pass: its final
front changes from 12.065 to 18.305 m (analytical 17.776 m), and its front RMSE
falls from 3.458 to 0.489 m. The forensic audit finds identical input and native
bed arrays, but 12-significant-digit ASCII rounding makes 1200/5000 cells
appear non-planar to both the old and new classifier. The old source therefore
projects shallow momentum on this mathematically planar bed, near the old
stalled front. This is not a new geometry/AMR boundary defect. It also means
that preserving the old artifact is not equivalent to preserving the physical
plane solution. Input serialization needs an explicit general fix and paired
verification, not an unexplained tolerance increase. The plugin currently
writes only 10 significant digits; the analytical helper writes 12.
The original high-refinement Coulomb AMR
case still has pathological thin-film subcycling and was stopped with raw
evidence retained. It is not a completed verification.

An isolated experimental Windows package installs both managed runtimes and
completes the normal QGIS workflow without manually installed dependencies.
The known offscreen QGIS native shutdown crash occurs after functional PASS,
as it did for the prior package. This is not a clean application-exit claim.
