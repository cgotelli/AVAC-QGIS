# Nordkette 2022 observational validation

## Selected case

This directory is reserved for the AVAC reconstruction of controlled avalanche
experiment `#20220025`, released on 22 February 2022 in the Seilbahnrinne at
Nordkette, Innsbruck, Austria. The reference study is:

- Neuhauser, M., Köhler, A., Wirbel, A., Oesterle, F., Fellin, W.,
  Gerstmayr, J., Dressler, F., and Fischer, J.-T. (2025), *Particle and front
  tracking in experimental and computational avalanche dynamics*, Natural
  Hazards and Earth System Sciences, 25, 4185–4202,
  <https://doi.org/10.5194/nhess-25-4185-2025>.

The paper compares a thickness-integrated dense-flow solver with a controlled
full-scale avalanche observed by mobile radar and three in-flow GNSS sensors.
The authors provide the DEM, release polygon, path, split point, radar geometry,
and the two published best-fit configurations in an open supplement:

- <https://doi.org/10.5194/nhess-25-4185-2025-supplement>
- supplement ZIP SHA-256:
  `7680a6b86e8bfe1df852b6a3951e812e15cd5017ae23ec750a6dfa6dcf39ea67`

The article and supplement are distributed under CC BY 4.0. Any copied or
derived data must retain the citation, licence, and source checksums.

## Why this case was chosen

Nordkette is the closest recent published field test to AVAC's present model
scope:

1. The observed event is treated as a dense-flow avalanche, rather than as a
   powder-cloud case.
2. The comparison model is depth integrated, as is AVAC.
3. The published basal resistance contains Coulomb friction, Voellmy drag, and
   a minimum shear stress. These terms map directly to AVAC's
   `cohesive_Voellmy` law.
4. The supplied best-fit configurations do not activate entrainment. The case
   therefore does not require adding a physical process that AVAC does not
   currently solve.
5. The experiment provides dynamic observations of the front, not only a final
   deposit outline.

The alternatives reviewed were less suitable. The 2023 Knollgraben and Pichler
Erschbaum study states that the authors cannot share the event data. The open
Eiskar and Wolfsgruben examples used by OpenFOAM-avalanche rely on entrainment
and, in part, powder-cloud dynamics. They remain useful future tests, but using
them now would mix validation of AVAC with physics that are outside its current
scope.

## Published inputs and reference quantities

The supplement provides a 5 m DEM (`Nordkette.asc`, 830 by 771 cells), a
release polygon in MGI / Austria GK West (EPSG:31254), and the radar field of
view. The release polygon has a planimetric area of approximately
2755.75 m². With the prescribed uniform release thickness of 0.7 m, its
planimetric release volume is approximately 1929.02 m³.

The first AVAC run will use the published front-fit resistance parameters
without AVAC-specific tuning:

| Quantity | Value |
|---|---:|
| Coulomb coefficient, $\mu$ | 0.40 |
| Voellmy coefficient, $\xi$ | 5000 m s⁻² |
| Minimum shear stress / AVAC cohesion, $C$ | 125 Pa |
| Release thickness | 0.70 m |

The primary observational targets reported in the article are:

| Quantity | Observation |
|---|---:|
| Maximum radar approach velocity | 26 m s⁻¹ |
| Projected event travel length | 690 m |
| Maximum event altitude difference | 400 m |
| Radar-front position uncertainty | approximately ±1–2 m |

The article reports a 4.34 m front-position RMSE and a 27.5 m s⁻¹ maximum
front velocity for its own front-fit simulation. Those values are an external
model reference, not acceptance limits for AVAC.

## Validation protocol

The case will be implemented as a notebook that performs every step from a
clean checkout:

1. Download the DOI-pinned supplement and verify its SHA-256 before extracting
   any files.
2. Prepare the supplied DEM and release polygon through the same preprocessing
   path used by AVAC4QGIS.
3. Run the normal AVAC solver with `cohesive_Voellmy`; no event-specific solver
   branch or source-code switch is permitted.
4. Transform the numerical front into the supplied radar range coordinate and
   compare it with the observed front only over the radar's valid field of
   view.
5. Report front-position RMSE, maximum approach velocity, arrival-time error at
   fixed ranges, final flow extent, mass balance, and mesh sensitivity.
6. Produce the validation figure using the paper's pastel plotting style and
   write a machine-readable summary containing the solver and source-data
   hashes.

The wet/dry threshold and front-extraction rule must be declared before looking
at the score and then held fixed for all resolution levels. A sensitivity plot
will show whether the conclusion changes over a physically reasonable
threshold interval.

The front-fit parameters above are already informed by this event through the
reference paper. Consequently, the first result must be described as an event
reconstruction or back-calculation, not as an independent prediction. Any
AVAC-specific calibration will be kept separate from the untuned parameter
transfer and will use a predeclared calibration/evaluation split.

## Measurement-data limitation

The supplement contains the complete simulation initialization but not the raw
radar or GNSS time series. The article makes the processed front visible in its
high-resolution Figure 2 and provides summary tables as downloadable XLSX
files. A provisional notebook can therefore digitize the published black front
trace reproducibly from:

<https://nhess.copernicus.org/articles/25/4185/2025/nhess-25-4185-2025-f02.png>

The figure SHA-256 at selection time is
`2b34ead5bb5978375a78d90a30c1db6ce776d4928c62a2c3a9989d471e94376a`.
Digitization uncertainty must be added to the stated radar uncertainty and the
digitized series must be identified as derived data. Before using the case as
the manuscript's definitive observational validation, the preferred route is
to request the numerical tracked-front series from the corresponding authors
and replace the digitized trace without changing the predeclared metrics.

The radar loses sight of the flow near the bottom of the track. Its apparent
deceleration below roughly 250 m radar range must not be interpreted or scored
as physical stopping. The reported 690 m event travel length is retained only
as a secondary extent check.

The AvaNodes measure individual synthetic particles, whereas AVAC predicts
Eulerian depth-averaged flow. Their trajectories are useful context but are not
a primary acceptance criterion unless a documented tracer method is added.

## Next implementation steps

- add a pinned data-download and provenance helper;
- add the notebook and a small, testable Python case driver;
- reproduce the DEM, release, and radar geometry before running AVAC;
- implement and unit-test front extraction in radar coordinates;
- run a coarse smoke case, then the AMR resolution study;
- generate the comparison figure and a JSON/CSV metrics record;
- request the processed radar-front series from the study authors.

No observational validation result is claimed by this planning document.
