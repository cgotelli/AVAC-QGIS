# AVAC solver-correction plan

## Purpose

This branch starts from the verified restored solver baseline. Corrections will be
reintroduced one at a time, with a small purpose-built test before any expensive
publication validation is repeated. No correction is promoted to `main` until its
targeted test passes and the two Coulomb cases used in Figure 3 show no material
loss of agreement with the analytical solutions.

Baseline commits:

- restored solver: `d48e0a5` (`Restore verified pre-Voellmy AVAC solver baseline`);
- published branch point: `d582be4` (`Make validation notebooks reproduce publication controls`).

The article directory is outside the scope of this branch until the solver changes
have been accepted.

## Test and promotion workflow

For every item below:

1. Define the governing expectation and acceptance quantities before changing the
   solver.
2. Add a short, controlled Jupyter-notebook case that isolates the issue. The case
   should be small enough to run during development and should include a limiting
   configuration in which the existing solution must be recovered.
3. Implement only that correction and run its focused tests. Do not run the full
   Coulomb publication cases while making small edits.
4. Once the focused test is stable, run both Figure 3 Coulomb notebooks with their
   publication controls: the horizontal Kerswell case and the inclined
   Hergarten--Robl case.
5. Compare the numerical profiles, front and rear trajectories, final front
   positions, mass balance, and arrest behaviour with the baseline. A change is
   acceptable only if the analytically defined result improves or remains within
   the agreed numerical tolerance. The tolerance will be fixed with the authors
   before implementation of each item; it will not be chosen after seeing a
   regression.
6. Review the focused evidence and Figure 3 comparison together. Only then commit
   the correction for promotion to `main`.
7. After promotion, rerun the three ISeeSnow cases when the correction can affect
   real-terrain dynamics, velocity, runout, or deposition, and record the change
   relative to both the restored baseline and the published intercomparison data.

Reference values from the restored Figure 3 runs are retained as a regression
record:

| Case | Front RMSE | Rear RMSE | Final front |
|---|---:|---:|---:|
| Horizontal Coulomb | 0.149098 | 0.003111829 | 19.83125 m |
| Inclined Coulomb | 0.187273 | 0.012416 | 17.4865625 m |

The full saved profiles and run summaries, rather than these rounded values alone,
are the authoritative baseline.

## Ordered correction list

### 1. Conservative positivity and real-terrain volume conservation

- [ ] Specify which discrete volume is conserved for the AVAC depth convention on
  sloping terrain and at AMR transfers.
- [ ] Add a short synthetic topography case in which a compact layer crosses a
  slope change and a refinement boundary. Measure total mass, negative depth,
  momentum change, and sensitivity to patch placement.
- [ ] Reintroduce a conservative positivity correction that redistributes a depth
  deficit without creating or deleting mass and leaves already positive cells
  unchanged.
- [ ] Check uniform-grid and AMR results of the targeted case.
- [ ] Run the two Figure 3 cases as the final gate.
- [ ] If accepted, rerun all three ISeeSnow cases and report changes in support,
  volume, runout, maximum thickness, and peak flow velocity.

### 2. Wet--dry velocity regularization and peak-velocity diagnostics

- [ ] Add a short dry-front case with a shallow numerical film carrying finite
  momentum. It must expose the unbounded `hu/h` diagnostic without requiring a
  full avalanche run.
- [ ] Define a depth-aware desingularization that suppresses dry-front velocity
  spikes while converging to `hu/h` in resolved flow.
- [ ] Define the minimum resolved depth used when reporting peak flow velocity;
  keep diagnostic filtering separate from the conserved solver state.
- [ ] Verify that velocity and momentum in well-resolved cells are unchanged.
- [ ] Run the two Figure 3 cases as the final gate, then rerun the ISeeSnow cases if
  accepted.

### 3. Steep-slope geometry and Voellmy source integration

- [ ] Re-derive the Cartesian source term from the depth and momentum conventions
  actually stored by AVAC, including the flow-parallel gravity and Coulomb terms.
- [ ] Add fast frozen-coefficient tests on a planar slope: the Coulomb limit, a
  Voellmy acceleration/deceleration trajectory with a known ODE solution, the
  terminal-speed balance, and an uphill state.
- [ ] Reintroduce the corrected Voellmy formulation and its exact or bounded source
  integration without changing the Coulomb limit.
- [ ] Confirm the horizontal-bed identity and both signs of velocity.
- [ ] Run the two Figure 3 cases as the final gate, then rerun the three ISeeSnow
  cases if accepted.

