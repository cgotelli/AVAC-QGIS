# AVAC4QGIS validation suite

This directory contains the reproducible verification and intercomparison
notebooks for the AVAC and WAVE source solvers shipped with AVAC4QGIS.

## Requirements

- Python 3.10 or newer and Jupyter;
- GNU Make (called `make`, `gmake`, or `mingw32-make`) and gfortran;
- a C++ compiler for the SWASHES analytical generator;
- internet access on the first ISeeSnow run.

On Windows, install Git Bash as well as the compilers. The notebooks detect
Windows `xgeoclaw.exe` files and use the repository's Windows build helper;
SWASHES is compiled directly from its pinned C++ files because its upstream
Makefile relies on POSIX `find`. macOS and Linux use the normal source
Makefiles.

Open any notebook and run its cells in order. Its first code cell locates the
repository and installs the avac4qgis-validation package and its Python
dependencies into the active kernel. If the requested AVAC or WAVE executable
is absent, the shared package compiles it from the source in this repository.

Generated solver trees, result tables, figures, downloaded datasets, and
compiled programs are excluded from Git. Every notebook therefore starts from
the case definition and recreates the quantities it presents.

## AVAC analytical verification

- [2008 WRR dry-bottom sloping bed](AVAC/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb)
- [Kerswell horizontal Coulomb dam break](AVAC/Kerswell_Coulomb/Kerswell_Coulomb.ipynb)
- [Coulomb dam break on a sloping bed](AVAC/Coulomb_sloping_bed/Coulomb_sloping_bed.ipynb)

## WAVE water verification

- [Transcritical flow with shock](WAVE/01_transcritical_shock/transcritical_shock.ipynb)
- [MacDonald smooth transition and shock](WAVE/02_macdonald_smooth_shock/macdonald_smooth_shock.ipynb)
- [Ritter dry-domain dam break](WAVE/03_ritter_dry_dam_break/ritter_dry_dam_break.ipynb)
- [Thacker planar surface in a paraboloid](WAVE/04_thacker_planar_paraboloid/thacker_planar_paraboloid.ipynb)
- [MacDonald pseudo-2D supercritical flow](WAVE/05_macdonald_pseudo2d_supercritical/pseudo2d_supercritical.ipynb)
- [MacDonald pseudo-2D subcritical flow](WAVE/06_macdonald_pseudo2d_subcritical/pseudo2d_subcritical.ipynb)
- [Baines flow over a bump and lake at rest](WAVE/07_baines_flow_over_bump/Baines_flow_over_bump.ipynb)
- [AMR and OpenMP reproducibility](WAVE/08_amr_parallel/AMR_OpenMP.ipynb)
- [2008 WRR dry-bottom sloping bed](WAVE/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb)

The six SWASHES notebooks build the pinned 1.05.01 analytical generator
included under vendor; the generator's CeCILL licenses are retained with its
source.

## ISeeSnow intercomparison

- [Idealized topography, Voellmy](ISeeSnow/IdealizedTopo/IdealizedTopo.ipynb)
- [Real topography, Voellmy](ISeeSnow/RealTopo/RealTopo.ipynb)
- [Idealized topography, Coulomb only](ISeeSnow/CoulombOnly/CoulombOnly.ipynb)

These notebooks download the official ISeeSnow 1.0 repository, use its
prescribed inputs without calibration, create standard-format AVAC submissions,
and compare only peer rasters whose grids match exactly. No peer output is used
to tune the AVAC run.

## Reference material

- The water cases follow the published [SWASHES benchmark library](https://www.idpoisson.fr/swashes/).
- The avalanche intercomparison uses the official [ISeeSnow repository](https://github.com/avaframe/ISeeSnow/tree/1.0).
- The WRR and Coulomb constructions are implemented from the analytical
  definitions used in the version-pinned Clawpack tutorial accompanying these
  solver sources; the analytical routines are separate from solver execution.

## Notebook design

Scientific and numerical functions live in avac4qgis_validation or in the
published case drivers. Notebooks contain only the narrative, explicit case
parameters, execution calls, diagnostics, and presentation calls. Run
python validation/build_notebooks.py after changing that narrative structure;
the generator always clears execution counts and stored outputs.
