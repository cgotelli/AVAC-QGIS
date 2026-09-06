# Precision-preserving terrain serialization

For the completed native controls and full-duration scientific decisions,
see the [later validation checkpoint](../validation/ISeeSnow/PRECISION_VALIDATION_20260905.md).
The staged-input audit below is explicitly an earlier, in-flight snapshot.

The general plugin and validation terrain writers preserve all supplied
binary64 precision. This is a scientific-input correction, not a change to
the curvature classifier, friction law, momentum source, timestep controller
or case-specific physical parameters.

## Why this matters

Second differences amplify small elevation-rounding errors. A mathematically
affine terrain raster can therefore acquire numerical curvature when its
values are serialized with too few significant digits. In the investigated
uniform Coulomb control, the old 12-digit validation terrain was identical
between solvers but triggered both actual classifiers in 1,200 of 5,000 cells.
The first false-curvature cells occurred at x = 11.435 m, near the decimal
precision transition where the bed magnitude crossed 1 m.

The native bed's maximum deviation from the intended plane was only
3.81e-12 m, but its second differences reached 6.66e-12 m, above the local
1e-12 m classifier tolerance. An actual compiled old source call on a saved
state changed momentum even at `dt=0` when this false-curvature gate enabled
the existing shallow-state projection. This establishes a real numerical
mechanism; it is not evidence of a new patch-boundary or AMR geometry defect.

A separate bounded analytic-plane roundtrip test produced zero false
classifications at 17 significant digits in both compiled classifiers.
That result alone did not establish a full solver regression; completed
native controls are recorded below.

## General implementation and unchanged behavior

| Writer | Previous terrain output | Current terrain output |
|---|---|---|
| Plugin `write_topography` | `.10g` elevation samples | `.17g` elevation samples |
| Validation `_arc_ascii` | `.12g` samples and coordinate headers | `.17g` samples and coordinate headers |
| Coulomb publication driver's `write_arc_ascii` | Separate `.15g` terrain writer | Delegates to the shared `.17g` terrain writer |

The plugin's coordinate and nodata headers already used Python's
binary64-roundtrip float representation and retain that compatible format.
Seventeen significant digits preserve a finite binary64 elevation when
parsed back as binary64. The writers retain their existing north/south row
order, cell-edge/centre registration, terrain halo and nodata behavior.

Implementation:
[plugin preprocessing](../avac_qgis/core/preprocessing.py) and
[validation runtime](../validation/avac4qgis_validation/runtime.py), plus the
[Coulomb publication wrapper](../validation/AVAC/Coulomb_sloping_bed/run_avac_validation.py).

Release/qinit serialization is unchanged, including the existing `.12g`
legacy XYZ writers, the Coulomb publication driver's `.15g` qinit and the
binary initial-state pathway. No limiter, CFL target,
regularization depth, curvature tolerance or physical coefficient was tuned
for this correction. Full precision cannot recover information already lost
in an input raster, eliminate genuine terrain curvature, or by itself prove
timestep convergence.

## Completed tests and native controls

[The serialization tests](../validation/tests/test_terrain_serialization.py)
exercise both actual writers, read the emitted files directly into Fortran
`real(kind=8)`, and call the production affine/non-affine classifier. The
20 tests cover exact coordinate/sample bits, north/south orientation, nodata,
sloping and oblique planes, large positive/negative vertical datums, retained
resolved curvature, the real validation preparation path and unchanged
release XYZ precision. The publication driver's actual `write_inputs` path
also preserves terrain exactly while retaining its `.15g` qinit. Negative
controls reproduce false curvature with the
old 10- and 12-digit elevation formats.

These tests plus existing grid-registration and terrain-reader coverage
passed after the publication-wrapper test was added: **28 passed**. An earlier
expanded preprocessing/runtime selection produced
66 passed, 3 skipped and one pre-existing WAVE partial-shoreline-mask failure;
that failure also reproduced independently on main and does not call either
terrain writer. It was not changed as part of this work.

The completed native comparison uses full-precision terrain on both sides:
AMR-only main solver `16cdba0f...` and experimental V1 solver `831f9835...`.
Both keep identical physical/numerical inputs apart from explicitly audited
auxiliary metadata: V1 adds a third auxiliary component for granular cases;
water retains two.

