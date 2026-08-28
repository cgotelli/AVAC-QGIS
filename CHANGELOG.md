# AVAC4QGIS changelog

## 0.5.12 — 2026-08-28

This release adds the first native Windows AMD64 package and contains the
cross-platform solver, preprocessing, runtime-cache, and WAVE-result fixes made
since 0.5.11.

### User-visible changes

- Added a plug-and-play Windows AMD64 package containing the AVAC and WAVE
  solvers, Clawpack Python sources, GNU Fortran/OpenMP runtime libraries, and
  the direct-execution backends. Users do not need Python packages, a compiler,
  Clawpack, or MinGW to run the packaged plugin.
- AVAC initial conditions are now written as `init.avacbin`, a compact,
  versioned little-endian binary raster. This avoids formatting and parsing
  millions of repeated XYZ coordinates while preserving the numerical values
  produced by the legacy `init.xyz` writer. The solver still auto-detects and
  reads legacy text initial-condition files.
- Fixed AVAC OpenMP scaling by moving FGmax interpolation out of the global
  fixed-grid lock. Shared FGmax initialization and maxima updates remain
  protected, while patch-local interpolation runs concurrently.
- Prevented a hidden refinement DEM selector from silently choosing the first
  raster in the QGIS project. Fine terrain may still improve terrain sampling,
  but zoom FGmax/FGout products are now created only when AMR refinement is
  actually greater than level 1.
- Improved the non-square DEM error to report the selected layer and its X/Y
  resolutions.
- Fixed same-version runtime caching. Runtime descriptors now include a hash of
  the complete runtime manifest, so an updated package replaces an older cached
  solver even when the semantic version is unchanged.
- Fixed WAVE result loading on Windows. Valid derived rasters and diagnostics
  are fingerprinted and reused, avoiding attempts to replace a GeoTIFF that is
  already open in QGIS. If raw WAVE output changes, regenerated rasters use
  immutable fingerprinted filenames so existing map layers remain valid.
- Stale WAVE result error logs are cleared after a successful retry.

### Build and release changes

- Added `avac-main/src/AVAC/Makefile.windows` and
  `avac-main/src/WAVE/Makefile.windows`. The normal `Makefile` files remain the
  macOS/Linux entry points.
- Added `tools/build_windows_solvers.py` to consolidate the long Clawpack source
  lists before invoking `mingw32-make`, avoiding the Windows command-line length
  limit.
- Added `tools/build_windows_release.ps1` to rebuild both solvers, assemble both
  managed runtimes, package the QGIS plugin, and run release validation.
- Added `tools/build_windows_plugin_package.py` and strengthened both platform
  package builders and `tools/validate_release.py` with runtime-manifest identity
  checks.
- Added `tools/convert_init_xyz.py` for converting legacy AVAC XYZ initial
  conditions to the new binary format.
- Added and updated regression tests for binary qinit ordering/precision,
  runtime cache replacement, hidden refinement selection, FGmax locking, and
  Windows-safe WAVE result caching.

## 0.5.11 — 2026-08-27

- Corrected and republished the AVAC4QGIS user-interface guide.
