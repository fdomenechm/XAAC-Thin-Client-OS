#!/usr/bin/python3
"""Runtime support for XAAC Thin Client OS maintenance and diagnostics.

The module is intentionally self-contained so it can run on the installed
appliance without the build-time Python package. It never reads configuration
files known to contain credentials and sanitizes all free-form log text before
it is shown or included in a support bundle.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLICY_PATH = Path("/etc/xaac/maintenance/policy.json")
STATE_PATH = Path("/var/lib/xaac-maintenance/state.json")
DIAGNOSTICS_ROOT = Path("/var/lib/xaac-maintenance/diagnostics")
CURRENT_RELEASE_PATH = Path("/usr/share/xaac/update/current-release.json")
REBOOT_REQUIRED_PATH = Path("/var/run/reboot-required")
UPDATE_STATE_PATHS = (
    Path("/var/lib/xaac-update/state.json"),
    Path("/var/lib/xaac-update/transaction-state.json"),
    Path("/var/lib/xaac-update/rollback-state.json"),
    Path("/var/lib/xaac-update/base-os-state.json"),
)

_COMPONENT_PACKAGES = (
    "xaac-thinclient",
    "xaac-thin-client-vpn",
    "xaac-agent",
)

_SENSITIVE_LINE = re.compile(
    r"(?i)(password|passwd|passphrase|credential|authorization|bearer|"
    r"token|otp|one[-_ ]time|secret|private[-_ ]?key|auth-user-pass|"
    r"pkcs12|\.p12\b|enrollment\.token|client\.key)"
)
_PEM_PRIVATE = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URL_CREDENTIALS = re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)")
_BEARER_VALUE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=_:.~-]+")
_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(password|passwd|passphrase|token|otp|secret)\b\s*[:=]\s*([^\s,;]+)"
)


class MaintenanceRuntimeError(RuntimeError):
    """Raised when a maintenance operation cannot be completed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MaintenanceRuntimeError(
            f"No s'ha pogut executar {command[0]}: {exc}"
        ) from exc


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaintenanceRuntimeError(
            f"No s'ha pogut llegir {description}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise MaintenanceRuntimeError(f"{description} invàlid")
    return value


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _load_json(path, "la política de manteniment")
    if (
        policy.get("schema_version") != 1
        or policy.get("maintenance_id") != "xaac-maintenance"
        or policy.get("phase") != "10.3"
    ):
        raise MaintenanceRuntimeError("Política de manteniment no compatible")
    privacy = policy.get("privacy")
    if (
        not isinstance(privacy, dict)
        or privacy.get("sanitize_logs") is not True
        or privacy.get("include_configuration_contents") is not False
        or privacy.get("include_private_keys") is not False
        or privacy.get("include_credentials") is not False
        or privacy.get("include_vpn_secrets") is not False
    ):
        raise MaintenanceRuntimeError("Política de privacitat insegura")
    return policy


def atomic_json(path: Path, payload: object, mode: int = 0o640) -> None:
    if path.is_symlink():
        raise MaintenanceRuntimeError(f"Destinació insegura (symlink): {path}")
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


def sanitize_text(value: str) -> str:
    """Remove credentials and credential-like material from free-form text."""
    text = _PEM_PRIVATE.sub("[REDACTED PRIVATE KEY]", value)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]\2", text)
    text = _BEARER_VALUE.sub(r"\1 [REDACTED]", text)
    text = _ASSIGNMENT_SECRET.sub(r"\1=[REDACTED]", text)
    lines: list[str] = []
    for line in text.splitlines():
        if _SENSITIVE_LINE.search(line):
            lines.append("[REDACTED sensitive line]")
        else:
            lines.append(line)
    result = "\n".join(lines)
    if value.endswith("\n"):
        result += "\n"
    return result


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        if "=" not in line or line.startswith("#"):
            continue
        key, raw = line.split("=", 1)
        values[key] = raw.strip().strip('"')
    return values


def _package_version(package: str) -> str:
    result = _run(["/usr/bin/dpkg-query", "-W", "-f=${Status}\n${Version}\n", package])
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and len(lines) == 2 and lines[0] == "install ok installed":
        return lines[1]
    return "no instal·lat"


def _unit_info(unit: str) -> dict[str, str]:
    show = _run(
        [
            "/usr/bin/systemctl",
            "show",
            "--property=LoadState,ActiveState,UnitFileState",
            "--value",
            unit,
        ],
        timeout=20,
    )
    values = show.stdout.splitlines()
    if show.returncode != 0 or not values:
        return {"load": "not-found", "active": "unknown", "enabled": "unknown"}
    padded = values + ["unknown", "unknown", "unknown"]
    return {"load": padded[0], "active": padded[1], "enabled": padded[2]}


