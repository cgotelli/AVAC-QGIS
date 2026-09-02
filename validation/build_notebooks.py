#!/usr/bin/env python3
"""Generate the public, output-free validation notebooks."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
KERNEL = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.10"},
}


def markdown(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {},
        "outputs": [], "source": text.splitlines(keepends=True),
    }


def environment(family: str, name: str, *, extra: str = "") -> list[dict]:
    prerequisite = (
        "The first code cell installs the repository's validation package and Python "
        "dependencies into the active kernel. A clean checkout also needs GNU Make and "
        "gfortran to compile the selected solver on first use."
    )
    if extra:
        prerequisite += " " + extra
    return [
        markdown("## Reproducible environment\n\n" + prerequisite + "\n"),
        code(
            "from pathlib import Path\n"
            "SEARCH_ROOT = Path.cwd().resolve()\n"
            "REPOSITORY = next(candidate for candidate in (SEARCH_ROOT, *SEARCH_ROOT.parents) "
            "if (candidate / 'validation' / 'pyproject.toml').is_file())\n"
            "%pip install -q -e {REPOSITORY / 'validation'}\n"
        ),
        code(
            "import os\n"
            "from avac4qgis_validation import validation_case\n"
            f"case = validation_case('{family}', '{name}')\n"
            "CORES = max(1, os.cpu_count() or 1)\n"
            "case.path\n"
        ),
    ]


def notebook(cells: list[dict]) -> dict:
    for index, cell in enumerate(cells, start=1):
        cell["id"] = f"cell-{index:02d}"
    return {"cells": cells, "metadata": KERNEL, "nbformat": 4, "nbformat_minor": 5}


def write(relative: str, cells: list[dict]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook(cells), indent=1) + "\n", encoding="utf-8")


def avac_notebooks() -> None:
    name = "2008_WRR_sloping_bed"
    cells = [
        markdown(
            "# 2008 WRR dry-bottom sloping-bed benchmark — AVAC\n\n"
            "This notebook verifies AVAC's water limit against the analytical dry-front and "
            "rear-wave solution used in the original GeoClaw/TsunamiClaw benchmark. The "
            "one-dimensional problem is extruded across a five-cell periodic strip and the "
            "centerline is evaluated.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Physical and numerical definition\n\n"
            "The bed is a frictionless 10° slope. The initial water depth is the exact "
            "triangular wedge $h=H_0(1-x/x_b)$ on $x_b\\leq x\\leq0$, with $H_0=1$ m and "
            "$x_b=-H_0/\\tan(10°)$. The upstream boundary is a wall, the downstream boundary "
            "is extrapolating, and the transverse boundaries are periodic. AVAC is configured "
            "in its frictionless water mode; no avalanche rheology contributes to this run. "
            "Three AMR levels use two successive 4:1 longitudinal refinements. Narrow, "
            "overlapping space--time corridors are prescribed around the two independently "
            "known analytical boundary paths; the analytical values allocate resolution but "
            "are never supplied to the state or flux. Distant cells remain on the 40 mm base mesh. "
            "The triangular qinit raster is sampled independently at the 2.5 mm finest spacing, "
            "so the coarse far field does not alter the analytical initial profile. The downstream "
            "limit is extended from the tutorial's 40 m to 60 m so the advancing front remains "
            "inside the computational domain through the final output.\n"
        ),
        code(
            "BASE_DX_M = 0.04\nAMR_LEVELS = 3\nAMR_RATIO = 4\n"
            "SPEED_TOLERANCE_M_S = 0.02\nT_FINAL_S = 5.0\nOUTPUT_FRAMES = 20\n"
            "RUN_NAME = os.environ.get('AVAC_VALIDATION_RUN_NAME', 'publication_amr')\n"
            "case.run('run_avac_validation.py', '--dx', BASE_DX_M, '--t-final', T_FINAL_S, "
            "'--nout', OUTPUT_FRAMES, '--cores', CORES, '--amr-levels', AMR_LEVELS, "
            "'--amr-ratio', AMR_RATIO, '--speed-tolerance', SPEED_TOLERANCE_M_S, "
            "'--ny', 5, '--max1d', 1000, '--output-root', case.path / RUN_NAME)\n"
        ),
        markdown("## Quantitative diagnostics\n\nThe summary reports front errors, rear-wave errors, initial-condition error, mass variation, grid spacing, core count, and the exact solver hash.\n"),
        code("summary = case.json(f'{RUN_NAME}/results/summary.json')\nsummary\n"),
        markdown("## Comparison with theory\n\nThe marker curves are AVAC centerline measurements; continuous analytical curves are evaluated independently by the driver.\n"),
        code(
            "case.show(f'{RUN_NAME}/figures/wrr_characteristics_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/wrr_depth_profiles_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/wrr_surface_profile_avac.png')\n"
        ),
    ]
    write(f"AVAC/{name}/WRR_sloping_bed.ipynb", cells)

    name = "Kerswell_Coulomb"
    cells = [
        markdown(
            "# Kerswell horizontal Coulomb dam break — AVAC\n\n"
            "This notebook tests Coulomb spreading and natural arrest against Kerswell's "
            "analytical solution. It evaluates both moving boundaries and depth profiles.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Physical and numerical definition\n\n"
            "A one-meter-deep column spreads on a horizontal bed with basal Coulomb coefficient "
            "$\\mu=0.1$. The state is uniform across a five-cell wall-bounded strip. There is "
            "no Voellmy turbulent term and no fitted stopping threshold; arrest must follow from "
            "the Coulomb/static-yield implementation. Three AMR levels refine narrow corridors "
            "around the independently known boundary paths from a 40 mm base mesh to a 2.5 mm "
            "finest mesh while leaving distant regions coarse.\n"
        ),
        code(
            "BASE_DX_M = 0.04\nAMR_LEVELS = 3\nAMR_RATIO = 4\n"
            "SPEED_TOLERANCE_M_S = 0.02\nT_FINAL_S = 10.0\nOUTPUT_FRAMES = 40\n"
            "RUN_NAME = os.environ.get('AVAC_VALIDATION_RUN_NAME', 'publication_amr')\n"
            "case.run('run_avac_validation.py', '--dx', BASE_DX_M, '--t-final', T_FINAL_S, "
            "'--nout', OUTPUT_FRAMES, '--cores', CORES, '--case-name', RUN_NAME, "
            "'--amr-levels', AMR_LEVELS, '--amr-ratio', AMR_RATIO, "
            "'--speed-tolerance', SPEED_TOLERANCE_M_S, '--max1d', 1000)\n"
        ),
        markdown("## Quantitative diagnostics\n\nFront/rear errors, arrested-state measures, mass history, and solver identity are written by the same run.\n"),
        code("summary = case.json(f'{RUN_NAME}/results/summary.json')\nsummary\n"),
        markdown("## Comparison with Kerswell theory\n"),
        code(
            "case.show(f'{RUN_NAME}/figures/figure_8_7_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/figure_8_10_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/profiles_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/avac_arrest_and_mass.png')\n"
        ),
    ]
    write(f"AVAC/{name}/Kerswell_Coulomb.ipynb", cells)

    name = "Coulomb_sloping_bed"
    cells = [
        markdown(
            "# Coulomb dam break on a sloping bed — AVAC\n\n"
            "This Chapter 8 benchmark combines a 5° incline with Coulomb basal resistance and "
            "compares AVAC's quasi-one-dimensional centerline with the analytical boundaries "
            "and profiles.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Physical and numerical definition\n\n"
            "The released depth is $H_0=1$ m, the Coulomb coefficient is $\\mu=0.2$, and the "
            "bed angle is 5°. A five-cell transverse strip preserves the intended one-dimensional state. "
            "Three AMR levels refine narrow corridors around the independently known boundary "
            "paths from a 30 mm base mesh to a 1.875 mm finest mesh; this is finer at the "
            "fronts than the preceding 2.5 mm result.\n"
        ),
        code(
            "BASE_DX_M = 0.03\nAMR_LEVELS = 3\nAMR_RATIO = 4\n"
            "SPEED_TOLERANCE_M_S = 0.02\nT_FINAL_S = 6.0\nOUTPUT_FRAMES = 30\n"
            "RUN_NAME = os.environ.get('AVAC_VALIDATION_RUN_NAME', 'publication_amr')\n"
            "case.run('run_avac_validation.py', '--dx', BASE_DX_M, '--ny', 5, '--t-final', "
            "T_FINAL_S, '--nout', OUTPUT_FRAMES, '--case-name', RUN_NAME, '--cores', CORES, "
            "'--amr-levels', AMR_LEVELS, '--amr-ratio', AMR_RATIO, "
            "'--speed-tolerance', SPEED_TOLERANCE_M_S, '--max1d', 1000, '--replace')\n"
        ),
        code("summary = case.json(f'{RUN_NAME}/results/summary.json')\nsummary\n"),
        markdown("## Analytical comparison\n"),
        code(
            "case.show(f'{RUN_NAME}/figures/boundary_positions_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/boundary_positions_dimensionless_avac_vs_theory.png', "
            "f'{RUN_NAME}/figures/characteristics_dimensionless.png', "
            "f'{RUN_NAME}/figures/flow-depth_dimensionless.png')\n"
        ),
    ]
    write(f"AVAC/{name}/Coulomb_sloping_bed.ipynb", cells)

    name = "Real_terrain_conservation"
    cells = [
        markdown(
            "# Real-terrain volume conservation and positivity — AVAC\n\n"
            "This focused property test checks the numerical invariants needed before the "
            "full Coulomb verification is repeated. It uses the normal AVAC executable and "
            "the same solver path as every operational case.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Physical and numerical definition\n\n"
            "A compact two-dimensional release moves over a smooth inclined surface with a "
            "ridge and transverse undulations. All four boundaries are closed, and there is "
            "no mass source, so the discrete material volume must remain constant. The same "
            "initial state is run on a uniform 0.20 m mesh and with two dynamically regridded "
            "AMR levels. The AMR run deliberately creates and removes fine patches as the "
            "wet--dry front moves. The case is not calibrated to a site or analytical profile; "
            "it tests nonnegative depth and conservation properties that must hold for every "
            "AVAC simulation.\n"
        ),
        code(
            "VARIANT = 'current'\n"
            "case.run('run_conservation_validation.py', '--variant', VARIANT, "
            "'--mode', 'both', '--cores', CORES)\n"
        ),
        markdown(
            "## Acceptance diagnostics\n\n"
            "Native AMR output is integrated as a non-overlapping hierarchy: coarse cells "
            "covered by finer patches are excluded. The summary reports volume variation, "
            "minimum active depth, boundary clearance, achieved AMR level, patch-layout "
            "changes, and the exact solver hash.\n"
        ),
        code("summary = case.json(f'results/{VARIANT}_summary.json')\nsummary\n"),
        code("case.show(f'figures/{VARIANT}_real_terrain_conservation.png')\n"),
    ]
    write(f"AVAC/{name}/Real_terrain_conservation.ipynb", cells)

    name = "Static_cohesive_arrest"
    cells = [
        markdown(
            "# Static Coulomb and cohesive arrest — AVAC\n\n"
            "This focused verification exercises the production AVAC executable immediately "
            "below and above the static-yield boundary. Each physical state is mirrored to "
            "separate the constitutive transition from a left/right numerical bias.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Physical and numerical definition\n\n"
            "A one-meter vertical-depth layer initially rests on a planar bed. Two Coulomb "
            "cases place the bed slope below and above $\\mu=0.2$. Two cohesive-Voellmy "
            "cases use a 0.30 bed slope and cohesion 2% below or above the analytical critical "
            "value $C_{cr}=\\rho g h\\cos^2(\\phi)[\\tan(\\phi)-\\mu]$. Turbulent resistance "
            "is negligible at onset and is assigned $\\xi=10^{12}$ m s$^{-2}$. Every case is "
            "run with both signs of the bed slope. Two additional symmetric triangular "
            "Coulomb deposits exercise the wet/dry interface below and above yield.\n"
        ),
        code(
            "case.run('run_static_cohesive_validation.py', '--cores', CORES)\n"
        ),
        markdown(
            "## Acceptance diagnostics\n\n"
            "Sub-yield states must remain at machine rest; super-yield states must accelerate "
            "downslope. Mirrored inclined layers and the two sides of each compact deposit "
            "must agree, with no material transverse velocity.\n"
        ),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        code("case.show('figures/static_cohesive_arrest.png')\n"),
    ]
    write(f"AVAC/{name}/Static_cohesive_arrest.ipynb", cells)

    name = "Paper_figures"
    cells = [
        markdown(
            "# AVAC analytical-verification figures\n\n"
            "This notebook creates the Section 4 manuscript figures exclusively from the "
            "saved `publication_amr/results` products of the three AVAC case notebooks. It "
            "does not launch either solver, so later style and layout changes do not require "
            "new simulations.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Required numerical products\n\n"
            "Run the WRR, Kerswell horizontal-Coulomb, and inclined-Coulomb notebooks first. "
            "Their summaries retain the solver hash, AMR controls, and achieved levels. The "
            "two Coulomb rows are postprocessed with one boundary definition: the wet support "
            "uses the solver dry tolerance and the undisturbed rear uses a 0.1% relative-depth "
            "tolerance so AMR interpolation noise is not mistaken for motion. Both the raw run "
            "summaries and the common manuscript diagnostics are archived with the figures.\n"
        ),
        code(
            "case.run('make_avac_verification_figures.py', '--output-root', "
            "REPOSITORY / 'docs' / 'article' / 'figures')\n"
        ),
        code(
            "case.show('../../../docs/article/figures/avac_coulomb_verification.png', "
            "'../../../docs/article/figures/avac_wrr_water_limit.png')\n"
        ),
    ]
    write(f"AVAC/{name}/AVAC_verification_figures.ipynb", cells)


def wave_notebooks() -> None:
    cases = [
        ("01_transcritical_shock", "transcritical_shock", "Transcritical flow with shock", None,
         "A frictionless steady flow crosses a smooth bump and a hydraulic shock. The discharge is 0.18 m²/s; stage/discharge boundary data reproduce the SWASHES case."),
        ("02_macdonald_smooth_shock", "macdonald_smooth_shock", "MacDonald smooth transition and shock", None,
         "A 100 m steady profile uses discharge 2 m²/s and Manning $n=0.0328$ s/m$^{1/3}$. It explicitly validates bed slope, Manning friction, and the downstream stage condition."),
        ("03_ritter_dry_dam_break", "ritter_dry_dam_break", "Dry-domain dam break without friction", None,
         "A 5 mm water column occupies the left half of a flat 10 m domain and collapses into a dry bed. The comparison is made at 6 s with no basal friction."),
        ("04_thacker_planar_paraboloid", "thacker_planar_paraboloid", "Thacker planar surface in a paraboloid", None,
         "A genuinely two-dimensional planar free surface oscillates in a parabolic bowl for three periods. This tests wetting/drying and preservation of the moving analytical surface."),
        ("05_macdonald_pseudo2d_supercritical", "pseudo2d_supercritical", "MacDonald pseudo-2D supercritical flow", 0.10,
         "A contracting 200 m channel carries a 20 m³/s supercritical flow with Manning $n=0.03$ s/m$^{1/3}$. The section-mean numerical surface is compared with SWASHES."),
        ("06_macdonald_pseudo2d_subcritical", "pseudo2d_subcritical", "MacDonald pseudo-2D subcritical flow", 0.20,
         "A 400 m variable-width channel carries a 20 m³/s subcritical flow with Manning $n=0.03$ s/m$^{1/3}$ and prescribed upstream discharge/downstream stage."),
    ]
    for folder, key, title, pseudo_dx, description in cases:
        pseudo_dx_control = (
            f"PSEUDO_DX_M = {pseudo_dx:.2f}\n" if pseudo_dx is not None else ""
        )
        pseudo_dx_argument = (
            ", '--pseudo-dx', PSEUDO_DX_M" if pseudo_dx is not None else ""
        )
        cells = [
            markdown(f"# {title} — WAVE\n\nThis notebook runs WAVE and compares it with the SWASHES analytical reference.\n"),
            *environment("WAVE", folder, extra="A C++ compiler is also required to build the pinned SWASHES 1.05.01 analytical generator."),
            markdown("## Physical and numerical definition\n\n" + description + "\n"),
            code(
                f"CASE_KEY = '{key}'\n"
                f"{pseudo_dx_control}"
                "case.run(case.path.parent / 'run_validation.py', CASE_KEY, '--solver', 'wave', "
                f"'--output-root', case.path.parent, '--cores', CORES{pseudo_dx_argument}, "
                "cwd=case.path.parent)\n"
            ),
            markdown("## Error metrics and solver provenance\n\nThe run records the grid, final time, analytical error norms, and SHA-256 of the WAVE executable.\n"),
            code("summary = case.json('results/summary.json')\nsummary\n"),
            markdown("## WAVE and analytical solution\n"),
            code("case.show('figures/wave_vs_swashes.png')\n"),
        ]
        write(f"WAVE/{folder}/{key}.ipynb", cells)

    folder = "07_baines_flow_over_bump"
    cells = [
        markdown(
            "# Baines flow over a bump and lake at rest — AVAC and WAVE\n\n"
            "Two well-balanced tests are executed with identical grids and boundary data in both solvers: a steady subcritical Baines flow and a closed lake at rest.\n"
        ),
        *environment("WAVE", folder),
        markdown(
            "## Physical and numerical definition\n\nThe smooth bump occupies $8<x<12$ m. The steady case uses depth 2 m and discharge 4 m²/s with analytical Bernoulli depth and stage/discharge boundaries. The second case has a horizontal 2 m free surface and closed boundaries.\n"
        ),
        code("case.run(case.path.parent / 'run_baines_validation.py', cwd=case.path.parent)\n"),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        markdown("## Analytical and cross-solver comparison\n"),
        code("case.show('figures/avac_wave_baines_and_lake_at_rest.png')\n"),
    ]
    write(f"WAVE/{folder}/Baines_flow_over_bump.ipynb", cells)

    folder = "08_amr_parallel"
    cells = [
        markdown(
            "# WAVE AMR and OpenMP reproducibility\n\nA small flat-bed dry dam break isolates numerical consistency. It compares a coarse grid, a uniform fine reference, and level-2 AMR, while independently repeating the fine and AMR runs with one and multiple OpenMP threads.\n"
        ),
        *environment("WAVE", folder),
        markdown("## Acceptance quantities\n\nThe test records depth differences, actual AMR levels, patch counts, binary equality, native composite-grid mass conservation, and elapsed time. Timing is descriptive; numerical reproducibility is the criterion.\n"),
        code("case.run(case.path.parent / 'run_amr_parallel_validation.py', cwd=case.path.parent)\n"),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        code("case.show('figures/wave_amr_parallel_validation.png')\n"),
    ]
    write(f"WAVE/{folder}/AMR_OpenMP.ipynb", cells)

    folder = "2008_WRR_sloping_bed"
    cells = [
        markdown(
            "# 2008 WRR dry-bottom sloping-bed benchmark — WAVE\n\nThe same frictionless water benchmark used for AVAC is executed independently with WAVE, preserving its exact wedge initial condition and quasi-one-dimensional periodic strip.\n"
        ),
        *environment("WAVE", folder),
        markdown("## Physical and boundary conditions\n\nThe bed is a 10° slope; the one-meter triangular water wedge is bounded by a wall upstream and an extrapolating boundary downstream. Transverse boundaries are periodic.\n"),
        code(
            "DX_M = 0.005\nT_FINAL_S = 5.0\nOUTPUT_FRAMES = 100\n"
            "XLOWER_M = -10.0\nXUPPER_M = 40.0\n"
            "driver = case.path.parents[1] / 'AVAC' / '2008_WRR_sloping_bed' / 'run_avac_validation.py'\n"
            "case.run(driver, '--solver', 'wave', '--output-root', case.path, '--dx', DX_M, "
            "'--t-final', T_FINAL_S, '--nout', OUTPUT_FRAMES, '--cores', CORES, "
            "'--xlower', XLOWER_M, '--xupper', XUPPER_M, "
            "'--rear-tracker', 'tutorial')\n"
        ),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        code(
            "case.show('figures/wrr_characteristics_wave_vs_theory.png', "
            "'figures/wrr_depth_profiles_wave_vs_theory.png', "
            "'figures/wrr_surface_profile_wave.png')\n"
        ),
    ]
    write(f"WAVE/{folder}/WRR_sloping_bed.ipynb", cells)

    folder = "Paper_figures"
    cells = [
        markdown(
            "# WAVE analytical-verification figure\n\n"
            "This notebook creates the main-paper WAVE figure from already completed lake-at-rest "
            "and Thacker simulations. It does not launch WAVE, so stylistic revisions remain "
            "independent of the numerical runs.\n"
        ),
        *environment("WAVE", folder),
        code("case.run('make_wave_verification_figures.py')\ncase.run('make_wave_appendix_figures.py')\n"),
        code(
            "case.show('../../../docs/article/figures/wave_analytical_verification.png', "
            "'../../../docs/article/figures/wave_additional_benchmarks.png', "
            "'../../../docs/article/figures/wave_numerical_diagnostics.png')\n"
        ),
    ]
    write(f"WAVE/{folder}/WAVE_verification_figures.ipynb", cells)


def coupling_notebook() -> None:
    folder = "Paper_figures"
    cells = [
        markdown(
            "# AVAC-to-WAVE coupling verification\n\n"
            "This notebook prescribes smooth synthetic AVAC shoreline states and sends them through "
            "the production AVAC reader, conservative source converter, written source file, WAVE "
            "Fortran source update, and current WAVE executable. It checks transferred volume and both "
            "horizontal momentum components on uniform and AMR grids, plus source-time convergence and "
            "a stair-step shoreline representation.\n"
        ),
        *environment("COUPLING", folder),
        markdown(
            "## Numerical experiment\n\n"
            "The domain is periodic, has a uniform initial lake depth, and is frictionless, so its global changes in depth "
            "and depth-integrated momentum must equal the coupling ledger. The smooth pulse has a known "
            "continuous-time integral. All finest AMR cells are integrated without double-counting the "
            "underlying coarse grid.\n"
        ),
        code(
            "case.run(case.path.parent / 'run_coupling_verification.py', '--cores', CORES, "
            "'--output-root', case.path.parent / 'publication', cwd=case.path.parent)\n"
        ),
        code("summary = case.json('../publication/results/summary.json')\nsummary\n"),
    ]
    write(f"COUPLING/{folder}/Coupling_verification.ipynb", cells)

    cells = [
        markdown(
            "# AVAC-to-WAVE coupling figure\n\n"
            "This notebook reads only the archived coupling ledgers and WAVE closure metrics. "
            "It can revise the manuscript figure without rerunning either solver.\n"
        ),
        *environment("COUPLING", folder),
        code("case.run('make_coupling_figure.py')\n"),
        code("case.show('../../../docs/article/figures/coupling_verification.png')\n"),
    ]
    write(f"COUPLING/{folder}/Coupling_verification_figures.ipynb", cells)


def iseesnow_notebooks() -> None:
    descriptions = {
        "IdealizedTopo": (
            "Idealized topography — Voellmy",
            "The supplied 5 m DEM and release polygon are run with $\\mu=0.4$, $\\xi=2000$ m/s², and 1.5 m release thickness normal to the terrain.",
        ),
        "RealTopo": (
            "Real topography — Voellmy",
            "The supplied real-terrain 5 m DEM and release polygon are run with $\\mu=0.2$, $\\xi=2000$ m/s², and 1.5 m normal release thickness.",
        ),
        "CoulombOnly": (
            "Idealized topography — Coulomb only",
            "The idealized case is repeated with $\\mu=0.4$ and the turbulent resistance disabled, following the ISeeSnow Coulomb-only protocol.",
        ),
    }
    for folder, (title, description) in descriptions.items():
        cells = [
            markdown(
                f"# ISeeSnow: {title} — AVAC\n\n"
                "This notebook runs one official ISeeSnow case without calibration, writes the required peak-flow-thickness and peak-flow-velocity rasters, and compares them on the supplied grid with participating-model submissions.\n"
            ),
            *environment(
                "ISeeSnow", folder,
                extra=(
                    "The pinned official ISeeSnow 1.0 dataset is downloaded automatically "
                    "on first use. Before a case is run, the driver rebuilds AVAC once from "
                    "this checkout so the recorded solver hash always represents the current source."
                ),
            ),
            code("from avac4qgis_validation.datasets import ensure_iseesnow\nbenchmark = ensure_iseesnow()\nbenchmark\n"),
            markdown("## Prescribed benchmark configuration\n\n" + description + " No peer-model result is used to select an AVAC parameter. The simulation ceiling is 1200 s and the native state is checked for practical arrest.\n"),
            code(
                f"CASE_NAME = '{folder}'\n"
                "RESULTS_ROOT = Path(os.environ.get('AVAC_ISEESNOW_RESULTS_ROOT', case.path.parent)).expanduser().resolve()\n"
                "case.run(case.path.parent / 'run_iseesnow_avac.py', '--case', CASE_NAME, "
                "'--workers', CORES, '--spatial-order', 2, '--results-root', RESULTS_ROOT, "
                "'--overwrite', cwd=case.path.parent)\n"
            ),
            markdown("## Run diagnostics and ISeeSnow submission\n\nThe summary records volume, duration, practical stop time, numerical controls, solver hash, and generated standard-format files.\n"),
            code("import json\nsummary = json.loads((RESULTS_ROOT / CASE_NAME / 'run_summary.json').read_text(encoding='utf-8'))\nsummary\n"),
            markdown("## Direct peer comparison\n\nOnly peer fields with exactly matching dimensions, cell size, and cell-center coordinates are included; no shifting, clipping, padding, or resampling is performed.\n"),
            code(
                "case.run(case.path.parent / 'compare_iseesnow.py', '--case', CASE_NAME, "
                "'--results-root', RESULTS_ROOT, '--output-root', RESULTS_ROOT, cwd=case.path.parent)\n"
                "case.show(RESULTS_ROOT / 'plots' / f'{CASE_NAME}_pft_peer_comparison.png', "
                "RESULTS_ROOT / 'plots' / f'{CASE_NAME}_pfv_peer_comparison.png', "
                "RESULTS_ROOT / 'plots' / f'{CASE_NAME}_scalar_peer_comparison.png')\n"
            ),
        ]
        if folder == "IdealizedTopo":
            cells.extend([
                markdown("## Paper-style idealized-case figures\n\nThese panels follow the ISeeSnow paper display conventions while retaining every model's native submitted grid and values.\n"),
                code(
                    "if RESULTS_ROOT == case.path.parent.resolve():\n"
                    "    case.run(case.path.parent / 'reproduce_paper_idealized_voellmy.py', cwd=case.path.parent)\n"
                    "    case.show('../paper_figures/VoellmyIdealized/Figure_2_style_VoellmyIdealized_PFT_with_AVAC4QGIS.png', "
                    "'../paper_figures/VoellmyIdealized/Figure_3_style_VoellmyIdealized_PFT_0p5m_contours_with_AVAC4QGIS.png', "
                    "'../paper_figures/VoellmyIdealized/Figure_C2_style_VoellmyIdealized_PFV_with_AVAC4QGIS.png')\n"
                    "else:\n"
                    "    print('Candidate results preserved; publication figures intentionally not replaced.')\n"
                ),
            ])
        write(f"ISeeSnow/{folder}/{folder}.ipynb", cells)

    # Unlike the other figure folders, the published ISeeSnow directory is
    # deliberately lower-case.  Keep the notebook case identifier identical
    # to its on-disk path so it also opens on case-sensitive filesystems.
    folder = "paper_figures"
    cells = [
        markdown(
            "# ISeeSnow three-case manuscript figure\n\n"
            "This notebook creates the cross-case AVAC4QGIS intercomparison figure from archived "
            "exact-grid field summaries. It does not rerun AVAC or modify any participating-model field.\n"
        ),
        *environment("ISeeSnow", folder),
        code(
            "case.run(case.path.parent / 'compare_iseesnow.py', '--case', 'all', "
            "cwd=case.path.parent)\n"
            "case.run('make_iseesnow_case_figure.py')\n"
            "case.run('make_iseesnow_figures.py')\n"
        ),
        code(
            "case.show('../../../docs/article/figures/iseesnow_case_setup.png', "
            "'../../../docs/article/figures/iseesnow_intercomparison.png')\n"
        ),
    ]
    write(f"ISeeSnow/{folder}/ISeeSnow_intercomparison_figures.ipynb", cells)


def main() -> None:
    avac_notebooks()
    wave_notebooks()
    coupling_notebook()
    iseesnow_notebooks()


if __name__ == "__main__":
    main()
