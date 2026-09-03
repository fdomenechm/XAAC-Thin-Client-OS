from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaac_thin_client_os.configuration import load_project_configuration
from xaac_thin_client_os.manifest import (
    ManifestError,
    canonical_json,
    create_manifest,
    finalize_manifest,
    load_manifest,
    payload_hash,
    sha256_file,
    source_hashes,
    verify_manifest,
)
from xaac_thin_client_os.packages import resolve_packages


def test_sha256_file_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"xaac")
    assert sha256_file(path) == "14d2368e939f2aa2514ace5f6b0b67fb209d09855d72997d3e687fd19a2aaa26"


def test_canonical_json_ignores_mapping_order() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})


def test_create_manifest_contains_traceability(project_root: Path) -> None:
    configuration = load_project_configuration(project_root)
    packages = resolve_packages(project_root, configuration)
    manifest = create_manifest(project_root, configuration, packages)
    assert manifest["schema_version"] == 1
    assert manifest["project"]["version"] == "1.1.0"
    assert manifest["target"]["profile_chain"] == ["common", "wyse3040"]
    assert manifest["packages"]["package_count"] == len(packages.packages)
    assert "config/build.yaml" in manifest["source"]["files"]
    assert manifest["repositories"]


def test_source_hashes_are_deterministic(project_root: Path) -> None:
    first = source_hashes(project_root, ("common", "wyse3040"))
    second = source_hashes(project_root, ("common", "wyse3040"))
    assert first == second
    assert all(len(value) == 64 for value in first.values())


def test_finalize_and_verify_manifest(tmp_path: Path) -> None:
    rendered = tmp_path / "rendered"
    log = tmp_path / "hook.log"
    rendered.write_text("content", encoding="utf-8")
    log.write_text("ok", encoding="utf-8")
    manifest = finalize_manifest(
        {"schema_version": 1, "project": {"name": "XAAC"}},
        rendered_files=[rendered],
        hook_logs=[log],
        root=tmp_path,
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_manifest(path)
    assert manifest["outputs"]["rendered_files"]["rendered"] == sha256_file(rendered)


def test_tampered_manifest_is_rejected(tmp_path: Path) -> None:
    manifest = finalize_manifest({"schema_version": 1, "value": 1}, root=tmp_path)
    manifest["value"] = 2
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ManifestError, match="integritat"):
        verify_manifest(path)


def test_load_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError, match="No es pot llegir"):
        load_manifest(path)


def test_load_manifest_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ManifestError, match="esquema"):
        load_manifest(path)


def test_payload_hash_excludes_integrity() -> None:
    first = payload_hash({"schema_version": 1, "integrity": {"manifest": "x"}})
    second = payload_hash({"schema_version": 1, "integrity": {"manifest": "y"}})
    assert first == second