def _process_running(pattern: str) -> bool:
    return _run(["/usr/bin/pgrep", "-f", pattern], timeout=10).returncode == 0


def _uptime_text() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return "desconegut"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days} d {hours} h {minutes} min"
    return f"{hours} h {minutes} min"


def _boot_time() -> str:
    result = _run(["/usr/bin/uptime", "-s"], timeout=10)
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "desconegut"


def _ip_summary() -> str:
    result = _run(["/usr/sbin/ip", "-brief", "address", "show", "up"], timeout=10)
    if result.returncode != 0:
        return "desconeguda"
    addresses: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts or parts[0] == "lo":
            continue
        for value in parts[2:]:
            if "/" in value and not value.startswith("fe80:"):
                addresses.append(value)
    return ", ".join(addresses) if addresses else "sense adreça activa"


def _memory_summary() -> str:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return "desconeguda"
    for line in lines:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.strip().split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    if not total:
        return "desconeguda"
    used = total - available
    return f"{used // 1024} MiB usats / {total // 1024} MiB"


def _zram_summary() -> str:
    try:
        lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return "desconegut"
    zram = [line.split() for line in lines if line.split() and "zram" in line.split()[0]]
    if not zram:
        return "no actiu"
    total_kib = sum(int(parts[2]) for parts in zram if len(parts) > 3 and parts[2].isdigit())
    used_kib = sum(int(parts[3]) for parts in zram if len(parts) > 3 and parts[3].isdigit())
    return f"{used_kib // 1024} MiB usats / {total_kib // 1024} MiB"


def _disk_usage() -> tuple[int, int, int]:
    usage = shutil.disk_usage("/")
    percent = int(round((usage.used / usage.total) * 100)) if usage.total else 100
    return usage.total, usage.free, percent


def _last_error(lines: int = 1) -> str:
    result = _run(
        [
            "/usr/bin/journalctl",
            "-b",
            "-p",
            "err..alert",
            "--no-pager",
            "-o",
            "short-iso",
            "-n",
            str(lines),
        ],
        timeout=20,
    )
    text = sanitize_text(result.stdout.strip())
    if not text or text == "-- No entries --":
        return "cap"
    return text


def status_report(policy: dict[str, Any]) -> str:
    os_release = _os_release()
    total, free, percent = _disk_usage()
    current: dict[str, Any] = {}
    if CURRENT_RELEASE_PATH.is_file():
        try:
            current = _load_json(CURRENT_RELEASE_PATH, "la release actual")
        except MaintenanceRuntimeError:
            current = {}
    tx: dict[str, Any] = {}
    base_os: dict[str, Any] = {}
    tx_path = Path("/var/lib/xaac-update/transaction-state.json")
    if tx_path.is_file():
        try:
            tx = _load_json(tx_path, "l'estat d'actualització")
        except MaintenanceRuntimeError:
            tx = {}
    base_path = Path("/var/lib/xaac-update/base-os-state.json")
    if base_path.is_file():
        try:
            base_os = _load_json(base_path, "l'estat d'actualització del sistema base")
        except MaintenanceRuntimeError:
            base_os = {}

    lines = [
        "XAAC Thin Client OS — Estat",
        "===========================",
        f"Sistema: {os_release.get('PRETTY_NAME', 'XAAC Thin Client OS')}",
        f"Versió OS: {os_release.get('VERSION_ID', current.get('os_version', 'desconeguda'))}",
        f"Kernel: {os.uname().release}",
        f"Uptime: {_uptime_text()}",
        f"Boot actual des de: {_boot_time()}",
        f"IP: {_ip_summary()}",
        f"RAM: {_memory_summary()}",
        f"zram: {_zram_summary()}",
        f"Arrel: {percent}% usat, {free // (1024 * 1024)} MiB lliures de {total // (1024 * 1024)} MiB",
        "",
        "Components XAAC:",
    ]
    for package in _COMPONENT_PACKAGES:
        lines.append(f"  {package}: {_package_version(package)}")
    lines.extend(
        [
            "",
            "Runtime:",
            f"  Thin Client: {'en execució' if _process_running('xaac-thinclient') else 'no detectat'}",
            f"  VPN manager: {_unit_info('xaac-vpn-manager.service')['active']}",
            f"  Agent: {_unit_info('xaac-agent.service')['active']}",
            f"  NetworkManager: {_unit_info('NetworkManager.service')['active']}",
            f"  nftables: {_unit_info('nftables.service')['active']}",
            f"  AppArmor: {_unit_info('apparmor.service')['active']}",
            f"  SSH: {_unit_info('ssh.service')['active']}",
            "",
            f"Actualització components XAAC: {tx.get('status', 'sense estat')}",
            f"Actualització Debian: {base_os.get('status', 'sense estat')}",
            f"Reinici Debian pendent: {'sí' if REBOOT_REQUIRED_PATH.exists() else 'no'}",
            f"Última transacció completada: {tx.get('completed_at') or 'cap'}",
            f"Últim error important: {_last_error()}",
        ]
    )
    return "\n".join(lines) + "\n"


