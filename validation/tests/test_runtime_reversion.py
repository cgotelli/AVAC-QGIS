"""Version-only runtime promotion must not change executable/source/license bytes."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_reversion", ROOT / "tools/reversion_windows_runtime.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_archive(path, fault=None):
    files = {"bin/solver.exe": b"solver", "lib/runtime.dll": b"dll", "backend/AVAC/setrun.py": b"source\r\n", "clawpack/init.py": b"clawpack", "licenses/LICENSE": b"license"}
    def record(name):
        return {"path": name, "sha256": hashlib.sha256(files[name]).hexdigest()}
    manifest = {"format": 1, "platform": "windows-amd64", "architecture": "amd64", "runtime_version": "0.6.1", "solver": record("bin/solver.exe"), "native_libraries": [record("lib/runtime.dll")], "backend": [record("backend/AVAC/setrun.py")], "clawpack": {"files": [record("clawpack/init.py")]}, "licenses": [record("licenses/LICENSE")]}
    if fault == "tamper":
        files["bin/solver.exe"] = b"changed"
    elif fault == "undeclared":
        files["licenses/extra"] = b"unlisted"
    files["runtime-manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo("windows-amd64/" + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_version_only_preserves_every_payload(tmp_path):
    source, target = tmp_path / "old.tar.gz", tmp_path / "new.tar.gz"
    make_archive(source)
    report = MODULE.reversion_archive(source, target, "0.6.1", "1.0.0")
    assert report["unchanged_manifested_files"] == 5
    assert report["changed_manifest_fields"] == ["runtime_version"]
    assert report["changed_files"] == ["windows-amd64/runtime-manifest.json"]


@pytest.mark.parametrize("fault", ["tamper", "undeclared", "wrong-version", "invalid-version", "overwrite"])
def test_reversion_refuses_invalid_sources(tmp_path, fault):
    source, target = tmp_path / "old.tar.gz", tmp_path / "new.tar.gz"
    make_archive(source, fault)
    if fault == "overwrite":
        target.write_bytes(b"preserve me")
    with pytest.raises(ValueError):
        MODULE.reversion_archive(source, target, "0.5.0" if fault == "wrong-version" else "0.6.1", "../x" if fault == "invalid-version" else "1.0.0")
    if fault == "overwrite":
        assert target.read_bytes() == b"preserve me"
    else:
        assert not target.exists()


def test_live_windows_descriptors_follow_plugin_version():
    metadata = dict(line.split("=", 1) for line in (ROOT / "avac_qgis/metadata.txt").read_text().splitlines() if "=" in line)
    version = metadata["version"]
    for name, prefix in [("runtime-release.json", "avac"), ("wave-runtime-release.json", "wave")]:
        payload = json.loads((ROOT / "avac_qgis/resources" / name).read_text())
        record = payload["runtimes"]["windows-amd64"]
        assert record["runtime_version"] == version
        assert record["platform"] == "windows-amd64"
        assert record["archive"] == f"{prefix}-runtime-windows-amd64-{version}.tar.gz"
        assert len(record["runtime_manifest_sha256"]) == 64
