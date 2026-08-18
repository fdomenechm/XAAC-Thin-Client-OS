"""Build-time recovery environment for XAAC Thin Client OS phase 10.4."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class RecoveryEnvironmentError(RuntimeError):
    """Raised when the phase 10.4 recovery policy is unsafe."""


_ALLOWED_COMMANDS = ("status", "rollback", "repair", "network-on", "network-off")
_REQUIRED_OUTPUTS = {
    "policy",
    "state",
    "admin",
    "runtime",
    "target",
    "grub_entry",
    "grub_defaults",
    "tmpfiles",
}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise RecoveryEnvironmentError(f"Ruta insegura en {field}")
    path = PurePosixPath(value)
    if ".." in path.parts or str(path) == "/":
        raise RecoveryEnvironmentError(f"Ruta insegura en {field}")
    return value


def load_recovery_environment(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RecoveryEnvironmentError(
            f"No s'ha pogut carregar la política de recuperació: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise RecoveryEnvironmentError("Política de recuperació invàlida")
    if raw.get("recovery_id") != "xaac-recovery" or raw.get("phase") != "10.4":
        raise RecoveryEnvironmentError("Identitat de recuperació invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise RecoveryEnvironmentError("Perfil de maquinari no suportat")

    boot = raw.get("boot")
    if not isinstance(boot, dict):
        raise RecoveryEnvironmentError("Política d'arranc de recuperació absent")
    if boot.get("target") != "xaac-recovery.target":
        raise RecoveryEnvironmentError("Target de recuperació invàlid")
    if boot.get("root_label") != "XAAC_ROOT":
        raise RecoveryEnvironmentError("Etiqueta arrel de recuperació invàlida")
    timeout = boot.get("hidden_menu_timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3:
        raise RecoveryEnvironmentError("Timeout ocult de GRUB invàlid")
    if boot.get("network_default") != "disabled" or boot.get("kiosk_default") != "disabled":
        raise RecoveryEnvironmentError("Recovery ha d'arrancar sense xarxa ni quiosc")
    entry = boot.get("grub_entry")
    if not isinstance(entry, str) or not entry.strip() or "\n" in entry:
        raise RecoveryEnvironmentError("Nom de l'entrada GRUB invàlid")

    commands = raw.get("commands")
    if not isinstance(commands, list) or tuple(commands) != _ALLOWED_COMMANDS:
        raise RecoveryEnvironmentError("Conjunt o ordre de subordres de recovery invàlid")

    rollback = raw.get("rollback")
    if not isinstance(rollback, dict) or any(
        rollback.get(key) is not True
        for key in ("require_confirmation", "restore_packages", "restore_configuration")
    ):
        raise RecoveryEnvironmentError("Política de rollback de recovery invàlida")

    repair = raw.get("repair")
    if not isinstance(repair, dict) or any(
        repair.get(key) is not True
        for key in (
            "require_recovery_boot",
            "dpkg_configure",
            "update_initramfs",
            "update_grub",
            "restore_configuration_supported",
        )
    ):
        raise RecoveryEnvironmentError("Política de reparació incompleta")

    network = raw.get("network")
    if (
        not isinstance(network, dict)
        or network.get("optional") is not True
        or network.get("require_explicit_enable") is not True
        or network.get("manager_unit") != "NetworkManager.service"
    ):
        raise RecoveryEnvironmentError("Política de xarxa de recovery invàlida")

    factory = raw.get("factory_reset")
    if (
        not isinstance(factory, dict)
        or factory.get("enabled") is not False
        or factory.get("reason") != "signed_factory_image_not_provisioned"
    ):
        raise RecoveryEnvironmentError("Factory reset ha de romandre fail-closed")

    safety = raw.get("safety")
    if not isinstance(safety, dict):
        raise RecoveryEnvironmentError("Política de seguretat de recovery absent")
    for key in ("require_local_admin", "fail_closed", "preserve_evidence"):
        if safety.get(key) is not True:
            raise RecoveryEnvironmentError(f"Control de seguretat obligatori desactivat: {key}")
    for key in ("automatic_factory_reset", "remote_unattended_factory_reset"):
        if safety.get(key) is not False:
            raise RecoveryEnvironmentError("El factory reset automàtic o remot està prohibit")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise RecoveryEnvironmentError("outputs de recovery incomplet")
    raw["outputs"] = {
        key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()
    }
    return raw


@dataclass(frozen=True, slots=True)
class RecoveryEnvironmentPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "recovery_id": self.profile["recovery_id"],
            "phase": self.profile["phase"],
            "hardware_profile": self.profile["hardware_profile"],
            "commands": list(self.profile["commands"]),
            "factory_reset_enabled": False,
            "network_default": "disabled",
        }


def create_recovery_environment_plan(
    rootfs: Path, profile_path: Path
) -> RecoveryEnvironmentPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise RecoveryEnvironmentError(f"Rootfs insegur: {root}")
    return RecoveryEnvironmentPlan(root, load_recovery_environment(profile_path))


class RecoveryEnvironmentInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise RecoveryEnvironmentError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(
        self, plan: RecoveryEnvironmentPlan, *, dry_run: bool = False
    ) -> tuple[Path, ...]:
        order = ("policy", "state", "target", "grub_entry", "grub_defaults", "tmpfiles")
        targets = tuple(plan.output(key) for key in order)
        if dry_run:
            return targets

        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "ready",
            "last_action": None,
            "last_action_at": None,
            "last_error": None,
        }
        target = """[Unit]
Description=XAAC Thin Client OS Recovery Mode
Requires=local-fs.target
Wants=systemd-user-sessions.service getty@tty1.service
After=local-fs.target systemd-user-sessions.service
Conflicts=graphical.target greetd.service xaac-vpn-manager.service xaac-agent.service
AllowIsolate=yes
"""
        entry_name = plan.profile["boot"]["grub_entry"]
        root_label = plan.profile["boot"]["root_label"]
        grub_entry = f"""#!/bin/sh
set -eu
cat <<'XAAC_RECOVERY_ENTRY'
menuentry '{entry_name}' --class xaac --class recovery {{
    insmod part_gpt
    insmod ext2
    search --no-floppy --label --set=root {root_label}
    linux /boot/vmlinuz root=LABEL={root_label} ro systemd.unit=xaac-recovery.target systemd.show_status=1
    initrd /boot/initrd.img
}}
XAAC_RECOVERY_ENTRY
"""
        timeout = plan.profile["boot"]["hidden_menu_timeout_seconds"]
        grub_defaults = (
            "# XAAC Thin Client OS phase 10.4: keep normal boot hidden but allow Esc recovery access\n"
            f"GRUB_TIMEOUT={timeout}\n"
            "GRUB_TIMEOUT_STYLE=hidden\n"
            f"GRUB_RECORDFAIL_TIMEOUT={timeout}\n"
        )
        tmpfiles = (
            "d /var/lib/xaac-recovery 0750 root root -\n"
            "d /var/log/xaac-recovery 0750 root root -\n"
        )
        contents = (
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            target,
            grub_entry,
            grub_defaults,
            tmpfiles,
        )
        modes = (0o640, 0o640, 0o644, 0o750, 0o644, 0o644)
        for path, content, mode in zip(targets, contents, modes, strict=True):
            self._write(path, content, mode)
        return targets
