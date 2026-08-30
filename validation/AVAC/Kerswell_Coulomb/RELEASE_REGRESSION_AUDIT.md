# Kerswell Coulomb release-regression audit

Date: 2026-08-30

## Purpose

This audit identifies the AVAC source boundary at which the horizontal
Kerswell Coulomb verification stopped reproducing the result used in
manuscript Figure 3. Every full comparison used the same case definition:

- 40 mm base spacing;
- three AMR levels with two 4:1 longitudinal refinements;
- 2.5 mm finest spacing;
- 0.15 m analytical front and rear refinement corridors;
- 10 s duration with 40 output frames; and
- the same `h > 1e-12` leading-front diagnostic.

The manuscript Figure 3 result is the acceptance baseline. Small future
changes are acceptable only when they are physically explained by an intended
model correction; a several-metre runout loss is not acceptable.

## Results

| Solver state | Solver SHA-256 | Front RMSE (m) | Final front (m) | Rear RMSE (m) | Final rear (m) | Mass range (m2/m) | Outcome |
|---|---|---:|---:|---:|---:|---:|---|
| Figure 3 reference | `6a208dac3259...` | 0.148613 | 19.83125 | 0.007570 | -7.29375 | 0.00061544 | Accept |
| Released 0.5.14 | `9a34f54f07d5...` | 2.419124 | 16.11875 | 0.007731 | -7.28625 | 0.00064520 | Reject |
| Released 0.5.13 | `ca06f54079f3...` | 2.422909 | 16.11875 | 0.007432 | -7.29375 | 0.00064175 | Reject |
| Pre-`f895d68` committed source | `954ac469ae13...` | 0.148406 | 19.83125 | 0.007570 | -7.29375 | 0.00061543 | Accept |

Both distributed releases therefore contain the shortened leading-front
runout. Their rear-front and mass diagnostics remain close to the reference,
so the failure is specific to leading-front propagation rather than a global
mass loss or general instability.

The Figure 3 binary was an intermediate development build: release 0.5.13 was
built at 19:08 CEST, the preserved Figure 3 products were written at 21:58
CEST, and release 0.5.14 was built at 22:57 CEST. Its hash matches neither
release manifest. The exact intermediate source was not committed.

The last reproducible committed AVAC numerical core before `f895d68` is
`e493f3b`; its AVAC source is identical to `4b004c9`. Rebuilding that source
reproduces Figure 3 to within 0.00021 m in front RMSE and exactly reproduces
the reported final leading and rear positions on the diagnostic grid.

## Repository action

The working-tree AVAC numerical core and its source-level tests were restored
to `e493f3b`. The WAVE solver, QGIS interface, coupling work, validation
notebooks, manuscript files, and release archives were not rolled back. The
old AVAC configuration already uses two ghost cells.

The abandoned curvature implementation and its tracked validation edits are
preserved locally in Git stash `wip-curvature-before-pre-f895-solver-rollback`.
They must not be reapplied wholesale. Later corrections should be introduced
one at a time, and the Figure 3 Coulomb verification must be run after each
change before proceeding to ISeeSnow.

## Verification after rollback

The rebuilt working-tree solver passed the 0.5 s smoke case with front RMSE
0.06040 m and final front 2.92125 m versus 3.00947 m analytically. The focused
source suite passed 12 tests covering rheology, AMR transfer, dry states, and
velocity geometry.
