"""Declarative XAAC APT repository layout (phase 10.2)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class XaacAptRepositoryError(RuntimeError):
    """Raised when the XAAC APT repository policy is invalid or unsafe."""


_TOKEN = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_ARCH = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FINGERPRINT = re.compile(r"^[0-9A-F]{40}$")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XaacAptRepositoryError(f"Valor invàlid en {field}")
    return value


def _token(value: object, field: str) -> str:
    text = _text(value, field)
    if not _TOKEN.fullmatch(text):
        raise XaacAptRepositoryError(f"Token invàlid en {field}")
    return text


def _path(value: object, field: str) -> str:
    text = _text(value, field)
    parts = PurePosixPath(text).parts
    if not text.startswith("/") or ".." in parts:
        raise XaacAptRepositoryError(f"Ruta insegura en {field}")
    return text


def load_xaac_apt_repository(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise XaacAptRepositoryError(f"No s'ha pogut carregar el repositori: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise XaacAptRepositoryError("Política de repositori invàlida")
    raw["repository_id"] = _token(raw.get("repository_id"), "repository_id")

    publication = raw.get("publication")
    if not isinstance(publication, dict):
        raise XaacAptRepositoryError("Secció publication absent")
    publication["origin"] = _text(publication.get("origin"), "publication.origin")
    publication["label"] = _text(publication.get("label"), "publication.label")
    publication["base_url"] = _text(publication.get("base_url"), "publication.base_url")
    if not publication["base_url"].startswith("https://"):
        raise XaacAptRepositoryError("La publicació ha d'utilitzar HTTPS")
    publication["root"] = _path(publication.get("root"), "publication.root")
    publication["incoming"] = _path(publication.get("incoming"), "publication.incoming")

    channels = raw.get("channels")
    if not isinstance(channels, list) or not channels:
        raise XaacAptRepositoryError("Cal definir canals")
    ids: list[str] = []
    suites: list[str] = []
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            raise XaacAptRepositoryError("Canal invàlid")
        channel["id"] = _token(channel.get("id"), f"channels[{index}].id")
        channel["suite"] = _token(channel.get("suite"), f"channels[{index}].suite")
        channel["codename"] = _token(channel.get("codename"), f"channels[{index}].codename")
        if not isinstance(channel.get("automatic_publish"), bool):
            raise XaacAptRepositoryError("automatic_publish ha de ser booleà")
        ids.append(channel["id"]); suites.append(channel["suite"])
    if len(ids) != len(set(ids)) or len(suites) != len(set(suites)):
        raise XaacAptRepositoryError("Canals o suites duplicats")

    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise XaacAptRepositoryError("Cal definir components")
    raw["components"] = [_token(item, "components") for item in components]
    if len(raw["components"]) != len(set(raw["components"])):
        raise XaacAptRepositoryError("Components duplicats")

    architectures = raw.get("architectures")
    if not isinstance(architectures, list) or not architectures:
        raise XaacAptRepositoryError("Cal definir arquitectures")
    if not all(isinstance(item, str) and _ARCH.fullmatch(item) for item in architectures):
        raise XaacAptRepositoryError("Arquitectura invàlida")
    if len(architectures) != len(set(architectures)):
        raise XaacAptRepositoryError("Arquitectures duplicades")

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        raise XaacAptRepositoryError("Metadades absents")
    if metadata.get("generate_packages") is not True or metadata.get("generate_release") is not True:
        raise XaacAptRepositoryError("Les metadades APT obligatòries no es poden desactivar")
    if metadata.get("generate_inrelease") is not True or metadata.get("generate_release_gpg") is not True:
        raise XaacAptRepositoryError("La signatura de Release és obligatòria")
    hashes = metadata.get("hashes")
    if not isinstance(hashes, list) or "SHA256" not in hashes or any(item in {"MD5Sum", "SHA1"} for item in hashes):
        raise XaacAptRepositoryError("Política de hashes insegura")
    valid_days = metadata.get("valid_for_days")
    if not isinstance(valid_days, int) or isinstance(valid_days, bool) or not 1 <= valid_days <= 30:
        raise XaacAptRepositoryError("Vigència de metadades invàlida")

    signing = raw.get("signing")
    if not isinstance(signing, dict):
        raise XaacAptRepositoryError("Configuració de signatura absent")
    fingerprint = _text(signing.get("fingerprint"), "signing.fingerprint")
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise XaacAptRepositoryError("Empremta de signatura invàlida")
    signing["private_key_source"] = _path(signing.get("private_key_source"), "signing.private_key_source")
    if signing.get("allow_unsigned") is not False:
        raise XaacAptRepositoryError("No es permet publicar sense signatura")

    mirror = raw.get("local_mirror")
    if not isinstance(mirror, dict) or not isinstance(mirror.get("enabled"), bool):
        raise XaacAptRepositoryError("Configuració de mirall invàlida")
    mirror["root"] = _path(mirror.get("root"), "local_mirror.root")
    mirror["source_url"] = _text(mirror.get("source_url"), "local_mirror.source_url")
    if not mirror["source_url"].startswith("https://"):
        raise XaacAptRepositoryError("El mirall ha de tindre un origen HTTPS")
    if not isinstance(mirror.get("verify_signatures"), bool) or mirror["verify_signatures"] is not True:
        raise XaacAptRepositoryError("El mirall ha de verificar signatures")

    retention = raw.get("retention")
    if not isinstance(retention, dict):
        raise XaacAptRepositoryError("Política de retenció absent")
    keep = retention.get("versions_per_package")
    if not isinstance(keep, int) or isinstance(keep, bool) or not 2 <= keep <= 20:
        raise XaacAptRepositoryError("Retenció de versions invàlida")
    if retention.get("keep_published_snapshots") is not True:
        raise XaacAptRepositoryError("Cal conservar snapshots publicats")

    outputs = raw.get("outputs")
    required = {"policy", "layout", "distributions", "mirror_config", "state"}
    if not isinstance(outputs, dict) or set(outputs) != required:
        raise XaacAptRepositoryError("outputs incomplet")
    raw["outputs"] = {key: _path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class XaacAptRepositoryPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "repository_id": self.profile["repository_id"],
            "channel_count": len(self.profile["channels"]),
            "component_count": len(self.profile["components"]),
            "architecture_count": len(self.profile["architectures"]),
        }


def create_xaac_apt_repository_plan(rootfs: Path, profile_path: Path) -> XaacAptRepositoryPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise XaacAptRepositoryError(f"Rootfs insegur: {root}")
    return XaacAptRepositoryPlan(root, load_xaac_apt_repository(profile_path))


class XaacAptRepositoryInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise XaacAptRepositoryError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def install(self, plan: XaacAptRepositoryPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "layout", "distributions", "mirror_config", "state"))
        if dry_run:
            return targets
        p = plan.profile
        layout = {
            "root": p["publication"]["root"],
            "incoming": p["publication"]["incoming"],
            "pool": "pool/{component}/{source-prefix}/{source}",
            "indices": "dists/{suite}/{component}/binary-{architecture}/Packages",
            "channels": {channel["id"]: channel["suite"] for channel in p["channels"]},
        }
        distributions = []
        for channel in p["channels"]:
            distributions.append(
                "\n".join((
                    f"Origin: {p['publication']['origin']}",
                    f"Label: {p['publication']['label']}",
                    f"Codename: {channel['codename']}",
                    f"Suite: {channel['suite']}",
                    f"Architectures: {' '.join(p['architectures'])}",
                    f"Components: {' '.join(p['components'])}",
                    f"SignWith: {p['signing']['fingerprint']}",
                ))
            )
        mirror = {
            "enabled": p["local_mirror"]["enabled"],
            "source_url": p["local_mirror"]["source_url"],
            "root": p["local_mirror"]["root"],
            "verify_signatures": True,
            "suites": [channel["suite"] for channel in p["channels"]],
            "components": p["components"],
            "architectures": p["architectures"],
        }
        state = {"status": "configured", **plan.manifest(), "published_snapshots": []}
        policy = {key: value for key, value in p.items() if key != "outputs"}
        self._write(plan.output("policy"), json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o644)
        self._write(plan.output("layout"), json.dumps(layout, indent=2, sort_keys=True) + "\n", 0o644)
        self._write(plan.output("distributions"), "\n\n".join(distributions) + "\n", 0o640)
        self._write(plan.output("mirror_config"), json.dumps(mirror, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(plan.output("state"), json.dumps(state, indent=2, sort_keys=True) + "\n", 0o640)
        return targets
