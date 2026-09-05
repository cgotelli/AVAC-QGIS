"""Complete-template AVAC parameter mapping shared by the dock and preparation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml
import numpy as np


REQUIRED_SECTIONS = ("animation", "computation", "dem_extent", "file_names", "gauges", "output", "refinement", "release", "rheology")
# Every user-facing standalone GUI field, plus ``release.nu`` which is used by
# its initial-depth calculation although it was previously hidden in its form.
PARAMETER_PATHS = (
    "release.d0", "release.theta_cr", "release.gradient_hypso", "release.z_ref", "release.nu", "release.period_return",
    "release.correction_slope", "release.correction_elevation",
    "rheology.model", "rheology.mu", "rheology.xi", "rheology.C", "rheology.rho", "rheology.u_cr", "rheology.beta",
    "computation.t_max", "computation.nb_simul", "computation.cfl_target", "computation.cfl_max",
    "computation.refinement", "computation.cell_size", "computation.boundary", "computation.limiter",
    "computation.state_momentum_regularization_depth",
    "computation.voellmy_state_momentum_regularization_depth",
    "output.output_format", "output.delta_t", "output.verbosity",
    "animation.variable", "animation.n_out",
)

# Added after the complete-configuration schema was already public.  Loading
# an older saved case must not fail merely because these explicit numerical
# controls were previously implicit solver defaults.
OPTIONAL_CONTROL_DEFAULTS: dict[str, Any] = {
    "computation.state_momentum_regularization_depth": 0.05,
    "computation.voellmy_state_momentum_regularization_depth": 0.10,
}


# These defaults are the established AVAC initial-condition defaults.  Keep
# them in the configuration layer as well as using them during preprocessing,
# so a preview, a prepared qinit file, and a saved complete configuration all
# enforce the same physical input contract.
RELEASE_DEPTH_DEFAULTS: dict[str, float | bool] = {
    "d0": 0.0,
    "z_ref": 0.0,
    "gradient_hypso": 0.0,
    "theta_cr": 30.0,
    "nu": 0.2,
    "correction_elevation": False,
    "correction_slope": False,
}


def validate_release_depth_parameters(release: Mapping[str, Any]) -> list[str]:
    """Return errors for parameters that define AVAC's initial mobile depth.

    This deliberately validates the numeric inputs before any terrain-based
    correction is evaluated.  A comparison with ``NaN`` is false in Python,
    so checking only inequalities would otherwise let non-finite values reach
    qinit preparation and be silently converted to zero downstream.

    The preprocessing layer is not a second, hidden calibration interface:
    finite elevation, slope, and hypsometric controls are accepted, while the
    resulting terrain-dependent candidate is checked separately.  Only
    ``d0`` has a direct physical sign constraint because it is a thickness
    before any correction is applied.
    """
    if not isinstance(release, Mapping):
        return ["Release parameters must be a mapping."]

    issues: list[str] = []
    numeric_controls = {
        "d0": "Release d0",
        "z_ref": "Release reference elevation",
        "gradient_hypso": "Hypsometric gradient",
        "theta_cr": "Critical slope",
        "nu": "Slope correction ν",
    }
    for key, label in numeric_controls.items():
        value = release.get(key, RELEASE_DEPTH_DEFAULTS[key])
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            issues.append(f"{label} must be a finite number.")
            continue
        if not np.isfinite(number):
            issues.append(f"{label} must be a finite number.")
        elif key == "d0" and number < 0.0:
            issues.append("Release d0 must be non-negative.")

    for key, label in (
        ("correction_elevation", "Elevation correction"),
        ("correction_slope", "Slope correction"),
    ):
        value = release.get(key, RELEASE_DEPTH_DEFAULTS[key])
        if not isinstance(value, (bool, np.bool_)):
            issues.append(f"{label} must be true or false.")
    return issues


def load_complete_configuration(path: str | Path) -> dict[str, Any]:
    """Load a complete AVAC schema without dropping unknown advanced values."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise ValueError(f"Cannot read AVAC configuration: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("AVAC configuration must be a YAML mapping.")
    missing = [section for section in REQUIRED_SECTIONS if not isinstance(payload.get(section), dict)]
    if missing:
        raise ValueError("Configuration is not a complete AVAC schema; missing mappings: " + ", ".join(missing))
    return payload


