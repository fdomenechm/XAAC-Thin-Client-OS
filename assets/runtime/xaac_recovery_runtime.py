"""Local recovery runtime for XAAC Thin Client OS phase 10.4.

The module is stdlib-only and deliberately independent from the graphical XAAC
applications. Package/configuration rollback reuses the transaction runtime from
phase 10.2 so both paths enforce the same hashes, locks and health checks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIBEXEC = Path("/usr/local/libexec")
if str(LIBEXEC) not in sys.path:
    sys.path.insert(0, str(LIBEXEC))
try:
    import xaac_update_runtime as update_runtime
except ImportError as exc:
    update_runtime = None  # type: ignore[assignment]
    _UPDATE_IMPORT_ERROR = exc
else:
    _UPDATE_IMPORT_ERROR = None

POLICY_PATH = Path("/etc/xaac/recovery/policy.json")
STATE_PATH = Path("/var/lib/xaac-recovery/state.json")
AUDIT_PATH = Path("/var/log/xaac-recovery/recovery.jsonl")
CMDLINE_PATH = Path("/proc/cmdline")
REBOOT_REQUIRED_PATH = Path("/var/run/reboot-required")
RECOVERY_TARGET_TOKEN = "systemd.unit=xaac-recovery.target"


class RecoveryRuntimeError(RuntimeError):
    """Raised when a recovery action cannot be completed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    command: list[str],
    *,
    timeout: int = 300,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryRuntimeError(f"No s'ha pogut executar {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise RecoveryRuntimeError(
            f"Ha fallat {' '.join(command[:2])} ({result.returncode}): {detail}"
        )
    return result


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryRuntimeError(f"No s'ha pogut llegir {description}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecoveryRuntimeError(f"{description} invàlid")
    return raw


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _load_json(path, "la política de recuperació")
    if (
        policy.get("schema_version") != 1
        or policy.get("recovery_id") != "xaac-recovery"
        or policy.get("phase") != "10.4"
        or policy.get("hardware_profile") != "wyse3040"
    ):
        raise RecoveryRuntimeError("Política de recuperació no compatible")
    return policy


def _atomic_json(path: Path, payload: object, mode: int = 0o640) -> None:
    if path.is_symlink():
        raise RecoveryRuntimeError(f"Destinació insegura (symlink): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _audit(event: str, detail: dict[str, Any]) -> None:
    if AUDIT_PATH.is_symlink():
        raise RecoveryRuntimeError(f"Destinació d'auditoria insegura: {AUDIT_PATH}")
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(AUDIT_PATH.parent, 0o750)
    record = {"timestamp": utc_now(), "event": event, "detail": detail}
    try:
        fd = os.open(AUDIT_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        raise RecoveryRuntimeError(f"No s'ha pogut escriure l'auditoria: {exc}") from exc


def _write_state(action: str, *, error: str | None = None) -> None:
    previous: dict[str, Any] = {}
    if STATE_PATH.is_file() and not STATE_PATH.is_symlink():
        try:
            previous = _load_json(STATE_PATH, "l'estat de recuperació")
        except RecoveryRuntimeError:
            previous = {}
    state = {
        "schema_version": 1,
        "recovery_id": "xaac-recovery",
        "phase": "10.4",
        "status": "error" if error else "ready",
        "last_action": action,
        "last_action_at": utc_now(),
        "last_error": error,
        "action_count": int(previous.get("action_count", 0)) + 1,
    }
    _atomic_json(STATE_PATH, state)


def in_recovery_mode(cmdline_path: Path = CMDLINE_PATH) -> bool:
    try:
        tokens = cmdline_path.read_text(encoding="utf-8").split()
    except OSError:
        return False
    return RECOVERY_TARGET_TOKEN in tokens


def _require_recovery_mode() -> None:
    if not in_recovery_mode():
        raise RecoveryRuntimeError(
            "Aquesta operació només està permesa després d'arrancar "
            "'XAAC Thin Client OS — Recovery' des de GRUB"
        )


def _update_runtime() -> Any:
    if update_runtime is None:
        raise RecoveryRuntimeError(
            f"No està disponible el runtime de rollback 10.2: {_UPDATE_IMPORT_ERROR}"
        )
    return update_runtime


def _latest_recovery_summary() -> dict[str, Any] | None:
    root = Path("/var/lib/xaac-update/recovery-points")
    if not root.is_dir() or root.is_symlink():
        return None
    points = [
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / "recovery-point.json").is_file()
    ]
    if not points:
        return None
    points.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    metadata = _load_json(points[0] / "recovery-point.json", "l'últim punt de recuperació")
    packages = metadata.get("packages")
    versions: dict[str, str] = {}
    if isinstance(packages, list):
        for item in packages:
            if isinstance(item, dict) and isinstance(item.get("package"), str):
                versions[item["package"]] = str(item.get("version"))
    return {
        "path": str(points[0]),
        "transaction_id": metadata.get("transaction_id"),
        "created_at": metadata.get("created_at"),
        "packages": versions,
    }


def _root_mount() -> str:
    result = _run(["/usr/bin/findmnt", "-nro", "SOURCE,FSTYPE,OPTIONS", "/"], timeout=15)
    if result.returncode != 0:
        return "desconegut"
    return result.stdout.strip() or "desconegut"


def _dpkg_audit() -> tuple[bool, str]:
    result = _run(["/usr/bin/dpkg", "--audit"], timeout=60)
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0 and not detail, detail


def _failed_units() -> str:
    result = _run(
        ["/usr/bin/systemctl", "--failed", "--no-legend", "--plain"], timeout=20
    )
    return result.stdout.strip() if result.returncode in {0, 1} else "no disponible"


def _network_active(unit: str) -> bool:
    return (
        _run(["/usr/bin/systemctl", "is-active", "--quiet", unit], timeout=20).returncode
        == 0
    )


def status_report(policy: dict[str, Any]) -> str:
    dpkg_ok, dpkg_detail = _dpkg_audit()
    latest = _latest_recovery_summary()
    unit = str(policy["network"]["manager_unit"])
    tx_state: dict[str, Any] | None = None
    base_os_state: dict[str, Any] | None = None
    tx_path = Path("/var/lib/xaac-update/transaction-state.json")
    if tx_path.is_file() and not tx_path.is_symlink():
        try:
            tx_state = _load_json(tx_path, "l'estat de transacció")
        except RecoveryRuntimeError:
            tx_state = {"status": "corrupt"}
    base_path = Path("/var/lib/xaac-update/base-os-state.json")
    if base_path.is_file() and not base_path.is_symlink():
        try:
            base_os_state = _load_json(base_path, "l'estat d'actualització del sistema base")
        except RecoveryRuntimeError:
            base_os_state = {"status": "corrupt"}
    lines = [
        "XAAC Thin Client OS — Recovery status",
        f"Mode recovery: {'sí' if in_recovery_mode() else 'no'}",
        f"Arrel: {_root_mount()}",
        f"dpkg: {'correcte' if dpkg_ok else 'requereix atenció'}",
        f"Xarxa: {'activa' if _network_active(unit) else 'desactivada'}",
        f"Factory reset: deshabilitat ({policy['factory_reset']['reason']})",
    ]
    if dpkg_detail:
        lines.append("Detall dpkg: " + dpkg_detail.replace("\n", " | ")[:1200])
    if tx_state is not None:
        lines.append(f"Actualització components XAAC: {tx_state.get('status', 'desconegut')}")
    if base_os_state is not None:
        lines.append(f"Actualització sistema base: {base_os_state.get('status', 'desconegut')}")
        if REBOOT_REQUIRED_PATH.exists():
            lines.append("Sistema base: reinici pendent")
    if latest is None:
        lines.append("Últim punt de recuperació: no disponible")
    else:
        lines.append(
            "Últim punt de recuperació: "
            + str(latest.get("transaction_id") or latest["path"])
            + (f" ({latest.get('created_at')})" if latest.get("created_at") else "")
        )
        if latest["packages"]:
            lines.append(
                "Versions recuperables: "
                + ", ".join(
                    f"{name}={version}" for name, version in sorted(latest["packages"].items())
                )
            )
    failed = _failed_units()
    lines.append("Serveis fallits: " + (failed.replace("\n", " | ")[:1500] if failed else "cap"))
    return "\n".join(lines) + "\n"


def rollback() -> dict[str, Any]:
    runtime = _update_runtime()
    _audit("rollback_started", {"recovery_mode": in_recovery_mode()})
    try:
        result = runtime.manual_rollback(
            audit=lambda event, detail: _audit(f"update:{event}", detail)
        )
    except Exception as exc:
        _write_state("rollback", error=str(exc))
        _audit("rollback_failed", {"error": str(exc)})
        raise RecoveryRuntimeError(str(exc)) from exc
    _write_state("rollback")
    _audit("rollback_completed", {"transaction_id": result.get("transaction_id")})
    return result


def restore_configuration() -> dict[str, Any]:
    _require_recovery_mode()
    runtime = _update_runtime()
    _audit("configuration_restore_started", {})
    try:
        result = runtime.restore_latest_configuration(
            audit=lambda event, detail: _audit(f"update:{event}", detail)
        )
    except Exception as exc:
        _write_state("restore-configuration", error=str(exc))
        _audit("configuration_restore_failed", {"error": str(exc)})
        raise RecoveryRuntimeError(str(exc)) from exc
    _write_state("restore-configuration")
    _audit(
        "configuration_restore_completed",
        {"transaction_id": result.get("transaction_id")},
    )
    return result


def repair_system() -> dict[str, Any]:
    _require_recovery_mode()
    policy = load_policy()
    _audit("repair_started", {})
    steps: list[dict[str, Any]] = []
    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        if policy["repair"]["dpkg_configure"]:
            result = _run(["/usr/bin/dpkg", "--configure", "-a"], check=True, env=env)
            steps.append({"step": "dpkg-configure", "ok": result.returncode == 0})
        dpkg_ok, detail = _dpkg_audit()
        steps.append({"step": "dpkg-audit", "ok": dpkg_ok, "detail": detail[-1000:] or None})
        if not dpkg_ok:
            raise RecoveryRuntimeError("dpkg continua informant paquets incomplets")
        if policy["repair"]["update_initramfs"]:
            result = _run(["/usr/sbin/update-initramfs", "-u", "-k", "all"], timeout=600, check=True)
            steps.append({"step": "update-initramfs", "ok": result.returncode == 0})
        if policy["repair"]["update_grub"]:
            result = _run(["/usr/sbin/update-grub"], timeout=300, check=True)
            steps.append({"step": "update-grub", "ok": result.returncode == 0})
            grub = Path("/boot/grub/grub.cfg")
            if not grub.is_file() or grub.is_symlink():
                raise RecoveryRuntimeError("/boot/grub/grub.cfg absent o insegur després de reparar")
            text = grub.read_text(encoding="utf-8", errors="replace")
            for entry in ("XAAC Thin Client OS'", "XAAC Thin Client OS — Recovery'"):
                if entry not in text:
                    raise RecoveryRuntimeError(f"GRUB no conté l'entrada esperada: {entry}")
            steps.append({"step": "grub-entries", "ok": True})
    except Exception as exc:
        _write_state("repair", error=str(exc))
        _audit("repair_failed", {"error": str(exc), "steps": steps})
        if isinstance(exc, RecoveryRuntimeError):
            raise
        raise RecoveryRuntimeError(str(exc)) from exc
    result_payload = {"status": "repaired", "completed_at": utc_now(), "steps": steps}
    _write_state("repair")
    _audit("repair_completed", {"steps": steps})
    return result_payload


def set_network(enabled: bool) -> dict[str, Any]:
    _require_recovery_mode()
    policy = load_policy()
    unit = str(policy["network"]["manager_unit"])
    command = "start" if enabled else "stop"
    _audit("network_change_started", {"enabled": enabled, "unit": unit})
    try:
        _run(["/usr/bin/systemctl", command, unit], timeout=60, check=True)
        active = _network_active(unit)
        if active != enabled:
            raise RecoveryRuntimeError(
                f"{unit} no ha quedat {'actiu' if enabled else 'aturat'}"
            )
    except Exception as exc:
        _write_state("network-on" if enabled else "network-off", error=str(exc))
        _audit("network_change_failed", {"enabled": enabled, "error": str(exc)})
        if isinstance(exc, RecoveryRuntimeError):
            raise
        raise RecoveryRuntimeError(str(exc)) from exc
    action = "network-on" if enabled else "network-off"
    _write_state(action)
    _audit("network_change_completed", {"enabled": enabled})
    return {"status": "active" if enabled else "inactive", "unit": unit}


def interactive_menu() -> int:
    _require_recovery_mode()
    while True:
        print("\nXAAC Thin Client OS — Recovery")
        print("1) Estat")
        print("2) Rollback de paquets i configuració")
        print("3) Reparar dpkg/initramfs/GRUB")
        print("4) Restaurar només la configuració anterior")
        print("5) Activar xarxa temporalment")
        print("6) Desactivar xarxa")
        print("7) Reiniciar")
        print("8) Apagar")
        print("0) Eixir a la consola")
        choice = input("Opció: ").strip()
        if choice == "1":
            print(status_report(load_policy()), end="")
        elif choice == "2":
            if input("Escriu ROLLBACK per continuar: ").strip() == "ROLLBACK":
                print(json.dumps(rollback(), ensure_ascii=False, indent=2, sort_keys=True))
        elif choice == "3":
            if input("Escriu REPAIR per continuar: ").strip() == "REPAIR":
                print(json.dumps(repair_system(), ensure_ascii=False, indent=2, sort_keys=True))
        elif choice == "4":
            if input("Escriu RESTORE CONFIG per continuar: ").strip() == "RESTORE CONFIG":
                print(
                    json.dumps(
                        restore_configuration(), ensure_ascii=False, indent=2, sort_keys=True
                    )
                )
        elif choice == "5":
            if input("Escriu NETWORK ON per continuar: ").strip() == "NETWORK ON":
                print(json.dumps(set_network(True), ensure_ascii=False, sort_keys=True))
        elif choice == "6":
            print(json.dumps(set_network(False), ensure_ascii=False, sort_keys=True))
        elif choice == "7":
            _run(["/usr/bin/systemctl", "reboot"], timeout=20, check=True)
            return 0
        elif choice == "8":
            _run(["/usr/bin/systemctl", "poweroff"], timeout=20, check=True)
            return 0
        elif choice == "0":
            return 0
        else:
            print("Opció invàlida", file=sys.stderr)
