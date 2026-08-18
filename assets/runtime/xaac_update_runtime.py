"""Transactional updater for XAAC Thin Client OS phase 10.2.

This module is deliberately stdlib-only so the recovery/update path does not depend
on the graphical XAAC applications or on the project build-time Python package.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

POLICY_PATH = Path("/etc/xaac/update/transactional-installation.json")
STATE_PATH = Path("/var/lib/xaac-update/transaction-state.json")
ROLLBACK_STATE_PATH = Path("/var/lib/xaac-update/rollback-state.json")
BLOCKED_PATH = Path("/var/lib/xaac-update/blocked-versions.json")
CURRENT_RELEASE_PATH = Path("/usr/share/xaac/update/current-release.json")
LOCK_PATH = Path("/run/lock/xaac-update.lock")


class UpdateRuntimeError(RuntimeError):
    """Raised when a transaction cannot be completed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object, mode: int = 0o640) -> None:
    if path.is_symlink():
        raise UpdateRuntimeError(f"Destinació insegura (symlink): {path}")
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


def load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateRuntimeError(f"No s'ha pogut llegir {description}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateRuntimeError(f"{description} invàlid")
    return value


def safe_relative_filename(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise UpdateRuntimeError("Nom d'artefacte invàlid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
        raise UpdateRuntimeError(f"Nom d'artefacte insegur: {value}")
    return value


def safe_version_path_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\x00" in value:
        raise UpdateRuntimeError("Versió de paquet insegura")
    return value.replace(":", "_")


def run(
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
        raise UpdateRuntimeError(f"No s'ha pogut executar {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise UpdateRuntimeError(f"Ha fallat {command[0]} ({result.returncode}): {detail}")
    return result


def installed_version(package: str) -> str | None:
    result = run(["/usr/bin/dpkg-query", "-W", "-f=${Status}\n${Version}\n", package])
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 2 or lines[0] != "install ok installed":
        return None
    return lines[1]


def process_running(pattern: str) -> bool:
    return run(["/usr/bin/pgrep", "-f", pattern], timeout=10).returncode == 0


def unit_exists(unit: str) -> bool:
    result = run(["/usr/bin/systemctl", "show", "-p", "LoadState", "--value", unit], timeout=20)
    return result.returncode == 0 and result.stdout.strip() == "loaded"


def unit_active(unit: str) -> bool:
    return run(["/usr/bin/systemctl", "is-active", "--quiet", unit], timeout=20).returncode == 0


def load_policy() -> dict[str, Any]:
    policy = load_json(POLICY_PATH, "la política transaccional")
    if policy.get("schema_version") != 2 or policy.get("transaction_id") != "xaac-transactional-update":
        raise UpdateRuntimeError("Política transaccional no compatible")
    return policy


def package_cache_path(policy: dict[str, Any], package: str, version: str) -> Path:
    root = Path(policy["recovery_point"]["package_cache"])
    return root / package / f"{safe_version_path_component(version)}.deb"


def _manifest_components(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise UpdateRuntimeError("Manifest sense components")
    normalized: list[dict[str, Any]] = []
    for item in components:
        if not isinstance(item, dict):
            raise UpdateRuntimeError("Component de manifest invàlid")
        for key in ("package", "version", "filename", "sha256"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise UpdateRuntimeError(f"Camp {key} invàlid al manifest")
        safe_relative_filename(item["filename"])
        normalized.append(item)
    return normalized


def _transaction_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"


def _lock() -> Any:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise UpdateRuntimeError("Ja hi ha una actualització o rollback en curs") from exc
    return handle


def _copy_verified_bundle(
    policy: dict[str, Any], manifest_path: Path, signature_path: Path, bundle: Path, txid: str
) -> tuple[Path, dict[str, Any]]:
    manifest = load_json(manifest_path, "el manifest verificat")
    components = _manifest_components(manifest)
    staging_root = Path(policy["staging"]["root"])
    staging = staging_root / txid
    if staging.exists():
        raise UpdateRuntimeError(f"Staging duplicat: {staging}")
    staging.mkdir(parents=True, mode=0o700)
    os.chmod(staging, 0o700)
    shutil.copy2(manifest_path, staging / "update-manifest.json", follow_symlinks=False)
    shutil.copy2(signature_path, staging / "update-manifest.json.asc", follow_symlinks=False)
    total = 0
    for item in components:
        name = safe_relative_filename(item["filename"])
        source = (bundle / name).resolve()
        try:
            source.relative_to(bundle.resolve())
        except ValueError as exc:
            raise UpdateRuntimeError(f"Artefacte fora del bundle: {name}") from exc
        if source.is_symlink() or not source.is_file():
            raise UpdateRuntimeError(f"Artefacte absent o insegur: {name}")
        target = staging / name
        shutil.copy2(source, target, follow_symlinks=False)
        total += target.stat().st_size
        if sha256(target) != item["sha256"]:
            raise UpdateRuntimeError(f"L'artefacte {name} ha canviat després de verificar-lo")
    maximum = int(policy["staging"]["maximum_bundle_bytes"])
    if total > maximum:
        raise UpdateRuntimeError("El bundle supera la mida màxima permesa")
    return staging, manifest


def _configuration_members(policy: dict[str, Any]) -> list[str]:
    members: list[str] = []
    for value in policy["recovery_point"]["configuration_paths"]:
        if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
            raise UpdateRuntimeError(f"Ruta de configuració insegura: {value}")
        path = Path(value)
        if path.exists() or path.is_symlink():
            members.append(value.lstrip("/"))
    return members


def _archive_configuration(policy: dict[str, Any], destination: Path) -> dict[str, Any]:
    members = _configuration_members(policy)
    archive = destination / "configuration.tar"
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as tar:
        for member in members:
            tar.add(Path("/") / member, arcname=member, recursive=True)
    os.chmod(archive, 0o600)
    return {"archive": archive.name, "sha256": sha256(archive), "members": members}


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise UpdateRuntimeError(f"Entrada insegura al backup: {member.name}")
    if member.ischr() or member.isblk() or member.isfifo():
        raise UpdateRuntimeError(f"Tipus especial no permès al backup: {member.name}")
    if member.issym() or member.islnk():
        target = PurePosixPath(member.linkname)
        if target.is_absolute() or ".." in target.parts:
            raise UpdateRuntimeError(f"Enllaç insegur al backup: {member.name}")


def _restore_configuration(recovery: Path, metadata: dict[str, Any]) -> None:
    archive = recovery / str(metadata["archive"])
    if not archive.is_file() or sha256(archive) != metadata.get("sha256"):
        raise UpdateRuntimeError("Backup de configuració absent o corrupte")
    with tarfile.open(archive, "r") as tar:
        for member in tar.getmembers():
            _validate_tar_member(member)
        tar.extractall(path="/", filter="fully_trusted")


def _create_recovery_point(
    policy: dict[str, Any], txid: str, manifest: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    recovery_root = Path(policy["recovery_point"]["root"])
    recovery = recovery_root / txid
    recovery.mkdir(parents=True, mode=0o700)
    os.chmod(recovery, 0o700)
    old_packages: list[dict[str, str]] = []
    for item in _manifest_components(manifest):
        package = item["package"]
        version = installed_version(package)
        if version is None:
            raise UpdateRuntimeError(f"No es pot recuperar {package}: no està instal·lat")
        cached = package_cache_path(policy, package, version)
        if not cached.is_file() or cached.is_symlink():
            raise UpdateRuntimeError(
                f"No existeix el .deb de rollback per a {package}={version}: {cached}"
            )
        old_packages.append(
            {"package": package, "version": version, "deb": str(cached), "sha256": sha256(cached)}
        )
    config = _archive_configuration(policy, recovery)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": txid,
        "created_at": utc_now(),
        "target_os_version": manifest.get("release", {}).get("os_version"),
        "packages": old_packages,
        "configuration": config,
    }
    if CURRENT_RELEASE_PATH.is_file():
        current_copy = recovery / "current-release.json"
        shutil.copy2(CURRENT_RELEASE_PATH, current_copy, follow_symlinks=False)
        metadata["current_release"] = {
            "file": current_copy.name,
            "sha256": sha256(current_copy),
        }
    atomic_json(recovery / "recovery-point.json", metadata, 0o600)
    return recovery, metadata


def _snapshot_runtime_state(manifest: dict[str, Any]) -> dict[str, bool]:
    packages = {item["package"] for item in _manifest_components(manifest)}
    return {
        "thin_client_running": "xaac-thinclient" in packages
        and process_running(r"(^|/)xaac-thinclient([[:space:]]|$)"),
        "agent_active": "xaac-agent" in packages and unit_exists("xaac-agent.service")
        and unit_active("xaac-agent.service"),
        "vpn_manager_active": "xaac-thin-client-vpn" in packages
        and unit_exists("xaac-vpn-manager.service") and unit_active("xaac-vpn-manager.service"),
    }


def _install_debs(paths: list[Path], packages: list[str], timeout: int) -> None:
    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    run(["/usr/bin/dpkg", "--unpack", *[str(path) for path in paths]], timeout=timeout, check=True, env=env)
    run(["/usr/bin/dpkg", "--configure", *packages], timeout=timeout, check=True, env=env)


def _restart_changed(packages: set[str], before: dict[str, bool]) -> list[str]:
    restarted: list[str] = []
    run(["/usr/bin/systemctl", "daemon-reload"], timeout=30)
    if "xaac-agent" in packages and before.get("agent_active") and unit_exists("xaac-agent.service"):
        run(["/usr/bin/systemctl", "restart", "xaac-agent.service"], timeout=60, check=True)
        restarted.append("xaac-agent.service")
    if (
        "xaac-thin-client-vpn" in packages
        and before.get("vpn_manager_active")
        and unit_exists("xaac-vpn-manager.service")
    ):
        run(["/usr/bin/systemctl", "restart", "xaac-vpn-manager.service"], timeout=60, check=True)
        restarted.append("xaac-vpn-manager.service")
    if "xaac-thinclient" in packages and before.get("thin_client_running"):
        # The bounded kiosk supervisor owns relaunch policy. Only terminate the
        # current client; never start a second unowned graphical instance as root.
        run(["/usr/bin/pkill", "-TERM", "-u", "xaac-kiosk", "-f", r"(^|/)xaac-thinclient([[:space:]]|$)"], timeout=10)
        restarted.append("xaac-thinclient (session supervisor)")
    return restarted


def _health_check(
    expected: dict[str, str], before: dict[str, bool], timeout: int
) -> tuple[dict[str, Any], bool]:
    checks: dict[str, Any] = {}
    package_ok = True
    for package, version in expected.items():
        actual = installed_version(package)
        ok = actual == version
        checks[f"package:{package}"] = {"ok": ok, "expected": version, "actual": actual}
        package_ok = package_ok and ok
    audit = run(["/usr/bin/dpkg", "--audit"], timeout=60)
    audit_ok = audit.returncode == 0 and not (audit.stdout + audit.stderr).strip()
    checks["dpkg_audit"] = {"ok": audit_ok, "detail": (audit.stdout + audit.stderr).strip()[-1000:] or None}
    apt = run(["/usr/bin/apt-get", "-o", "Debug::NoLocking=true", "check"], timeout=120)
    checks["apt_check"] = {"ok": apt.returncode == 0, "detail": (apt.stderr or apt.stdout).strip()[-1000:] or None}

    executable_map = {
        "xaac-thinclient": Path("/usr/bin/xaac-thinclient"),
        "xaac-thin-client-vpn": Path("/usr/bin/xaac-thin-client-vpn"),
        "xaac-agent": Path("/usr/bin/xaac-agent"),
    }
    executable_ok = True
    for package in expected:
        executable = executable_map.get(package)
        if executable is not None:
            ok = executable.is_file() and os.access(executable, os.X_OK)
            checks[f"executable:{package}"] = {"ok": ok, "path": str(executable)}
            executable_ok = executable_ok and ok

    service_ok = True
    if before.get("agent_active"):
        ok = unit_active("xaac-agent.service")
        checks["service:xaac-agent"] = {"ok": ok}
        service_ok = service_ok and ok
    if before.get("vpn_manager_active"):
        ok = unit_active("xaac-vpn-manager.service")
        checks["service:xaac-vpn-manager"] = {"ok": ok}
        service_ok = service_ok and ok
    if before.get("thin_client_running"):
        deadline = time.monotonic() + min(timeout, 45)
        ok = False
        while time.monotonic() < deadline:
            if process_running(r"(^|/)xaac-thinclient([[:space:]]|$)"):
                ok = True
                break
            time.sleep(1)
        checks["session:xaac-thinclient"] = {"ok": ok}
        service_ok = service_ok and ok

    ok = package_ok and audit_ok and apt.returncode == 0 and executable_ok and service_ok
    return checks, ok


def _cache_candidates(policy: dict[str, Any], staging: Path, manifest: dict[str, Any]) -> None:
    for item in _manifest_components(manifest):
        package = item["package"]
        version = item["version"]
        source = staging / safe_relative_filename(item["filename"])
        target = package_cache_path(policy, package, version)
        target.parent.mkdir(parents=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        if target.exists():
            if target.is_symlink() or sha256(target) != item["sha256"]:
                raise UpdateRuntimeError(f"Cache de paquets incoherent: {target}")
            continue
        shutil.copy2(source, target, follow_symlinks=False)
        os.chmod(target, 0o600)
        if sha256(target) != item["sha256"]:
            target.unlink(missing_ok=True)
            raise UpdateRuntimeError(f"No s'ha pogut preservar {package}={version} al cache")


def _blocked_registry() -> dict[str, Any]:
    if not BLOCKED_PATH.is_file():
        return {"schema_version": 1, "blocked": []}
    value = load_json(BLOCKED_PATH, "el registre de versions bloquejades")
    if not isinstance(value.get("blocked"), list):
        raise UpdateRuntimeError("Registre de versions bloquejades invàlid")
    return value


def is_blocked(manifest: dict[str, Any]) -> bool:
    target = manifest.get("release", {}).get("os_version")
    candidates = {(item["package"], item["version"]) for item in _manifest_components(manifest)}
    registry = _blocked_registry()
    for item in registry["blocked"]:
        if not isinstance(item, dict):
            continue
        if item.get("target_os_version") == target and {
            (p.get("package"), p.get("version")) for p in item.get("packages", []) if isinstance(p, dict)
        } == candidates:
            return True
    return False


def _block_failed(manifest: dict[str, Any], txid: str, reason: str) -> None:
    registry = _blocked_registry()
    entry = {
        "transaction_id": txid,
        "blocked_at": utc_now(),
        "target_os_version": manifest.get("release", {}).get("os_version"),
        "packages": [
            {"package": item["package"], "version": item["version"]}
            for item in _manifest_components(manifest)
        ],
        "reason": reason[-1000:],
    }
    registry["blocked"].append(entry)
    atomic_json(BLOCKED_PATH, registry)


def _prune_recovery_points(policy: dict[str, Any], keep_txid: str | None = None) -> None:
    root = Path(policy["recovery_point"]["root"])
    if not root.is_dir():
        return
    maximum = int(policy["recovery_point"]["max_points"])
    points = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    points.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    protected = {keep_txid} if keep_txid else set()
    retained = 0
    for point in points:
        if point.name in protected or retained < maximum:
            retained += 1
            continue
        shutil.rmtree(point)


def _write_transaction_state(payload: dict[str, Any]) -> None:
    atomic_json(STATE_PATH, payload)


def _rollback_from_recovery(
    policy: dict[str, Any], recovery: Path, before: dict[str, bool], *, cause: str
) -> dict[str, Any]:
    metadata = load_json(recovery / "recovery-point.json", "el punt de recuperació")
    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise UpdateRuntimeError("Punt de recuperació sense paquets")
    debs: list[Path] = []
    expected: dict[str, str] = {}
    for item in packages:
        if not isinstance(item, dict):
            raise UpdateRuntimeError("Metadades de rollback invàlides")
        path = Path(str(item.get("deb")))
        digest = item.get("sha256")
        if not path.is_file() or path.is_symlink() or not isinstance(digest, str) or sha256(path) != digest:
            raise UpdateRuntimeError(f"Paquet de rollback absent o corrupte: {path}")
        package = str(item.get("package"))
        version = str(item.get("version"))
        debs.append(path)
        expected[package] = version
    timeout = int(policy["installation"]["lock_timeout_seconds"])
    _install_debs(debs, list(expected), timeout)
    configuration = metadata.get("configuration")
    if not isinstance(configuration, dict):
        raise UpdateRuntimeError("Punt de recuperació sense configuració")
    _restore_configuration(recovery, configuration)
    restarted = _restart_changed(set(expected), before)
    checks, ok = _health_check(expected, before, int(policy["health"]["timeout_seconds"]))
    if not ok:
        raise UpdateRuntimeError("El health-check posterior al rollback ha fallat")
    current = metadata.get("current_release")
    if isinstance(current, dict):
        source = recovery / str(current.get("file"))
        if source.is_file() and sha256(source) == current.get("sha256"):
            CURRENT_RELEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, CURRENT_RELEASE_PATH, follow_symlinks=False)
    state = {
        "schema_version": 2,
        "status": "rolled_back",
        "transaction_id": metadata.get("transaction_id"),
        "completed_at": utc_now(),
        "cause": cause,
        "restored_packages": expected,
        "restarted": restarted,
        "checks": checks,
        "last_error": None,
    }
    atomic_json(ROLLBACK_STATE_PATH, state)
    return state


def apply_update(
    manifest_path: Path,
    signature_path: Path,
    bundle: Path,
    *,
    audit: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Install a bundle already cryptographically verified by xaac-update-admin.

    Files are copied into root-owned staging and hashed again before any package is
    modified. The function fails before installation unless every installed version
    has a cached .deb suitable for rollback.
    """
    policy = load_policy()
    handle = _lock()
    txid = _transaction_id()
    staging: Path | None = None
    recovery: Path | None = None
    manifest: dict[str, Any] | None = None
    before: dict[str, bool] = {}
    state: dict[str, Any] = {
        "schema_version": 2,
        "status": "preparing",
        "transaction_id": txid,
        "started_at": utc_now(),
        "completed_at": None,
        "recovery_point": None,
        "target_os_version": None,
        "changed_packages": [],
        "restarted": [],
        "checks": {},
        "last_error": None,
    }
    _write_transaction_state(state)
    try:
        staging, manifest = _copy_verified_bundle(policy, manifest_path, signature_path, bundle, txid)
        if is_blocked(manifest):
            raise UpdateRuntimeError("Aquesta combinació de versions està bloquejada per una fallada anterior")
        target_os = manifest.get("release", {}).get("os_version")
        state["target_os_version"] = target_os
        before = _snapshot_runtime_state(manifest)
        recovery, recovery_meta = _create_recovery_point(policy, txid, manifest)
        state["recovery_point"] = str(recovery)
        state["previous_packages"] = {
            item["package"]: item["version"] for item in recovery_meta["packages"]
        }
        state["status"] = "installing"
        _write_transaction_state(state)
        if audit:
            audit("transaction_installing", {"transaction_id": txid, "target_os_version": target_os})

        components = _manifest_components(manifest)
        paths = [staging / safe_relative_filename(item["filename"]) for item in components]
        expected = {item["package"]: item["version"] for item in components}
        changed = {
            package for package, version in expected.items() if installed_version(package) != version
        }
        state["changed_packages"] = sorted(changed)
        if changed:
            _install_debs(paths, list(expected), int(policy["installation"]["lock_timeout_seconds"]))
            restarted = _restart_changed(changed, before)
        else:
            restarted = []
        state["restarted"] = restarted
        state["status"] = "validating"
        _write_transaction_state(state)
        checks, ok = _health_check(expected, before, int(policy["health"]["timeout_seconds"]))
        state["checks"] = checks
        if not ok:
            raise UpdateRuntimeError("El health-check de la nova versió ha fallat")

        _cache_candidates(policy, staging, manifest)
        CURRENT_RELEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging / "update-manifest.json", CURRENT_RELEASE_PATH, follow_symlinks=False)
        os.chmod(CURRENT_RELEASE_PATH, 0o644)
        state["status"] = "confirmed"
        state["completed_at"] = utc_now()
        _write_transaction_state(state)
        if audit:
            audit("transaction_confirmed", {"transaction_id": txid, "changed_packages": sorted(changed)})
        _prune_recovery_points(policy, keep_txid=txid)
        if not policy["staging"]["preserve_on_success"]:
            shutil.rmtree(staging, ignore_errors=True)
        return state
    except Exception as exc:
        reason = str(exc)
        state["last_error"] = reason
        # Automatic rollback starts only after a recovery point exists. Before
        # that, the installed system has not been modified.
        if recovery is not None and manifest is not None and state.get("status") in {"installing", "validating"}:
            try:
                state["status"] = "rolling_back"
                _write_transaction_state(state)
                rollback = _rollback_from_recovery(policy, recovery, before, cause=reason)
                _block_failed(manifest, txid, reason)
                state["status"] = "rolled_back"
                state["rollback"] = rollback
                state["completed_at"] = utc_now()
                _write_transaction_state(state)
                if audit:
                    audit("transaction_rolled_back", {"transaction_id": txid, "reason": reason})
            except Exception as rollback_exc:
                state["status"] = "rollback_failed"
                state["rollback_error"] = str(rollback_exc)
                state["completed_at"] = utc_now()
                _write_transaction_state(state)
                if audit:
                    audit(
                        "transaction_rollback_failed",
                        {"transaction_id": txid, "reason": reason, "rollback_error": str(rollback_exc)},
                    )
                raise UpdateRuntimeError(
                    f"Actualització fallida i rollback fallit: {reason}; rollback: {rollback_exc}"
                ) from rollback_exc
        elif audit:
            audit("transaction_aborted", {"transaction_id": txid, "reason": reason})
        if isinstance(exc, UpdateRuntimeError):
            raise
        raise UpdateRuntimeError(reason) from exc
    finally:
        handle.close()


def _latest_recovery_point(policy: dict[str, Any]) -> Path:
    root = Path(policy["recovery_point"]["root"])
    if not root.is_dir():
        raise UpdateRuntimeError("No hi ha cap punt de recuperació disponible")
    points = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p / "recovery-point.json").is_file()]
    if not points:
        raise UpdateRuntimeError("No hi ha cap punt de recuperació disponible")
    points.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return points[0]


def manual_rollback(*, audit: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    policy = load_policy()
    handle = _lock()
    try:
        recovery = _latest_recovery_point(policy)
        metadata = load_json(recovery / "recovery-point.json", "el punt de recuperació")
        expected_packages = metadata.get("packages", [])
        package_names = {
            item.get("package") for item in expected_packages if isinstance(item, dict) and isinstance(item.get("package"), str)
        }
        before = {
            "thin_client_running": "xaac-thinclient" in package_names and process_running(r"(^|/)xaac-thinclient([[:space:]]|$)"),
            "agent_active": "xaac-agent" in package_names and unit_exists("xaac-agent.service") and unit_active("xaac-agent.service"),
            "vpn_manager_active": "xaac-thin-client-vpn" in package_names and unit_exists("xaac-vpn-manager.service") and unit_active("xaac-vpn-manager.service"),
        }
        result = _rollback_from_recovery(policy, recovery, before, cause="manual rollback")
        transaction_state = {
            "schema_version": 2,
            "status": "rolled_back_manual",
            "transaction_id": metadata.get("transaction_id"),
            "completed_at": utc_now(),
            "recovery_point": str(recovery),
            "last_error": None,
        }
        _write_transaction_state(transaction_state)
        if audit:
            audit("manual_rollback_completed", {"transaction_id": metadata.get("transaction_id")})
        return result
    finally:
        handle.close()


def restore_latest_configuration(
    *, audit: Callable[[str, dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """Restore only configuration from the newest verified recovery point.

    This is intended for the phase 10.4 recovery environment when package
    versions are healthy but configuration has become unusable. It uses the
    same archive hash and tar-member validation as a full package rollback.
    """
    policy = load_policy()
    handle = _lock()
    try:
        recovery = _latest_recovery_point(policy)
        metadata = load_json(recovery / "recovery-point.json", "el punt de recuperació")
        configuration = metadata.get("configuration")
        if not isinstance(configuration, dict):
            raise UpdateRuntimeError("Punt de recuperació sense configuració")
        _restore_configuration(recovery, configuration)
        state = {
            "schema_version": 2,
            "status": "configuration_restored_manual",
            "transaction_id": metadata.get("transaction_id"),
            "completed_at": utc_now(),
            "recovery_point": str(recovery),
            "members": list(configuration.get("members", [])),
            "last_error": None,
        }
        _write_transaction_state(state)
        if audit:
            audit(
                "manual_configuration_restore_completed",
                {"transaction_id": metadata.get("transaction_id")},
            )
        return state
    finally:
        handle.close()


def recover_interrupted(*, audit: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any] | None:
    """Rollback an update interrupted after package mutation, typically at boot."""
    if not STATE_PATH.is_file():
        return None
    state = load_json(STATE_PATH, "l'estat de transacció")
    if state.get("status") not in {"installing", "validating", "rolling_back"}:
        return None
    recovery_value = state.get("recovery_point")
    if not isinstance(recovery_value, str) or not recovery_value.startswith("/"):
        raise UpdateRuntimeError("Transacció interrompuda sense punt de recuperació vàlid")
    policy = load_policy()
    recovery = Path(recovery_value)
    metadata = load_json(recovery / "recovery-point.json", "el punt de recuperació")
    package_names = {
        item.get("package") for item in metadata.get("packages", []) if isinstance(item, dict)
    }
    before = {
        "thin_client_running": False,
        "agent_active": "xaac-agent" in package_names and unit_exists("xaac-agent.service") and unit_active("xaac-agent.service"),
        "vpn_manager_active": "xaac-thin-client-vpn" in package_names and unit_exists("xaac-vpn-manager.service") and unit_active("xaac-vpn-manager.service"),
    }
    handle = _lock()
    try:
        result = _rollback_from_recovery(policy, recovery, before, cause="interrupted transaction recovery")
        state["status"] = "rolled_back_after_interruption"
        state["completed_at"] = utc_now()
        state["rollback"] = result
        _write_transaction_state(state)
        if audit:
            audit("interrupted_transaction_recovered", {"transaction_id": state.get("transaction_id")})
        return result
    finally:
        handle.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="xaac-update-runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("recover-interrupted")
    args = parser.parse_args(argv)
    try:
        result = recover_interrupted()
    except UpdateRuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
