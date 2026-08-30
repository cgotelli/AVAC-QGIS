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

Generated submissions, copied inputs, reports, plots, and raw solver results
are intentionally not committed. The development-only
[Idealized Coulomb velocity audit](IDEALIZED_COULOMB_VELOCITY_AUDIT.md)
records the wet--dry numerical issue found during the manuscript reruns and
the corrected full-run diagnostics; it is not manuscript text. See the
[validation suite index](../README.md) for links and requirements.
