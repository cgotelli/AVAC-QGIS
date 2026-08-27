# AVAC-QGIS macOS interactive release verification

Use this protocol in a real QGIS 3.44 desktop session. It is deliberately an
interactive test: do not use `QGIS --code`, the Python console, or Advanced /
Development settings. Record the actual paths, messages and Pass/Fail in the
evidence blocks below.

## Clean starting condition

1. Create a new QGIS profile named `avac-task14-clean` and restart QGIS into it.
2. Confirm QGIS environment/settings contain no `CLAW`, `CLAW_PYTHON`, `FC`,
   AVAC backend, Clawpack, external Python, or template override.
3. Enable/open the installed AVAC-QGIS plugin. Do not open Advanced /
   Development.

Expected initial UI:

```text
AVAC Working Directory: [ path ] [Browse]
Inputs | Parameters | Run | Results
```

The workspace field must be above the tabs. Backend, Clawpack, Python,
template, compiler and Make fields must not appear in normal tabs. Results
reopen is available; temporal/export/profile actions are disabled initially.

Evidence: profile __________ QGIS version __________ initial UI Pass/Fail _____

## First-use workspace, Prepare and provenance

1. Select/create a new empty test workspace. Do not choose a run directory.
2. Select the external DEM and release layer in **Inputs**.
3. In **Parameters**, load/set a valid short scenario, including Return period
   [years]. Return period is user-supplied scenario metadata.
4. Preview, then Validate, then Prepare from **Run**.
5. Record the automatically created `<workspace>/runs/run_<id>` path.
6. Inspect `.avac_qgis_run.json` and the directory tree. Confirm the marker
   contains workspace root/run ID, original and materialized inputs, matching
   hashes, CRS, runtime/version and lifecycle data.

Expected data-only tree (names may include additional `.data` after staging):

```text
<workspace>/
  runs/run_<id>/
    inputs/dem/
    inputs/release/              # .shp/.shx/.dbf and applicable sidecars
    AVAC/AVAC_configuration.yaml
    AVAC/init.xyz
    AVAC/*.data
    AVAC/_output/
    Topo/topography.asc
    .avac_qgis_run.json
```

Run this search against the workspace and record no matches:

```sh
find '<workspace>' \( -name xgeoclaw -o -name '*.dylib' -o -name '*.f90' -o -name '*.f' -o -name 'Makefile*' -o -name setrun.py \) -print
```

Evidence: workspace __________ run __________ provenance Pass/Fail _____

## Normal runtime and Results

1. Press **Check Environment**. Confirm no traceback and a **Ready** report
   identifying the managed runtime/workspace/template without requiring Make,
   gfortran, external Clawpack or Conda.
2. Press **Run**. Record Prepared → Running → Completed,
   solver path, runtime path, exit code, final frame count and final time.
3. Confirm the solver path is Application Support runtime, not the workspace;
   log/environment must not require Make, gfortran, external Clawpack, Conda,
   `CLAW`, `CLAW_PYTHON` or `FC`.
4. In **Results**, load Time Series Depth, Velocity and Pressure in turn.
   Seek at `0`, `2.3333333`, `4.6666667` and `7 s`; confirm no traceback,
   retained position while switching variable, and no local-time offset.
5. In **Profile Analysis**, confirm an ordinary existing QGIS line layer is
   listed as **Profile layer**. Select exactly one feature, then confirm
   **Extract / Plot Profile** opens a plot and enables CSV export.
6. Export one PNG frame
   series and confirm its filenames contain elapsed simulation seconds and that
   at least two successive frames visibly differ for an evolving avalanche.
7. Prepare a second short run in the same workspace. Confirm its ID differs
   and the first completed run is unchanged/discoverable.

Evidence: runtime __________ exit/time/frames __________ results Pass/Fail _____

## Restart/reopen and missing workspace

1. Close QGIS normally; reopen the same clean profile.
2. Confirm the working directory is restored and the managed runtime is reused.
3. From Results, reopen the completed run without preparing/running again;
   load static and temporal products and perform one profile or PNG action.
4. For missing-workspace handling, close QGIS, temporarily rename only the
   disposable test workspace, reopen, and confirm a clear unavailable-path
   message and the ability to choose a replacement. Restore the directory.

Evidence: restart/reopen __________ missing-workspace message __________ Pass/Fail _____

## Cancellation and user-facing errors

Use short disposable runs. For every row record the primary user message,
recovery action and whether QGIS stayed usable. A primary message must state
what failed, why it matters, and what to do next; tracebacks belong only in
the log.

| Area | Scenario | Observed message | Recovery | Pass/Fail |
|---|---|---|---|---|
| Workspace | none selected | | select workspace | |
| Workspace | plugin/runtime path | | choose data folder | |
| Inputs | DEM missing CRS | | assign/select projected DEM | |
| Inputs | release missing CRS/empty/outside/unsupported geometry | | correct release layer | |
| Configuration | malformed/incomplete/invalid CFL/output/grid | | load/correct valid configuration | |
| Prepare | cancel while active | | marker is cancelled/failed, never prepared | |
| Run | Stop during short active solver | | cancelled, no orphan xgeoclaw, Results disabled | |
| Run | stale prepared state | | Prepare again | |
| Runtime | missing/corrupt runtime asset | | repair from plugin archive or clear message | |
| Results | missing raw output/fgmax/fgout pair, corrupt cache/partial temporal cache | | repair/reload affected run; completed marker remains completed | |
| Profiles | none/multiple/outside/disconnected selection | | select one valid connected line | |
| Export | unwritable destination/cancel | | explain destination/cancel state; restore temporal state | |

## Completion decision

Attach this completed checklist and the tested workspace tree to `output14.md`.
Task 14 is release-ready only after all mandatory rows pass in the actual dock.
