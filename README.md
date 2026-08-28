# AVAC4QGIS

AVAC4QGIS integrates avalanche simulation and optional avalanche-generated
lake-wave modeling into QGIS. The plugin provides case preparation, managed
solver execution, temporal visualization, profiles, gauges, and map export
without requiring users to configure Clawpack or a compiler.

The current release is **0.5.12** and targets **QGIS 3.44 LTS**.

## Installation

1. Download the installable package from the
   [AVAC4QGIS 0.5.12 release](https://github.com/cgotelli/AVAC-QGIS/releases/tag/v0.5.12).
   The macOS Apple Silicon package is
   [`avac_qgis-0.5.12-macos-arm64.zip`](https://github.com/cgotelli/AVAC-QGIS/releases/download/v0.5.12/avac_qgis-0.5.12-macos-arm64.zip).
   The 64-bit Windows package is
   [`avac_qgis-0.5.12-windows-amd64.zip`](https://github.com/cgotelli/AVAC-QGIS/releases/download/v0.5.12/avac_qgis-0.5.12-windows-amd64.zip).
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the downloaded ZIP and open **AVAC4QGIS** from the Plugins menu.

Each release ZIP contains a managed solver runtime. Running the installed
plugin does not require GNU Make, a Fortran compiler, or a separate Clawpack
installation.

The GitHub source-code ZIP does **not** contain the managed solver runtimes and
is not an installable QGIS package. Use the release asset linked above when
installing AVAC4QGIS on another computer.

## Documentation

The [AVAC4QGIS User Interface Reference](docs/AVAC_QGIS_UI_REFERENCE.pdf)
explains the simulation workflow and every control in the graphical interface.
The same guide is available from the plugin's **Help** button.

The editable LaTeX source is
[`docs/AVAC_QGIS_UI_REFERENCE.tex`](docs/AVAC_QGIS_UI_REFERENCE.tex). Its
screenshots are stored in [`docs/images`](docs/images/) and can be regenerated
under the QGIS Python environment with
[`docs/generate_ui_screenshots.py`](docs/generate_ui_screenshots.py). Run
`latexmk -pdf AVAC_QGIS_UI_REFERENCE.tex` from `docs/` to rebuild the PDF.

## Basic workflow

Choose an **AVAC Working Directory**, select the terrain DEM and release
polygon, configure the physical parameters, and prepare and run AVAC. The
working directory contains copied inputs, isolated runs, results, and exports;
the managed runtime remains separate.

The optional **Enable Lake-Wave Extension** switch adds the WAVE parameter and
run pages. A WAVE scenario reads a completed AVAC result without modifying it
and transfers the avalanche contribution through the prepared internal
shoreline coupling. Before running AVAC, the lake polygon can be selected from
QGIS or derived directly from the terrain DEM by entering a water-surface
elevation and clicking a point inside the connected basin. AVAC and WAVE maps,
profiles, gauges, and time series are handled together in the final
**Results** page.

## Validation notebooks

The [`validation`](validation/) directory contains the reproducible scientific
checks in three groups:

- [`AVAC`](validation/AVAC/) — water-limit and Coulomb analytical benchmarks;
- [`WAVE`](validation/WAVE/) — SWASHES water benchmarks, the Baines
  well-balanced test, the WRR sloping-bed case, and AMR/OpenMP reproducibility;
- [`ISeeSnow`](validation/ISeeSnow/) — the three official ISeeSnow avalanche
  intercomparison cases.

Every case has an independent Jupyter notebook. The notebooks install the
shared Python validation package into their active kernel, execute the current
source solver, calculate quantitative diagnostics, and recreate their
comparison figures. Generated solver output and figures are intentionally not
versioned.

Running validation from a clean checkout requires Python 3.10 or newer, Jupyter,
GNU Make, and `gfortran`. The SWASHES notebooks also require a C++ compiler.
The ISeeSnow notebooks download the pinned official 1.0 dataset on first use.

## Repository layout

- [`avac_qgis`](avac_qgis/) — QGIS plugin source;
- [`avac-main/src/AVAC`](avac-main/src/AVAC/) — AVAC solver source;
- [`avac-main/src/WAVE`](avac-main/src/WAVE/) — WAVE solver source;
- [`avac-main/clawpack-v5.14.0`](avac-main/clawpack-v5.14.0/) — pinned shared
  Clawpack source;
- [`validation`](validation/) — executable notebooks, drivers, analytical
  routines, and validation support package;
- [`docs`](docs/) — published user documentation;
- [`tools`](tools/) — runtime and plugin package builders.

Compiled executables, managed runtime archives, installable release ZIPs, and
generated validation products are excluded from source control.

## Third-party software

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the included solver and
analytical-reference dependencies and their retained license notices.