### 4. Terrain-tangent velocity reporting

- [ ] Add a planar-slope diagnostic case whose map-plane and terrain-tangent speeds
  have a known geometric relation.
- [ ] Correct result reporting and peak-velocity extraction without modifying the
  conserved state or the dynamics.
- [ ] Confirm exact identity on a horizontal bed and correct transformation on
  slopes in both coordinate directions.
- [ ] Run the Figure 3 post-processing gate and then update the ISeeSnow velocity
  comparison if accepted.

### 5. Static and cohesive arrest

- [ ] Add compact sub-yield and super-yield deposits on an inclined plane, plus a
  case immediately below and above the cohesive threshold.
- [ ] Reintroduce the static/cohesive arrest logic with explicit transition rules
  and no direction-dependent bias.
- [ ] Confirm that a sub-yield deposit remains at rest, a super-yield deposit
  accelerates, and moving material is not arrested spuriously.
- [ ] Run the two Figure 3 cases as the final gate, then the ISeeSnow cases if
  accepted.

### 6. Two-ghost AMR patch-edge and transverse wet--dry treatment

- [ ] Keep one solver path with two ghost cells for verification and normal use.
- [ ] Add a small state that crosses an AMR patch edge and compare it with the same
  state on a single patch. Repeat with the patch boundary shifted by one cell.
- [ ] Add a transverse dry-front case and compare one-thread and multi-thread runs.
- [ ] Reintroduce only the limiter/regularization needed to make these comparisons
  invariant within roundoff or the agreed discretization tolerance.
- [ ] Run the two Figure 3 cases as the final gate, then relevant ISeeSnow cases if
  accepted.

### 7. Curvature contribution to normal stress and basal shear stress

- [ ] Fix the curvature sign convention and the velocity/depth convention before
  coding. For a flow-following direction, the effective basal normal stress should
  contain both the gravitational normal component and the centripetal contribution,
  schematically

  `sigma_n = rho h (g cos(theta) + kappa U^2)`,

  with the exact signs and metric factors derived for AVAC's coordinates.
- [ ] Apply contact/non-negativity logic when convex curvature would reduce the
  effective normal stress to zero. The bed cannot exert tensile normal stress.
- [ ] Propagate the corrected normal stress into Coulomb basal shear,
  `tau_C = mu sigma_n`. Curvature must therefore affect shear resistance as well as
  the normal balance; it must not be added only as an independent acceleration.
- [ ] Keep the Voellmy turbulent drag term distinct from the curvature-dependent
  Coulomb term so that the `U^2` contribution is not counted twice.
- [ ] Add three controlled cases before any publication run:
  1. a straight planar bed (`kappa = 0`) that is identical to the current solver;
  2. a constant concave arc, for which normal stress and Coulomb shear increase and
     agree with the local analytical balance;
  3. a constant convex arc, for which normal stress and Coulomb shear decrease and
     the loss-of-contact limit is exercised safely.
- [ ] Add an energy/work check showing that the curvature normal force itself does
  no tangential work; only its effect on basal shear changes dissipation.
- [ ] Check both Coulomb and Voellmy variants of the curved tests.
- [ ] Run the two Figure 3 cases as the final gate. Because their beds are flat or
  planar, their curvature is zero and their results should be unchanged apart from
  roundoff.
- [ ] If accepted, rerun all three ISeeSnow cases and report the curvature-induced
  changes before modifying the article.

## Separate model-development backlog

These assumptions require scientific decisions and dedicated verification. They
should not be folded silently into one of the corrections above:

- [ ] Decide whether geometric angles should continue to use the fixed bed
  (Hergarten--Robl `z_b` variant) or use the evolving free surface.
- [ ] Assess the neglected transverse steep-slope correction and design a genuinely
  two-dimensional benchmark before implementing it.
- [ ] Assess curvature and centripetal terms not covered by the flow-following
  normal-stress correction above.
- [ ] Assess the hydrostatic pressure assumption and earth-pressure coefficient
  `K = 1`; any alternative needs a benchmark with known lateral stress behaviour.
- [ ] Assess whether first-order Godunov splitting of source terms materially limits
  the second-order spatial update; design a temporal-convergence test first.
- [ ] Replace or justify the map-plane approximation in the Riemann-interface
  cohesive arrest criterion, with rotated-grid invariance as the focused test.

Multiple Strickler-region handling is already present in the restored baseline and
is not part of this correction list. The existing damping condition is intentional
and is likewise not scheduled for modification.
