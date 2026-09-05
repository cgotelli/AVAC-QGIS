#!/usr/bin/env python3
"""Create the three-case ISeeSnow scalar intercomparison figure."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import shapefile
import yaml


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "validation"))

from avac4qgis_validation.plot_style import (  # noqa: E402
    MODEL_COLORS,
    PAPER_COLORS,
    apply_paper_style,
    figure_size,
)


CASES = (
    ("IdealizedTopo", "Idealized Voellmy"),
    ("RealTopo", "Real-terrain Voellmy"),
    ("CoulombOnly", "Idealized Coulomb"),
)
METRICS = (
    ("runout_length_m", 1.0e-3, "Runout length (km)"),
    ("pft_peak_m", 1.0, "Peak flow thickness (m)"),
    ("pfv_peak_mps", 1.0, r"Peak flow velocity (m s$^{-1}$)"),
)

PUBLICATION_PROTOCOL = {
    "simulation_end_ceiling_seconds": 1200.0,
    "native_state_output_interval_seconds": 10.0,
    "fixed_grid_output_interval_seconds": 10.0,
    "fixed_grid_output_frame_count": 121,
    "spatial_order": 2,
    "native_dry_tolerance_m": 0.0001,
    "practical_rest_minimum_depth_m": 0.05,
    "speed_limit_mps": 1.0e99,
    "cfl_max": 1.0,
    "coulomb_state_momentum_regularization_depth_m": 0.05,
    "voellmy_state_momentum_regularization_depth_m": 0.10,
    "refinement_levels": 1,
    "refinement_ratio": 2,
    "maximum_amr_level": 1,
    "finest_effective_cell_size_m": 5.0,
    "diagnostic_gauge": None,
}
CASE_PROTOCOL = {
    "IdealizedTopo": {
        "limiter": "vanleer",
        "cfl_target": 0.5,
        "active_state_momentum_regularization_depth_m": 0.10,
        "model": "Voellmy",
        "mu": 0.4,
        "xi": 2000.0,
    },
    "RealTopo": {
        "limiter": "vanleer",
        "cfl_target": 0.5,
        "active_state_momentum_regularization_depth_m": 0.10,
        "model": "Voellmy",
        "mu": 0.2,
        "xi": 2000.0,
    },
    "CoulombOnly": {
        "limiter": "minmod",
        "cfl_target": 0.25,
        "active_state_momentum_regularization_depth_m": 0.05,
        "model": "Coulomb",
        "mu": 0.4,
        "xi": 1.0e12,
    },
}
PLUGIN_COMMON_PROTOCOL = {
    "computation.t_max": 1200.0,
    "computation.nb_simul": 120,
    "computation.cfl_max": 1.0,
    "computation.refinement": 1,
    "computation.cell_size": 5.0,
    "computation.state_momentum_regularization_depth": 0.05,
    "computation.voellmy_state_momentum_regularization_depth": 0.10,
    "output.delta_t": 10.0,
    "animation.n_out": 121,
}
EXPECTED_PEER_COUNTS = {
    "IdealizedTopo": 11,
    "RealTopo": 10,
    "CoulombOnly": 11,
}
THALWEG_REQUIRED_SUFFIXES = {".shp", ".shx", ".dbf"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_submission_path(root: Path, case: str, variable: str) -> Path:
    """Return the sole AVAC submission raster for one case and variable."""
    if variable not in {"pft", "pfv"}:
        raise ValueError(f"Unknown ISeeSnow submission variable: {variable!r}")
    matches = sorted(
        (root / case / "Submission").glob(
            f"*_AVAC4QGIS_{variable}.asc"
        )
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {case} {variable.upper()} submission, "
            f"found {len(matches)}"
        )
    return matches[0]


def _require_exact_values(
    values: dict[str, object], expected: dict[str, object], context: str,
) -> None:
    """Require the declared publication protocol without implicit coercion."""
    for key, expected_value in expected.items():
        if key not in values:
            raise RuntimeError(f"{context} is missing required value {key!r}")
        actual = values[key]
        if isinstance(expected_value, (int, float)) and not isinstance(
            expected_value, bool
        ):
            if (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float, np.integer, np.floating))
                or not np.isfinite(float(actual))
                or float(actual) != float(expected_value)
            ):
                raise RuntimeError(
                    f"{context} has {key}={actual!r}; selected publication "
                    f"protocol requires {expected_value!r}"
                )
        elif actual != expected_value:
            raise RuntimeError(
                f"{context} has {key}={actual!r}; selected publication "
                f"protocol requires {expected_value!r}"
            )


def _contained_path(case_root: Path, raw_path: object, description: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeError(f"{description} path is missing from run_summary.json")
    path = Path(raw_path).expanduser().resolve()
    try:
        path.relative_to(case_root.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"{description} is not contained in the completed case: {path}"
        ) from exc
    if not path.is_file():
        raise RuntimeError(f"{description} is missing: {path}")
    return path


def _unique_recorded_artifact(
    case_root: Path,
    summary: dict[str, object],
    summary_key: str,
    pattern: str,
    description: str,
) -> Path:
    matches = sorted(path.resolve() for path in case_root.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one contained {description}, found {len(matches)}"
        )
    recorded = _contained_path(case_root, summary.get(summary_key), description)
    if recorded != matches[0]:
        raise RuntimeError(
            f"run_summary.json does not name the contained {description}: {matches[0]}"
        )
    return recorded


def _stable_artifact(path: Path) -> tuple[bytes, dict[str, str]]:
    hash_before = sha256(path)
    content = path.read_bytes()
    hash_after = sha256(path)
    if hash_before != hash_after:
        raise RuntimeError(f"Artifact changed while being verified: {path}")
    return content, {"path": str(path), "sha256": hash_before}


def _record_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        values[key.strip()] = value.split("  #", 1)[0].strip()
    return values


def _verify_configuration_record(
    case: str,
    content: bytes,
    summary: dict[str, object],
    protocol: dict[str, object],
) -> None:
    text = content.decode("utf-8")
    if not text.splitlines() or text.splitlines()[0] != (
        "AVAC4QGIS ISeeSnow benchmark configuration"
    ):
        raise RuntimeError(f"{case} has an invalid AVAC configuration record")
    values = _record_values(text)
    expected_strings = {
        "case": case,
        "execution_mode": "current_source",
        "solver_sha256": str(summary["solver_sha256"]),
        "setrun_backend_sha256": str(summary["setrun_backend_sha256"]),
        "submission_pft_sha256": str(summary["submission_pft_sha256"]),
        "submission_pfv_sha256": str(summary["submission_pfv_sha256"]),
        "rheology": str(protocol["model"]),
        "limiter": str(protocol["limiter"]),
    }
    for key, expected in expected_strings.items():
        if values.get(key) != expected:
            raise RuntimeError(
                f"{case} configuration record has {key}={values.get(key)!r}; "
                f"expected {expected!r}"
            )
    numeric_expected = {
        "mu": protocol["mu"],
        "xi": protocol["xi"],
        "cell_size_m": 5.0,
        "refinement_levels": 1,
        "finest_effective_cell_size_m": 5.0,
        "simulation_end_ceiling_s": 1200.0,
        "native_state_output_interval_s": 10.0,
        "fixed_grid_output_interval_s": 10.0,
        "fixed_grid_output_frame_count": 121,
        "cfl_target": protocol["cfl_target"],
        "cfl_max": 1.0,
        "active_state_momentum_regularization_depth_m": protocol[
            "active_state_momentum_regularization_depth_m"
        ],
        "coulomb_state_momentum_regularization_depth_m": 0.05,
        "voellmy_state_momentum_regularization_depth_m": 0.10,
    }
    parsed: dict[str, object] = {}
    for key in numeric_expected:
        try:
            parsed[key] = float(values[key])
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"{case} configuration record is missing numeric value {key!r}"
            ) from exc
    _require_exact_values(
        parsed, numeric_expected, f"{case} configuration record"
    )


def _verify_official_inputs(
    case: str, case_root: Path, summary: dict[str, object],
) -> list[dict[str, str]]:
    raw_manifest = summary.get("official_input_manifest")
    if not isinstance(raw_manifest, list) or not raw_manifest:
        raise RuntimeError(f"{case} has no official input manifest")
    inputs_root = (case_root / "Inputs").resolve()
    records: list[dict[str, str]] = []
    names: set[str] = set()
    for raw_record in raw_manifest:
        if not isinstance(raw_record, dict):
            raise RuntimeError(f"{case} has an invalid official input manifest")
        name = raw_record.get("name")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in names
        ):
            raise RuntimeError(
                f"{case} has a missing, unsafe, or duplicate official input name"
            )
        names.add(name)
        expected_path = (inputs_root / name).resolve()
        path = _contained_path(
            case_root, raw_record.get("path"), f"{case} official input {name}"
        )
        if path != expected_path:
            raise RuntimeError(
                f"{case} official input {name} is not the contained Inputs copy"
            )
        expected_hash = raw_record.get("sha256")
        actual_hash = sha256(path)
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise RuntimeError(
                f"{case} official input hash mismatch for {name}"
            )
        records.append(
            {"name": name, "path": str(path), "sha256": actual_hash}
        )
    contained_names = {
        path.name for path in inputs_root.iterdir() if path.is_file()
    }
    if contained_names != names:
        missing = sorted(names - contained_names)
        unrecorded = sorted(contained_names - names)
        raise RuntimeError(
            f"{case} official input manifest mismatch: missing={missing}, "
            f"unrecorded={unrecorded}"
        )
    return records


def _nested_value(mapping: dict[str, object], dotted_key: str) -> object:
    value: object = mapping
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise RuntimeError(f"Configuration is missing {dotted_key!r}")
        value = value[part]
    return value


def _verify_case_artifacts(
    case: str, case_root: Path, summary: dict[str, object],
) -> dict[str, object]:
    protocol = CASE_PROTOCOL[case]
    official_inputs = _verify_official_inputs(case, case_root, summary)
    input_paths = {record["path"] for record in official_inputs}

    configuration_path = _unique_recorded_artifact(
        case_root,
        summary,
        "configuration",
        "Submission/*_AVAC4QGIS.txt",
        f"{case} AVAC configuration record",
    )
    configuration_content, configuration_artifact = _stable_artifact(
        configuration_path
    )
    _verify_configuration_record(
        case, configuration_content, summary, protocol
    )

    plugin_path = _unique_recorded_artifact(
        case_root,
        summary,
        "plugin_case",
        "AVAC4QGIS_ISeeSnow_*_Case.yaml",
        f"{case} plugin-case YAML",
    )
    plugin_content, plugin_artifact = _stable_artifact(plugin_path)
    plugin = yaml.safe_load(plugin_content.decode("utf-8"))
    if not isinstance(plugin, dict):
        raise RuntimeError(f"{case} plugin-case YAML is not a mapping")
    if plugin.get("format") != "AVAC4QGIS plugin configuration":
        raise RuntimeError(f"{case} plugin-case YAML has an invalid format")
    if Path(str(plugin.get("working_directory", ""))).resolve() != case_root.resolve():
        raise RuntimeError(
            f"{case} plugin-case working directory is not the contained case"
        )
    avac = plugin.get("avac")
    if not isinstance(avac, dict) or not isinstance(avac.get("parameters"), dict):
        raise RuntimeError(f"{case} plugin-case YAML has no AVAC parameters")
    parameters = avac["parameters"]
    plugin_expected = {
        **PLUGIN_COMMON_PROTOCOL,
        "computation.limiter": protocol["limiter"],
        "computation.cfl_target": protocol["cfl_target"],
        "rheology.model": protocol["model"],
        "rheology.mu": protocol["mu"],
        "rheology.xi": protocol["xi"],
    }
    _require_exact_values(
        parameters, plugin_expected, f"{case} contained plugin-case YAML"
    )

    template_path = _contained_path(
        case_root,
        avac.get("configuration_template"),
        f"{case} plugin configuration template",
    )
    if template_path != (case_root / "avac_iseesnow_template.yaml").resolve():
        raise RuntimeError(
            f"{case} plugin case does not use its contained AVAC template"
        )
    template_content, template_artifact = _stable_artifact(template_path)
    template = yaml.safe_load(template_content.decode("utf-8"))
    if not isinstance(template, dict):
        raise RuntimeError(f"{case} AVAC template is not a mapping")
    template_values = {
        key: _nested_value(template, key) for key in plugin_expected
    }
    _require_exact_values(
        template_values, plugin_expected, f"{case} contained AVAC template"
    )

    plugin_inputs = avac.get("inputs")
    if not isinstance(plugin_inputs, dict):
        raise RuntimeError(f"{case} plugin-case YAML has no input layers")
    for role in ("dem", "release"):
        layer = plugin_inputs.get(role)
        if not isinstance(layer, dict):
            raise RuntimeError(f"{case} plugin-case YAML has no {role} layer")
        source = _contained_path(
            case_root, layer.get("source"), f"{case} plugin {role} input"
        )
        if str(source) not in input_paths:
            raise RuntimeError(
                f"{case} plugin {role} does not name a verified official input"
            )

    return {
        "official_inputs": official_inputs,
        "configuration_record": configuration_artifact,
        "plugin_case": plugin_artifact,
        "configuration_template": template_artifact,
        "verified_plugin_parameters": {
            key: parameters[key] for key in plugin_expected
        },
    }


def validate_current_source_results(root: Path) -> dict[str, dict[str, object]]:
    """Require one clean, same-source publication run for every article row."""
    summaries: dict[str, dict[str, object]] = {}
    solver_hashes: set[str] = set()
    setrun_hashes: set[str] = set()
    for case, _label in CASES:
        summary_path = root / case / "run_summary.json"
        if not summary_path.is_file():
            raise RuntimeError(
                f"Article figure requires a completed summary: {summary_path}"
            )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("case") != case:
            raise RuntimeError(f"Mismatched case provenance in {summary_path}")
        if summary.get("execution_mode") != "current_source":
            raise RuntimeError(
                f"{case} is not a current-source run: "
                f"{summary.get('execution_mode')!r}"
            )
        violation_count = summary.get("accepted_cfl_violation_count")
        maximum_cfl = summary.get("maximum_courant_number")
        cfl_max = summary.get("cfl_max")
        if violation_count != 0:
            raise RuntimeError(
                f"{case} records {violation_count!r} accepted CFL violations"
            )
        try:
            maximum_cfl_value = float(maximum_cfl)
            cfl_max_value = float(cfl_max)
        except (TypeError, ValueError):
            maximum_cfl_value = np.nan
            cfl_max_value = np.nan
        if (
            not np.isfinite(maximum_cfl_value)
            or not np.isfinite(cfl_max_value)
            or maximum_cfl_value < 0.0
            or cfl_max_value <= 0.0
            or maximum_cfl_value > cfl_max_value
        ):
            raise RuntimeError(
                f"{case} has an invalid CFL audit: maximum={maximum_cfl!r}, "
                f"limit={cfl_max!r}"
            )
        case_protocol = CASE_PROTOCOL[case]
        _require_exact_values(
            summary,
            {
                **PUBLICATION_PROTOCOL,
                "limiter": case_protocol["limiter"],
                "cfl_target": case_protocol["cfl_target"],
                "active_state_momentum_regularization_depth_m": case_protocol[
                    "active_state_momentum_regularization_depth_m"
                ],
                "state_momentum_regularization_depth_m": case_protocol[
                    "active_state_momentum_regularization_depth_m"
                ],
            },
            f"{case} run_summary.json",
        )
        solver_hash = str(summary.get("solver_sha256", ""))
        setrun_hash = str(summary.get("setrun_backend_sha256", ""))
        if not solver_hash or not setrun_hash:
            raise RuntimeError(f"{case} is missing solver/setrun provenance")
        solver_hashes.add(solver_hash)
        setrun_hashes.add(setrun_hash)

        for variable, key in (("pft", "submission_pft_sha256"),
                              ("pfv", "submission_pfv_sha256")):
            submission_path = unique_submission_path(root, case, variable)
            expected = str(summary.get(key, ""))
            actual = sha256(submission_path)
            if not expected or actual != expected:
                raise RuntimeError(
                    f"{case} {variable.upper()} hash does not match run_summary.json"
                )
        summary["_article_verified_artifacts"] = _verify_case_artifacts(
            case, root / case, summary
        )
        summaries[case] = summary

    if len(solver_hashes) != 1 or len(setrun_hashes) != 1:
        raise RuntimeError(
            "Article figure requires all three cases to use one solver and setrun build"
        )
    return summaries


def read_ascii(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    header: dict[str, float] = {}
    with path.open(encoding="utf-8") as stream:
        for _ in range(6):
            key, value = stream.readline().split()[:2]
            header[key.lower()] = float(value)
        values_north = np.loadtxt(stream, dtype=float)
    cell = float(header["cellsize"])
    x0 = float(header.get("xllcenter", header.get("xllcorner", 0.0) + cell / 2.0))
    y0 = float(header.get("yllcenter", header.get("yllcorner", 0.0) + cell / 2.0))
    x = x0 + np.arange(int(header["ncols"])) * cell
    y = y0 + np.arange(int(header["nrows"])) * cell
    nodata = float(header.get("nodata_value", -9999.0))
    values_north[np.isclose(values_north, nodata)] = 0.0
    return x, y, values_north


def _require_valid_submission_values(path: Path, values: np.ndarray) -> None:
    if not np.all(np.isfinite(values)):
        raise RuntimeError(f"Submission raster contains non-finite values: {path}")
    if np.any(values < 0.0):
        raise RuntimeError(f"Submission raster contains negative values: {path}")


def submission_field(path: Path) -> np.ndarray:
    """Read one publication field without silently cleaning invalid values."""
    _x, _y, values = read_ascii(path)
    _require_valid_submission_values(path, values)
    return values


def validated_submission_fields(
    root: Path,
    summaries: dict[str, dict[str, object]],
) -> dict[str, dict[str, dict[str, object]]]:
    """Load selected fields directly from their hash-validated rasters.

    The comparison CSV is a derived report and can be stale. Article values
    therefore come from the immutable submission artifacts named by each run
    summary. Hashing both before and after reading also rejects a raster
    replaced while the figure is being assembled.
    """
    fields: dict[str, dict[str, dict[str, object]]] = {}
    for case, _label in CASES:
        summary = summaries[case]
        case_fields: dict[str, dict[str, object]] = {}
        for variable, key in (("pft", "submission_pft_sha256"),
                              ("pfv", "submission_pfv_sha256")):
            path = unique_submission_path(root, case, variable)
            expected = str(summary.get(key, ""))
            hash_before = sha256(path)
            x, y, values = read_ascii(path)
            _require_valid_submission_values(path, values)
            hash_after = sha256(path)
            if not expected or hash_before != expected or hash_after != expected:
                raise RuntimeError(
                    f"{case} {variable.upper()} hash does not match "
                    "run_summary.json while reading the article field"
                )
            case_fields[variable] = {
                "path": str(path),
                "sha256": expected,
                "peak": float(np.max(values)),
                "_x": x,
                "_y": y,
                "_values_north": values,
            }
        fields[case] = case_fields
    return fields


def unverified_submission_peak(root: Path, case: str, variable: str) -> float:
    """Read an optional historical comparison without claiming provenance."""
    path = unique_submission_path(root, case, variable)
    return float(np.max(submission_field(path)))


def read_path(path: Path) -> np.ndarray:
    reader = shapefile.Reader(str(path))
    lines = [np.asarray(shape.points, dtype=float) for shape in reader.shapes() if len(shape.points) >= 2]
    if len(lines) != 1:
        raise ValueError(f"Expected one ISeeSnow thalweg in {path}, found {len(lines)}")
    return lines[0]


def validated_thalweg(case: str) -> dict[str, object]:
    """Read one reference thalweg while hashing its complete shapefile set."""
    base = (
        REPO / "validation" / "_data" / "ISeeSnow" / "data" / case
        / "Inputs" / "LINES" / "path_aimec"
    )
    sidecars = sorted(
        path.resolve() for path in base.parent.glob(f"{base.name}.*")
        if path.is_file()
    )
    suffixes = {path.suffix.lower() for path in sidecars}
    missing = sorted(THALWEG_REQUIRED_SUFFIXES - suffixes)
    if missing:
        raise RuntimeError(
            f"{case} thalweg is missing required shapefile sidecars: {missing}"
        )
    before = {path: sha256(path) for path in sidecars}
    points = read_path(base.with_suffix(".shp"))
    after = {path: sha256(path) for path in sidecars}
    if before != after:
        raise RuntimeError(f"{case} thalweg changed while being read")
    return {
        "artifacts": [
            {"path": str(path), "sha256": before[path]} for path in sidecars
        ],
        "_points": points,
    }


def along_path_coordinate(points: np.ndarray, path: np.ndarray) -> np.ndarray:
    """Project map points onto a polyline and return curvilinear distance."""
    starts, vectors = path[:-1], np.diff(path, axis=0)
    lengths = np.linalg.norm(vectors, axis=1)
    valid = lengths > 0.0
    starts, vectors, lengths = starts[valid], vectors[valid], lengths[valid]
    cumulative = np.concatenate(([0.0], np.cumsum(lengths[:-1])))
    projected = np.empty(points.shape[0], dtype=float)
    for start in range(0, points.shape[0], 4096):
        values = points[start:start + 4096]
        relative = values[:, None, :] - starts[None, :, :]
        fraction = np.sum(relative * vectors[None, :, :], axis=2) / lengths[None, :] ** 2
        fraction = np.clip(fraction, 0.0, 1.0)
        closest = starts[None, :, :] + fraction[:, :, None] * vectors[None, :, :]
        distance2 = np.sum((values[:, None, :] - closest) ** 2, axis=2)
        segment = np.argmin(distance2, axis=1)
        projected[start:start + values.shape[0]] = (
            cumulative[segment] + fraction[np.arange(values.shape[0]), segment] * lengths[segment]
        )
    return projected


def runout_from_validated_field(
    pft_field: dict[str, object],
    thalweg: dict[str, object],
    threshold_m: float = 0.5,
) -> float:
    """Measure runout without reopening the already authenticated PFT."""
    x = np.asarray(pft_field["_x"], dtype=float)
    y = np.asarray(pft_field["_y"], dtype=float)
    values_north = np.asarray(pft_field["_values_north"], dtype=float)
    active_rows, active_columns = np.nonzero(values_north > threshold_m)
    if active_rows.size == 0:
        return 0.0
    points = np.column_stack((x[active_columns], y[::-1][active_rows]))
    return float(
        np.max(
            along_path_coordinate(
                points, np.asarray(thalweg["_points"], dtype=float)
            )
        )
    )


def unverified_avac_runout(
    case: str, results_root: Path, threshold_m: float = 0.5,
) -> float:
    """Read a historical comparison runout without publication provenance."""
    pft_path = unique_submission_path(results_root, case, "pft")
    x, y, values_north = read_ascii(pft_path)
    _require_valid_submission_values(pft_path, values_north)
    path = (
        REPO / "validation" / "_data" / "ISeeSnow" / "data" / case
        / "Inputs" / "LINES" / "path_aimec.shp"
    )
    active_rows, active_columns = np.nonzero(values_north > threshold_m)
    if active_rows.size == 0:
        return 0.0
    points = np.column_stack((x[active_columns], y[::-1][active_rows]))
    return float(np.max(along_path_coordinate(points, read_path(path))))


def field_provenance(field: dict[str, object]) -> dict[str, object]:
    return {
        "path": field["path"],
        "sha256": field["sha256"],
        "peak": field["peak"],
    }


def validated_peer_table(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load the exact peer table and reject incomplete or ambiguous rows."""
    content, artifact = _stable_artifact(path.resolve())
    table = pd.read_csv(io.BytesIO(content))
    required = {"case", "model", *(field for field, _scale, _title in METRICS)}
    missing_columns = sorted(required - set(table.columns))
    if missing_columns:
        raise RuntimeError(
            f"ISeeSnow peer table is missing columns: {missing_columns}"
        )
    if table[["case", "model"]].isna().any().any():
        raise RuntimeError("ISeeSnow peer table has a missing case or model")
    duplicates = table.duplicated(["case", "model"], keep=False)
    if duplicates.any():
        labels = sorted(
            f"{row.case}/{row.model}"
            for row in table.loc[duplicates, ["case", "model"]].itertuples(
                index=False
            )
        )
        raise RuntimeError(
            f"ISeeSnow peer table has duplicate case/model rows: {labels}"
        )
    actual_cases = set(table["case"].astype(str))
    expected_cases = set(EXPECTED_PEER_COUNTS)
    if actual_cases != expected_cases:
        raise RuntimeError(
            "ISeeSnow peer table case mismatch: "
            f"missing={sorted(expected_cases - actual_cases)}, "
            f"unexpected={sorted(actual_cases - expected_cases)}"
        )
    for case, expected_count in EXPECTED_PEER_COUNTS.items():
        count = int((table["case"] == case).sum())
        if count != expected_count:
            raise RuntimeError(
                f"ISeeSnow peer table requires {expected_count} {case} rows; "
                f"found {count}"
            )
    for field, _scale, _title in METRICS:
        try:
            values = pd.to_numeric(table[field], errors="raise").to_numpy(float)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"ISeeSnow peer table has a non-numeric {field} value"
            ) from exc
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise RuntimeError(
                f"ISeeSnow peer table has an invalid {field} value"
            )
        table[field] = values
    return table, artifact


