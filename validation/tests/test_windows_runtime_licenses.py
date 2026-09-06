"""Packaging-only checks: no solver execution or production state changes."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("windows_runtime_licenses", ROOT / "tools/windows_runtime_licenses.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    library = tmp_path / "example.dll"
    library.write_bytes(b"unchanged library")
    (bundle / "COPYING").write_bytes(b"license text")
    manifest = {
        "format": 1,
        "libraries": {library.name: hashlib.sha256(library.read_bytes()).hexdigest()},
        "files": [{"path": "COPYING", "sha256": hashlib.sha256(b"license text").hexdigest()}],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return bundle, library, manifest


def test_copy_is_offline_and_preserves_payload(tmp_path):
    bundle, library, manifest = fixture_bundle(tmp_path)
    before = library.read_bytes()
    MODULE.copy_runtime_licenses(tmp_path / "licenses", [library], bundle)
    assert library.read_bytes() == before
    assert (tmp_path / "licenses/COPYING").read_bytes() == b"license text"
    assert json.loads((tmp_path / "licenses/WINDOWS_RUNTIME_SOURCES.json").read_text()) == manifest


@pytest.mark.parametrize("fault", ["changed-dll", "missing-dll", "duplicate-dll", "changed-notice", "missing-notice", "unsafe-path", "empty"])
def test_refuses_unreviewed_or_incomplete_bundle(tmp_path, fault):
    bundle, library, manifest = fixture_bundle(tmp_path)
    libraries = [library]
    if fault == "changed-dll":
        library.write_bytes(b"another compiler")
    elif fault == "missing-dll":
        libraries = []
    elif fault == "duplicate-dll":
        libraries *= 2
    elif fault == "changed-notice":
        (bundle / "COPYING").write_bytes(b"changed")
    elif fault == "missing-notice":
        (bundle / "COPYING").unlink()
    elif fault == "unsafe-path":
        manifest["files"][0]["path"] = "../COPYING"
    elif fault == "empty":
        manifest["files"] = []
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        MODULE.copy_runtime_licenses(tmp_path / "licenses", libraries, bundle)
    assert not (tmp_path / "licenses").exists()


def test_checked_in_notice_bundle_hashes():
    bundle = MODULE.DEFAULT_BUNDLE
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert len(manifest["libraries"]) == 6
    assert len(manifest["files"]) == 8
    for record in manifest["files"]:
        assert hashlib.sha256((bundle / record["path"]).read_bytes()).hexdigest() == record["sha256"]


@pytest.mark.parametrize("template", ["old", "windows"])
def test_windows_readme_refreshes_tested_version(template):
    spec = importlib.util.spec_from_file_location("win_package", ROOT / "tools/build_windows_plugin_package.py")
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    text = (
        "The current release is **0.6.1** and targets **QGIS 3.44 LTS**."
        if template == "old" else
        "The current Windows release is **0.6.1**, supports **QGIS 3.40 or newer**, and\n"
        "was tested with **QGIS 3.40.11-Bratislava**."
    )
    result = package.windows_readme_support(text, "0.6.1", "3.44.0")
    assert "QGIS 3.44.0" in result
    assert "3.40.11" not in result
    assert package.windows_readme_support(result, "0.6.1", "3.44.0") == result
