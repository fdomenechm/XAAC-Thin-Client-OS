"""Cross-project validation for XAAC Agent integration (Block 7.6).

The checks in this module intentionally inspect the *packaged* Agent artifact,
not a neighbouring source checkout.  This makes the OS build validate exactly
what will be installed in the root filesystem.
"""
from __future__ import annotations

import configparser
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xaac_thin_client_os.xaac_agent_package import (
    XaacAgentPackageError,
    inspect_agent_package,
    load_xaac_agent_profile,
)


class Block7IntegrationError(RuntimeError):
    """Raised when the packaged Agent and XAAC OS contract disagree."""


@dataclass(frozen=True, slots=True)
class Block7IntegrationReport:
    package_version: str
    package_sha256: str
    checks: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": "xaac-block7-integration-report/v1",
            "passed": self.passed,
            "package_version": self.package_version,
            "package_sha256": self.package_sha256,
            "checks": list(self.checks),
        }


def _fail(code: str) -> None:
    raise Block7IntegrationError(code)


def _yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise Block7IntegrationError(f"configuration_unreadable:{path.name}") from exc
    if not isinstance(raw, dict):
        _fail(f"configuration_invalid:{path.name}")
    return raw


def _unit_directives(path: Path, section: str) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Block7IntegrationError(f"unit_unreadable:{path.name}") from exc
    current = ""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if current == section and line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _agent_ini(path: Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except (OSError, configparser.Error) as exc:
        raise Block7IntegrationError("agent_configuration_invalid") from exc
    if "agent" not in parser:
        _fail("agent_configuration_missing_section")
    return parser["agent"]


def validate_packaged_block7_integration(project_root: Path) -> Block7IntegrationReport:
    """Validate the complete OS/Agent boundary using the embedded .deb."""
    root = project_root.resolve()
    try:
        profile = load_xaac_agent_profile(root / "config/xaac-agent-package.yaml")
    except XaacAgentPackageError as exc:
        raise Block7IntegrationError(f"agent_profile_invalid:{exc}") from exc
    artifact = root / str(profile["package"]["artifact"])
    try:
        metadata = inspect_agent_package(artifact)
    except XaacAgentPackageError as exc:
        raise Block7IntegrationError(f"agent_package_invalid:{exc}") from exc
    if metadata.version != profile["package"]["version"]:
        _fail("agent_package_version_mismatch")
    if metadata.sha256 != profile["package"]["sha256"]:
        _fail("agent_package_sha256_mismatch")

    checks: list[str] = ["package-identity"]
    with tempfile.TemporaryDirectory(prefix="xaac-block7-") as temporary:
        temp = Path(temporary)
        data_root = temp / "rootfs"
        control_root = temp / "control"
        data_root.mkdir()
        control_root.mkdir()
        try:
            subprocess.run(("dpkg-deb", "-x", str(artifact), str(data_root)), check=True, capture_output=True, text=True)
            subprocess.run(("dpkg-deb", "-e", str(artifact), str(control_root)), check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Block7IntegrationError("agent_package_extract_failed") from exc

        service = _unit_directives(data_root / "usr/lib/systemd/system/xaac-agent.service", "Service")
        expected_writable = {
            "/run/xaac-agent/runtime",
            "/var/lib/xaac-agent",
            "/var/cache/xaac-agent",
            "/var/log/xaac-agent",
            "/var/lib/xaac/thin-client/config",
            "/run/xaac/commands",
        }
        writable = set(service.get("ReadWritePaths", "").split())
        if service.get("ProtectSystem") != "strict" or writable != expected_writable:
            _fail("agent_systemd_writable_boundary_invalid")
        if {"/var/lib/xaac/thin-client/state", "/run/xaac/thin-client/events"} & writable:
            _fail("agent_systemd_directionality_broken")
        if service.get("User") != "xaac-agent" or service.get("Group") != "xaac-agent":
            _fail("agent_service_identity_invalid")
        if set(service.get("SupplementaryGroups", "").split()) != {"xaac-command", "xaac-ipc"}:
            _fail("agent_service_groups_invalid")
        checks.append("systemd-agent-boundary")

        helper = _unit_directives(data_root / "usr/lib/systemd/system/xaac-privileged-helper.service", "Service")
        if helper.get("ProtectSystem") != "strict" or helper.get("ReadWritePaths") != "/etc/xaac":
            _fail("privileged_helper_write_boundary_invalid")
        if helper.get("CapabilityBoundingSet") != "CAP_SYS_BOOT" or "CAP_SYS_ADMIN" in (data_root / "usr/lib/systemd/system/xaac-privileged-helper.service").read_text(encoding="utf-8"):
            _fail("privileged_helper_capabilities_invalid")
        checks.append("privileged-helper-boundary")

        postinst = (control_root / "postinst").read_text(encoding="utf-8")
        if "systemctl enable xaac-privileged-helper.socket" not in postinst:
            _fail("helper_socket_not_enabled")
        if "systemctl disable xaac-agent.service" not in postinst:
            _fail("unenrolled_agent_not_disabled")
        if "systemctl enable xaac-privileged-helper.socket xaac-agent.service" in postinst:
            _fail("agent_enabled_unconditionally")
        checks.append("enrollment-lifecycle")

        runtime_root = data_root / "opt/xaac-agent/runtime"
        runtime_python = runtime_root / "bin/python3.13"
        runtime_agent = runtime_root / "bin/xaac-agent"
        runtime_admin = runtime_root / "bin/xaac-agent-admin"
        for runtime_path in (runtime_python, runtime_agent, runtime_admin):
            try:
                mode = runtime_path.stat().st_mode
            except OSError:
                _fail("agent_private_runtime_missing")
            if not runtime_path.is_file() or mode & 0o111 == 0:
                _fail("agent_private_runtime_missing")
        if (runtime_root / "runtime").exists():
            _fail("agent_private_runtime_nested")

        admin_link = data_root / "usr/sbin/xaac-agent-admin"
        if not admin_link.is_symlink() or admin_link.readlink().as_posix() != "/opt/xaac-agent/runtime/bin/xaac-agent-admin":
            _fail("agent_admin_link_invalid")
        agent = _agent_ini(data_root / "etc/xaac-agent/agent.ini")
        if agent.get("enabled", "").strip().lower() != "false":
            _fail("agent_default_activation_invalid")
        if agent.get("thin_client_user") != "xaac-kiosk" or agent.get("thin_client_shared_group") != "xaac-ipc":
            _fail("agent_local_principals_invalid")
        allowed_operations = {item.strip() for item in agent.get("thin_client_allowed_operations", "").split(",") if item.strip()}
        if allowed_operations != {"read-state", "read-events", "collect-diagnostics"}:
            _fail("agent_local_operations_invalid")
        checks.append("agent-runtime-configuration")

        local = _yaml(root / "config/local-integration.yaml")
        directories = local.get("directories")
        principals = local.get("principals")
        formats = local.get("contract", {}).get("formats") if isinstance(local.get("contract"), dict) else None
        if not isinstance(directories, dict) or not isinstance(principals, dict) or not isinstance(formats, dict):
            _fail("local_contract_invalid")
        if principals != {"agent_user": "xaac-agent", "thin_client_user": "xaac-kiosk", "shared_group": "xaac-ipc"}:
            _fail("local_contract_principals_mismatch")
        path_pairs = {
            "runtime": "thin_client_runtime_directory",
            "state": "thin_client_state_directory",
            "configuration": "thin_client_config_directory",
            "commands": "thin_client_command_directory",
        }
        for local_key, agent_key in path_pairs.items():
            item = directories.get(local_key)
            if not isinstance(item, dict) or item.get("path") != agent.get(agent_key):
                _fail(f"local_contract_path_mismatch:{local_key}")
        if formats.get("state") != "xaac-state/v2" or formats.get("event") != "xaac-local-event/v1":
            _fail("local_contract_format_mismatch")
        if formats.get("configuration") != "xaac-configuration/v1" or formats.get("command") != "xaac-local-command/v1":
            _fail("local_contract_format_mismatch")
        limits = local.get("limits")
        if not isinstance(limits, dict) or int(agent.get("thin_client_state_max_bytes", "0")) != limits.get("state_max_bytes"):
            _fail("local_contract_state_limit_mismatch")
        if int(agent.get("thin_client_runtime_max_events", "0")) != limits.get("max_events"):
            _fail("local_contract_event_limit_mismatch")
        checks.append("local-contract-cross-check")

        kiosk = _yaml(root / "config/kiosk-user.yaml")
        account = kiosk.get("user")
        if not isinstance(account, dict):
            _fail("kiosk_account_invalid")
        supplementary = set(account.get("supplementary_groups", []))
        if "xaac-ipc" not in supplementary or "xaac-command" in supplementary:
            _fail("kiosk_group_boundary_invalid")
        checks.append("kiosk-group-boundary")

        xms = _yaml(root / "config/xms-enrollment.yaml")
        enrollment = xms.get("enrollment")
        if not isinstance(enrollment, dict) or enrollment.get("format") != "xaac-agent-admin" or enrollment.get("version") != 1:
            _fail("xms_enrollment_contract_invalid")
        if enrollment.get("bootstrap_token_one_time") is not True or enrollment.get("explicit_reenrollment") is not True:
            _fail("xms_enrollment_security_invalid")
        checks.append("xms-enrollment-contract")

        vpn_admin = (root / "assets/runtime/xaac-vpn-admin").read_text(encoding="utf-8")
        for marker in ("xaac-vpn-status/v1", 'VALID_POLICIES = ("disabled", "optional", "required")', '"--json"'):
            if marker not in vpn_admin:
                _fail("vpn_admin_contract_invalid")
        checks.append("vpn-policy-contract")

    return Block7IntegrationReport(metadata.version, metadata.sha256, tuple(checks))


def rootfs_verification_script(expected_debian_version: str) -> str:
    """Return the final in-chroot Block 7 verification gate."""
    version = expected_debian_version.replace("'", "")
    return f"""
set -eu

test \"$(dpkg-query -W -f='${{Status}}' xaac-agent)\" = 'install ok installed'
test \"$(dpkg-query -W -f='${{Version}}' xaac-agent)\" = '{version}'
test \"$(dpkg-query -W -f='${{Status}}' xaac-thinclient)\" = 'install ok installed'
test \"$(dpkg-query -W -f='${{Version}}' xaac-thinclient)\" = '1.0.0'

getent passwd xaac-agent >/dev/null
getent passwd xaac-kiosk >/dev/null
getent group xaac-command >/dev/null
getent group xaac-ipc >/dev/null
id -nG xaac-agent | tr ' ' '\\n' | grep -Fx xaac-command >/dev/null
id -nG xaac-agent | tr ' ' '\\n' | grep -Fx xaac-ipc >/dev/null
id -nG xaac-kiosk | tr ' ' '\\n' | grep -Fx xaac-ipc >/dev/null
! id -nG xaac-kiosk | tr ' ' '\\n' | grep -Fx xaac-command >/dev/null

grep -Fx 'ProtectSystem=strict' /usr/lib/systemd/system/xaac-agent.service >/dev/null
grep -Fx 'ReadWritePaths=/run/xaac-agent/runtime /var/lib/xaac-agent /var/cache/xaac-agent /var/log/xaac-agent /var/lib/xaac/thin-client/config /run/xaac/commands' /usr/lib/systemd/system/xaac-agent.service >/dev/null
! grep -F 'ReadWritePaths=' /usr/lib/systemd/system/xaac-agent.service | grep -E '/var/lib/xaac/thin-client/state|/run/xaac/thin-client/events' >/dev/null
grep -Fx 'ReadWritePaths=/etc/xaac' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null
grep -Fx 'CapabilityBoundingSet=CAP_SYS_BOOT' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null
! grep -F 'CAP_SYS_ADMIN' /usr/lib/systemd/system/xaac-privileged-helper.service >/dev/null

systemctl is-enabled --quiet xaac-privileged-helper.socket
! systemctl is-enabled --quiet xaac-agent.service
test -x /opt/xaac-agent/runtime/bin/python3.13
test -x /opt/xaac-agent/runtime/bin/xaac-agent
test -x /opt/xaac-agent/runtime/bin/xaac-agent-admin
! test -e /opt/xaac-agent/runtime/runtime
test -x /usr/sbin/xaac-agent-admin
test \"$(readlink /usr/sbin/xaac-agent-admin)\" = '/opt/xaac-agent/runtime/bin/xaac-agent-admin'
grep -Eq '^[[:space:]]*enabled[[:space:]]*=[[:space:]]*false[[:space:]]*$' /etc/xaac-agent/agent.ini
! test -e /etc/xaac-agent/enrollment.token

for spec in \\
  '/var/lib/xaac/thin-client/state xaac-kiosk:xaac-ipc:2750' \\
  '/var/lib/xaac/thin-client/config xaac-agent:xaac-ipc:2750' \\
  '/run/xaac/thin-client/events xaac-kiosk:xaac-ipc:2750' \\
  '/run/xaac/commands xaac-agent:xaac-ipc:2750'
do
  path=${{spec%% *}}
  expected=${{spec#* }}
  test \"$(stat -c '%U:%G:%a' \"$path\")\" = \"$expected\"
done

test -f /etc/xaac/local-integration-manifest.json
grep -F 'xaac-local-integration/v1' /etc/xaac/local-integration-manifest.json >/dev/null
grep -F 'xaac-state/v2' /etc/xaac/local-integration-manifest.json >/dev/null
test -f /etc/xaac/xms-enrollment-manifest.json
grep -F 'xaac-agent-admin/v1' /etc/xaac/xms-enrollment-manifest.json >/dev/null
! grep -Ei 'credential[^s]|password|otp|private.key' /etc/xaac/xms-enrollment-manifest.json >/dev/null
test -x /usr/local/sbin/xaac-vpn-admin
grep -F 'xaac-vpn-status/v1' /usr/local/sbin/xaac-vpn-admin >/dev/null
""".strip()