def peer_statistics(peer_values: np.ndarray) -> dict[str, float | int]:
    """Return statistics over every peer, including displayed outliers."""
    values = np.asarray(peer_values, dtype=float)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise RuntimeError("Peer statistics require finite non-empty values")
    q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75])
    return {
        "peer_count": int(values.size),
        "peer_min": float(np.min(values)),
        "peer_q1": float(q1),
        "peer_median": float(median),
        "peer_q3": float(q3),
        "peer_max": float(np.max(values)),
    }


def coulomb_pfv_offscale_metadata(
    models: np.ndarray,
    peer_values: np.ndarray,
    focus_values: list[float],
) -> dict[str, object]:
    """Describe the isolated Coulomb PFV outlier and a robust display range."""
    names = np.asarray(models, dtype=str)
    values = np.asarray(peer_values, dtype=float)
    if names.size != values.size or values.size < 4:
        raise RuntimeError("Coulomb PFV off-scale detection has invalid peer data")
    if int(np.count_nonzero(names == "r.avaflow")) != 1:
        raise RuntimeError(
            "Coulomb PFV panel requires exactly one r.avaflow peer row"
        )
    outlier_index = int(np.argmax(values))
    if names[outlier_index] != "r.avaflow":
        raise RuntimeError(
            "Coulomb PFV maximum is not the expected r.avaflow outlier"
        )
    visible = np.delete(values, outlier_index)
    q1, q3 = np.quantile(visible, [0.25, 0.75])
    detection_threshold = float(q3 + 3.0 * max(q3 - q1, np.finfo(float).eps))
    if values[outlier_index] <= detection_threshold:
        raise RuntimeError(
            "Coulomb PFV r.avaflow value is no longer a distinct off-scale outlier"
        )
    focus = np.asarray([*visible, *focus_values], dtype=float)
    if not np.all(np.isfinite(focus)):
        raise RuntimeError("Coulomb PFV display values must be finite")
    span = float(np.max(focus) - np.min(focus))
    padding = max(0.10 * span, 1.0)
    tick_step = 2.0
    axis_min = tick_step * np.floor((float(np.min(focus)) - padding) / tick_step)
    axis_max = tick_step * np.ceil((float(np.max(focus)) + padding) / tick_step)
    return {
        "model": str(names[outlier_index]),
        "value": float(values[outlier_index]),
        "peer_index": outlier_index,
        "detection_threshold": detection_threshold,
        "axis_min": float(axis_min),
        "axis_max": float(axis_max),
        "included_in_peer_statistics": True,
        "peer_count_in_statistics": int(values.size),
        "note": (
            "r.avaflow is drawn as an off-scale marker but remains included "
            f"in all n={values.size} peer statistics."
        ),
    }


