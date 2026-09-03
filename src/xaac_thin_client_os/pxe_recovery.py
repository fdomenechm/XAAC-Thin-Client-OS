"""Authorised PXE and remote recovery configuration for phase 11.8."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml


class PxeRecoveryError(RuntimeError):
    """Raised when PXE recovery policy is incomplete or unsafe."""


_REQUIRED_OUTPUTS = {"policy", "state", "ipxe_script", "service", "runner", "network"}


def _path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise PxeRecoveryError(f"Ruta insegura en {field}")
    return value


def _https_url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PxeRecoveryError(f"URL invàlida en {field}")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PxeRecoveryError(f"URL HTTPS insegura en {field}")
    return value


def load_pxe_recovery(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PxeRecoveryError(f"No s'ha pogut carregar la política PXE: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise PxeRecoveryError("Política PXE invàlida")
    if raw.get("hardware_profile") != "wyse3040":
        raise PxeRecoveryError("Perfil de maquinari PXE no suportat")

    network = raw.get("network_boot")
    if not isinstance(network, dict) or network.get("protocol") != "https" or network.get("pxe_loader") != "ipxe":
        raise PxeRecoveryError("Arrencada de xarxa PXE invàlida")
    if network.get("require_wired_network") is not True or network.get("allow_plain_http") is not False:
        raise PxeRecoveryError("Arrencada de xarxa PXE insegura")
    timeout = network.get("dhcp_timeout_seconds")
    if not isinstance(timeout, int) or not 5 <= timeout <= 300:
        raise PxeRecoveryError("Temps DHCP PXE invàlid")
    for key in ("image_url", "kernel_url", "initramfs_url"):
        network[key] = _https_url(network.get(key), f"network_boot.{key}")

    trust = raw.get("trust")
    if not isinstance(trust, dict) or any(trust.get(k) is not True for k in ("require_manifest", "require_signature", "require_tls_validation")):
        raise PxeRecoveryError("Confiança PXE insuficient")
    if trust.get("hash_algorithm") != "sha256":
        raise PxeRecoveryError("Algorisme hash PXE no suportat")
    _path(trust.get("trusted_keyring"), "trust.trusted_keyring")

    auth = raw.get("authorization")
    required_auth = ("require_xms_order", "require_device_identity", "require_nonce", "single_use_order", "fail_closed")
    if not isinstance(auth, dict) or any(auth.get(k) is not True for k in required_auth) or auth.get("order_type") != "recovery.pxe":
        raise PxeRecoveryError("Autorització XMS insuficient")
    age = auth.get("maximum_order_age_seconds")
    if not isinstance(age, int) or not 30 <= age <= 900:
        raise PxeRecoveryError("Caducitat de l'ordre XMS invàlida")

    confirmation = raw.get("confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("require_local_confirmation") is not True or confirmation.get("require_ac_power") is not True:
        raise PxeRecoveryError("Confirmació local PXE insuficient")
    if confirmation.get("confirmation_phrase") != "RECOVER XAAC DEVICE":
        raise PxeRecoveryError("Frase de confirmació PXE invàlida")
    confirm_timeout = confirmation.get("timeout_seconds")
    if not isinstance(confirm_timeout, int) or not 30 <= confirm_timeout <= 300:
        raise PxeRecoveryError("Temps de confirmació PXE invàlid")

    recovery = raw.get("recovery")
    required_recovery = ("transactional", "verify_before_write", "verify_after_write", "preserve_device_identity", "preserve_enrollment", "notify_xms")
    if not isinstance(recovery, dict) or any(recovery.get(k) is not True for k in required_recovery) or recovery.get("allow_downgrade") is not False:
        raise PxeRecoveryError("Recuperació PXE insegura")

    state = raw.get("state")
    if not isinstance(state, dict) or state.get("persistent") is not True or state.get("report_progress") is not True:
        raise PxeRecoveryError("Gestió d'estat PXE insuficient")
    interval = state.get("progress_interval_seconds")
    if not isinstance(interval, int) or not 5 <= interval <= 300:
        raise PxeRecoveryError("Interval d'estat PXE invàlid")
    if state.get("terminal_states") != ["completed", "failed", "cancelled"]:
        raise PxeRecoveryError("Estats terminals PXE invàlids")

    errors = raw.get("errors")
    required_errors = ("persistent_log", "notify_agent", "notify_xms", "disable_on_repeated_failure")
    if not isinstance(errors, dict) or any(errors.get(k) is not True for k in required_errors):
        raise PxeRecoveryError("Gestió d'errors PXE insuficient")
    failures = errors.get("maximum_failures")
    if not isinstance(failures, int) or not 1 <= failures <= 10:
        raise PxeRecoveryError("Límit de fallades PXE invàlid")

    outputs = raw.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != _REQUIRED_OUTPUTS:
        raise PxeRecoveryError("outputs PXE incomplet")
    raw["outputs"] = {key: _path(value, f"outputs.{key}") for key, value in outputs.items()}
    return raw


@dataclass(frozen=True, slots=True)
class PxeRecoveryPlan:
    rootfs: Path
    profile: dict[str, Any]

    def output(self, key: str) -> Path:
        return self.rootfs / self.profile["outputs"][key].lstrip("/")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "recovery_id": self.profile["recovery_id"],
            "transport": "https",
            "loader": "ipxe",
            "xms_order_required": True,
            "local_confirmation_required": True,
            "signature_required": True,
        }


def create_pxe_recovery_plan(rootfs: Path, profile_path: Path) -> PxeRecoveryPlan:
    root = rootfs.resolve()
    if root == Path("/") or root.name != "rootfs":
        raise PxeRecoveryError(f"Rootfs insegur: {root}")
    return PxeRecoveryPlan(root, load_pxe_recovery(profile_path))


class PxeRecoveryInstaller:
    @staticmethod
    def _write(path: Path, content: str, mode: int) -> None:
        if path.is_symlink():
            raise PxeRecoveryError(f"Destinació amb enllaç simbòlic: {path}")
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

    def install(self, plan: PxeRecoveryPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
        order = ("policy", "state", "ipxe_script", "service", "runner", "network")
        targets = tuple(plan.output(key) for key in order)
        if dry_run:
            return targets

        policy = {key: value for key, value in plan.profile.items() if key != "outputs"}
        state = {
            **plan.manifest(),
            "status": "idle",
            "order_id": None,
            "nonce": None,
            "progress": 0,
            "last_error": None,
            "updated_at": None,
        }
        network = plan.profile["network_boot"]
        ipxe = (
            "#!ipxe\n"
            "dhcp || exit\n"
            f"kernel {network['kernel_url']} initrd=initrd.img xaac.recovery=pxe || exit\n"
            f"initrd {network['initramfs_url']} || exit\n"
            "boot || exit\n"
        )
        service = """[Unit]\nDescription=XAAC authorised PXE recovery\nAfter=network-online.target xaac-agent.service\nWants=network-online.target\nConditionACPower=true\n\n[Service]\nType=oneshot\nExecStart=/usr/libexec/xaac-pxe-recovery\nUser=root\nGroup=root\nNoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectSystem=strict\nReadWritePaths=/run/xaac-recovery /var/lib/xaac-recovery /var/log/xaac-recovery /var/lib/xaac /etc/xaac\nPrivateDevices=no\nLockPersonality=yes\nRestrictRealtime=yes\nUMask=0027\n"""
        runner = """#!/bin/sh\nset -eu\nPOLICY=/etc/xaac/recovery/pxe-recovery.json\nSTATE=/var/lib/xaac-recovery/pxe-recovery-state.json\n[ -r \"$POLICY\" ] || exit 2\nexec /usr/bin/xaac-agent recovery pxe --policy \"$POLICY\" --state \"$STATE\" --require-xms-order --require-local-confirmation --verify-tls --verify-signature --transactional\n"""
        network_unit = """[Match]\nName=en*\nType=ether\n\n[Network]\nDHCP=yes\nIPv6AcceptRA=no\nLLMNR=no\nMulticastDNS=no\nDNSOverTLS=opportunistic\n\n[DHCPv4]\nUseDNS=yes\nUseNTP=yes\nSendHostname=no\n"""
        contents = (
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            ipxe,
            service,
            runner,
            network_unit,
        )
        modes = (0o640, 0o640, 0o644, 0o644, 0o750, 0o644)
        for path, content, mode in zip(targets, contents, modes, strict=True):
            self._write(path, content, mode)
        return targets
