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
            "in its frictionless water mode; no avalanche rheology contributes to this run.\n"
        ),
        code(
            "DX_M = 0.005\nT_FINAL_S = 5.0\nOUTPUT_FRAMES = 100\n"
            "case.run('run_avac_validation.py', '--dx', DX_M, '--t-final', T_FINAL_S, "
            "'--nout', OUTPUT_FRAMES, '--cores', CORES)\n"
        ),
        markdown("## Quantitative diagnostics\n\nThe summary reports front errors, rear-wave errors, initial-condition error, mass variation, grid spacing, core count, and the exact solver hash.\n"),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        markdown("## Comparison with theory\n\nThe marker curves are AVAC centerline measurements; continuous analytical curves are evaluated independently by the driver.\n"),
        code(
            "case.show('figures/wrr_characteristics_avac_vs_theory.png', "
            "'figures/wrr_depth_profiles_avac_vs_theory.png', "
            "'figures/wrr_surface_profile_avac.png')\n"
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
            "the Coulomb/static-yield implementation.\n"
        ),
        code(
            "DX_M = 0.01\nT_FINAL_S = 10.0\nOUTPUT_FRAMES = 200\n"
            "case.run('run_avac_validation.py', '--dx', DX_M, '--t-final', T_FINAL_S, "
            "'--nout', OUTPUT_FRAMES, '--cores', CORES)\n"
        ),
        markdown("## Quantitative diagnostics\n\nFront/rear errors, arrested-state measures, mass history, and solver identity are written by the same run.\n"),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        markdown("## Comparison with Kerswell theory\n"),
        code(
            "case.show('figures/figure_8_7_avac_vs_theory.png', "
            "'figures/figure_8_10_avac_vs_theory.png', "
            "'figures/profiles_avac_vs_theory.png', "
            "'figures/avac_arrest_and_mass.png')\n"
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
            "bed angle is 5°. One transverse cell preserves the intended one-dimensional state. "
            "Level-2 AMR refines the 5 mm base cells without introducing case-specific physics.\n"
        ),
        code(
            "DX_M = 0.005\nT_FINAL_S = 6.0\nOUTPUT_FRAMES = 60\nRUN_NAME = 'notebook_run'\n"
            "case.run('run_avac_validation.py', '--dx', DX_M, '--ny', 1, '--t-final', "
            "T_FINAL_S, '--nout', OUTPUT_FRAMES, '--case-name', RUN_NAME, '--cores', CORES, "
            "'--amr-levels', 2, '--replace')\n"
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


def wave_notebooks() -> None:
    cases = [
        ("01_transcritical_shock", "transcritical_shock", "Transcritical flow with shock",
         "A frictionless steady flow crosses a smooth bump and a hydraulic shock. The discharge is 0.18 m²/s; stage/discharge boundary data reproduce the SWASHES case."),
        ("02_macdonald_smooth_shock", "macdonald_smooth_shock", "MacDonald smooth transition and shock",
         "A 100 m steady profile uses discharge 2 m²/s and Manning $n=0.0328$ s/m$^{1/3}$. It explicitly validates bed slope, Manning friction, and the downstream stage condition."),
        ("03_ritter_dry_dam_break", "ritter_dry_dam_break", "Dry-domain dam break without friction",
         "A 5 mm water column occupies the left half of a flat 10 m domain and collapses into a dry bed. The comparison is made at 6 s with no basal friction."),
        ("04_thacker_planar_paraboloid", "thacker_planar_paraboloid", "Thacker planar surface in a paraboloid",
         "A genuinely two-dimensional planar free surface oscillates in a parabolic bowl for three periods. This tests wetting/drying and preservation of the moving analytical surface."),
        ("05_macdonald_pseudo2d_supercritical", "pseudo2d_supercritical", "MacDonald pseudo-2D supercritical flow",
         "A contracting 200 m channel carries a 20 m³/s supercritical flow with Manning $n=0.03$ s/m$^{1/3}$. The section-mean numerical surface is compared with SWASHES."),
        ("06_macdonald_pseudo2d_subcritical", "pseudo2d_subcritical", "MacDonald pseudo-2D subcritical flow",
         "A 400 m variable-width channel carries a 20 m³/s subcritical flow with Manning $n=0.03$ s/m$^{1/3}$ and prescribed upstream discharge/downstream stage."),
    ]
    for folder, key, title, description in cases:
        cells = [
            markdown(f"# {title} — WAVE\n\nThis notebook runs WAVE and compares it with the SWASHES analytical reference.\n"),
            *environment("WAVE", folder, extra="A C++ compiler is also required to build the pinned SWASHES 1.05.01 analytical generator."),
            markdown("## Physical and numerical definition\n\n" + description + "\n"),
            code(
                f"CASE_KEY = '{key}'\n"
                "case.run(case.path.parent / 'run_validation.py', CASE_KEY, '--solver', 'wave', "
                "'--output-root', case.path.parent, '--cores', CORES, cwd=case.path.parent)\n"
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
            "driver = case.path.parents[1] / 'AVAC' / '2008_WRR_sloping_bed' / 'run_avac_validation.py'\n"
            "case.run(driver, '--solver', 'wave', '--output-root', case.path, '--dx', DX_M, "
            "'--t-final', T_FINAL_S, '--nout', OUTPUT_FRAMES, '--cores', CORES)\n"
        ),
        code("summary = case.json('results/summary.json')\nsummary\n"),
        code(
            "case.show('figures/wrr_characteristics_wave_vs_theory.png', "
            "'figures/wrr_depth_profiles_wave_vs_theory.png', "
            "'figures/wrr_surface_profile_wave.png')\n"
        ),
    ]
    write(f"WAVE/{folder}/WRR_sloping_bed.ipynb", cells)


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
            *environment("ISeeSnow", folder, extra="The pinned official ISeeSnow 1.0 dataset is downloaded automatically on first use."),
            code("from avac4qgis_validation.datasets import ensure_iseesnow\nbenchmark = ensure_iseesnow()\nbenchmark\n"),
            markdown("## Prescribed benchmark configuration\n\n" + description + " No peer-model result is used to select an AVAC parameter. The simulation ceiling is 1200 s and the native state is checked for practical arrest.\n"),
            code(
                f"CASE_NAME = '{folder}'\n"
                "case.run(case.path.parent / 'run_iseesnow_avac.py', '--case', CASE_NAME, "
                "'--workers', CORES, '--spatial-order', 2, '--overwrite', cwd=case.path.parent)\n"
            ),
            markdown("## Run diagnostics and ISeeSnow submission\n\nThe summary records volume, duration, practical stop time, numerical controls, solver hash, and generated standard-format files.\n"),
            code("summary = case.json('run_summary.json')\nsummary\n"),
            markdown("## Direct peer comparison\n\nOnly peer fields with exactly matching dimensions, cell size, and cell-center coordinates are included; no shifting, clipping, padding, or resampling is performed.\n"),
            code(
                "case.run(case.path.parent / 'compare_iseesnow.py', '--case', CASE_NAME, cwd=case.path.parent)\n"
                "case.show(f'../plots/{CASE_NAME}_pft_peer_comparison.png', "
                "f'../plots/{CASE_NAME}_pfv_peer_comparison.png', "
                "f'../plots/{CASE_NAME}_scalar_peer_comparison.png')\n"
            ),
        ]
        if folder == "IdealizedTopo":
            cells.extend([
                markdown("## Paper-style idealized-case figures\n\nThese panels follow the ISeeSnow paper display conventions while retaining every model's native submitted grid and values.\n"),
                code(
                    "case.run(case.path.parent / 'reproduce_paper_idealized_voellmy.py', cwd=case.path.parent)\n"
                    "case.show('../paper_figures/VoellmyIdealized/Figure_2_style_VoellmyIdealized_PFT_with_AVAC4QGIS.png', "
                    "'../paper_figures/VoellmyIdealized/Figure_3_style_VoellmyIdealized_PFT_0p5m_contours_with_AVAC4QGIS.png', "
                    "'../paper_figures/VoellmyIdealized/Figure_C2_style_VoellmyIdealized_PFV_with_AVAC4QGIS.png')\n"
                ),
            ])
        write(f"ISeeSnow/{folder}/{folder}.ipynb", cells)


def main() -> None:
    avac_notebooks()
    wave_notebooks()
    iseesnow_notebooks()


if __name__ == "__main__":
    main()