def main(
    output: Path,
    stem: str,
    avac_label: str,
    results_root: Path,
    comparison_root: Path | None = None,
    comparison_label: str = "Previous configuration",
) -> None:
    apply_paper_style()
    root = results_root.expanduser().resolve()
    summaries = validate_current_source_results(root)
    selected_fields = validated_submission_fields(root, summaries)
    selected_thalwegs = {
        case: validated_thalweg(case) for case, _label in CASES
    }
    output.mkdir(parents=True, exist_ok=True)
    comparison_root = comparison_root.expanduser().resolve() if comparison_root is not None else None
    table_c1_path = Path(__file__).with_name("iseesnow_table_c1_core.csv")
    table_c1, table_c1_artifact = validated_peer_table(table_c1_path)

    fig, axes = plt.subplots(3, 3, figsize=figure_size(2, aspect=0.88), squeeze=False)
    rng = np.random.default_rng(4127)
    provenance: dict[str, object] = {
        "avac_field_source": "hash-validated PFT/PFV submission rasters",
        "peer_scalar_source": str(table_c1_path),
        "peer_scalar_sha256": table_c1_artifact["sha256"],
        "peer_group": "ISeeSnow Table C1 core group",
        "runout_definition": "furthest thalweg coordinate with PFT > 0.5 m",
        "off_scale_notes": [],
        "publication_gate": {
            "execution_mode": "current_source",
            "solver_sha256": summaries[CASES[0][0]]["solver_sha256"],
            "setrun_backend_sha256": summaries[CASES[0][0]]["setrun_backend_sha256"],
            "accepted_cfl_violation_count": 0,
            "selected_protocol": {
                "common": PUBLICATION_PROTOCOL,
                "cases": CASE_PROTOCOL,
            },
            "cases": {
                case: {
                    "maximum_courant_number": summaries[case]["maximum_courant_number"],
                    "cfl_max": summaries[case]["cfl_max"],
                    "pft": field_provenance(selected_fields[case]["pft"]),
                    "pfv": field_provenance(selected_fields[case]["pfv"]),
                    "thalweg": {
                        "artifacts": selected_thalwegs[case]["artifacts"],
                    },
                    "artifacts": summaries[case][
                        "_article_verified_artifacts"
                    ],
                }
                for case, _label in CASES
            },
        },
        "cases": {},
    }

    for row, (case, row_label) in enumerate(CASES):
        case_info: dict[str, object] = {}
        avac_values = {
            "runout_length_m": runout_from_validated_field(
                selected_fields[case]["pft"], selected_thalwegs[case]
            ),
            "pft_peak_m": float(selected_fields[case]["pft"]["peak"]),
            "pfv_peak_mps": float(selected_fields[case]["pfv"]["peak"]),
        }
        comparison_values = None
        if comparison_root is not None:
            comparison_values = {
                "runout_length_m": unverified_avac_runout(
                    case, comparison_root
                ),
                "pft_peak_m": unverified_submission_peak(
                    comparison_root, case, "pft"
                ),
                "pfv_peak_mps": unverified_submission_peak(
                    comparison_root, case, "pfv"
                ),
            }
        peers = table_c1[table_c1["case"] == case]
        for col, (field, scale, title) in enumerate(METRICS):
            ax = axes[row, col]
            peer_values = peers[field].to_numpy(float) * scale
            peer_models = peers["model"].astype(str).to_numpy()
            avac_value = avac_values[field] * scale
            statistics = peer_statistics(peer_values)
            q1 = float(statistics["peer_q1"])
            median = float(statistics["peer_median"])
            q3 = float(statistics["peer_q3"])

            focus_values = [avac_value]
            if comparison_values is not None:
                focus_values.append(comparison_values[field] * scale)
            off_scale = None
            if case == "CoulombOnly" and field == "pfv_peak_mps":
                off_scale = coulomb_pfv_offscale_metadata(
                    peer_models, peer_values, focus_values
                )

            jitter = rng.uniform(-0.075, 0.075, peer_values.size)
            ax.fill_between([-0.18, 0.18], q1, q3, color=MODEL_COLORS["wave"], alpha=0.25, zorder=1)
            ax.hlines(median, -0.18, 0.18, color=MODEL_COLORS["wave"], linewidth=2.2, zorder=2)
            visible = np.ones(peer_values.size, dtype=bool)
            if off_scale is not None:
                visible[int(off_scale["peer_index"])] = False
            ax.scatter(jitter[visible], peer_values[visible], color=MODEL_COLORS["wave"], edgecolor="white", linewidth=0.6, zorder=3)
            avac_x = 2.0 if comparison_values is not None else 1.0
            ax.scatter([avac_x], [avac_value], color=MODEL_COLORS["avac"], marker="D", s=44,
                       edgecolor="white", linewidth=0.7, zorder=4)
            if comparison_values is not None:
                comparison_value = comparison_values[field] * scale
                ax.scatter([1.0], [comparison_value], color=PAPER_COLORS["green"], marker="o", s=42,
                           edgecolor="white", linewidth=0.7, zorder=4)
                ax.set_xlim(-0.45, 2.45)
                ax.set_xticks([0, 1, 2], ["Peers", "Previous", "Selected"])
            else:
                ax.set_xlim(-0.40, 1.40)
                ax.set_xticks([0, 1], ["Peers", "AVAC"])
            if off_scale is not None:
                outlier_index = int(off_scale["peer_index"])
                axis_max = float(off_scale["axis_max"])
                ax.set_ylim(float(off_scale["axis_min"]), axis_max)
                ax.scatter(
                    [jitter[outlier_index]], [axis_max],
                    color=MODEL_COLORS["wave"], marker="^", s=48,
                    edgecolor="white", linewidth=0.6, zorder=5,
                    clip_on=False,
                )
                ax.annotate(
                    f"{off_scale['model']} {float(off_scale['value']):.2f}\n"
                    "(off scale)",
                    xy=(jitter[outlier_index], axis_max),
                    xytext=(2, -4), textcoords="offset points",
                    ha="left", va="top", fontsize=6.7,
                )
                provenance["off_scale_notes"].append(off_scale["note"])
            if row == 0:
                ax.set_title(title)
            if col == 0:
                ax.set_ylabel(row_label)
            panel = chr(ord("a") + row * 3 + col)
            ax.text(0.02, 0.96, f"({panel})", transform=ax.transAxes,
                    ha="left", va="top", fontweight="bold")
            provenance_field = (
                "runout_length_km" if field == "runout_length_m" else field
            )
            case_info[provenance_field] = {
                "source_field": field,
                "display_scale": scale,
                **statistics,
                "avac": avac_value,
            }
            if off_scale is not None:
                case_info[provenance_field]["off_scale_peer"] = off_scale
            if comparison_values is not None:
                case_info[provenance_field]["comparison"] = (
                    comparison_values[field] * scale
                )
        provenance["cases"][case] = case_info

    handles = [
        Line2D([], [], marker="o", linestyle="None", color=MODEL_COLORS["wave"], label="ISeeSnow core models"),
        Patch(facecolor=MODEL_COLORS["wave"], alpha=0.25, edgecolor="none", label="Peer interquartile range"),
        Line2D([], [], color=MODEL_COLORS["wave"], linewidth=2.2, label="Peer median"),
        Line2D([], [], marker="D", linestyle="None", color=MODEL_COLORS["avac"], label=avac_label),
    ]
    if comparison_root is not None:
        handles.insert(
            -1,
            Line2D([], [], marker="o", linestyle="None", color=PAPER_COLORS["green"], label=comparison_label),
        )
    fig.legend(handles=handles, loc="outside lower center", ncol=4)
    fig.subplots_adjust(bottom=0.13, hspace=0.33, wspace=0.30)
    for suffix in ("pdf", "png"):
        fig.savefig(output / f"{stem}.{suffix}")
    plt.close(fig)
    provenance["avac_label"] = avac_label
    provenance["comparison_root"] = str(comparison_root) if comparison_root is not None else None
    provenance["comparison_label"] = comparison_label if comparison_root is not None else None
    (output / f"{stem}.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "docs" / "article" / "figures",
        help="Directory for the PDF, PNG, and provenance JSON.",
    )
    parser.add_argument(
        "--stem",
        default="iseesnow_intercomparison",
        help="Shared filename stem for the figure outputs.",
    )
    parser.add_argument(
        "--avac-label",
        default="AVAC4QGIS",
        help="Legend label for the AVAC marker.",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=REPO / "validation" / "ISeeSnow",
        help="Directory containing the three completed AVAC case folders.",
    )
    parser.add_argument(
        "--comparison-root",
        type=Path,
        help="Optional preserved result directory to show beside the current AVAC values.",
    )
    parser.add_argument(
        "--comparison-label",
        default="Previous configuration",
        help="Legend label for values read from --comparison-root.",
    )
    arguments = parser.parse_args()
    main(
        arguments.output,
        arguments.stem,
        arguments.avac_label,
        arguments.results_root,
        arguments.comparison_root,
        arguments.comparison_label,
    )
