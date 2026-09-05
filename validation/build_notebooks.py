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

    name = "Paper_figures"
    cells = [
        markdown(
            "# AVAC analytical-verification figures\n\n"
            "This notebook creates the Section 4 manuscript figures from the three AVAC "
            "publication cases. On a clean checkout it visibly regenerates those cases with "
            "the current source before plotting; set `ENSURE_CURRENT_RESULTS=False` only to "
            "restyle already-audited results.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Required numerical products\n\n"
            "The WRR, Kerswell horizontal-Coulomb, and inclined-Coulomb drivers below use "
            "the same controls as their dedicated notebooks. Their summaries retain the "
            "solver hash, AMR controls, and achieved levels. The "
            "two Coulomb rows are postprocessed with one boundary definition: the wet support "
            "uses the solver dry tolerance and the undisturbed rear uses a 0.1% relative-depth "
            "tolerance so AMR interpolation noise is not mistaken for motion. Both the raw run "
            "summaries and the common manuscript diagnostics are archived with the figures.\n"
        ),
        code(
            "ENSURE_CURRENT_RESULTS = True\n"
            "AVAC_ROOT = case.path.parent\n"
            "if ENSURE_CURRENT_RESULTS:\n"
            "    wrr = AVAC_ROOT / '2008_WRR_sloping_bed'\n"
            "    case.run(wrr / 'run_avac_validation.py', '--dx', 0.04, '--t-final', 5.0, "
            "'--nout', 20, '--cores', CORES, '--amr-levels', 3, '--amr-ratio', 4, "
            "'--speed-tolerance', 0.02, '--ny', 5, '--max1d', 1000, "
            "'--output-root', wrr / 'publication_amr', cwd=wrr)\n"
            "    kerswell = AVAC_ROOT / 'Kerswell_Coulomb'\n"
            "    case.run(kerswell / 'run_avac_validation.py', '--dx', 0.04, '--t-final', 10.0, "
            "'--nout', 40, '--cores', CORES, '--case-name', 'publication_amr', "
            "'--amr-levels', 3, '--amr-ratio', 4, '--speed-tolerance', 0.02, "
            "'--max1d', 1000, cwd=kerswell)\n"
            "    inclined = AVAC_ROOT / 'Coulomb_sloping_bed'\n"
            "    case.run(inclined / 'run_avac_validation.py', '--dx', 0.03, '--ny', 5, "
            "'--t-final', 6.0, '--nout', 30, '--case-name', 'publication_amr', "
            "'--cores', CORES, '--amr-levels', 3, '--amr-ratio', 4, "
            "'--speed-tolerance', 0.02, '--max1d', 1000, '--replace', cwd=inclined)\n"
            "case.run('make_avac_verification_figures.py', '--output-root', "
            "REPOSITORY / 'docs' / 'article' / 'figures')\n"
        ),
        code(
            "case.show('../../../docs/article/figures/avac_coulomb_verification.png', "
            "'../../../docs/article/figures/avac_wrr_water_limit.png')\n"
        ),
    ]
    write(f"AVAC/{name}/AVAC_verification_figures.ipynb", cells)


