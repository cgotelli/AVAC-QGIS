# AVAC4QGIS 1.0.0 methods manuscript

`AVAC4QGIS_GMD.tex` and `references.bib` are the editable sources supplied
with the user's article and updated to the accepted solver. The PDF is the
compiled version. This remains a working manuscript: planned observational
and coupled laboratory validation sections are not completed experiments.

With a LaTeX installation that includes the listed packages, build from this
directory using:

```text
latexmk -pdf -interaction=nonstopmode -halt-on-error AVAC4QGIS_GMD.tex
```

The ISeeSnow 1.0.0 figure uses archived, authenticated completed-run metrics
and the tracked Table C1 core peer table, not new solver runs. Its replot
builder and provenance data are stored alongside this manuscript. The original
flat, WAVE and coupling figures are retained and clearly identified as
historical checkpoints; their summaries were not relabelled as current runs.

The numerical-method description distinguishes general plugin defaults from
the explicit ISeeSnow protocol, incoming-state CFL acceptance from post-source
stability, and transient Voellmy source stopping from static equilibrium.
The original Windows 1.0.0 promotion did not change its accepted numerical
binaries. The replacement macOS 1.0.0 package includes the subsequently
tested preparation and performance fixes documented in the
[release notes](../releases/v1.0.0-macos-refresh.md). These regression checks
do not replace the archived scientific runs used by this manuscript.
