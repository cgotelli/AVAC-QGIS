#!/usr/bin/env python3
"""Validate a release assembled by a platform package builder."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def manifest_sha256(manifest: dict) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_object(payload: bytes, *, label: str) -> dict:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def _safe_relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{label} has no valid path")
    if "\\" in value:
        raise SystemExit(f"{label} contains a non-portable path: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"{label} contains an unsafe path: {value}")
    return path.as_posix()


def _canonical_archive_name(value: object, *, platform: str, label: str) -> str:
    """Return the extraction identity of one portable archive member.

    Normal Windows and macOS installations may treat case and canonically
    equivalent Unicode spellings as one file, so two byte-distinct archive
    members can still overwrite the same installed path. Reject those aliases
    before validating payload hashes. We also require the archive spelling to
    already be structurally normalized so ``a/./b`` and ``a//b`` cannot hide
    a second extraction identity.
    """
    if not isinstance(value, str):
        raise SystemExit(f"{label} has no valid path")
    normalized = _safe_relative_path(value, label=label)
    if normalized in {"", "."} or normalized != value:
        raise SystemExit(f"{label} contains a non-canonical path: {value}")
    if platform == "windows-amd64":
        for component in PurePosixPath(normalized).parts:
            if ":" in component or component.endswith((" ", ".")):
                raise SystemExit(f"{label} contains an unsafe Windows path: {value}")
    if platform in {"windows-amd64", "macos-arm64"}:
        return unicodedata.normalize("NFC", normalized).casefold()
    return normalized


def _runtime_record(
    descriptor: dict,
    release: dict,
    *,
    platform: str,
    release_version_key: str,
) -> dict:
    """Select and validate a descriptor record as the plugin loader does."""
    runtimes = descriptor.get("runtimes")
    record = runtimes.get(platform) if isinstance(runtimes, dict) else descriptor
    if not isinstance(record, dict):
        raise SystemExit(f"runtime descriptor has no {platform} record")

    declared_platform = record.get("platform", platform)
    if not isinstance(declared_platform, str) or declared_platform != platform:
        raise SystemExit(f"runtime descriptor has the wrong platform for {platform}")
    version = record.get("runtime_version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("runtime descriptor has no valid runtime version")
    release_version = release.get(release_version_key)
    if not isinstance(release_version, str) or release_version != version:
        raise SystemExit("runtime descriptor version differs from release manifest")
    archive_value = record.get("archive")
    archive_name = _safe_relative_path(archive_value, label="runtime archive")
    if archive_value != archive_name or PurePosixPath(archive_name).name != archive_name:
        raise SystemExit("runtime archive must be a basename")
    return record


def _runtime_file_hash(
    bundle: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    runtime_root: str,
    record: object,
    *,
    label: str,
) -> str:
    if not isinstance(record, dict):
        raise SystemExit(f"{label} is not a file record")
    relative = _safe_relative_path(record.get("path"), label=label)
    expected = record.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise SystemExit(f"{label} has no valid SHA-256")
    member_name = f"{runtime_root}/{relative}"
    member = members.get(member_name)
    if member is None or not member.isfile():
        raise SystemExit(f"embedded runtime is missing {member_name}")
    stream = bundle.extractfile(member)
    if stream is None:
        raise SystemExit(f"could not read embedded runtime file {member_name}")
    actual = hashlib.sha256(stream.read()).hexdigest()
    if actual != expected:
        raise SystemExit(f"embedded runtime hash differs for {member_name}")
    return actual


def validate_embedded_runtime(
    package: zipfile.ZipFile,
    descriptor: dict,
    release: dict,
    *,
    platform: str,
    archive_hash_key: str,
    manifest_hash_key: str,
    solver_hash_key: str,
    release_version_key: str,
    backend_name: str,
    allow_legacy_macos_runtime: bool = False,
) -> None:
    record = _runtime_record(
        descriptor,
        release,
        platform=platform,
        release_version_key=release_version_key,
    )
    archive_name = str(record["archive"])
    zip_name = f"avac_qgis/resources/{archive_name}"
    try:
        payload = package.read(zip_name)
    except KeyError as exc:
        raise SystemExit(f"ZIP is missing embedded runtime {zip_name}") from exc
    if sha256_bytes(payload) != release.get(archive_hash_key):
        raise SystemExit(f"{zip_name} hash differs from release manifest")

    try:
        bundle = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    except tarfile.TarError as exc:
        raise SystemExit(f"embedded runtime is not a readable gzip tar: {zip_name}") from exc
    with bundle:
        entries = bundle.getmembers()
        canonical_names: set[str] = set()
        for entry in entries:
            canonical = _canonical_archive_name(
                entry.name,
                platform=platform,
                label=f"embedded runtime member in {zip_name}",
            )
            if canonical in canonical_names:
                raise SystemExit(f"embedded runtime repeats a tar member: {zip_name}")
            canonical_names.add(canonical)
        members = {entry.name: entry for entry in entries}
        runtime_root = platform
        manifest_name = f"{runtime_root}/runtime-manifest.json"
        # Format-1 macOS archives predate the explicit platform field and
        # use the architecture as their top-level directory.  They remain a
        # supported release input; Windows archives use the full target key.
        if manifest_name not in members and platform == "macos-arm64":
            runtime_root = "arm64"
            manifest_name = f"{runtime_root}/runtime-manifest.json"
        root_identity = _canonical_archive_name(
            runtime_root,
            platform=platform,
            label="runtime root",
        )
        for entry in entries:
            entry_identity = _canonical_archive_name(
                entry.name,
                platform=platform,
                label=f"embedded runtime member in {zip_name}",
            )
            first_component = entry_identity.split("/", 1)[0]
            if first_component != root_identity:
                raise SystemExit(f"embedded runtime member is outside {runtime_root}: {entry.name}")
        manifest_member = members.get(manifest_name)
        if manifest_member is None or not manifest_member.isfile():
            raise SystemExit(f"embedded runtime lacks {manifest_name}")
        manifest_stream = bundle.extractfile(manifest_member)
        if manifest_stream is None:
            raise SystemExit(f"could not read {manifest_name}")
        runtime_manifest = _json_object(
            manifest_stream.read(), label=f"embedded runtime manifest in {zip_name}",
        )

        identity = manifest_sha256(runtime_manifest)
        descriptor_identity = record.get("runtime_manifest_sha256")
        if identity != descriptor_identity or identity != release.get(manifest_hash_key):
            raise SystemExit(f"embedded runtime manifest identity differs: {zip_name}")
        if runtime_manifest.get("format") != 1:
            raise SystemExit(f"embedded runtime has an unsupported format: {zip_name}")
        declared_platform = runtime_manifest.get("platform")
        if declared_platform != platform and not (
            platform == "macos-arm64"
            and declared_platform is None
            and runtime_manifest.get("architecture") == "arm64"
        ):
            raise SystemExit(f"embedded runtime has the wrong platform: {zip_name}")
        expected_architecture = "amd64" if platform == "windows-amd64" else "arm64"
        if runtime_manifest.get("architecture") != expected_architecture:
            raise SystemExit(f"embedded runtime has the wrong architecture: {zip_name}")
        if runtime_manifest.get("runtime_version") != record.get("runtime_version"):
            raise SystemExit(f"embedded runtime has the wrong version: {zip_name}")

        solver_record = runtime_manifest.get("solver")
        solver_relative = _safe_relative_path(
            solver_record.get("path") if isinstance(solver_record, dict) else None,
            label="runtime solver",
        )
        solver_hash = _runtime_file_hash(
            bundle,
            members,
            runtime_root,
            solver_record,
            label="runtime solver",
        )
        if solver_hash != release.get(solver_hash_key):
            raise SystemExit(f"embedded runtime solver differs from release manifest: {zip_name}")

        def record_identity(relative: str) -> str:
            if platform in {"windows-amd64", "macos-arm64"}:
                return unicodedata.normalize("NFC", relative).casefold()
            return relative

        seen: set[str] = {record_identity(solver_relative)}
        declared = {record_identity(solver_relative)}
        backend_paths: set[str] = set()
        backend_root = f"backend/{backend_name}"
        for section in ("native_libraries", "backend"):
            records = runtime_manifest.get(section)
            if not isinstance(records, list) or not records:
                raise SystemExit(f"embedded runtime has no {section} records: {zip_name}")
            for index, file_record in enumerate(records):
                relative = _safe_relative_path(
                    file_record.get("path") if isinstance(file_record, dict) else None,
                    label=f"{section}[{index}]",
                )
                identity_key = record_identity(relative)
                if identity_key in seen:
                    raise SystemExit(f"embedded runtime repeats file record {relative}")
                seen.add(identity_key)
                declared.add(identity_key)
                if section == "backend":
                    if not relative.startswith(backend_root + "/"):
                        raise SystemExit(
                            f"embedded runtime backend file is outside {backend_root}: {relative}"
                        )
                    backend_paths.add(relative)
                _runtime_file_hash(
                    bundle,
                    members,
                    runtime_root,
                    file_record,
                    label=f"{section}[{index}]",
                )
        expected_backend = f"{backend_root}/setrun.py"
        if expected_backend not in backend_paths:
            raise SystemExit(f"embedded runtime lacks backend record {expected_backend}")

        clawpack = runtime_manifest.get("clawpack")
        if not isinstance(clawpack, dict):
            raise SystemExit(f"embedded runtime has no Clawpack record: {zip_name}")
        clawpack_root = _safe_relative_path(clawpack.get("root"), label="Clawpack root")
        init_record = {
            "path": f"{clawpack_root}/clawpack/__init__.py",
            "sha256": clawpack.get("source_sha256"),
        }
        _runtime_file_hash(
            bundle,
            members,
            runtime_root,
            init_record,
            label="Clawpack version source",
        )
        declared.add(record_identity(init_record["path"]))
        clawpack_files = clawpack.get("files")
        legacy_macos = (
            platform == "macos-arm64"
            and runtime_root == "arm64"
            and declared_platform is None
        )
        if clawpack_files is None:
            if not legacy_macos or not allow_legacy_macos_runtime:
                raise SystemExit(f"embedded runtime has no Clawpack file records: {zip_name}")
        else:
            if not isinstance(clawpack_files, list) or not clawpack_files:
                raise SystemExit(f"embedded runtime has invalid Clawpack file records: {zip_name}")
            for index, file_record in enumerate(clawpack_files):
                relative = _safe_relative_path(
                    file_record.get("path") if isinstance(file_record, dict) else None,
                    label=f"clawpack.files[{index}]",
                )
                identity_key = record_identity(relative)
                if identity_key in seen:
                    raise SystemExit(f"embedded runtime repeats file record {relative}")
                seen.add(identity_key)
                declared.add(identity_key)
                if relative != clawpack_root and not relative.startswith(clawpack_root + "/"):
                    raise SystemExit(f"Clawpack file is outside its declared root: {relative}")
                _runtime_file_hash(
                    bundle,
                    members,
                    runtime_root,
                    file_record,
                    label=f"clawpack.files[{index}]",
                )

        protected_roots = ["bin", "lib", "backend"]
        if clawpack_files is not None:
            protected_roots.append(clawpack_root)
        protected_identities = [record_identity(root) for root in protected_roots]
        prefix_parts = len(PurePosixPath(runtime_root).parts)
        undeclared: list[str] = []
        for entry in entries:
            if entry.isdir():
                continue
            normalized = PurePosixPath(entry.name).as_posix()
            relative = PurePosixPath(*PurePosixPath(normalized).parts[prefix_parts:]).as_posix()
            identity_key = record_identity(relative)
            protected = any(
                identity_key == root or identity_key.startswith(root + "/")
                for root in protected_identities
            )
            if protected and identity_key not in declared:
                undeclared.append(relative)
        if undeclared:
            raise SystemExit(
                f"embedded {platform} runtime contains undeclared payload: "
                + ", ".join(sorted(undeclared)[:5])
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--package", type=Path, help="validate this ZIP when dist retains prior releases")
    parser.add_argument("--platform", default="macos-arm64", help="release target suffix, e.g. windows-amd64")
    parser.add_argument(
        "--allow-legacy-macos-runtime",
        action="store_true",
        help=(
            "accept old arm64 runtime manifests that predate complete Clawpack "
            "file records; never use this for newly built releases"
        ),
    )
    args = parser.parse_args()
    dist = args.dist.resolve()
    release_manifest = dist / "RELEASE_MANIFEST.json"
    try:
        manifest_payload = release_manifest.read_bytes()
    except OSError as exc:
        raise SystemExit(f"release manifest cannot be read: {release_manifest}") from exc
    manifest = _json_object(manifest_payload, label="release manifest")
    package = args.package.resolve() if args.package else None
    if package is None:
        packages = list(dist.glob(f"avac_qgis-*-{args.platform}.zip"))
        if len(packages) != 1:
            raise SystemExit("expected exactly one release ZIP (or pass --package)")
        package = packages[0]
    if not package.is_file():
        raise SystemExit(f"release ZIP not found: {package}")
    if sha256(package) != manifest.get("plugin_zip_sha256"):
        raise SystemExit("plugin ZIP hash differs from release manifest")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        zip_identities: set[str] = set()
        for entry in archive.infolist():
            spelling = entry.filename[:-1] if entry.is_dir() else entry.filename
            identity = _canonical_archive_name(
                spelling,
                platform=args.platform,
                label="plugin ZIP member",
            )
            if identity in zip_identities:
                raise SystemExit("plugin ZIP repeats an extraction path")
            zip_identities.add(identity)
        if not names or any(not name.startswith("avac_qgis/") for name in names):
            raise SystemExit("ZIP does not have one avac_qgis/ root")
        wave_descriptor = "avac_qgis/resources/wave-runtime-release.json"
        required = {
            "avac_qgis/__init__.py",
            "avac_qgis/plugin.py",
            "avac_qgis/metadata.txt",
            "avac_qgis/resources/AVAC_configuration100.yaml",
            "avac_qgis/resources/runtime-release.json",
        }
        required.add(wave_descriptor)
        if not required.issubset(names):
            raise SystemExit("ZIP is missing mandatory plugin resources")
        bad = [name for name in names if "/tests/" in name or "__pycache__" in name or name.endswith((".pyc", ".DS_Store"))]
        if bad:
            raise SystemExit("development artifacts in ZIP: " + ", ".join(bad[:5]))
        runtime_specs = [
            (
                "avac_qgis/resources/runtime-release.json",
                "runtime_manifest_sha256",
                "runtime_archive_sha256",
                "solver_sha256",
                "runtime_version",
                "AVAC",
            ),
            (
                "avac_qgis/resources/wave-runtime-release.json",
                "wave_runtime_manifest_sha256",
                "wave_runtime_archive_sha256",
                "wave_solver_sha256",
                "wave_runtime_version",
                "WAVE",
            ),
        ]
        wave_release_keys = {
            "wave_runtime_manifest_sha256",
            "wave_runtime_archive_sha256",
            "wave_solver_sha256",
            "wave_runtime_version",
        }
        # Both platform packages are complete AVAC+WAVE products.  Neither
        # optional workflow may require an end user to add a runtime manually.
        if not wave_release_keys.issubset(manifest):
            raise SystemExit("release has an incomplete WAVE runtime declaration")

        for (
            descriptor_name,
            release_key,
            archive_key,
            solver_key,
            version_key,
            backend_name,
        ) in runtime_specs:
            descriptor = _json_object(
                archive.read(descriptor_name), label=descriptor_name,
            )
            runtimes = descriptor.get("runtimes")
            record = runtimes.get(args.platform) if isinstance(runtimes, dict) else descriptor
            fingerprint = record.get("runtime_manifest_sha256") if isinstance(record, dict) else None
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                raise SystemExit(f"{descriptor_name} has no runtime manifest identity")
            if fingerprint != manifest.get(release_key):
                raise SystemExit(f"{descriptor_name} differs from release manifest")
            validate_embedded_runtime(
                archive,
                descriptor,
                manifest,
                platform=args.platform,
                archive_hash_key=archive_key,
                manifest_hash_key=release_key,
                solver_hash_key=solver_key,
                release_version_key=version_key,
                backend_name=backend_name,
                allow_legacy_macos_runtime=args.allow_legacy_macos_runtime,
            )
    print(f"release validation: PASS ({package.name})")


if __name__ == "__main__":
    main()