def _dpkg_audit() -> tuple[bool, str]:
    result = _run(["/usr/bin/dpkg", "--audit"], timeout=30)
    output = sanitize_text((result.stdout + result.stderr).strip())
    return result.returncode == 0 and not output, output or "net"


def health_report(policy: dict[str, Any]) -> tuple[str, str]:
    limits = policy["limits"]
    _, free, percent = _disk_usage()
    checks: list[tuple[str, str, str]] = []

    if percent >= int(limits["root_critical_percent"]):
        checks.append(("emmagatzematge", "ERROR", f"arrel al {percent}%"))
    elif percent >= int(limits["root_warning_percent"]):
        checks.append(("emmagatzematge", "AVÍS", f"arrel al {percent}%"))
    else:
        checks.append(("emmagatzematge", "OK", f"{percent}% usat; {free // (1024 * 1024)} MiB lliures"))

    dpkg_ok, dpkg_detail = _dpkg_audit()
    checks.append(("dpkg", "OK" if dpkg_ok else "ERROR", dpkg_detail))

    failed = _run(["/usr/bin/systemctl", "--failed", "--no-legend", "--plain"], timeout=20)
    failed_lines = [line for line in failed.stdout.splitlines() if line.strip()]
    checks.append(
        (
            "systemd",
            "OK" if not failed_lines else "ERROR",
            "cap unitat fallida" if not failed_lines else f"{len(failed_lines)} unitat(s) fallida(es)",
        )
    )

    services = policy["services"]
    for unit in services["active_required"]:
        info = _unit_info(str(unit))
        checks.append(
            (
                unit,
                "OK" if info["active"] == "active" else "ERROR",
                f"active={info['active']} enabled={info['enabled']}",
            )
        )
    for unit in services["installed_required"]:
        info = _unit_info(str(unit))
        checks.append(
            (
                unit,
                "OK" if info["load"] == "loaded" else "ERROR",
                f"load={info['load']} active={info['active']} enabled={info['enabled']}",
            )
        )
    for unit in services["optional"]:
        info = _unit_info(str(unit))
        level = "OK" if info["load"] == "loaded" else "AVÍS"
        checks.append((unit, level, f"load={info['load']} active={info['active']} enabled={info['enabled']}"))

    levels = {item[1] for item in checks}
    overall = "error" if "ERROR" in levels else ("degraded" if "AVÍS" in levels else "ok")
    lines = ["XAAC Thin Client OS — Health", "============================", f"Resultat: {overall.upper()}", ""]
    lines.extend(f"[{level}] {name}: {detail}" for name, level, detail in checks)
    return "\n".join(lines) + "\n", overall


