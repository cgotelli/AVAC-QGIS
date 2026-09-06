"""Local macOS candidate metadata must not modify published source metadata."""
import configparser
import json
import sys
import zipfile

import pytest

from test_release_validation import MAC_PACKAGE


METADATA = (
    "[general]\nname=AVAC4QGIS\nversion=1.0.0\nqgisMinimumVersion=3.40\n"
    "description=Published source plugin.\n\n[experimental]\nexperimental=False\n"
)


@pytest.fixture
def package_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    plugin = source / "avac_qgis"
    resources = plugin / "resources"
    resources.mkdir(parents=True)
    (plugin / "metadata.txt").write_text(METADATA, encoding="utf-8")
    (resources / "runtime-release.json").write_text(
        '{"runtimes":{"windows-amd64":{"runtime_version":"1.0.0"}}}\n', encoding="utf-8",
    )
    (source / "README.md").write_text("Readme\n", encoding="utf-8")
    (source / "THIRD_PARTY_NOTICES.md").write_text("Notices\n", encoding="utf-8")
    for relative in ("ui_reference/AVAC_QGIS_UI_REFERENCE.pdf", "tutorial/AVAC4QGIS_TUTORIAL.pdf"):
        path = source / "docs" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Fixture PDF")
    avac = tmp_path / "avac-runtime.tar.gz"
    wave = tmp_path / "wave-runtime.tar.gz"
    avac.write_bytes(b"AVAC runtime fixture")
    wave.write_bytes(b"WAVE runtime fixture")
    monkeypatch.setattr(MAC_PACKAGE, "ROOT", source)
    monkeypatch.setattr(MAC_PACKAGE, "PLUGIN", plugin)
    return source, plugin, avac, wave


def _parse(text):
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read_string(text)
    return metadata


@pytest.mark.parametrize("overrides", [
    {}, {"plugin_version": "1.0.1-rc2"}, {"experimental": True}, {"experimental": False},
    {"plugin_version": "1.0.1-rc2", "experimental": True},
])
def test_candidate_overrides_change_only_staged_metadata(package_source, tmp_path, overrides):
    _, plugin, avac, wave = package_source
    source_files = {path.relative_to(plugin): path.read_bytes() for path in plugin.rglob("*") if path.is_file()}
    staged = MAC_PACKAGE.copy_plugin(
        tmp_path / "staging", avac, "avac-test", {"format": 1},
        wave, "wave-test", {"format": 1}, **overrides,
    )
    text = (staged / "metadata.txt").read_text(encoding="utf-8")
    if not overrides:
        assert text == METADATA  # Preserve the existing default byte for byte.
    parsed = _parse(text)
    assert parsed["general"]["version"] == overrides.get("plugin_version", "1.0.0")
    assert parsed["general"]["qgisMinimumVersion"] == "3.40"
    assert parsed["general"]["description"] == "Published source plugin."
    if "experimental" in overrides:
        assert parsed["general"].getboolean("experimental") is overrides["experimental"]
        assert not parsed.has_section("experimental")
    for relative, original in source_files.items():
        assert (plugin / relative).read_bytes() == original
    assert MAC_PACKAGE.metadata_version() == "1.0.0"


@pytest.mark.parametrize("version", [
    "", "1.0.1\nexperimental=True", "1.0.1\rexperimental=True", "1.0.1-dev",
    "1.0.1-dev.2", "../1.0.1", "1.0.1/other", " 1.0.1", "1.0.1 ",
])
def test_invalid_version_override_is_rejected_before_staging(package_source, tmp_path, version):
    _, plugin, avac, wave = package_source
    staging = tmp_path / "staging"
    with pytest.raises(ValueError, match="plugin version"):
        MAC_PACKAGE.copy_plugin(
            staging, avac, "avac-test", {"format": 1},
            wave, "wave-test", {"format": 1}, plugin_version=version,
        )
    assert not staging.exists()
    assert (plugin / "metadata.txt").read_text(encoding="utf-8") == METADATA


@pytest.mark.parametrize("candidate", [False, True])
@pytest.mark.parametrize("stable", [False, True])
def test_cli_propagates_metadata_to_zip_name_and_release_manifest(package_source, tmp_path, monkeypatch, candidate, stable):
    _, plugin, avac, wave = package_source
    dist = tmp_path / "dist"
    arguments = [
        "build_plugin_package.py", "--runtime-archive", str(avac), "--runtime-version", "avac-test",
        "--wave-runtime-archive", str(wave), "--wave-runtime-version", "wave-test", "--dist", str(dist),
    ]
    if candidate:
        arguments += ["--plugin-version", "1.0.1-rc2", "--experimental"]
    if stable:
        arguments += ["--no-experimental"]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(MAC_PACKAGE, "runtime_manifest", lambda archive, version: {
        "format": 1, "minimum_macos_version": "14.0", "clawpack": {"version": "5.14.0"},
        "solver": {"sha256": "a" * 64, "source_sha256": "b" * 64},
    })
    validation_calls = []
    monkeypatch.setattr(MAC_PACKAGE.subprocess, "run", lambda *args, **kwargs: validation_calls.append((args, kwargs)))
    MAC_PACKAGE.main()
    version = "1.0.1-rc2" if candidate else "1.0.0"
    package = dist / f"avac_qgis-{version}-macos-arm64.zip"
    assert package.is_file()
    with zipfile.ZipFile(package) as bundle:
        staged = bundle.read("avac_qgis/metadata.txt").decode("utf-8")
    if candidate or stable:
        parsed = _parse(staged)
        assert parsed["general"]["version"] == version
        assert parsed["general"].getboolean("experimental") is (not stable)
        assert not parsed.has_section("experimental")
    else:
        assert staged == METADATA
    manifest = json.loads((dist / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["plugin_version"] == version
    assert manifest["runtime_version"] == "avac-test"
    assert manifest["wave_runtime_version"] == "wave-test"
    assert (plugin / "metadata.txt").read_text(encoding="utf-8") == METADATA
    assert len(validation_calls) == 1
    assert validation_calls[0][1]["check"] is True
