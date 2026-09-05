"""Release-package tests for the embedded managed runtimes."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools" / "validate_release.py"
SPEC = importlib.util.spec_from_file_location("validate_release", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
MAC_PACKAGE_PATH = ROOT / "tools" / "build_plugin_package.py"
MAC_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "build_plugin_package", MAC_PACKAGE_PATH,
)
assert MAC_PACKAGE_SPEC is not None and MAC_PACKAGE_SPEC.loader is not None
MAC_PACKAGE = importlib.util.module_from_spec(MAC_PACKAGE_SPEC)
MAC_PACKAGE_SPEC.loader.exec_module(MAC_PACKAGE)
MAC_RUNTIME_PATH = ROOT / "tools" / "build_macos_arm64_runtime.py"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest_sha256(manifest: dict[str, object]) -> str:
    payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(payload)


def _record(path: str, payload: bytes) -> dict[str, str]:
    return {"path": path, "sha256": _sha256(payload)}


def _runtime_archive(
    platform: str,
    product: str,
    *,
    fault: tuple[str, str] | None = None,
    modern_macos: bool = False,
) -> tuple[bytes, dict[str, object]]:
    """Build a minimal format-1 runtime entirely in memory.

    ``fault`` is applied after the manifest is generated, allowing the outer
    archive and package hashes to remain correct while a nested attestation is
    deliberately false.
    """
    is_windows = platform == "windows-amd64"
    runtime_root = platform if is_windows else "arm64"
    backend_name = product
    solver_path = "bin/xgeoclaw.exe" if is_windows else "bin/xgeoclaw"
    library_path = "lib/runtime.dll" if is_windows else "lib/runtime.dylib"
    clawpack_root = "clawpack" if is_windows else "python/clawpack-src"
    clawpack_init = f"{clawpack_root}/clawpack/__init__.py"
    clawpack_module = f"{clawpack_root}/clawpack/geoclaw/data.py"
    backend_path = f"backend/{backend_name}/setrun.py"
    files = {
        solver_path: f"{product} solver\n".encode(),
        library_path: f"{product} native library\n".encode(),
        backend_path: f"# {product} backend\n".encode(),
        clawpack_init: b"__version__ = '5.14.0'\n",
        clawpack_module: b"# geoclaw fixture\n",
    }
    if fault is not None and fault[0] == "misplaced-backend":
        backend_payload = files.pop(backend_path)
        backend_path = fault[1]
        files[backend_path] = backend_payload

    manifest: dict[str, object] = {
        "format": 1,
        "runtime_version": f"{product.lower()}-test-runtime",
        "architecture": "amd64" if is_windows else "arm64",
        "solver": _record(solver_path, files[solver_path]),
        "native_libraries": [_record(library_path, files[library_path])],
        "backend": [_record(backend_path, files[backend_path])],
        "clawpack": {
            "version": "5.14.0",
            "root": clawpack_root,
            "source_sha256": _sha256(files[clawpack_init]),
        },
    }
    if is_windows:
        manifest["platform"] = platform
        manifest["clawpack"]["files"] = [  # type: ignore[index]
            _record(clawpack_init, files[clawpack_init]),
            _record(clawpack_module, files[clawpack_module]),
        ]
    elif modern_macos:
        manifest["platform"] = platform
        manifest["clawpack"]["files"] = [  # type: ignore[index]
            _record(clawpack_init, files[clawpack_init]),
            _record(clawpack_module, files[clawpack_module]),
        ]

    archived_files = dict(files)
    if fault is not None:
        action, relative = fault
        if action == "tamper":
            archived_files[relative] = b"tampered after manifest generation\n"
        elif action == "missing":
            archived_files.pop(relative)
        elif action == "extra":
            archived_files[relative] = b"undeclared runtime payload\n"
        elif action == "unicode-collision":
            archived_files["bin/caf\u00e9"] = b"composed name\n"
            archived_files["bin/cafe\u0301"] = b"decomposed name\n"
        elif action in {"misplaced-backend", "non-object-manifest"}:
            pass
        else:  # pragma: no cover - fixture misuse
            raise AssertionError(f"unknown runtime fixture fault: {action}")

    manifest_value: object = manifest
    if fault is not None and fault[0] == "non-object-manifest":
        manifest_value = []
    archived_files["runtime-manifest.json"] = (
        json.dumps(manifest_value, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for relative, payload in sorted(archived_files.items()):
            info = tarfile.TarInfo(f"{runtime_root}/{relative}")
            info.size = len(payload)
            info.mode = 0o755 if relative == solver_path else 0o644
            bundle.addfile(info, io.BytesIO(payload))
    return output.getvalue(), manifest


def _write_release(
    tmp_path: Path,
    platform: str,
    *,
    faults: dict[str, tuple[str, str]] | None = None,
    descriptor_overrides: dict[str, object] | None = None,
    descriptor_record_overrides: dict[str, dict[str, object]] | None = None,
    include_wave: bool = True,
    modern_macos: bool = False,
) -> Path:
    faults = faults or {}
    descriptor_overrides = descriptor_overrides or {}
    descriptor_record_overrides = descriptor_record_overrides or {}
    dist = tmp_path / "dist"
    dist.mkdir()
    resources: dict[str, bytes] = {}
    runtimes: dict[str, tuple[bytes, dict[str, object], str]] = {}
    products = [("AVAC", "avac")]
    if include_wave:
        products.append(("WAVE", "wave"))
    for product, prefix in products:
        payload, manifest = _runtime_archive(
            platform,
            product,
            fault=faults.get(product),
            modern_macos=modern_macos,
        )
        archive_name = f"{prefix}-runtime-{platform}-test.tar.gz"
        resources[archive_name] = payload
        runtimes[product] = (payload, manifest, archive_name)

    def descriptor(product: str) -> dict[str, object]:
        _, manifest, archive_name = runtimes[product]
        record = {
            "runtime_version": manifest["runtime_version"],
            "archive": archive_name,
            "runtime_manifest_sha256": _manifest_sha256(manifest),
        }
        if platform == "windows-amd64":
            record["platform"] = platform
        record.update(descriptor_record_overrides.get(product, {}))
        if platform == "windows-amd64":
            return {"runtimes": {platform: record}}
        return record

    package = dist / f"avac_qgis-0.0.0-{platform}.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for required in (
            "__init__.py",
            "plugin.py",
            "metadata.txt",
            "resources/AVAC_configuration100.yaml",
        ):
            bundle.writestr(f"avac_qgis/{required}", b"fixture\n")
        bundle.writestr(
            "avac_qgis/resources/runtime-release.json",
            json.dumps(descriptor_overrides.get("AVAC", descriptor("AVAC"))),
        )
        if include_wave:
            bundle.writestr(
                "avac_qgis/resources/wave-runtime-release.json",
                json.dumps(descriptor_overrides.get("WAVE", descriptor("WAVE"))),
            )
        for name, payload in resources.items():
            bundle.writestr(f"avac_qgis/resources/{name}", payload)

    avac_payload, avac_manifest, _ = runtimes["AVAC"]
    release = {
        "runtime_manifest_sha256": _manifest_sha256(avac_manifest),
        "runtime_archive_sha256": _sha256(avac_payload),
        "solver_sha256": avac_manifest["solver"]["sha256"],  # type: ignore[index]
        "runtime_version": avac_manifest["runtime_version"],
        "plugin_zip_sha256": _sha256(package.read_bytes()),
    }
    if include_wave:
        wave_payload, wave_manifest, _ = runtimes["WAVE"]
        release.update({
            "wave_runtime_manifest_sha256": _manifest_sha256(wave_manifest),
            "wave_runtime_archive_sha256": _sha256(wave_payload),
            "wave_solver_sha256": wave_manifest["solver"]["sha256"],  # type: ignore[index]
            "wave_runtime_version": wave_manifest["runtime_version"],
        })
    (dist / "RELEASE_MANIFEST.json").write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return dist


def _validate(
    monkeypatch: pytest.MonkeyPatch,
    dist: Path,
    platform: str,
    *,
    allow_legacy_macos_runtime: bool = False,
) -> None:
    arguments = [
        str(VALIDATOR_PATH),
        "--dist",
        str(dist),
        "--platform",
        platform,
    ]
    if allow_legacy_macos_runtime:
        arguments.append("--allow-legacy-macos-runtime")
    monkeypatch.setattr(
        sys,
        "argv",
        arguments,
    )
    VALIDATOR.main()


def _refresh_package_hash(dist: Path, package: Path) -> None:
    release_path = dist / "RELEASE_MANIFEST.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["plugin_zip_sha256"] = _sha256(package.read_bytes())
    release_path.write_text(json.dumps(release), encoding="utf-8")


def test_valid_windows_package_attests_avac_and_wave_nested_runtimes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = _write_release(tmp_path, "windows-amd64")

    _validate(monkeypatch, dist, "windows-amd64")

    assert "release validation: PASS" in capsys.readouterr().out


def test_windows_package_rejects_tampered_nested_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"AVAC": ("tamper", "backend/AVAC/setrun.py")},
    )

    with pytest.raises(
        SystemExit,
        match=r"embedded runtime hash differs for .*backend/AVAC/setrun\.py",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


def test_windows_package_rejects_missing_nested_wave_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"WAVE": ("missing", "lib/runtime.dll")},
    )

    with pytest.raises(
        SystemExit,
        match=r"embedded runtime is missing .*lib/runtime\.dll",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


def test_legacy_macos_format_one_package_requires_explicit_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = _write_release(tmp_path, "macos-arm64")

    with pytest.raises(SystemExit, match="has no Clawpack file records"):
        _validate(monkeypatch, dist, "macos-arm64")

    _validate(
        monkeypatch,
        dist,
        "macos-arm64",
        allow_legacy_macos_runtime=True,
    )

    assert "release validation: PASS" in capsys.readouterr().out


def test_modern_macos_avac_and_wave_package_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = _write_release(
        tmp_path,
        "macos-arm64",
        include_wave=True,
        modern_macos=True,
    )

    _validate(monkeypatch, dist, "macos-arm64")

    assert "release validation: PASS" in capsys.readouterr().out


def test_macos_package_rejects_orphaned_wave_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "macos-arm64",
        include_wave=False,
        modern_macos=True,
    )
    package = next(dist.glob("*.zip"))
    with zipfile.ZipFile(package, "a") as bundle:
        bundle.writestr(
            "avac_qgis/resources/wave-runtime-release.json",
            json.dumps({"runtime_version": "orphaned"}),
        )
    _refresh_package_hash(dist, package)

    with pytest.raises(SystemExit, match="incomplete WAVE runtime declaration"):
        _validate(monkeypatch, dist, "macos-arm64")


@pytest.mark.parametrize("platform", ["windows-amd64", "macos-arm64"])
def test_package_rejects_case_insensitive_zip_collision(
    platform: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        platform,
        modern_macos=platform == "macos-arm64",
    )
    package = next(dist.glob("*.zip"))
    with zipfile.ZipFile(package, "a") as bundle:
        bundle.writestr(
            "avac_qgis/RESOURCES/RUNTIME-RELEASE.JSON",
            b"case-colliding descriptor",
        )
    _refresh_package_hash(dist, package)

    with pytest.raises(SystemExit, match="ZIP repeats an extraction path"):
        _validate(monkeypatch, dist, platform)


@pytest.mark.parametrize("platform", ["windows-amd64", "macos-arm64"])
def test_package_rejects_unicode_normalization_zip_collision(
    platform: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        platform,
        modern_macos=platform == "macos-arm64",
    )
    package = next(dist.glob("*.zip"))
    with zipfile.ZipFile(package, "a") as bundle:
        bundle.writestr("avac_qgis/resources/caf\u00e9.txt", b"composed name")
        bundle.writestr("avac_qgis/resources/cafe\u0301.txt", b"decomposed name")
    _refresh_package_hash(dist, package)

    with pytest.raises(SystemExit, match="ZIP repeats an extraction path"):
        _validate(monkeypatch, dist, platform)


def test_macos_staging_replaces_tracked_wave_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    plugin = source_root / "avac_qgis"
    resources = plugin / "resources"
    resources.mkdir(parents=True)
    (resources / "wave-runtime-release.json").write_text("{}", encoding="utf-8")
    (resources / "wave-runtime-macos-arm64-stale.tar.gz").write_bytes(b"stale")
    (source_root / "README.md").write_text("readme", encoding="utf-8")
    (source_root / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")
    for relative in (
        "docs/ui_reference/AVAC_QGIS_UI_REFERENCE.pdf",
        "docs/tutorial/AVAC4QGIS_TUTORIAL.pdf",
    ):
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    runtime_archive = tmp_path / "avac-runtime.tar.gz"
    runtime_archive.write_bytes(b"runtime")
    wave_runtime_archive = tmp_path / "wave-runtime.tar.gz"
    wave_runtime_archive.write_bytes(b"wave runtime")
    monkeypatch.setattr(MAC_PACKAGE, "ROOT", source_root)
    monkeypatch.setattr(MAC_PACKAGE, "PLUGIN", plugin)

    staged = MAC_PACKAGE.copy_plugin(
        tmp_path / "staging",
        runtime_archive,
        "test",
        {"format": 1},
        wave_runtime_archive,
        "wave-test",
        {"format": 1, "product": "WAVE"},
    )

    wave_archives = list((staged / "resources").glob("wave-runtime-*.tar.gz"))
    assert [path.name for path in wave_archives] == [
        "wave-runtime-macos-arm64-wave-test.tar.gz",
    ]
    descriptor = json.loads(
        (staged / "resources" / "runtime-release.json").read_text(encoding="utf-8")
    )
    assert descriptor["platform"] == "macos-arm64"
    wave_descriptor = json.loads(
        (staged / "resources" / "wave-runtime-release.json").read_text(
            encoding="utf-8",
        )
    )
    assert wave_descriptor["platform"] == "macos-arm64"


def test_macos_package_builder_requires_wave_and_runs_release_gate() -> None:
    source = MAC_PACKAGE_PATH.read_text(encoding="utf-8")

    assert 'parser.add_argument("--wave-runtime-archive", type=Path, required=True)' in source
    assert 'parser.add_argument("--wave-runtime-version", required=True)' in source
    assert 'str(ROOT / "tools" / "validate_release.py")' in source
    assert '"--platform",\n            "macos-arm64"' in source


def test_new_macos_runtime_manifest_is_platform_explicit_and_complete() -> None:
    source = MAC_RUNTIME_PATH.read_text(encoding="utf-8")

    assert '"platform": "macos-arm64"' in source
    assert 'for path in sorted(packaged_clawpack.rglob("*"))' in source
    assert '"path": path.relative_to(staging).as_posix()' in source
    assert '"sha256": sha256(path)' in source


@pytest.mark.parametrize(
    ("platform", "modern_macos"),
    [("windows-amd64", False), ("macos-arm64", True)],
)
def test_platform_package_requires_wave_runtime(
    platform: str,
    modern_macos: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        platform,
        include_wave=False,
        modern_macos=modern_macos,
    )

    with pytest.raises(SystemExit, match="missing mandatory plugin resources"):
        _validate(monkeypatch, dist, platform)


@pytest.mark.parametrize("fault", ["tamper", "extra"])
def test_modern_macos_package_closes_manifested_clawpack_payload(
    fault: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = "python/clawpack-src/clawpack/geoclaw/data.py"
    if fault == "extra":
        relative = "python/clawpack-src/clawpack/geoclaw/rogue.py"
    dist = _write_release(
        tmp_path,
        "macos-arm64",
        faults={"AVAC": (fault, relative)},
        modern_macos=True,
    )

    with pytest.raises(SystemExit, match=r"(hash differs|undeclared payload)"):
        _validate(monkeypatch, dist, "macos-arm64")


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("BIN/XGEOCLAW", "repeats a tar member"),
        ("BIN/rogue", "undeclared payload"),
    ],
)
def test_modern_macos_package_rejects_case_insensitive_tar_aliases(
    relative: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "macos-arm64",
        faults={"AVAC": ("extra", relative)},
        modern_macos=True,
    )

    with pytest.raises(SystemExit, match=message):
        _validate(monkeypatch, dist, "macos-arm64")


def test_release_manifest_must_be_a_json_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(tmp_path, "windows-amd64")
    (dist / "RELEASE_MANIFEST.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="release manifest must be a JSON object"):
        _validate(monkeypatch, dist, "windows-amd64")


def test_runtime_descriptor_must_be_a_json_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        descriptor_overrides={"WAVE": []},
    )

    with pytest.raises(
        SystemExit,
        match=r"wave-runtime-release\.json must be a JSON object",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


def test_nested_runtime_manifest_must_be_a_json_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"AVAC": ("non-object-manifest", "runtime-manifest.json")},
    )

    with pytest.raises(
        SystemExit,
        match=r"embedded runtime manifest .* must be a JSON object",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


@pytest.mark.parametrize(
    "relative",
    [
        "bin/rogue.exe",
        "lib/rogue.dll",
        "backend/AVAC/rogue.py",
        "clawpack/clawpack/rogue.py",
    ],
)
def test_windows_package_rejects_undeclared_runtime_payload(
    relative: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"AVAC": ("extra", relative)},
    )

    with pytest.raises(
        SystemExit,
        match=rf"undeclared payload: .*{Path(relative).name}",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


def test_windows_package_rejects_case_insensitive_tar_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"AVAC": ("extra", "BIN/XGEOCLAW.EXE")},
    )

    with pytest.raises(SystemExit, match="repeats a tar member"):
        _validate(monkeypatch, dist, "windows-amd64")


@pytest.mark.parametrize(
    ("platform", "modern_macos"),
    [("windows-amd64", False), ("macos-arm64", True)],
)
def test_package_rejects_unicode_normalization_tar_collision(
    platform: str,
    modern_macos: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        platform,
        faults={"AVAC": ("unicode-collision", "")},
        modern_macos=modern_macos,
    )

    with pytest.raises(SystemExit, match="repeats a tar member"):
        _validate(monkeypatch, dist, platform)


@pytest.mark.parametrize("relative", ["BIN/rogue.exe", "bin//rogue.exe"])
def test_windows_package_rejects_case_or_spelling_protected_root_bypass(
    relative: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"AVAC": ("extra", relative)},
    )

    with pytest.raises(SystemExit, match=r"(undeclared payload|non-canonical path)"):
        _validate(monkeypatch, dist, "windows-amd64")


def test_wave_runtime_backend_records_are_product_specific(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        faults={"WAVE": ("misplaced-backend", "backend/AVAC/setrun.py")},
    )

    with pytest.raises(
        SystemExit,
        match=r"backend file is outside backend/WAVE: backend/AVAC/setrun\.py",
    ):
        _validate(monkeypatch, dist, "windows-amd64")


def test_runtime_descriptor_platform_matches_requested_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        descriptor_record_overrides={"AVAC": {"platform": "macos-arm64"}},
    )

    with pytest.raises(SystemExit, match="descriptor has the wrong platform"):
        _validate(monkeypatch, dist, "windows-amd64")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"archive": "nested/runtime.tar.gz"}, "archive must be a basename"),
        ({"runtime_version": 1}, "no valid runtime version"),
        ({"runtime_version": "different"}, "version differs from release manifest"),
    ],
)
def test_runtime_descriptor_uses_loader_compatible_types_and_paths(
    override: dict[str, object],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _write_release(
        tmp_path,
        "windows-amd64",
        descriptor_record_overrides={"AVAC": override},
    )

    with pytest.raises(SystemExit, match=message):
        _validate(monkeypatch, dist, "windows-amd64")


@pytest.mark.parametrize("path", ["/absolute/member", "../escape", r"lib\\native.dll"])
def test_runtime_manifest_paths_use_portable_posix_relatives(path: str) -> None:
    with pytest.raises(SystemExit, match=r"(unsafe|non-portable) path"):
        VALIDATOR._safe_relative_path(path, label="fixture")