def network_report(policy: dict[str, Any]) -> str:
    sections: list[tuple[str, list[str]]] = [
        (
            "Dispositius NetworkManager",
            [
                "/usr/bin/nmcli",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "device",
                "status",
            ],
        ),
        ("Adreces", ["/usr/sbin/ip", "-brief", "address", "show"]),
        ("Rutes IPv4", ["/usr/sbin/ip", "-4", "route", "show"]),
        ("Rutes IPv6", ["/usr/sbin/ip", "-6", "route", "show"]),
    ]
    lines = ["XAAC Thin Client OS — Xarxa", "==========================="]
    for title, command in sections:
        lines.extend(["", f"[{title}]"])
        result = _run(command, timeout=20)
        content = sanitize_text((result.stdout or result.stderr).strip())
        lines.append(content or "sense dades")
    lines.extend(
        [
            "",
            "[Serveis]",
            f"NetworkManager: {_unit_info('NetworkManager.service')['active']}",
            f"VPN manager: {_unit_info('xaac-vpn-manager.service')['active']}",
            f"SSH: {_unit_info('ssh.service')['active']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _emmc_health_lines() -> list[str]:
    lines: list[str] = []
    sys_root = Path("/sys/block")
    try:
        devices = sorted(sys_root.glob("mmcblk*"))
    except OSError:
        devices = []
    for device in devices:
        if not device.name.startswith("mmcblk") or "boot" in device.name or "rpmb" in device.name:
            continue
        lines.append(f"{device.name}:")
        for filename, label in (
            ("device/name", "nom"),
            ("device/pre_eol_info", "pre-EOL"),
            ("device/life_time", "vida estimada"),
        ):
            value = _read_optional(device / filename)
            if value:
                lines.append(f"  {label}: {value}")
        smartctl = shutil.which("smartctl")
        node = Path("/dev") / device.name
        if smartctl and node.exists():
            result = _run([smartctl, "-H", str(node)], timeout=30)
            text = sanitize_text((result.stdout or result.stderr).strip())
            if text:
                lines.append("  SMART:")
                lines.extend(f"    {line}" for line in text.splitlines()[:20])
    if not lines:
        lines.append("No s'ha detectat informació eMMC/SMART disponible.")
    return lines


def storage_report(policy: dict[str, Any]) -> str:
    total, free, percent = _disk_usage()
    df = _run(["/usr/bin/df", "-h", "/"], timeout=20)
    lsblk = _run(
        [
            "/usr/bin/lsblk",
            "-o",
            "NAME,TYPE,SIZE,FSTYPE,FSUSE%,MOUNTPOINTS,MODEL",
        ],
        timeout=20,
    )
    lines = [
        "XAAC Thin Client OS — Emmagatzematge",
        "=====================================",
        f"Arrel: {percent}% usat; {free // (1024 * 1024)} MiB lliures / {total // (1024 * 1024)} MiB",
        "",
        "[df]",
        sanitize_text((df.stdout or df.stderr).strip()) or "sense dades",
        "",
        "[Dispositius]",
        sanitize_text((lsblk.stdout or lsblk.stderr).strip()) or "sense dades",
        "",
        "[eMMC / SMART]",
        *_emmc_health_lines(),
    ]
    return "\n".join(lines) + "\n"


def services_report(policy: dict[str, Any]) -> str:
    lines = ["XAAC Thin Client OS — Serveis", "============================"]
    all_units = (
        list(policy["services"]["active_required"])
        + list(policy["services"]["installed_required"])
        + list(policy["services"]["optional"])
    )
    for unit in all_units:
        info = _unit_info(str(unit))
        lines.append(
            f"{unit}: load={info['load']} active={info['active']} enabled={info['enabled']}"
        )
    lines.extend(
        [
            f"xaac-thinclient procés: {'actiu' if _process_running('xaac-thinclient') else 'no detectat'}",
            "",
            "[Unitats fallides]",
        ]
    )
    failed = _run(["/usr/bin/systemctl", "--failed", "--no-pager", "--plain"], timeout=20)
    lines.append(sanitize_text((failed.stdout or failed.stderr).strip()) or "cap")
    return "\n".join(lines) + "\n"


def logs_report(policy: dict[str, Any]) -> str:
    limit = int(policy["limits"]["log_lines"])
    result = _run(
        [
            "/usr/bin/journalctl",
            "-b",
            "-p",
            "warning..alert",
            "--no-pager",
            "-o",
            "short-iso",
            "-n",
            str(limit),
        ],
        timeout=30,
    )
    text = sanitize_text((result.stdout or result.stderr).strip())
    return (
        "XAAC Thin Client OS — Logs sanititzats\n"
        "=======================================\n"
        + (text or "cap entrada warning..alert en l'arranc actual")
        + "\n"
    )


def _remove_old_diagnostics(root: Path, retention_days: int) -> int:
    cutoff = time.time() - retention_days * 86400
    removed = 0
    if not root.exists():
        return removed
    for item in root.iterdir():
        if not item.name.startswith("xaac-diagnostics-") or not item.name.endswith(".tar.gz"):
            continue
        try:
            if item.lstat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        if item.is_dir() and not item.is_symlink():
            continue
        item.unlink(missing_ok=True)
        removed += 1
    return removed


def cleanup(policy: dict[str, Any]) -> str:
    limits = policy["limits"]
    diagnostics_root = DIAGNOSTICS_ROOT
    removed = _remove_old_diagnostics(
        diagnostics_root, int(limits["diagnostics_retention_days"])
    )
    journal = _run(
        [
            "/usr/bin/journalctl",
            f"--vacuum-time={int(limits['journal_retention_days'])}d",
            f"--vacuum-size={int(limits['journal_max_bytes'])}",
        ],
        timeout=120,
    )
    apt = _run(["/usr/bin/apt-get", "clean"], timeout=120)
    if journal.returncode != 0:
        raise MaintenanceRuntimeError(
            "No s'ha pogut aplicar la retenció del journal: "
            + sanitize_text((journal.stderr or journal.stdout).strip())
        )
    if apt.returncode != 0:
        raise MaintenanceRuntimeError(
            "No s'ha pogut netejar la cache APT: "
            + sanitize_text((apt.stderr or apt.stdout).strip())
        )
    state: dict[str, Any] = {}
    if STATE_PATH.is_file():
        try:
            state = _load_json(STATE_PATH, "l'estat de manteniment")
        except MaintenanceRuntimeError:
            state = {}
    state.update({"schema_version": 1, "last_cleanup_at": utc_now()})
    atomic_json(STATE_PATH, state)
    return (
        "Neteja completada. "
        f"Bundles de diagnòstic antics eliminats: {removed}. "
        "S'ha aplicat la retenció del journal i s'ha netejat la cache APT.\n"
    )


def _write_report(path: Path, content: str) -> None:
    if path.is_symlink():
        raise MaintenanceRuntimeError(f"Destinació insegura: {path}")
    path.write_text(sanitize_text(content), encoding="utf-8")
    path.chmod(0o600)


def _write_json_report(path: Path, payload: object) -> None:
    if path.is_symlink():
        raise MaintenanceRuntimeError(f"Destinació insegura: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _safe_update_state_text(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        return "absent\n"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"no llegible: {exc}\n"
    return sanitize_text(raw)


def _diagnostic_manifest(policy: dict[str, Any]) -> dict[str, Any]:
    os_release = _os_release()
    return {
        "schema_version": 1,
        "bundle": "xaac-diagnostics",
        "created_at": utc_now(),
        "os_version": os_release.get("VERSION_ID"),
        "kernel": os.uname().release,
        "components": {package: _package_version(package) for package in _COMPONENT_PACKAGES},
        "privacy": {
            "sanitized": True,
            "configuration_contents_included": False,
            "credentials_included": False,
            "private_keys_included": False,
            "vpn_secrets_included": False,
        },
        "excluded_sensitive_paths": list(policy["privacy"]["forbidden_paths"]),
    }


def diagnostics(policy: dict[str, Any]) -> Path:
    root = DIAGNOSTICS_ROOT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    build_dir = Path(tempfile.mkdtemp(prefix=".xaac-diagnostics-", dir=root))
    os.chmod(build_dir, 0o700)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    destination = root / f"xaac-diagnostics-{timestamp}.tar.gz"
    if destination.exists() or destination.is_symlink():
        raise MaintenanceRuntimeError(f"El bundle ja existeix: {destination}")
    try:
        _write_report(build_dir / "status.txt", status_report(policy))
        health_text, overall = health_report(policy)
        _write_report(build_dir / "health.txt", health_text)
        _write_report(build_dir / "network.txt", network_report(policy))
        _write_report(build_dir / "storage.txt", storage_report(policy))
        _write_report(build_dir / "services.txt", services_report(policy))
        _write_report(build_dir / "logs.txt", logs_report(policy))
        dpkg = _run(["/usr/bin/dpkg", "--audit"], timeout=30)
        _write_report(build_dir / "dpkg-audit.txt", dpkg.stdout + dpkg.stderr)
        for state_path in UPDATE_STATE_PATHS:
            _write_report(
                build_dir / f"update-{state_path.name}",
                _safe_update_state_text(state_path),
            )
        manifest = _diagnostic_manifest(policy)
        manifest["health"] = overall
        _write_json_report(build_dir / "manifest.json", manifest)

        maximum = int(policy["limits"]["diagnostics_max_bytes"])
        total = sum(
            item.stat().st_size
            for item in build_dir.iterdir()
            if item.is_file() and not item.is_symlink()
        )
        if total > maximum:
            raise MaintenanceRuntimeError("Les dades de diagnòstic superen la mida màxima")

        with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for item in sorted(build_dir.iterdir(), key=lambda candidate: candidate.name):
                if item.is_symlink() or not item.is_file():
                    raise MaintenanceRuntimeError(f"Element insegur al bundle: {item.name}")
                archive.add(item, arcname=item.name, recursive=False)
        os.chmod(destination, 0o600)
        if destination.stat().st_size > maximum:
            destination.unlink(missing_ok=True)
            raise MaintenanceRuntimeError("El bundle comprimit supera la mida màxima")

        state: dict[str, Any] = {}
        if STATE_PATH.is_file():
            try:
                state = _load_json(STATE_PATH, "l'estat de manteniment")
            except MaintenanceRuntimeError:
                state = {}
        state.update(
            {
                "schema_version": 1,
                "last_diagnostics_at": utc_now(),
                "last_diagnostics_bundle": str(destination),
            }
        )
        atomic_json(STATE_PATH, state)
        return destination
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
