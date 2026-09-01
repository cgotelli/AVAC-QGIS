from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"

PUBLIC_NOTEBOOKS = (
    "AVAC/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb",
    "AVAC/Kerswell_Coulomb/Kerswell_Coulomb.ipynb",
    "AVAC/Coulomb_sloping_bed/Coulomb_sloping_bed.ipynb",
    "AVAC/Real_terrain_conservation/Real_terrain_conservation.ipynb",
    "AVAC/Static_cohesive_arrest/Static_cohesive_arrest.ipynb",
    "AVAC/Curvature_normal_stress/Curvature_normal_stress.ipynb",
    "AVAC/Paper_figures/AVAC_verification_figures.ipynb",
    "WAVE/01_transcritical_shock/transcritical_shock.ipynb",
    "WAVE/02_macdonald_smooth_shock/macdonald_smooth_shock.ipynb",
    "WAVE/03_ritter_dry_dam_break/ritter_dry_dam_break.ipynb",
    "WAVE/04_thacker_planar_paraboloid/thacker_planar_paraboloid.ipynb",
    "WAVE/05_macdonald_pseudo2d_supercritical/pseudo2d_supercritical.ipynb",
    "WAVE/06_macdonald_pseudo2d_subcritical/pseudo2d_subcritical.ipynb",
    "WAVE/07_baines_flow_over_bump/Baines_flow_over_bump.ipynb",
    "WAVE/08_amr_parallel/AMR_OpenMP.ipynb",
    "WAVE/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb",
    "WAVE/Paper_figures/WAVE_verification_figures.ipynb",
    "COUPLING/Paper_figures/Coupling_verification.ipynb",
    "COUPLING/Paper_figures/Coupling_verification_figures.ipynb",
    "ISeeSnow/IdealizedTopo/IdealizedTopo.ipynb",
    "ISeeSnow/RealTopo/RealTopo.ipynb",
    "ISeeSnow/CoulombOnly/CoulombOnly.ipynb",
    "ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb",
)


def test_validation_tree_contains_only_the_public_notebooks() -> None:
    actual = {
        path.relative_to(VALIDATION).as_posix()
        for path in VALIDATION.rglob("*.ipynb")
    }
    assert actual == set(PUBLIC_NOTEBOOKS)


def test_iseesnow_figure_sources_are_published() -> None:
    source_root = VALIDATION / "ISeeSnow" / "paper_figures"
    required = {
        "ISeeSnow_intercomparison_figures.ipynb",
        "iseesnow_table_c1_core.csv",
        "make_iseesnow_case_figure.py",
        "make_iseesnow_figures.py",
    }
    assert required == {path.name for path in source_root.iterdir() if path.is_file()}
