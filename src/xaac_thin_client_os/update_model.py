"""Update architecture and version policy for XAAC Thin Client OS phase 10.2."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class UpdateModelError(RuntimeError):
    """Raised when the phase 10.2 update architecture is unsafe or inconsistent."""


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_ALLOWED_KINDS = {"application", "vpn", "agent"}
_ALLOWED_ARCHITECTURES = {"all", "amd64"}
_BUILD_CHANNELS = {"development", "testing", "candidate", "stable", "long-term"}
_REQUIRED_OUTPUTS = {"policy", "state", "current_release", "admin"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise UpdateModelError(f"Ruta insegura en {field}")
    path = PurePosixPath(value)
    if ".." in path.parts or str(path) == "/":
        raise UpdateModelError(f"Ruta insegura en {field}")
    return value


def _relative_source_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpdateModelError(f"Ruta de projecte invàlida en {field}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise UpdateModelError(f"Ruta de projecte insegura en {field}")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpdateModelError(f"Valor invàlid en {field}")
    return value


def _identifier(value: object, field: str) -> str:
    result = _nonempty(value, field)
    if not _ID.fullmatch(result):
        raise UpdateModelError(f"Identificador invàlid en {field}")
    return result


def load_update_model(path: Path) -> dict[str, Any]:
    """Load and strictly validate the phase 10.2 update contract."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UpdateModelError(f"No s'ha pogut carregar el model: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 2:
        raise UpdateModelError("Model d'actualització invàlid")
    if raw.get("model_id") != "xaac-update-architecture-v1" or raw.get("phase") != "10.2":
        raise UpdateModelError("Identitat del model d'actualització invàlida")
    if raw.get("hardware_profile") != "wyse3040" or raw.get("architecture") != "amd64":
        raise UpdateModelError("Perfil de maquinari o arquitectura no suportats")

    platform = raw.get("platform")
    if not isinstance(platform, dict):
        raise UpdateModelError("Plataforma d'actualització absent")
    if platform.get("id") != "xaac-thin-client-os":
        raise UpdateModelError("Identitat de plataforma invàlida")
    if platform.get("version_source") != "/etc/os-release:VERSION_ID":
        raise UpdateModelError("Origen de versió del sistema invàlid")
    if platform.get("version_format") != "semver":
        raise UpdateModelError("Format de versió del sistema invàlid")
    if platform.get("update_strategy") != "controlled-debian-package-set":
        raise UpdateModelError("Estratègia d'actualització no suportada")

    components = raw.get("components")
    if not isinstance(components, list) or len(components) != 3:
        raise UpdateModelError("Cal definir exactament els tres components XAAC actualitzables")
    ids: list[str] = []
    packages: list[str] = []
    for index, item in enumerate(components):
        if not isinstance(item, dict):
            raise UpdateModelError("Component invàlid")
        component_id = _identifier(item.get("id"), f"components[{index}].id")
        package = _identifier(item.get("package"), f"components[{index}].package")
        kind = _nonempty(item.get("kind"), f"components[{index}].kind")
        architecture = _nonempty(item.get("architecture"), f"components[{index}].architecture")
        item["package_config"] = _relative_source_path(
            item.get("package_config"), f"components[{index}].package_config"
        )
        if kind not in _ALLOWED_KINDS:
            raise UpdateModelError("Tipus de component invàlid")
        if architecture not in _ALLOWED_ARCHITECTURES:
            raise UpdateModelError("Arquitectura de component invàlida")
        if item.get("critical") is not True:
            raise UpdateModelError("Tots els components XAAC han de ser crítics")
        ids.append(component_id)
        packages.append(package)
    if len(ids) != len(set(ids)) or len(packages) != len(set(packages)):
        raise UpdateModelError("Identificadors o paquets de component duplicats")
    expected_packages = {"xaac-thinclient", "xaac-thin-client-vpn", "xaac-agent"}
    if set(packages) != expected_packages:
        raise UpdateModelError("El model no coincideix amb els paquets de producció XAAC")

    channels = raw.get("channels")
    if not isinstance(channels, list) or [item.get("id") for item in channels if isinstance(item, dict)] != [
        "laboratory", "pilot", "production"
    ]:
        raise UpdateModelError("Canals d'actualització invàlids")
    priorities: list[int] = []
    mapped_build_channels: list[str] = []
    for item in channels:
        if not isinstance(item, dict):
            raise UpdateModelError("Canal invàlid")
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            raise UpdateModelError("Prioritat de canal invàlida")
        priorities.append(priority)
        build_channels = item.get("build_channels")
        if (
            not isinstance(build_channels, list)
            or not build_channels
            or not all(isinstance(value, str) and value in _BUILD_CHANNELS for value in build_channels)
        ):
            raise UpdateModelError("Mapatge de canals de build invàlid")
        mapped_build_channels.extend(build_channels)
    if priorities != sorted(priorities) or len(priorities) != len(set(priorities)):
        raise UpdateModelError("Prioritats de canal invàlides")
    if set(mapped_build_channels) != _BUILD_CHANNELS or len(mapped_build_channels) != len(set(mapped_build_channels)):
        raise UpdateModelError("Mapatge de canals de build incomplet o duplicat")

    versions = raw.get("version_policy")
    if not isinstance(versions, dict):
        raise UpdateModelError("Política de versions absent")
    if versions.get("os_format") != "semver" or versions.get("package_format") != "debian":
        raise UpdateModelError("Política de formats de versió invàlida")
    if versions.get("allow_downgrade") is not False:
        raise UpdateModelError("Els downgrades han d'estar bloquejats")
    if versions.get("allow_os_version_change") is not False:
        raise UpdateModelError("La fase 10.2 no pot canviar VERSION_ID sense un paquet de plataforma")
    minimum = versions.get("minimum_os_version")
    if not isinstance(minimum, str) or not _SEMVER.fullmatch(minimum):
        raise UpdateModelError("Versió mínima del sistema invàlida")
    prerelease = versions.get("allow_prerelease_channels")
    if prerelease != ["laboratory", "pilot"]:
        raise UpdateModelError("Política de prerelease invàlida")

    compatibility = raw.get("compatibility")
    if not isinstance(compatibility, dict):
        raise UpdateModelError("Política de compatibilitat absent")
    required_true = (
        "require_complete_component_set",
        "require_exact_manifest_versions",
        "require_hardware_profile",
        "require_architecture",
    )
    if any(compatibility.get(key) is not True for key in required_true):
        raise UpdateModelError("La política de compatibilitat no pot relaxar-se")
    atomic = compatibility.get("atomic_component_set")
    if not isinstance(atomic, list) or set(atomic) != set(ids) or len(atomic) != len(ids):
        raise UpdateModelError("Conjunt atòmic de compatibilitat invàlid")

    manifest = raw.get("manifest")
    if not isinstance(manifest, dict):
        raise UpdateModelError("Política de manifest absent")
    if manifest.get("schema") != "xaac-update-manifest/v1" or manifest.get("hash_algorithm") != "sha256":
        raise UpdateModelError("Contracte de manifest invàlid")
    if manifest.get("require_detached_signature") is not True or manifest.get("fail_closed") is not True:
        raise UpdateModelError("La verificació criptogràfica ha de ser fail-closed")
    if manifest.get("signature_suffix") != ".asc":
        raise UpdateModelError("Sufix de signatura no suportat")
    manifest["keyring"] = _absolute_path(manifest.get("keyring"), "manifest.keyring")

    preflight = raw.get("preflight")
    if not isinstance(preflight, dict):
        raise UpdateModelError("Política de preflight absent")
    minimum_free = preflight.get("minimum_free_bytes")
    if not isinstance(minimum_free, int) or isinstance(minimum_free, bool) or minimum_free < 268435456:
        raise UpdateModelError("Espai lliure mínim massa baix")
    if preflight.get("require_dpkg_audit_clean") is not True or preflight.get("require_apt_check") is not True:
        raise UpdateModelError("Les comprovacions dpkg/apt són obligatòries")
    if preflight.get("require_os_identity") != "xaac-thin-client-os":
        raise UpdateModelError("Identitat requerida del sistema invàlida")
    preserve = preflight.get("preserve_configuration")
    if not isinstance(preserve, list) or not preserve:
        raise UpdateModelError("Cal definir configuració a preservar")
    preflight["preserve_configuration"] = [
        _absolute_path(value, "preflight.preserve_configuration") for value in preserve
    ]
    if len(preflight["preserve_configuration"]) != len(set(preflight["preserve_configuration"])):
        raise UpdateModelError("Rutes de configuració a preservar duplicades")

    audit = raw.get("audit")
    if not isinstance(audit, dict) or audit.get("enabled") is not True:
        raise UpdateModelError("Auditoria d'actualitzacions obligatòria")
    audit["path"] = _absolute_path(audit.get("path"), "audit.path")
    if audit.get("record_manifest_hash") is not True or audit.get("record_component_versions") is not True:
        raise UpdateModelError("Auditoria d'actualitzacions incompleta")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise UpdateModelError("outputs incomplet")
    raw["outputs"] = {
        key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()
    }
    return raw


