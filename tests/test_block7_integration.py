from pathlib import Path

from xaac_thin_client_os.block7_integration import (
    rootfs_verification_script,
    validate_packaged_block7_integration,
)

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_block7_contract_is_cross_project_consistent() -> None:
    report = validate_packaged_block7_integration(ROOT)
    assert report.passed is True
    assert set(report.checks) == {
        "package-identity",
        "systemd-agent-boundary",
        "privileged-helper-boundary",
        "enrollment-lifecycle",
        "agent-runtime-configuration",
        "local-contract-cross-check",
        "kiosk-group-boundary",
        "xms-enrollment-contract",
        "vpn-policy-contract",
    }


def test_rootfs_gate_checks_directionality_and_unenrolled_lifecycle() -> None:
    script = rootfs_verification_script("1.0.0-7")
    assert "/var/lib/xaac/thin-client/config /run/xaac/commands" in script
    assert "/var/lib/xaac/thin-client/state|/run/xaac/thin-client/events" in script
    assert "! systemctl is-enabled --quiet xaac-agent.service" in script
    assert "systemctl is-enabled --quiet xaac-privileged-helper.socket" in script
    assert "xaac-kiosk | tr ' '" in script
    assert "grep -Fx xaac-command" in script


def test_validation_script_is_posix_sh_and_machine_readable() -> None:
    script = ROOT / "scripts/validate-block7-integration.sh"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "BASH_SOURCE" not in text
    assert "pipefail" not in text
    completed = __import__("subprocess").run(
        [str(script)], cwd=ROOT, check=True, capture_output=True, text=True
    )
    payload = __import__("json").loads(completed.stdout)
    assert payload["passed"] is True
    assert payload["package_version"] == "1.0.0-7"
