from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "validation"

PUBLIC_NOTEBOOKS = (
    "AVAC/2008_WRR_sloping_bed/WRR_sloping_bed.ipynb",
    "AVAC/Kerswell_Coulomb/Kerswell_Coulomb.ipynb",
    "AVAC/Coulomb_sloping_bed/Coulomb_sloping_bed.ipynb",
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


def test_published_validation_notebooks_are_present() -> None:
    actual = {
        path.relative_to(VALIDATION).as_posix()
        for path in VALIDATION.rglob("*.ipynb")
    }
    assert actual == set(PUBLIC_NOTEBOOKS)


def test_repository_notebooks_have_no_saved_outputs() -> None:
    """Notebook files remain reviewable source, not a cache of old results."""
    notebooks = [
        path for path in ROOT.rglob("*.ipynb")
        if ".git" not in path.parts
    ]
    assert notebooks
    for path in notebooks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for cell in payload["cells"]:
            if cell["cell_type"] == "code":
                assert cell.get("outputs", []) == [], path
                assert cell.get("execution_count") is None, path


def test_figure_notebooks_can_regenerate_current_prerequisites() -> None:
    expected_markers = {
        "AVAC/Paper_figures/AVAC_verification_figures.ipynb": "make_avac_verification_figures.py",
        "WAVE/Paper_figures/WAVE_verification_figures.ipynb": "make_wave_verification_figures.py",
        "COUPLING/Paper_figures/Coupling_verification_figures.ipynb": "make_coupling_figure.py",
        "ISeeSnow/paper_figures/ISeeSnow_intercomparison_figures.ipynb": "run_iseesnow_avac.py",
    }
    for relative, marker in expected_markers.items():
        payload = json.loads((VALIDATION / relative).read_text(encoding="utf-8"))
        source = "".join(
            "".join(cell["source"])
            for cell in payload["cells"]
            if cell["cell_type"] == "code"
        )
        assert "ENSURE_CURRENT_RESULTS = True" in source
        assert marker in source


def test_iseesnow_figure_sources_are_published() -> None:
    source_root = VALIDATION / "ISeeSnow" / "paper_figures"
    required = {
        "ISeeSnow_intercomparison_figures.ipynb",
        "iseesnow_table_c1_core.csv",
        "make_iseesnow_case_figure.py",
        "make_iseesnow_figures.py",
    }
    assert required == {path.name for path in source_root.iterdir() if path.is_file()}