def resolve_update_channel(profile: dict[str, Any], build_channel: str) -> str:
    """Translate the legacy image build channel into the update release channel."""
    for channel in profile["channels"]:
        if build_channel in channel["build_channels"]:
            return str(channel["id"])
    raise UpdateModelError(f"Canal de build sense mapatge d'actualització: {build_channel}")


@dataclass(frozen=True, slots=True)
class UpdateModelPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "model_id": self.profile["model_id"],
            "phase": self.profile["phase"],
            "hardware_profile": self.profile["hardware_profile"],
            "architecture": self.profile["architecture"],
            "component_count": len(self.profile["components"]),
            "manifest_schema": self.profile["manifest"]["schema"],
            "downgrades_allowed": self.profile["version_policy"]["allow_downgrade"],
        }


def create_update_model_plan(rootfs: Path, profile_path: Path) -> UpdateModelPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise UpdateModelError(f"Rootfs insegur: {root}")
    return UpdateModelPlan(root, load_update_model(profile_path))


class UpdateModelInstaller:
    """Install only the phase 10.2 policy and initial state into a rootfs."""

    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise UpdateModelError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: UpdateModelPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = (plan.output("policy"), plan.output("state"))
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        # package_config is a source-tree implementation detail and must not leak into the appliance.
        policy["components"] = [
            {key: value for key, value in component.items() if key != "package_config"}
            for component in plan.profile["components"]
        ]
        state = {
            **plan.manifest(),
            "status": "idle",
            "last_check": None,
            "last_manifest_sha256": None,
            "available_os_version": None,
            "last_error": None,
        }
        self._write(
            targets[0],
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        )
        self._write(
            targets[1],
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            0o640,
        )
        return targets
