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

### macOS agent handoff

The macOS package must be rebuilt from this version; do not reuse either 0.5.11
runtime. Both solver binaries and their packaged backends/manifests are release
inputs. The Windows-only makefiles and builder are not used on macOS.

1. Pull `main` and verify `avac_qgis/metadata.txt` reports version `0.5.12`.
2. Build both Apple Silicon solvers with the normal makefiles and OpenMP:

   ```bash
   export CLAW="$PWD/avac-main/clawpack-v5.14.0"
   export CLAW_PYTHON="$(command -v python3)"
   export FC="$(command -v gfortran)"
   export CLAW_FC="$FC"
   make -C avac-main/src/AVAC -B new REAL_WORLD_TOPO=1
   make -C avac-main/src/WAVE -B new
   ```

3. Build fresh AVAC and WAVE arm64 runtime archives. Use a new/empty output
   directory because the runtime builder deliberately refuses to overwrite an
   existing artifact:

   ```bash
   DIST="$PWD/dist/macos-arm64-0.5.12"
   python3 tools/build_macos_arm64_runtime.py \
     --solver avac-main/src/AVAC/xgeoclaw \
     --backend avac-main/src/AVAC --backend-name AVAC \
     --archive-prefix avac \
     --claw-root avac-main/clawpack-v5.14.0 \
     --output "$DIST" --version 0.5.12 --archive-only
   python3 tools/build_macos_arm64_runtime.py \
     --solver avac-main/src/WAVE/xgeoclaw \
     --backend avac-main/src/WAVE --backend-name Wave \
     --archive-prefix wave \
     --claw-root avac-main/clawpack-v5.14.0 \
     --output "$DIST" --version 0.5.12 --archive-only
   ```

4. Build and validate the installable plugin:

   ```bash
   python3 tools/build_plugin_package.py \
     --runtime-archive "$DIST/avac-runtime-macos-arm64-0.5.12.tar.gz" \
     --runtime-version 0.5.12 \
     --wave-runtime-archive "$DIST/wave-runtime-macos-arm64-0.5.12.tar.gz" \
     --wave-runtime-version 0.5.12 \
     --dist "$DIST"
   python3 tools/validate_release.py \
     --dist "$DIST" --platform macos-arm64
   ```

5. Run the checks in `avac_qgis/tests/MANUAL_MACOS_VERIFICATION.md`, paying
   particular attention to `init.avacbin`, AVAC/WAVE OpenMP startup, first-use
   runtime installation, and loading a WAVE maximum map after its temporal
   raster is already present.
6. Add `avac_qgis-0.5.12-macos-arm64.zip` and its `.sha256` file to the existing
   GitHub `v0.5.12` release. The Windows assets are published first.

## 0.5.11 — 2026-08-27

- Corrected and republished the AVAC4QGIS user-interface guide.