def curvature_notebook() -> None:
    name = "Curvature_normal_stress"
    cells = [
        markdown(
            "# Curvature-dependent normal stress - AVAC\n\n"
            "This notebook verifies the Fischer et al. (2012) centripetal "
            "correction to Coulomb normal stress for planar, concave-circular, "
            "and convex-circular tracks. It then isolates the changing-basis "
            "term that a terrain-following material point acquires on a curved "
            "track but AVAC's deliberately reduced local Cartesian source omits.\n"
        ),
        *environment("AVAC", name),
        markdown(
            "## Controlled source definition\n\n"
            "The first suite places a one-metre-deep material element moving at "
            "8 m s$^{-1}$ at each track nadir. With radius 40 m and $\\mu=0.30$, "
            "the compiled Fortran source is compared with "
            "$\\mathrm{d}u/\\mathrm{d}t=-\\mu(g+\\kappa u^2)$ for "
            "$\\kappa=0$, $+1/R$, and $-1/R$. The convex case remains below "
            "loss of contact, and one source step is compared with eight "
            "substeps. A frozen 30-degree tangent with zero applied force also "
            "checks that the reduced scalar source does not invent map-plane "
            "acceleration.\n"
        ),
        code("case.run('run_curvature_validation.py')\n"),
        markdown("## Curvature-source agreement\n"),
        code("source_summary = case.json('results/summary.json')\nsource_summary\n"),
        code("case.show('figures/curvature_source_verification.png')\n"),
        markdown(
            "## Terrain-following circular-track diagnostic\n\n"
            "The frozen-cell check above is not a terrain-following transport "
            "test. This second executable integrates squared surface speed "
            "$w=v_s^2$ along a circular transition of radius 400 m from a "
            "34-degree slope to horizontal. It compares constrained "
            "terrain-following point dynamics with the surface-speed equation "
            "implied by AVAC's reduced horizontal-velocity projection. Flat and "
            "constant-slope Coulomb tracks are exact controls; a zero-force "
            "circle isolates the changing projection analytically. The exercise "
            "excludes depth and pressure evolution, so it documents a coordinate "
            "discrepancy and does not prescribe a production source correction.\n"
        ),
        code("case.run('run_circular_track_verification.py')\n"),
        code(
            "circular_summary = "
            "case.json('results/circular_track_summary.json')\n"
            "circular_summary\n"
        ),
        code(
            "case.show('figures/circular_track_coordinate_verification.png')\n"
        ),
    ]
    write(f"AVAC/{name}/Curvature_normal_stress.ipynb", cells)


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
            "This notebook creates the main-paper WAVE figures. It visibly regenerates every "
            "required WAVE benchmark with the current source on a clean checkout; set "
            "`ENSURE_CURRENT_RESULTS=False` only when restyling existing audited results.\n"
        ),
        *environment("WAVE", folder),
        code(
            "ENSURE_CURRENT_RESULTS = True\n"
            "WAVE_ROOT = case.path.parent\n"
            "if ENSURE_CURRENT_RESULTS:\n"
            "    for CASE_KEY in ('transcritical_shock', 'macdonald_smooth_shock', "
            "'ritter_dry_dam_break', 'thacker_planar_paraboloid'):\n"
            "        case.run(WAVE_ROOT / 'run_validation.py', CASE_KEY, '--solver', 'wave', "
            "'--output-root', WAVE_ROOT, '--cores', CORES, cwd=WAVE_ROOT)\n"
            "    case.run(WAVE_ROOT / '07_baines_flow_over_bump' / 'run_baines_validation.py', "
            "cwd=WAVE_ROOT / '07_baines_flow_over_bump')\n"
            "    case.run(WAVE_ROOT / '08_amr_parallel' / 'run_amr_parallel_validation.py', "
            "cwd=WAVE_ROOT / '08_amr_parallel')\n"
            "    wrr_driver = WAVE_ROOT.parents[1] / 'AVAC' / '2008_WRR_sloping_bed' / 'run_avac_validation.py'\n"
            "    case.run(wrr_driver, '--solver', 'wave', '--output-root', "
            "WAVE_ROOT / '2008_WRR_sloping_bed', '--dx', 0.005, '--t-final', 5.0, "
            "'--nout', 100, '--cores', CORES, '--xlower', -10.0, '--xupper', 40.0, "
            "'--rear-tracker', 'tutorial', cwd=WAVE_ROOT / '2008_WRR_sloping_bed')\n"
            "case.run('make_wave_verification_figures.py')\n"
            "case.run('make_wave_appendix_figures.py')\n"
        ),
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
            "This notebook creates the coupling figure. It visibly regenerates the coupling "
            "verification with current AVAC and WAVE sources on a clean checkout; set "
            "`ENSURE_CURRENT_RESULTS=False` only to restyle audited products.\n"
        ),
        *environment("COUPLING", folder),
        code(
            "ENSURE_CURRENT_RESULTS = True\n"
            "if ENSURE_CURRENT_RESULTS:\n"
            "    case.run(case.path.parent / 'run_coupling_verification.py', '--cores', CORES, "
            "'--output-root', case.path.parent / 'publication', cwd=case.path.parent)\n"
            "case.run('make_coupling_figure.py')\n"
        ),
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
        limiter_note = (
            "For the second-order calculation, Minmod is selected in a "
            "disclosed, in-sample numerical-scheme sweep using PFT agreement "
            "with the complete exactly aligned peer set; PFV is an audit only."
            if folder == "CoulombOnly"
            else "The second-order calculation retains the prior van Leer default; this Voellmy case was not part of the CoulombOnly limiter sweep."
        )
        cells = [
            markdown(
                f"# ISeeSnow: {title} — AVAC\n\n"
                "This notebook runs one official ISeeSnow case without physical-parameter calibration, writes the required peak-flow-thickness and peak-flow-velocity rasters, and compares them on the supplied grid with participating-model submissions.\n"
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
            markdown(
                "## Prescribed benchmark configuration\n\n"
                + description
                + " The prescribed physical parameters are not calibrated. "
                + limiter_note
                + " The simulation ceiling is 1200 s and the native "
                "state is checked for sustained practical arrest.\n"
            ),
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
            "This notebook creates the cross-case AVAC4QGIS intercomparison figure. It visibly "
            "regenerates all three official cases with the current source on a clean checkout; "
            "set `ENSURE_CURRENT_RESULTS=False` only to restyle audited field summaries.\n"
        ),
        *environment("ISeeSnow", folder),
        code(
            "ENSURE_CURRENT_RESULTS = True\n"
            "RESULTS_ROOT = Path(os.environ.get('AVAC_ISEESNOW_RESULTS_ROOT', case.path.parent)).expanduser().resolve()\n"
            "if ENSURE_CURRENT_RESULTS:\n"
            "    case.run(case.path.parent / 'run_iseesnow_avac.py', '--case', 'all', "
            "'--workers', CORES, '--spatial-order', 2, '--results-root', RESULTS_ROOT, "
            "'--overwrite', cwd=case.path.parent)\n"
            "case.run(case.path.parent / 'compare_iseesnow.py', '--case', 'all', "
            "'--results-root', RESULTS_ROOT, '--output-root', RESULTS_ROOT, cwd=case.path.parent)\n"
            "case.run('make_iseesnow_case_figure.py', '--results-root', RESULTS_ROOT)\n"
            "case.run('make_iseesnow_figures.py', '--results-root', RESULTS_ROOT)\n"
        ),
        code(
            "case.show('../../../docs/article/figures/iseesnow_case_setup.png', "
            "'../../../docs/article/figures/iseesnow_intercomparison.png')\n"
        ),
    ]
    write(f"ISeeSnow/{folder}/ISeeSnow_intercomparison_figures.ipynb", cells)


def main() -> None:
    avac_notebooks()
    curvature_notebook()
    wave_notebooks()
    coupling_notebook()
    iseesnow_notebooks()


if __name__ == "__main__":
    main()
