"""Deterministic build manifest creation and integrity verification."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from xaac_thin_client_os.configuration import ProjectConfiguration
from xaac_thin_client_os.packages import ResolvedPackages


class ManifestError(RuntimeError):
    """Raised when a manifest cannot be read or verified."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: object) -> bytes:
    """Serialize a payload deterministically for hashing."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    """Hash a manifest payload without its self-referential integrity field."""
    clean = {key: value for key, value in payload.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(clean)).hexdigest()


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if len(value) == 40 else None


def _repository_manifest(configuration: ProjectConfiguration) -> list[dict[str, object]]:
    return [
        {
            "name": repository.name,
            "uri": repository.uri,
            "suites": list(repository.suites),
            "components": list(repository.components),
            "signed_by": str(repository.signed_by),
            "enabled": repository.enabled,
        }
        for repository in sorted(configuration.repositories, key=lambda item: item.name)
    ]


def _source_paths(root: Path, profile_chain: Iterable[str]) -> tuple[Path, ...]:
    candidates = [
        root / "VERSION",
        root / "pyproject.toml",
        root / "config" / "build.yaml",
        root / "config" / "packages.yaml",
        root / "config" / "repositories.yaml",
        root / "config" / "system.yaml",
        root / "config" / "users.yaml",
        root / "config" / "network.yaml",
        root / "config" / "ssh.yaml",
        root / "config" / "firewall.yaml",
        root / "config" / "kernel.yaml",
        root / "config" / "uefi.yaml",
        root / "config" / "partitions.yaml",
        root / "config" / "systemd.yaml",
        root / "config" / "localization.yaml",
    ]
    candidates.extend(root / "profiles" / name / "profile.yaml" for name in profile_chain)
    templates = root / "templates"
    hooks = root / "hooks"
    for directory in (templates, hooks):
        if directory.is_dir():
            candidates.extend(
                path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()
            )
    return tuple(sorted({path.resolve() for path in candidates if path.is_file()}))


def source_hashes(root: Path, profile_chain: Iterable[str]) -> dict[str, str]:
    """Hash all declarative inputs that influence a build."""
    resolved_root = root.resolve()
    return {
        str(path.relative_to(resolved_root)): sha256_file(path)
        for path in _source_paths(resolved_root, profile_chain)
    }


def create_manifest(
    root: Path,
    configuration: ProjectConfiguration,
    packages: ResolvedPackages,
) -> dict[str, Any]:
    """Create the stable, pre-workspace portion of a build manifest."""
    build = configuration.build
    return {
        "schema_version": 1,
        "project": {
            "name": build.project,
            "version": build.version,
        },
        "target": {
            "architecture": build.architecture.value,
            "profile": build.profile,
            "profile_chain": list(packages.profile_chain),
            "channel": build.channel.value,
            "debian": {
                "suite": build.debian.suite,
                "mirror": build.debian.mirror,
                "components": list(build.debian.components),
            },
        },
        "image": {
            "formats": [item.value for item in build.image.formats],
            "size_mib": build.image.size_mib,
            "output_directory": str(build.image.output_directory),
        },
        "packages": packages.to_manifest(),
        "repositories": _repository_manifest(configuration),
        "source": {
            "git_commit": _git_commit(root.resolve()),
            "files": source_hashes(root, packages.profile_chain),
        },
    }


def finalize_manifest(
    manifest: dict[str, Any],
    *,
    rendered_files: Iterable[Path] = (),
    hook_logs: Iterable[Path] = (),
    root: Path,
) -> dict[str, Any]:
    """Add generated-output hashes and a self-integrity digest."""
    resolved_root = root.resolve()

    def hashes(paths: Iterable[Path]) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in sorted((item.resolve() for item in paths), key=str):
            if path.is_file():
                result[str(path.relative_to(resolved_root))] = sha256_file(path)
        return result

    finalized = dict(manifest)
    finalized["outputs"] = {
        "rendered_files": hashes(rendered_files),
        "hook_logs": hashes(hook_logs),
    }
    finalized["integrity"] = {
        "algorithm": "sha256",
        "manifest": payload_hash(finalized),
    }
    return finalized


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and minimally validate a build manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"No es pot llegir el manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError("El manifest ha de ser un objecte JSON")
    if payload.get("schema_version") != 1:
        raise ManifestError("Versió d'esquema de manifest no suportada")
    return payload


def verify_manifest(path: Path) -> bool:
    """Verify the embedded manifest digest."""
    payload = load_manifest(path)
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ManifestError("El manifest no conté una integritat SHA-256 vàlida")
    expected = integrity.get("manifest")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ManifestError("El hash del manifest no és vàlid")
    if payload_hash(payload) != expected:
        raise ManifestError("La integritat del manifest no coincideix")
    return True
