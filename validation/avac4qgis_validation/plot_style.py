"""Shared plotting style for AVAC4QGIS validation and paper figures.

The palette mirrors the color definitions in
``docs/article/AVAC4QGIS_GMD.tex``.  Figure drivers and notebooks should call
``apply_paper_style()`` once, then use the semantic color names below instead
of defining case-local colors.  Line style and marker shape must still carry
meaning so that figures remain legible when printed in grayscale.
"""

from __future__ import annotations

from collections.abc import Mapping


PAPER_COLORS: Mapping[str, str] = {
    "blue": "#6FA8DC",
    "orange": "#F4A261",
    "red": "#E76F51",
    "green": "#76B77A",
    "purple": "#9B8AC4",
    "yellow": "#E9C46A",
    "ink": "#2F3E46",
    "grid": "#D8E2E8",
    "paper": "#FFFFFF",
}

MODEL_COLORS: Mapping[str, str] = {
    "avac": PAPER_COLORS["orange"],
    "wave": PAPER_COLORS["blue"],
    "coupling": PAPER_COLORS["green"],
    "theory": PAPER_COLORS["ink"],
    "observations": PAPER_COLORS["purple"],
    "warning": PAPER_COLORS["red"],
}

SERIES_COLORS: tuple[str, ...] = (
    PAPER_COLORS["blue"],
    PAPER_COLORS["orange"],
    PAPER_COLORS["green"],
    PAPER_COLORS["red"],
    PAPER_COLORS["purple"],
    PAPER_COLORS["yellow"],
)

SERIES_MARKERS: tuple[str, ...] = ("o", "s", "^", "D", "v", "P")
SERIES_LINESTYLES: tuple[str, ...] = ("-", "--", "-.", ":", (0, (5, 2)), (0, (3, 1, 1, 1)))


def apply_paper_style() -> None:
    """Apply the common manuscript style to the active Matplotlib session."""
    import matplotlib as mpl
    from cycler import cycler

    mpl.rcParams.update(
        {
            "axes.prop_cycle": cycler(color=SERIES_COLORS),
            "axes.edgecolor": PAPER_COLORS["ink"],
            "axes.labelcolor": PAPER_COLORS["ink"],
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.facecolor": PAPER_COLORS["paper"],
            "figure.facecolor": PAPER_COLORS["paper"],
            "grid.color": PAPER_COLORS["grid"],
            "grid.linewidth": 0.65,
            "grid.alpha": 0.8,
            "font.family": "serif",
            "font.size": 9.5,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.5,
            "legend.fontsize": 8.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "lines.linewidth": 1.8,
            "lines.markersize": 5.0,
            "legend.frameon": False,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.facecolor": PAPER_COLORS["paper"],
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def figure_size(columns: int = 1, *, aspect: float = 0.66) -> tuple[float, float]:
    """Return a consistent figure size for one- or two-column layouts."""
    if columns not in (1, 2):
        raise ValueError("columns must be 1 or 2")
    width = 3.45 if columns == 1 else 7.10
    return width, width * float(aspect)
