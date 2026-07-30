"""Local authenticated recovery environment for phase 11.4."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


class LocalRecoveryError(RuntimeError):
    """Raised when the local recovery policy is incomplete or unsafe."""


_ALLOWED_ACTIONS = {
    "diagnostics", "restart-client", "restart-session", "repair-packages",
    "rollback-policy", "reboot", "poweroff",
}
_ALLOWED_INTERFACES = {"ethernet"}
_REQUIRED_OUTPUTS = {"policy", "state", "runner", "service", "target", "grub"}


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise LocalRecoveryError(f"Ruta insegura en {field}")
    return value


def _positive_int(value: object, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise LocalRecoveryError(f"Valor invàlid en {field}")
    return value


def load_local_recovery(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LocalRecoveryError(f"No s'ha pogut carregar el mode de recuperació local: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise LocalRecoveryError("Política de recuperació local invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise LocalRecoveryError("Perfil de maquinari no suportat")
    if not isinstance(raw.get("recovery_id"), str) or not raw["recovery_id"].strip():
        raise LocalRecoveryError("recovery_id invàlid")

    boot = raw.get("boot")
    if not isinstance(boot, dict) or boot.get("require_signed_kernel") is not True:
        raise LocalRecoveryError("L'arrencada de recuperació ha d'exigir un kernel signat")
    args = boot.get("kernel_arguments")
    if not isinstance(args, list) or "systemd.unit=xaac-recovery.target" not in args or len(args) != len(set(args)):
        raise LocalRecoveryError("Arguments del kernel incomplets")

    environment = raw.get("environment")
    if not isinstance(environment, dict):
        raise LocalRecoveryError("Entorn de recuperació absent")
    if environment.get("target") != "xaac-recovery.target" or environment.get("read_only_root") is not True:
        raise LocalRecoveryError("L'entorn mínim no és segur")
    if environment.get("allow_network") != "optional" or environment.get("network_default") != "disabled":
        raise LocalRecoveryError("La xarxa ha de ser opcional i desactivada per defecte")
    environment["shell"] = _absolute_path(environment.get("shell"), "environment.shell")

    auth = raw.get("authentication")
    users = auth.get("allowed_users") if isinstance(auth, dict) else None
    if not isinstance(auth, dict) or auth.get("required") is not True:
        raise LocalRecoveryError("L'autenticació és obligatòria")
    if not isinstance(users, list) or users != ["xaac-admin"]:
        raise LocalRecoveryError("Usuaris de recuperació invàlids")
    _positive_int(auth.get("max_attempts"), "authentication.max_attempts", 10)
    _positive_int(auth.get("lockout_seconds"), "authentication.lockout_seconds", 3600)

    menu = raw.get("menu")
    actions = menu.get("actions") if isinstance(menu, dict) else None
    if not isinstance(actions, list) or set(actions) != _ALLOWED_ACTIONS or len(actions) != len(set(actions)):
        raise LocalRecoveryError("Menú de recuperació incomplet")
    if menu.get("destructive_actions_require_confirmation") is not True:
        raise LocalRecoveryError("Les accions destructives han de requerir confirmació")

    logging = raw.get("logging")
    if not isinstance(logging, dict) or logging.get("preserve_on_success") is not True:
        raise LocalRecoveryError("Registre persistent obligatori")
    logging["persistent_directory"] = _absolute_path(logging.get("persistent_directory"), "logging.persistent_directory")

    network = raw.get("network")
    interfaces = network.get("permitted_interfaces") if isinstance(network, dict) else None
    if not isinstance(network, dict) or network.get("optional") is not True or network.get("require_explicit_enable") is not True:
        raise LocalRecoveryError("Controls de xarxa incomplets")
    if not isinstance(interfaces, list) or set(interfaces) != _ALLOWED_INTERFACES:
        raise LocalRecoveryError("Interfícies de recuperació invàlides")

    safety = raw.get("safety")
    if not isinstance(safety, dict) or safety.get("automatic_factory_reset") is not False:
        raise LocalRecoveryError("El factory reset automàtic està prohibit")
    for key in ("preserve_identity", "preserve_enrollment", "preserve_active_policy", "fail_closed"):
        if safety.get(key) is not True:
            raise LocalRecoveryError(f"Control de seguretat obligatori desactivat: {key}")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise LocalRecoveryError("outputs incomplet")
    raw["outputs"] = {key: _absolute_path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class LocalRecoveryPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "recovery_id": self.profile["recovery_id"],
            "hardware_profile": self.profile["hardware_profile"],
            "action_count": len(self.profile["menu"]["actions"]),
            "network_default": self.profile["environment"]["network_default"],
            "max_authentication_attempts": self.profile["authentication"]["max_attempts"],
        }


def create_local_recovery_plan(rootfs: Path, profile_path: Path) -> LocalRecoveryPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise LocalRecoveryError(f"Rootfs insegur: {root}")
    return LocalRecoveryPlan(root, load_local_recovery(profile_path))


class LocalRecoveryInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise LocalRecoveryError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: LocalRecoveryPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        order = ("policy", "state", "runner", "service", "target", "grub")
        targets = tuple(plan.output(key) for key in order)
        if dry_run:
            return targets
        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {**plan.manifest(), "status": "inactive", "authenticated_user": None,
                 "network_enabled": False, "selected_action": None, "started_at": None,
                 "completed_at": None, "last_error": None}
        runner = """#!/bin/sh
set -eu
POLICY=/etc/xaac/recovery/local-recovery.json
STATE=/var/lib/xaac-recovery/local-recovery-state.json
[ -r "$POLICY" ] || { echo "missing local recovery policy" >&2; exit 2; }
[ -r "$STATE" ] || { echo "missing local recovery state" >&2; exit 2; }
exec /usr/bin/xaac-agent recovery local-menu "$@"
"""
        service = """[Unit]
Description=XAAC local recovery console
After=systemd-user-sessions.service
ConditionPathExists=/etc/xaac/recovery/local-recovery.json

[Service]
Type=idle
ExecStart=/usr/libexec/xaac-local-recovery
User=root
Group=root
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/xaac-recovery /var/log/xaac-recovery /run
LockPersonality=yes
RestrictRealtime=yes
UMask=0027

[Install]
WantedBy=xaac-recovery.target
"""
        target = """[Unit]
Description=XAAC Local Recovery Mode
Requires=xaac-local-recovery.service
After=local-fs.target
AllowIsolate=yes
Conflicts=graphical.target
"""
        grub = """#!/bin/sh
set -eu
cat <<'ENTRY'
menuentry 'XAAC Thin Client OS Recovery' --class xaac --class recovery {
    linux /vmlinuz root=LABEL=XAAC_ROOT ro systemd.unit=xaac-recovery.target
    initrd /initrd.img
}
ENTRY
"""
        contents = (json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    runner, service, target, grub)
        modes = (0o640, 0o640, 0o750, 0o644, 0o644, 0o750)
        for path, content, mode in zip(targets, contents, modes, strict=True):
            self._write(path, content, mode)
        return targets
