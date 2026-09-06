# Third-party notices

The packaged AVAC-QGIS runtime includes:

- **Clawpack 5.14.0** — each Windows runtime contains its BSD license at
  `licenses/LICENSE` (relative to the extracted runtime root).
- **GCC 13.2.0 runtime libraries** (`libgfortran`, `libgomp`, and `libgcc_s`)
  — `licenses/gcc-COPYING3` and `licenses/gcc-COPYING.RUNTIME` contain the
  GPL and runtime exception. `libquadmath` has a separate Library/Lesser GPL
  license; retain `gcc-COPYING.LIB` and `libquadmath-COPYING.LIB` as well.
- **MinGW-w64 11.0.1 / winpthreads** — `licenses/mingw-w64-COPYING` and
  `licenses/winpthreads-COPYING` retain the applicable project notices.
- **dlfcn-win32 1.4.1** (`libdl.dll`) — `licenses/dlfcn-win32-COPYING` and
  the unmodified `dlfcn-win32-dlfcn.c` retain its permission and copyright
  notices. The dated WinLibs build recipe identifies this component version.
- **Windows toolchain source access** — `licenses/WINDOWS_RUNTIME_SOURCES.json`
  records upstream source/download links, notice hashes and the exact DLL
  hashes. The offline notice bundle is retained under
  `tools/windows_runtime_licenses`; packaging refuses unreviewed DLL changes.
  These libraries are unmodified, dynamically linked, and their source is
  available from the identified upstream projects. QGIS's own Python/GDAL/
  NumPy/Matplotlib components and Windows system libraries are not bundled
  by this plugin. The legacy Strawberry aggregate `License.rtf` is retained
  as supplemental information, not as a substitute for component licenses.
- **AVAC backend** — the packaged `setrun.py` is identified by hash in the
  runtime manifest.
- **SWASHES 1.05.01** — the analytical reference generator used by the
  published validation notebooks is included under
  `validation/vendor/SWASHES-1.05.01`. Its English and French CeCILL licenses
  are retained in that directory.

This inventory records packaged technical components and notices. It is not a
legal determination of redistribution obligations. Public distribution should
receive a version-specific licensing and corresponding-source review.
