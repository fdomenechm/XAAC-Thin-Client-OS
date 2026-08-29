"""Controlled Debian base-system update policy for XAAC Thin Client OS phase 10.6."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class BaseOsUpdateError(RuntimeError):
    """Raised when the phase 10.6 base OS update policy is unsafe."""


_REQUIRED_OUTPUTS = {
    "policy",
    "state",
    "checkpoint",
    "audit",
    "apt_preferences",
    "apt_conf",
    "runtime",
}
_REQUIRED_PROTECTED = {"xaac-thinclient", "xaac-thin-client-vpn", "xaac-thin-client-network", "xaac-thin-client-dock", "xaac-agent"}
_REQUIRED_SUITES = {"trixie", "trixie-updates", "trixie-security"}
_REQUIRED_SERVICES = {"NetworkManager.service", "nftables.service", "apparmor.service", "greetd.service", "xaac-network-manager.service"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise BaseOsUpdateError(f"Ruta insegura en {field}")
    path = PurePosixPath(value)
    if ".." in path.parts or str(path) == "/":
        raise BaseOsUpdateError(f"Ruta insegura en {field}")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaseOsUpdateError(f"Valor invàlid en {field}")
    return value


def load_base_os_update(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BaseOsUpdateError(f"No s'ha pogut carregar la política 10.6: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise BaseOsUpdateError("Política 10.6 invàlida")
    if raw.get("update_id") != "xaac-base-os-update" or raw.get("phase") != "10.6":
        raise BaseOsUpdateError("Identitat de la política 10.6 invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise BaseOsUpdateError("Perfil de maquinari 10.6 no suportat")

    platform = raw.get("platform")
    if not isinstance(platform, dict):
        raise BaseOsUpdateError("Plataforma 10.6 absent")
    if (
        platform.get("os_id") != "xaac-thin-client-os"
        or platform.get("debian_major") != 13
        or platform.get("suite") != "trixie"
        or platform.get("architecture") != "amd64"
    ):
        raise BaseOsUpdateError("La 10.6 només admet XAAC OS sobre Debian 13/trixie amd64")

    repositories = raw.get("repositories")
    if not isinstance(repositories, list) or len(repositories) != 2:
        raise BaseOsUpdateError("Repositoris 10.6 incomplets")
    seen_suites: set[str] = set()
    for index, repository in enumerate(repositories):
        if not isinstance(repository, dict):
            raise BaseOsUpdateError(f"Repositori {index} invàlid")
        uri = _nonempty(repository.get("uri"), f"repositories[{index}].uri")
        if not uri.startswith("https://"):
            raise BaseOsUpdateError("Els repositoris 10.6 han d'usar HTTPS")
        suites = repository.get("suites")
        components = repository.get("components")
        if not isinstance(suites, list) or not suites or not all(isinstance(v, str) for v in suites):
            raise BaseOsUpdateError(f"Suites invàlides en repositories[{index}]")
        if not isinstance(components, list) or not components or not all(isinstance(v, str) for v in components):
            raise BaseOsUpdateError(f"Components invàlids en repositories[{index}]")
        if set(components) != {"main", "non-free-firmware"}:
            raise BaseOsUpdateError("Components Debian fora de política")
        signed_by = _absolute_path(repository.get("signed_by"), f"repositories[{index}].signed_by")
        if signed_by != "/usr/share/keyrings/debian-archive-keyring.gpg":
            raise BaseOsUpdateError("Keyring Debian no autoritzat")
        seen_suites.update(suites)
    if seen_suites != _REQUIRED_SUITES:
        raise BaseOsUpdateError("La 10.6 requereix trixie, trixie-updates i trixie-security")

    policy = raw.get("policy")
    if not isinstance(policy, dict):
        raise BaseOsUpdateError("Política APT 10.6 absent")
    required_false = ("allow_release_change", "allow_downgrade", "allow_removals", "automatic_reboot", "automatic_rollback")
    if policy.get("apt_operation") != "upgrade-with-new-pkgs":
        raise BaseOsUpdateError("Només s'autoritza apt-get upgrade --with-new-pkgs")
    if any(policy.get(key) is not False for key in required_false):
        raise BaseOsUpdateError("La política 10.6 relaxa una protecció obligatòria")
    for key in ("allow_new_dependencies", "require_fresh_indexes", "require_no_unauthenticated_sources", "reject_unmanaged_sources"):
        if policy.get(key) is not True:
            raise BaseOsUpdateError(f"La protecció {key} és obligatòria")
    for key, minimum, maximum in (
        ("minimum_free_bytes", 256 * 1024 * 1024, 4 * 1024 * 1024 * 1024),
        ("minimum_free_after_download_bytes", 128 * 1024 * 1024, 2 * 1024 * 1024 * 1024),
        ("maximum_changed_packages", 1, 512),
        ("maximum_new_packages", 0, 128),
    ):
        value = policy.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise BaseOsUpdateError(f"Límit invàlid en policy.{key}")
    protected = policy.get("protected_packages")
    if not isinstance(protected, list) or set(protected) != _REQUIRED_PROTECTED:
        raise BaseOsUpdateError("Els paquets XAAC han de quedar protegits d'APT")
    prefixes = policy.get("reboot_package_prefixes")
    if not isinstance(prefixes, list) or not prefixes or not all(isinstance(v, str) and v for v in prefixes):
        raise BaseOsUpdateError("Patrons de reboot invàlids")

    health = raw.get("health")
    if not isinstance(health, dict) or health.get("require_dpkg_audit_clean") is not True or health.get("require_apt_check") is not True:
        raise BaseOsUpdateError("Health-check 10.6 incomplet")
    required_services = health.get("required_services")
    if not isinstance(required_services, list) or set(required_services) != _REQUIRED_SERVICES:
        raise BaseOsUpdateError("Serveis obligatoris 10.6 invàlids")
    installed = health.get("installed_services")
    if installed != ["ssh.service"]:
        raise BaseOsUpdateError("Política SSH 10.6 invàlida")
    executables = health.get("required_executables")
    expected_executables = {"/usr/bin/xaac-thinclient", "/usr/bin/xaac-thin-client-vpn", "/usr/bin/xaac-network-gui", "/usr/bin/xaac-network-manager", "/usr/bin/xaac-thin-client-dock", "/usr/bin/xaac-agent"}
    if not isinstance(executables, list) or set(executables) != expected_executables:
        raise BaseOsUpdateError("Executables XAAC obligatoris 10.6 invàlids")
    for executable in executables:
        _absolute_path(executable, "health.required_executables")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise BaseOsUpdateError("outputs 10.6 incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class BaseOsUpdatePlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "update_id": self.profile["update_id"],
            "phase": self.profile["phase"],
            "hardware_profile": self.profile["hardware_profile"],
            "debian_major": self.profile["platform"]["debian_major"],
            "suite": self.profile["platform"]["suite"],
            "automatic_updates": False,
            "automatic_reboot": False,
            "automatic_rollback": False,
        }


def create_base_os_update_plan(rootfs: Path, profile_path: Path) -> BaseOsUpdatePlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise BaseOsUpdateError(f"Rootfs insegur: {root}")
    return BaseOsUpdatePlan(root, load_base_os_update(profile_path))


class BaseOsUpdateInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise BaseOsUpdateError(f"Destinació amb enllaç simbòlic: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _preferences(profile: dict[str, Any]) -> str:
        packages = " ".join(profile["policy"]["protected_packages"])
        return (
            "# Managed by XAAC Thin Client OS phase 10.6\n"
            "# XAAC application packages are updated only by signed XAAC bundles.\n"
            f"Package: {packages}\n"
            "Pin: release *\n"
            "Pin-Priority: -1\n"
        )

    @staticmethod
    def _apt_conf() -> str:
        return (
            '// Managed by XAAC Thin Client OS phase 10.6\n'
            'APT::Get::AllowUnauthenticated "false";\n'
            'Acquire::AllowInsecureRepositories "false";\n'
            'Acquire::AllowDowngradeToInsecureRepositories "false";\n'
            'APT::Get::AutomaticRemove "false";\n'
        )

    def install(self, plan: BaseOsUpdatePlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        targets = tuple(plan.output(key) for key in ("policy", "state", "apt_preferences", "apt_conf"))
        if dry_run:
            return targets
        policy = dict(plan.profile)
        state = {
            **plan.manifest(),
            "status": "idle",
            "last_check": None,
            "last_update": None,
            "last_error": None,
            "reboot_required": False,
        }
        self._write(targets[0], json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[1], json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o640)
        self._write(targets[2], self._preferences(plan.profile), 0o644)
        self._write(targets[3], self._apt_conf(), 0o644)
        checkpoint = plan.output("checkpoint")
        checkpoint.mkdir(parents=True, exist_ok=True)
        checkpoint.chmod(0o700)
        return targets
