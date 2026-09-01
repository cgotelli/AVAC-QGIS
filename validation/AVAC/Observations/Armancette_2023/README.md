# Armancette 2023 observational validation

## Selected case

This directory is reserved for an AVAC reconstruction of the avalanche that
descended the Armancette glacier on 9 April 2023 near Les Contamines-Montjoie,
France. The event occurred in a snow-and-ice setting and is included in the
open data release accompanying:

- Escobar Rincon, A. F., Thibert, E., Bonnefoy-Demongeot, M., and Faug, T.
  (2026), *Volume-dependent effective friction of ice avalanches: insights
  from back-analyses using depth-averaged flow modelling*, supplementary
  dataset, <https://doi.org/10.5281/zenodo.20595652>;
- Escobar Rincon, A. F., Thibert, E., Bonnefoy-Demongeot, M., and Faug, T.
  (2026), *Back analysis of ice avalanches using depth-averaged modelling*,
  EGU General Assembly 2026, EGU26-3573,
  <https://doi.org/10.5194/egusphere-egu26-3573>.

The study uses a depth-averaged Voellmy model, making the case directly
relevant to AVAC's mass and momentum equations and its cohesive-Voellmy basal
resistance. The case is a test of dense-flow propagation and deposition in a
snow-and-ice avalanche setting. It must not be presented as a clean validation
of snow-specific constitutive behaviour.

As of 1 September 2026, the Zenodo record does not link a DOI for the full
companion manuscript named in its title. The public scientific description is
therefore the EGU abstract, while the numerical provenance and reproducibility
come from the DOI-pinned dataset. No unpublished information is assumed. If a
full article becomes public before submission, its methods and event
provenance must be reviewed and cited; running this validation does not depend
on obtaining it from the authors.

## Non-negotiable data requirement

This case was selected only after checking the downloadable files themselves.
Every quantity needed to initialize the run and every primary comparison
quantity is public numerical data. The workflow will not contact the authors,
digitize a published figure, infer an unreported release geometry, or substitute
a model output for an observation.

The source record is CC BY 4.0. Any copied or derived data must retain the
citation, licence, original filename, DOI, and checksum.

## Complete public input and observation set

All four case rasters share the same 1209 by 474 grid, 1 m cell spacing, origin
and extent. They are available as separate downloads, so a user does not need
to retrieve a large monolithic archive.

| Role | File | MD5 |
|---|---|---|
| Terrain | `Armancette_mntsimulation.asc` | `170b987eed1b3fe472d3258d68e87091` |
| Release mask | `Armancette_source.asc` | `162cf01affa56e2c11169dba194dcaab` |
| Observed deposit mask | `Armancette_deposit.asc` | `0f6b558218c4e6a31c91f5ba3c6a9f04` |
| Published best-match flow depth at arrest | `Armancette_h_tdiff.asc` | `aea43f6ceb594c90af85420073457969` |

The DOI record also supplies `Supplementary Table.csv`, MD5
`7c9d20c6ac4c610c2ad994b28abfec47`. Its Armancette row prescribes:

| Quantity | Published value |
|---|---:|
| Release volume | 40,000 m3 |
| Uniform release depth, $h_0$ | 8.3 m |
| Coulomb coefficient, $\mu$ | 0.45035 |
| Voellmy coefficient, $\xi$ | 2250 m s$^{-2}$ |
| Specific cohesive resistance, $\tau_c/\rho$ | 0.545 m$^2$ s$^{-2}$ |
| Source grid spacing | 1 m |

The release raster is a numerical mask rather than a figure-derived outline.
The observed deposit is likewise supplied as a numerical mask. The published
best-match raster is retained only for model-to-model context; it is not the
observational target.

The source mask contains 3945 active 1 m cells. Multiplying its planimetric
area by 8.3 m gives 32,743.5 m$^3$, which initially appears inconsistent with
the tabulated release volume. Using the supplied terrain to account for the
sloping surface gives approximately 40,400 m$^3$, only 1.0 % above the rounded
published value. This check confirms that the terrain, source mask and release
depth jointly define the initial volume; the AVAC notebook must preserve that
terrain-normal interpretation.

## Why the earlier candidates were rejected

The controlled Nordkette 2022 experiment was rejected because its open
supplement contains the simulation initialization but not the numerical radar
front or GNSS time series. Using that case would require figure digitization or
an author request.

The 7 February 2003 Vallée de la Sionne case was rejected because its Zenodo
supplement provides numerical front velocities and a longitudinal terrain
profile, but not the full two-dimensional terrain and release geometry needed
to reproduce the published field simulation.

The Makris et al. (2024) laboratory granular-avalanche archive was inspected in
full. It provides raw videos, deposit point clouds and processed runout data,
but does not report the dimensions of the filled release box. Mass and volume
alone do not uniquely define AVAC's initial depth distribution, so that case
also fails the no-assumption criterion.

## Validation protocol

The future case notebook will perform every step from a clean checkout:

1. Download the DOI-pinned terrain, source, observed-deposit, reference-result
   and parameter-table files, and verify every MD5 before use.
2. Read the source mask on its native grid and apply the published uniform
   release depth of 8.3 m through the normal AVAC initialization path.
3. Run the unmodified AVAC solver with its cohesive-Voellmy resistance. The
   mapping between the published specific cohesive resistance and AVAC's input
   convention must be unit-tested before the production run.
4. Use the published parameter set first, without AVAC-specific tuning. Keep
   any later calibration experiment separate and clearly labelled.
5. Compare AVAC directly with the observed deposit mask using predeclared
   support and stopping definitions. Report intersection over union, precision,
   recall, runout-position error along a fixed centerline, lateral-width error,
   and area bias.
6. Report release volume, final numerical volume and mass-balance error. State
   the distinction between planimetric volume and terrain-surface volume.
7. Perform a mesh-sensitivity study without exceeding the 1 m resolution of the
   supplied terrain and observation rasters.
8. Show the published best-match raster in a secondary comparison only. It may
   help diagnose differences, but it cannot replace the observed deposit in
   any acceptance score.
9. Save the solver hash, input checksums, numerical metrics and plotting
   thresholds in a machine-readable record.

The support threshold and centerline will be declared before inspecting the
AVAC score and held fixed across resolutions. A sensitivity panel will show
whether reasonable threshold variation changes the scientific conclusion.

## Interpretation limits

The published friction values were obtained through back-analysis of the same
event. The untuned AVAC run is therefore an event reconstruction using a
transferred calibrated parameter set, not an independent prediction.

The observed target is a final deposit footprint. It constrains runout and
lateral spreading but does not independently validate the simulated velocity
history or flow thickness. Those quantities must not be described as validated
by this case.

Because the event occurred on a glacier and the source study groups it with ice
avalanches, agreement would support AVAC's dense-flow transport and resistance
formulation in this setting. It would not, by itself, establish predictive skill
for dry-snow, wet-snow or powder-cloud avalanches.

## Next implementation steps

- add checksum-pinned download and provenance helpers;
- add the Armancette notebook and a small testable case driver;
- test the raster-to-AVAC initialization and cohesion-unit conversion without a
  full production run;
- reproduce the supplied terrain, source and observation masks visually;
- run a coarse smoke case, then the AMR resolution study;
- generate the pastel-style validation figure and a JSON/CSV metrics record.

No observational validation result is claimed by this planning document.