| Completed control | Native frames | Conserved q, including ghosts | Pre-existing auxiliary fields, including ghosts |
|---|---:|---|---|
| Uniform affine Coulomb, 6 s, 0.03 m cells | 61 | Bitwise identical; maximum difference 0 | Bitwise identical; maximum difference 0 |
| Kerswell quasi-1D Coulomb AMR, 10 s, three levels | 41 | Bitwise identical; maximum difference 0 | Bitwise identical; maximum difference 0 |
| Uniform water control, 5 s | 101 | Bitwise identical; maximum difference 0 | Bitwise identical; maximum difference 0 |

Frame times and patch geometries also match. This is physical-field parity,
not a claim that files with two versus three auxiliary components have
identical bytes. The uniform control's resolved final front remains
16.595 m versus its analytic 17.7759865 m; preserving the flat bypass does
not remove the control's remaining discretization error.

The detailed external workspace evidence is under
`AVAC-QGIS-validation-runs/iseesnow-investigation/`:

- `runout-investigation-76844b9/affine-mask-forensics/affine_mask_audit.md`
- `runout-investigation-76844b9/p17-c6-comparison/physical_flat_comparison.md`
- `runout-investigation-76844b9/p17-k10-comparison/physical_flat_comparison.md`
- `runout-investigation-76844b9/p17-w5-comparison/physical_flat_comparison.md`

Each comparison has companion JSON with exact input, source and field hashes.
These external run artifacts are not assumed to accompany a repository clone.

## Serialized-input provenance and full-suite gate

The [ISeeSnow driver](../validation/ISeeSnow/run_iseesnow_avac.py) now records
the actual generated terrain, binary initial state and native `.data` control
files after all controls are finalized and before launching the solver.
Before publishing results, it checks that those files are unchanged and
includes the records in `generated_input_manifest`. This complements the
existing original-benchmark-input and solver/backend authentication; hashing
only the supplied DEM cannot identify a change in its serialized terrain.
[Focused provenance tests](../validation/tests/test_iseesnow_generated_inputs.py)
cover the recorded files, detected mutation and missing initial state.
Both capture and article reauthentication require all 17 managed-backend
native controls, in addition to any extra `.data` files. A missing control
cannot be hidden by deleting its manifest entry. The expanded module has
41 passing tests per checkout, including legacy-manifest compatibility.

An independent read-only checkpoint of the three-case, 1,200-second main and
V1 cohorts found identical terrain and initial-state bytes for every paired
case. Every staged terrain value/header preserved the supplied float64
values after the existing halo/orientation conversion. The initial-state
binaries also matched the prior `07654535...` full-suite inputs exactly.
Only the expected auxiliary metadata differed in normalized native controls;
the active solver hashes matched their labelled source/runtime snapshots.
Evidence: `p17-staged-input-audit/staged_input_checkpoint.md` and its JSON.

This checkpoint was taken while the full-duration jobs were running. It is
**not** a full-suite pass, a peer-agreement claim or permission to promote
the experimental operator change. Successful completion, mass/rest checks,
CFL rejection behavior, timestep sensitivity and PFT-first peer comparisons
remain separate acceptance gates. Lower peak velocity alone is insufficient.

## Windows plugin delivery

Fresh main and experimental ZIPs contain the corrected plugin writer. Native
archives were reused only after all manifest records and relevant native/Python
source files matched their respective source trees. Main and V1 remain
separate cohorts; packaging did not promote experimental solver physics.

Both exact ZIPs passed release validation and an isolated QGIS 3.40.11 normal
dock workflow: automatic AVAC and WAVE runtime installation from a nonexistent
runtime directory, preparation and a completed short AVAC run with four native
and four fixed-grid frames. No dependency was installed manually, and the
user's normal profile was untouched. The already observed offscreen native
access violation occurred after functional PASS in both tests; these are not
clean application-exit claims or full-duration scientific validation.

Package records are in `p17-plugin-main/` and `p17-plugin-v1/` below the
external investigation root. Fresh-QGIS reports are in sibling validation-run
directories `qgis-p17-main/` and `qgis-p17-v1/`.
