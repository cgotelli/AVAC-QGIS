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
- [Real-terrain volume conservation and positivity](AVAC/Real_terrain_conservation/Real_terrain_conservation.ipynb)
- [Static Coulomb and cohesive arrest](AVAC/Static_cohesive_arrest/Static_cohesive_arrest.ipynb)
- [Curvature contribution to normal stress](AVAC/Curvature_normal_stress/Curvature_normal_stress.ipynb)
- [Section 4 AVAC verification figures](AVAC/Paper_figures/AVAC_verification_figures.ipynb)

## AVAC observational validation

- [Selected Nordkette 2022 field case and validation protocol](AVAC/Observations/Nordkette_2022/README.md)

The observational case is currently a documented implementation plan, not a
completed validation result, and is therefore not yet part of the notebook run
order below.

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
- [Main-paper WAVE verification figure](WAVE/Paper_figures/WAVE_verification_figures.ipynb)

The six SWASHES notebooks build the pinned 1.05.01 analytical generator
included under vendor; the generator's CeCILL licenses are retained with its
source.

## AVAC-to-WAVE coupling verification

- [Production-path source and conservation runs](COUPLING/Paper_figures/Coupling_verification.ipynb)
- [Coupling manuscript figure without solver reruns](COUPLING/Paper_figures/Coupling_verification_figures.ipynb)

The source notebook writes prescribed native AVAC frames, calls the same
shoreline converter used by the plugin, runs the WAVE Fortran source update,
and checks volume and both horizontal momentum components on uniform and AMR
grids. The separate figure notebook reads only the generated ledgers, so
figures can be restyled without rerunning either solver after the source
notebook has run.

## ISeeSnow intercomparison

- [Idealized topography, Voellmy](ISeeSnow/IdealizedTopo/IdealizedTopo.ipynb)
- [Real topography, Voellmy](ISeeSnow/RealTopo/RealTopo.ipynb)
- [Idealized topography, Coulomb only](ISeeSnow/CoulombOnly/CoulombOnly.ipynb)
- [Three-case manuscript figure](ISeeSnow/Paper_figures/ISeeSnow_intercomparison_figures.ipynb)

These notebooks download the official ISeeSnow 1.0 repository, use its
prescribed inputs without calibration, create standard-format AVAC submissions,
and compare only peer rasters whose grids match exactly. No peer output is used
to tune the AVAC run.

## Complete notebook run order

For a clean checkout, run the following notebooks in order. Each simulation
notebook creates the products consumed by the corresponding figure notebook.

1. `AVAC/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb`
2. `AVAC/Kerswell_Coulomb/Kerswell_Coulomb.ipynb`
3. `AVAC/Coulomb_sloping_bed/Coulomb_sloping_bed.ipynb`
4. `AVAC/Real_terrain_conservation/Real_terrain_conservation.ipynb`
5. `AVAC/Static_cohesive_arrest/Static_cohesive_arrest.ipynb`
6. `AVAC/Curvature_normal_stress/Curvature_normal_stress.ipynb`
7. `AVAC/Paper_figures/AVAC_verification_figures.ipynb`
8. `WAVE/01_transcritical_shock/transcritical_shock.ipynb`
9. `WAVE/02_macdonald_smooth_shock/macdonald_smooth_shock.ipynb`
10. `WAVE/03_ritter_dry_dam_break/ritter_dry_dam_break.ipynb`
11. `WAVE/04_thacker_planar_paraboloid/thacker_planar_paraboloid.ipynb`
12. `WAVE/05_macdonald_pseudo2d_supercritical/pseudo2d_supercritical.ipynb`
13. `WAVE/06_macdonald_pseudo2d_subcritical/pseudo2d_subcritical.ipynb`
14. `WAVE/07_baines_flow_over_bump/Baines_flow_over_bump.ipynb`
15. `WAVE/08_amr_parallel/AMR_OpenMP.ipynb`
16. `WAVE/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb`
17. `WAVE/Paper_figures/WAVE_verification_figures.ipynb`
18. `COUPLING/Paper_figures/Coupling_verification.ipynb`
19. `COUPLING/Paper_figures/Coupling_verification_figures.ipynb`
20. `ISeeSnow/IdealizedTopo/IdealizedTopo.ipynb`
21. `ISeeSnow/RealTopo/RealTopo.ipynb`
22. `ISeeSnow/CoulombOnly/CoulombOnly.ipynb`
23. `ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb`

The ISeeSnow real-topography comparison contains ten peer models because the
official Table C1 does not report a real-topography TITAN2D result; the two
idealized comparisons contain eleven peers.

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