def value_at(payload: dict[str, Any], path: str) -> Any:
    group, key = path.split(".", 1)
    if key not in payload[group]:
        raise ValueError(f"Configuration is missing user parameter {path}.")
    return payload[group][key]


def controlled_values(payload: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path in PARAMETER_PATHS:
        group, key = path.split(".", 1)
        if key in payload[group]:
            values[path] = payload[group][key]
        elif path in OPTIONAL_CONTROL_DEFAULTS:
            values[path] = OPTIONAL_CONTROL_DEFAULTS[path]
        else:
            values[path] = value_at(payload, path)
    # ``z_breaks`` is intentionally optional for backwards-compatible
    # one-zone configurations.  Normalise it here so all callers can use one
    # configuration contract.
    values["rheology.z_breaks"] = list(payload["rheology"].get("z_breaks") or [])
    return values


def apply_controlled_values(template: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Copy a full template and change only explicit user-facing YAML paths."""
    result = deepcopy(template)
    for path in PARAMETER_PATHS:
        if path in values:
            group, key = path.split(".", 1)
            result[group][key] = values[path]
    if "rheology.z_breaks" in values:
        z_breaks = values["rheology.z_breaks"]
        if z_breaks:
            result["rheology"]["z_breaks"] = z_breaks
        else:
            # Preserve established one-zone YAMLs without introducing an
            # empty advanced key on each save.
            result["rheology"].pop("z_breaks", None)
    return result


def restore_controlled_values(
    template: dict[str, Any], saved_values: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge a saved plugin Case over deterministic current defaults.

    Version-1 Case files can legitimately omit controls introduced later.
    Starting from the referenced complete template prevents those omissions
    from inheriting unrelated values left in a live GUI session.
    """
    values = controlled_values(template)
    values.update(saved_values)
    return values


def validate_controlled_values(values: dict[str, Any]) -> list[str]:
    """Only enforce constraints established by the standalone controls/code."""
    issues: list[str] = []
    try:
        issues.extend(validate_release_depth_parameters({
            "d0": values["release.d0"],
            "z_ref": values["release.z_ref"],
            "gradient_hypso": values["release.gradient_hypso"],
            "theta_cr": values["release.theta_cr"],
            "nu": values["release.nu"],
            "correction_elevation": values["release.correction_elevation"],
            "correction_slope": values["release.correction_slope"],
        }))
        # This is scenario metadata supplied by the user, not a value AVAC-QGIS
        # derives from the terrain, release field, or model results.  The
        # historical complete configuration schema expresses it as a positive
        # count of years; do not impose any statistical/physical upper bound.
        if int(values["release.period_return"]) < 1:
            issues.append("Return period must be a positive whole number of years.")
        if float(values["computation.t_max"]) <= 0:
            issues.append("Simulation end time must be positive.")
        if float(values["computation.cell_size"]) <= 0:
            issues.append("Computational cell size must be positive.")
        state_depth = float(values["computation.state_momentum_regularization_depth"])
        if not np.isfinite(state_depth) or state_depth < 0:
            issues.append(
                "Coulomb state momentum regularization depth must be a non-negative finite number."
            )
        voellmy_state_depth = float(
            values["computation.voellmy_state_momentum_regularization_depth"]
        )
        if not np.isfinite(voellmy_state_depth) or voellmy_state_depth < 0:
            issues.append(
                "Voellmy state momentum regularization depth must be a non-negative finite number."
            )
        if int(values["computation.nb_simul"]) < 1 or int(values["animation.n_out"]) < 1:
            issues.append("Solver and temporal output counts must each be at least one.")
        if float(values["computation.cfl_target"]) > float(values["computation.cfl_max"]):
            issues.append("CFL target must be less than or equal to CFL maximum.")
        if float(values["output.delta_t"]) > float(values["computation.t_max"]):
            issues.append("Maximum-result check interval must not exceed simulation end time.")
        if values["rheology.model"] not in {"Voellmy", "Coulomb", "cohesive_Voellmy"}:
            issues.append("Rheology model must be Voellmy, Coulomb, or cohesive Voellmy.")
        mu = values["rheology.mu"] if isinstance(values["rheology.mu"], list) else [values["rheology.mu"]]
        xi = values["rheology.xi"] if isinstance(values["rheology.xi"], list) else [values["rheology.xi"]]
        cohesion = values["rheology.C"] if isinstance(values["rheology.C"], list) else [values["rheology.C"]]
        z_breaks = list(values.get("rheology.z_breaks") or [])
        if not (len(mu) == len(xi) == len(cohesion)):
            issues.append("Altitude rheology zones require equally sized μ, ξ, and cohesion lists.")
        if len(z_breaks) != len(mu) - 1:
            issues.append("Altitude rheology zones require one fewer elevation break than zones.")
        if any(float(left) >= float(right) for left, right in zip(z_breaks, z_breaks[1:])):
            issues.append("Altitude rheology elevation breaks must be strictly ascending.")
        if any(float(item) <= 0 for item in mu) or any(float(item) <= 0 for item in xi):
            issues.append("Rheology μ and ξ values must be positive.")
        if any(float(item) < 0 for item in cohesion):
            issues.append("Rheology cohesion values must be non-negative.")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        issues.append(f"Invalid parameter value: {exc}")
    return issues


def validate_grid_contract(configuration: dict[str, Any], source_cell_size: float | None = None) -> list[str]:
    """Validate AVAC's independent terrain and computational-grid contract.

    ``dem_extent`` and ``computation.cell_size`` define the Clawpack domain;
    the selected source DEM is only the terrain sampling grid.  AVAC's
    real-world setup supports equal or finer terrain sampling, with an integer
    ratio, but not silently coarser terrain or fractional regridding. The
    minimum domain dimensions also reflect the two-cell Water and five-cell
    granular ghost stencils.
    """
    issues: list[str] = []
    try:
        dem, computation = configuration["dem_extent"], configuration["computation"]
        model = str(configuration.get("rheology", {}).get("model", "")).strip()
        minimum_cells = 4 if model == "Water" else 10
        cell_size = float(computation["cell_size"])
        if cell_size <= 0:
            return ["Computational cell size must be positive."]
        for axis in ("x", "y"):
            span = float(dem[f"{axis}max"]) - float(dem[f"{axis}min"])
            cells = span / cell_size
            if span <= 0 or not np.isclose(cells, round(cells), rtol=0.0, atol=1e-8):
                issues.append(
                    f"Computational {axis}-domain span must be a whole number of {cell_size:g} m cells. "
                    "Choose a compatible computational cell size or domain template."
                )
            elif int(round(cells)) < minimum_cells:
                issues.append(
                    f"Computational {axis}-domain needs at least {minimum_cells} cells "
                    f"for the {model or 'granular'} solver stencil and QGIS raster results."
                )
        if source_cell_size is not None:
            source = float(source_cell_size)
            ratio = cell_size / source
            if source <= 0 or ratio < 1 or not np.isclose(ratio, round(ratio), rtol=0.0, atol=1e-8):
                issues.append(
                    "Source DEM cell size must equal or evenly subdivide the computational cell size; "
                    "AVAC does not silently resample terrain during preparation."
                )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(f"Invalid computational-grid configuration: {exc}")
    return issues
