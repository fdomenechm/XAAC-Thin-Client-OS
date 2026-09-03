"""Controlled Debian 13 base-system updater for XAAC Thin Client OS phase 10.6.

This runtime intentionally uses only the Python standard library.  It never runs
``full-upgrade`` or ``dist-upgrade`` and it never changes the configured Debian
suite.  APT is used only after a strict source/preflight/plan validation.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

POLICY_PATH = Path("/etc/xaac/update/base-os-policy.json")
STATE_PATH = Path("/var/lib/xaac-update/base-os-state.json")
LOCK_PATH = Path("/run/lock/xaac-base-os-update.lock")
PLAN_PATH = Path("/var/lib/xaac-update/base-os-plan.json")
REBOOT_REQUIRED_PATH = Path("/var/run/reboot-required")

_INST_RE = re.compile(r"^Inst\s+(\S+)(?:\s+\[([^\]]+)\])?\s+\((\S+)")
_REMV_RE = re.compile(r"^Remv\s+(\S+)(?:\s+\[([^\]]+)\])?")


class BaseOsRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    command: list[str],
    *,
    timeout: int = 300,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "DEBIAN_FRONTEND": "noninteractive",
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        }
    )
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
        raise BaseOsRuntimeError(f"No s'ha pogut executar {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise BaseOsRuntimeError(
            f"Ha fallat {command[0]} (rc={result.returncode})"
            + (f": {detail}" if detail else "")
        )
    return result


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaseOsRuntimeError(f"No s'ha pogut llegir {description}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BaseOsRuntimeError(f"{description} invàlid")
    return payload


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _load_json(path, "la política d'actualització del sistema base")
    if (
        policy.get("schema_version") != 1
        or policy.get("update_id") != "xaac-base-os-update"
        or policy.get("phase") != "10.6"
    ):
        raise BaseOsRuntimeError("Política d'actualització del sistema base no compatible")
    platform = policy.get("platform")
    rules = policy.get("policy")
    outputs = policy.get("outputs")
    if not isinstance(platform, dict) or not isinstance(rules, dict) or not isinstance(outputs, dict):
        raise BaseOsRuntimeError("Política 10.6 incompleta")
    if (
        platform.get("debian_major") != 13
        or platform.get("suite") != "trixie"
        or platform.get("architecture") != "amd64"
    ):
        raise BaseOsRuntimeError("La política 10.6 no correspon a Debian 13/trixie amd64")
    if rules.get("apt_operation") != "upgrade-with-new-pkgs":
        raise BaseOsRuntimeError("Operació APT 10.6 no autoritzada")
    if (
        rules.get("allow_release_change") is not False
        or rules.get("allow_downgrade") is not False
        or rules.get("allow_removals") is not False
        or rules.get("automatic_reboot") is not False
        or rules.get("automatic_rollback") is not False
    ):
        raise BaseOsRuntimeError("La política 10.6 relaxa proteccions obligatòries")
    return policy


def _atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BaseOsRuntimeError(f"No s'escriurà sobre un enllaç simbòlic: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _audit(policy: dict[str, Any], event: str, data: dict[str, Any]) -> None:
    path = Path(policy["outputs"]["audit"])
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": _utc_now(), "event": event, **data}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(path, 0o640)


def _write_state(policy: dict[str, Any], **updates: Any) -> dict[str, Any]:
    state_path = Path(policy["outputs"]["state"])
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = _load_json(state_path, "l'estat 10.6")
        except BaseOsRuntimeError:
            state = {}
    state.update(
        {
            "schema_version": 1,
            "update_id": "xaac-base-os-update",
            "phase": "10.6",
            "hardware_profile": policy.get("hardware_profile"),
        }
    )
    state.update(updates)
    _atomic_json(state_path, state)
    return state


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BaseOsRuntimeError(f"No s'ha pogut llegir /etc/os-release: {exc}") from exc
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _debian_version() -> str:
    try:
        return Path("/etc/debian_version").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BaseOsRuntimeError(f"No s'ha pogut llegir /etc/debian_version: {exc}") from exc


def _architecture() -> str:
    result = _run(["/usr/bin/dpkg", "--print-architecture"], timeout=30)
    if result.returncode != 0 or not result.stdout.strip():
        raise BaseOsRuntimeError("No s'ha pogut determinar l'arquitectura Debian")
    return result.stdout.strip()


def _dpkg_compare(left: str, relation: str, right: str) -> bool:
    return _run(["/usr/bin/dpkg", "--compare-versions", left, relation, right], timeout=30).returncode == 0


def _installed_version(package: str) -> str | None:
    result = _run(["/usr/bin/dpkg-query", "-W", "-f=${Status}\n${Version}\n", package], timeout=30)
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 2 or lines[0] != "install ok installed":
        return None
    return lines[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files() -> list[Path]:
    files = [Path("/etc/apt/sources.list")]
    directory = Path("/etc/apt/sources.list.d")
    if directory.is_dir():
        files.extend(sorted(directory.glob("*.list")))
        files.extend(sorted(directory.glob("*.sources")))
    return [path for path in files if path.is_file() and path.stat().st_size > 0]


def _parse_list_sources(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("deb "):
            raise BaseOsRuntimeError(f"Entrada APT no suportada en {path}: {line[:80]}")
        if "[trusted=yes]" in line or "allow-insecure" in line.lower():
            raise BaseOsRuntimeError(f"Font APT insegura en {path}")
        parts = line.split()
        if len(parts) < 4:
            raise BaseOsRuntimeError(f"Entrada APT incompleta en {path}")
        offset = 1
        options = ""
        if parts[offset].startswith("["):
            option_parts: list[str] = []
            while offset < len(parts):
                option_parts.append(parts[offset])
                if parts[offset].endswith("]"):
                    break
                offset += 1
            options = " ".join(option_parts)
            offset += 1
        if len(parts) <= offset + 2:
            raise BaseOsRuntimeError(f"Entrada APT incompleta en {path}")
        signed_by = None
        if options:
            match = re.search(r"(?:^|[\s[])signed-by=([^\s\]]+)", options, re.IGNORECASE)
            if match:
                signed_by = match.group(1)
        entries.append(
            {
                "uri": parts[offset].rstrip("/"),
                "suite": parts[offset + 1],
                "components": parts[offset + 2 :],
                "options": options,
                "signed_by": signed_by,
                "source": str(path),
            }
        )
    return entries


def _parse_deb822_sources(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    content = path.read_text(encoding="utf-8")
    for block in re.split(r"\n\s*\n", content):
        fields: dict[str, str] = {}
        for raw in block.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        if not fields:
            continue
        if fields.get("enabled", "yes").lower() == "no":
            continue
        if fields.get("types") != "deb":
            raise BaseOsRuntimeError(f"Tipus APT no suportat en {path}")
        uris = fields.get("uris", "").split()
        suites = fields.get("suites", "").split()
        components = fields.get("components", "").split()
        signed_by = fields.get("signed-by")
        if len(uris) != 1 or not suites or not components:
            raise BaseOsRuntimeError(f"Font Deb822 incompleta en {path}")
        for suite in suites:
            entries.append(
                {
                    "uri": uris[0].rstrip("/"),
                    "suite": suite,
                    "components": components,
                    "signed_by": signed_by,
                    "source": str(path),
                }
            )
    return entries


def validate_sources(policy: dict[str, Any]) -> dict[str, Any]:
    allowed: set[tuple[str, str, tuple[str, ...]]] = set()
    keyring = "/usr/share/keyrings/debian-archive-keyring.gpg"
    for repository in policy["repositories"]:
        for suite in repository["suites"]:
            allowed.add(
                (
                    str(repository["uri"]).rstrip("/"),
                    str(suite),
                    tuple(repository["components"]),
                )
            )
    files = _source_files()
    if not files:
        raise BaseOsRuntimeError("No hi ha fonts APT configurades")
    entries: list[dict[str, Any]] = []
    for path in files:
        if path.suffix == ".sources":
            entries.extend(_parse_deb822_sources(path))
        else:
            entries.extend(_parse_list_sources(path))
    actual: set[tuple[str, str, tuple[str, ...]]] = set()
    for entry in entries:
        uri = str(entry["uri"])
        suite = str(entry["suite"])
        components = tuple(entry["components"])
        if not uri.startswith("https://"):
            raise BaseOsRuntimeError(f"Font APT sense HTTPS: {uri}")
        if entry.get("options") and "trusted=yes" in str(entry["options"]).lower():
            raise BaseOsRuntimeError(f"Font APT marcada com trusted=yes: {entry['source']}")
        signed_by = entry.get("signed_by")
        if signed_by != keyring:
            raise BaseOsRuntimeError(f"Falta Signed-By o usa un keyring no autoritzat en {entry['source']}")
        actual.add((uri, suite, components))
    if actual != allowed:
        missing = sorted(allowed - actual)
        extra = sorted(actual - allowed)
        raise BaseOsRuntimeError(f"Fonts APT fora de política; missing={missing}, extra={extra}")
    if not Path(keyring).is_file():
        raise BaseOsRuntimeError(f"No existeix el keyring Debian: {keyring}")
    return {
        "ok": True,
        "files": [str(path) for path in files],
        "entries": len(entries),
        "suites": sorted({entry["suite"] for entry in entries}),
    }


def _platform_checks(policy: dict[str, Any]) -> list[dict[str, Any]]:
    platform = policy["platform"]
    os_release = _os_release()
    debian_version = _debian_version()
    architecture = _architecture()
    return [
        {
            "name": "os_identity",
            "ok": os_release.get("ID") == platform["os_id"],
            "value": os_release.get("ID"),
        },
        {
            "name": "debian_major",
            "ok": debian_version == str(platform["debian_major"]) or debian_version.startswith(str(platform["debian_major"]) + "."),
            "value": debian_version,
        },
        {
            "name": "architecture",
            "ok": architecture == platform["architecture"],
            "value": architecture,
        },
    ]


def preflight(policy: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    checks = _platform_checks(policy)
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8").strip()
    except OSError:
        cmdline = ""
    in_recovery = "systemd.unit=xaac-recovery.target" in cmdline
    checks.append({"name": "normal_boot_mode", "ok": not in_recovery, "value": "recovery" if in_recovery else "normal"})
    try:
        sources = validate_sources(policy)
        checks.append({"name": "apt_sources", "ok": True, "detail": sources})
    except BaseOsRuntimeError as exc:
        checks.append({"name": "apt_sources", "ok": False, "detail": str(exc)})

    free_bytes = shutil.disk_usage("/var").free
    required = int(policy["policy"]["minimum_free_bytes"])
    checks.append(
        {
            "name": "free_space",
            "ok": free_bytes >= required,
            "free_bytes": free_bytes,
            "required_bytes": required,
        }
    )
    audit = _run(["/usr/bin/dpkg", "--audit"], timeout=60)
    checks.append(
        {
            "name": "dpkg_audit",
            "ok": audit.returncode == 0 and not (audit.stdout + audit.stderr).strip(),
            "detail": (audit.stdout + audit.stderr).strip()[-1000:] or None,
        }
    )
    apt = _run(["/usr/bin/apt-get", "-o", "Debug::NoLocking=true", "check"], timeout=120)
    checks.append(
        {
            "name": "apt_check",
            "ok": apt.returncode == 0,
            "detail": (apt.stderr or apt.stdout).strip()[-1000:] or None,
        }
    )
    for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        result = _run(["/usr/bin/systemctl", "is-enabled", timer], timeout=30)
        state = (result.stdout or result.stderr).strip()
        checks.append({"name": f"{timer}_masked", "ok": state == "masked", "value": state})
    ok = all(bool(item.get("ok")) for item in checks)
    return {"status": "ok" if ok else "failed", "phase": "10.6", "checks": checks}, ok


def refresh_indexes() -> dict[str, Any]:
    result = _run(
        [
            "/usr/bin/apt-get",
            "-o",
            "APT::Update::Error-Mode=any",
            "update",
        ],
        timeout=600,
    )
    detail = (result.stderr or result.stdout).strip()[-4000:]
    if result.returncode != 0:
        raise BaseOsRuntimeError(f"apt-get update ha fallat: {detail}")
    return {"ok": True, "detail": detail or None}


def _simulate() -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "/usr/bin/apt-get",
            "-s",
            "-o",
            "Debug::NoLocking=true",
            "--no-remove",
            "--with-new-pkgs",
            "upgrade",
        ],
        timeout=300,
    )


def parse_plan(output: str) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    for raw in output.splitlines():
        match = _INST_RE.match(raw)
        if match:
            package, installed, candidate = match.groups()
            changes.append(
                {
                    "package": package,
                    "base_package": package.split(":", 1)[0],
                    "installed": installed,
                    "candidate": candidate,
                    "new": installed is None,
                }
            )
            continue
        match = _REMV_RE.match(raw)
        if match:
            package, installed = match.groups()
            removals.append(
                {
                    "package": package,
                    "base_package": package.split(":", 1)[0],
                    "installed": installed,
                }
            )
    return {"changes": changes, "removals": removals}


def validate_plan(policy: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    changes = plan["changes"]
    removals = plan["removals"]
    rules = policy["policy"]
    if removals:
        raise BaseOsRuntimeError("El pla APT intenta eliminar paquets; operació bloquejada")
    if len(changes) > int(rules["maximum_changed_packages"]):
        raise BaseOsRuntimeError("El pla APT supera el màxim de paquets modificats")
    new_count = sum(1 for item in changes if item["new"])
    if new_count > int(rules["maximum_new_packages"]):
        raise BaseOsRuntimeError("El pla APT supera el màxim de dependències noves")
    protected = set(rules["protected_packages"])
    touched_protected = sorted({item["base_package"] for item in changes if item["base_package"] in protected})
    if touched_protected:
        raise BaseOsRuntimeError(
            "APT intenta modificar paquets XAAC protegits: " + ", ".join(touched_protected)
        )
    downgrades: list[str] = []
    for item in changes:
        installed = item["installed"]
        candidate = item["candidate"]
        if installed is not None and not _dpkg_compare(candidate, "ge", installed):
            downgrades.append(item["package"])
    if downgrades:
        raise BaseOsRuntimeError("Downgrade APT bloquejat: " + ", ".join(sorted(downgrades)))
    reboot_prefixes = tuple(rules["reboot_package_prefixes"])
    reboot_recommended = any(item["base_package"].startswith(reboot_prefixes) for item in changes)
    return {
        "status": "current" if not changes else "available",
        "phase": "10.6",
        "operation": "apt-get upgrade --with-new-pkgs --no-remove",
        "changed_packages": len(changes),
        "new_packages": new_count,
        "removals": 0,
        "reboot_recommended": reboot_recommended,
        "packages": changes,
    }


def _plan_fingerprint(payload: dict[str, Any]) -> str:
    stable = [
        {
            "package": item["package"],
            "installed": item["installed"],
            "candidate": item["candidate"],
            "new": item["new"],
        }
        for item in payload["packages"]
    ]
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def check_updates(policy: dict[str, Any], *, refresh: bool = True) -> dict[str, Any]:
    pre, ok = preflight(policy)
    if not ok:
        raise BaseOsRuntimeError("El preflight del sistema base ha fallat")
    refresh_result = refresh_indexes() if refresh else {"ok": True, "detail": "not refreshed"}
    simulation = _simulate()
    if simulation.returncode != 0:
        detail = (simulation.stderr or simulation.stdout).strip()[-2000:]
        raise BaseOsRuntimeError(f"La simulació APT ha fallat: {detail}")
    plan = validate_plan(policy, parse_plan(simulation.stdout))
    plan["checked_at"] = _utc_now()
    plan["fingerprint"] = _plan_fingerprint(plan)
    plan["preflight"] = pre
    plan["apt_update"] = refresh_result
    _atomic_json(PLAN_PATH, plan)
    _write_state(
        policy,
        status=plan["status"],
        last_check=plan["checked_at"],
        available_packages=plan["changed_packages"],
        last_plan_fingerprint=plan["fingerprint"],
        reboot_required=REBOOT_REQUIRED_PATH.exists(),
        last_error=None,
    )
    _audit(
        policy,
        "base_os_check",
        {
            "status": plan["status"],
            "changed_packages": plan["changed_packages"],
            "new_packages": plan["new_packages"],
            "fingerprint": plan["fingerprint"],
        },
    )
    return plan


def status(policy: dict[str, Any]) -> dict[str, Any]:
    state_path = Path(policy["outputs"]["state"])
    state = _load_json(state_path, "l'estat 10.6") if state_path.is_file() else None
    source_status: dict[str, Any]
    try:
        source_status = validate_sources(policy)
    except BaseOsRuntimeError as exc:
        source_status = {"ok": False, "error": str(exc)}
    return {
        "status": "ok",
        "phase": "10.6",
        "os": _os_release().get("PRETTY_NAME"),
        "debian_version": _debian_version(),
        "architecture": _architecture(),
        "suite": policy["platform"]["suite"],
        "apt_operation": "upgrade --with-new-pkgs",
        "automatic_updates": False,
        "automatic_reboot": False,
        "full_upgrade_allowed": False,
        "sources": source_status,
        "reboot_required": REBOOT_REQUIRED_PATH.exists(),
        "state": state,
    }


def _snapshot_checkpoint(policy: dict[str, Any], plan: dict[str, Any]) -> None:
    root = Path(policy["outputs"]["checkpoint"])
    if root.exists() and root.is_symlink():
        raise BaseOsRuntimeError("El checkpoint 10.6 és un enllaç simbòlic")
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    for child in root.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    status_path = Path("/var/lib/dpkg/status")
    if status_path.is_file():
        target = root / "dpkg-status.before"
        shutil.copy2(status_path, target, follow_symlinks=False)
        os.chmod(target, 0o600)
    versions = _run(["/usr/bin/dpkg-query", "-W", "-f=${Package}\t${Version}\n"], timeout=120)
    if versions.returncode != 0:
        raise BaseOsRuntimeError("No s'ha pogut capturar la llista de versions instal·lades")
    versions_target = root / "package-versions.before.tsv"
    versions_target.write_text(versions.stdout, encoding="utf-8")
    os.chmod(versions_target, 0o600)
    sources = root / "apt-sources.sha256"
    lines = []
    for path in _source_files():
        lines.append(f"{_sha256(path)}  {path}\n")
    sources.write_text("".join(lines), encoding="utf-8")
    os.chmod(sources, 0o600)
    _atomic_json(root / "approved-plan.json", plan, 0o600)


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise BaseOsRuntimeError("Ja hi ha una actualització del sistema base en curs") from exc
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _download() -> None:
    _run(
        [
            "/usr/bin/apt-get",
            "--yes",
            "--download-only",
            "--no-remove",
            "--with-new-pkgs",
            "upgrade",
        ],
        timeout=1800,
        check=True,
    )


def _install() -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "/usr/bin/apt-get",
            "--yes",
            "--no-download",
            "--no-remove",
            "--with-new-pkgs",
            "--no-install-recommends",
            "-o",
            "Dpkg::Options::=--force-confdef",
            "-o",
            "Dpkg::Options::=--force-confold",
            "upgrade",
        ],
        timeout=3600,
    )


def _post_health(policy: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    checks: list[dict[str, Any]] = []
    try:
        source_detail = validate_sources(policy)
        checks.append({"name": "apt_sources", "ok": True, "detail": source_detail})
    except BaseOsRuntimeError as exc:
        checks.append({"name": "apt_sources", "ok": False, "detail": str(exc)})
    for item in plan["packages"]:
        package = str(item["package"])
        candidate = str(item["candidate"])
        actual = _installed_version(package)
        checks.append(
            {
                "name": f"package:{package}",
                "ok": actual == candidate,
                "expected": candidate,
                "actual": actual,
            }
        )
    audit = _run(["/usr/bin/dpkg", "--audit"], timeout=120)
    checks.append(
        {
            "name": "dpkg_audit",
            "ok": audit.returncode == 0 and not (audit.stdout + audit.stderr).strip(),
            "detail": (audit.stdout + audit.stderr).strip()[-1000:] or None,
        }
    )
    apt = _run(["/usr/bin/apt-get", "-o", "Debug::NoLocking=true", "check"], timeout=180)
    checks.append(
        {
            "name": "apt_check",
            "ok": apt.returncode == 0,
            "detail": (apt.stderr or apt.stdout).strip()[-1000:] or None,
        }
    )
    for unit in policy["health"]["required_services"]:
        result = _run(["/usr/bin/systemctl", "is-active", unit], timeout=30)
        checks.append({"name": f"service:{unit}", "ok": result.returncode == 0, "value": result.stdout.strip()})
    for unit in policy["health"]["installed_services"]:
        result = _run(["/usr/bin/systemctl", "cat", unit], timeout=30)
        checks.append({"name": f"installed:{unit}", "ok": result.returncode == 0})
    for executable in policy["health"].get("required_executables", []):
        path = Path(str(executable))
        checks.append({"name": f"executable:{path.name}", "ok": path.is_file() and os.access(path, os.X_OK)})
    for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        result = _run(["/usr/bin/systemctl", "is-enabled", timer], timeout=30)
        state = (result.stdout or result.stderr).strip()
        checks.append({"name": f"{timer}_masked", "ok": state == "masked", "value": state})
    ok = all(bool(item.get("ok")) for item in checks)
    return {"checks": checks}, ok


def apply_update(policy: dict[str, Any]) -> dict[str, Any]:
    with _exclusive_lock():
        plan = check_updates(policy, refresh=True)
        if plan["status"] == "current":
            return {
                "status": "current",
                "phase": "10.6",
                "changed_packages": 0,
                "reboot_required": REBOOT_REQUIRED_PATH.exists(),
            }
        _snapshot_checkpoint(policy, plan)
        _write_state(
            policy,
            status="downloading",
            last_update_started=_utc_now(),
            approved_plan_fingerprint=plan["fingerprint"],
            last_error=None,
        )
        _audit(
            policy,
            "base_os_update_started",
            {
                "changed_packages": plan["changed_packages"],
                "new_packages": plan["new_packages"],
                "fingerprint": plan["fingerprint"],
            },
        )
        try:
            _download()
            free_after = shutil.disk_usage("/var").free
            minimum_after = int(policy["policy"]["minimum_free_after_download_bytes"])
            if free_after < minimum_after:
                raise BaseOsRuntimeError(
                    f"Espai insuficient després de la descàrrega: {free_after} < {minimum_after}"
                )
            second_simulation = _simulate()
            if second_simulation.returncode != 0:
                raise BaseOsRuntimeError("La reverificació del pla APT ha fallat")
            second = validate_plan(policy, parse_plan(second_simulation.stdout))
            second["fingerprint"] = _plan_fingerprint(second)
            if second["fingerprint"] != plan["fingerprint"]:
                raise BaseOsRuntimeError("El pla APT ha canviat després de la descàrrega; instal·lació cancel·lada")

            _write_state(policy, status="installing", install_started=_utc_now())
            install = _install()
            if install.returncode != 0:
                repair = _run(["/usr/bin/dpkg", "--configure", "-a"], timeout=900)
                detail = (install.stderr or install.stdout).strip()[-2000:]
                if repair.returncode != 0:
                    raise BaseOsRuntimeError(
                        "APT ha fallat i dpkg --configure -a no ha pogut reparar la transacció"
                        + (f": {detail}" if detail else "")
                    )
                check = _run(["/usr/bin/apt-get", "-o", "Debug::NoLocking=true", "check"], timeout=180)
                if check.returncode != 0:
                    raise BaseOsRuntimeError(
                        "APT ha fallat; dpkg s'ha reconfigurat però apt-get check continua fallant"
                    )

            health, healthy = _post_health(policy, plan)
            if not healthy:
                raise BaseOsRuntimeError("El health-check posterior a l'actualització del sistema base ha fallat")
            reboot_required = REBOOT_REQUIRED_PATH.exists() or bool(plan["reboot_recommended"])
            completed = _utc_now()
            _write_state(
                policy,
                status="completed",
                last_update=completed,
                changed_packages=plan["changed_packages"],
                new_packages=plan["new_packages"],
                reboot_required=reboot_required,
                last_error=None,
                health=health,
            )
            _audit(
                policy,
                "base_os_update_completed",
                {
                    "changed_packages": plan["changed_packages"],
                    "new_packages": plan["new_packages"],
                    "reboot_required": reboot_required,
                    "fingerprint": plan["fingerprint"],
                },
            )
            _run(["/usr/bin/apt-get", "clean"], timeout=120)
            return {
                "status": "completed",
                "phase": "10.6",
                "changed_packages": plan["changed_packages"],
                "new_packages": plan["new_packages"],
                "reboot_required": reboot_required,
                "health": health,
            }
        except BaseOsRuntimeError as exc:
            _write_state(
                policy,
                status="failed_requires_recovery",
                last_error=str(exc),
                reboot_required=REBOOT_REQUIRED_PATH.exists(),
            )
            _audit(policy, "base_os_update_failed", {"error": str(exc), "fingerprint": plan["fingerprint"]})
            raise
