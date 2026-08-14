from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "assets/runtime/xaac-vpn-admin"


def load_runtime():
    loader = importlib.machinery.SourceFileLoader("xaac_vpn_admin_runtime", str(RUNTIME))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_runtime_admin_tool_is_python_and_has_expected_commands() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert source.startswith("#!/usr/bin/python3\n")
    assert '"provision"' in source
    assert '"policy"' in source
    assert '"status"' in source
    assert '"remove"' in source
    assert '"disabled", "optional", "required"' in source


def test_p12_password_is_passed_over_stdin_not_command_line() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert '"-passin", "stdin"' in source
    assert "-passin pass:" not in source
    assert "TemporaryDirectory(prefix=\"xaac-vpn-admin-\", dir=\"/run\")" in source


def test_adapt_profile_expands_p12_and_rewrites_subject_to_cn(tmp_path: Path) -> None:
    module = load_runtime()
    source = tmp_path / "client.ovpn"
    output = tmp_path / "adapted.ovpn"
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"

    source.write_text(
        "\n".join(
            [
                "client",
                "dev tun",
                "remote 80.28.116.207 1194 udp",
                "auth-user-pass",
                'static-challenge "Enter OTP token:" 1',
                "pkcs12 VPN_usuaris_xaac_local_tc_proves.p12",
                "remote-cert-tls server",
                (
                    'verify-x509-name "C=ES, ST=Valncia, L=Canals, '
                    'O=Ajuntament de Canals, CN=fw-main.xaac.net" subject'
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    cn = module._adapt_profile(source, output, ca, cert, key)
    adapted = output.read_text(encoding="utf-8")

    assert cn == "fw-main.xaac.net"
    assert "pkcs12 " not in adapted
    assert f"ca {ca}" in adapted
    assert f"cert {cert}" in adapted
    assert f"key {key}" in adapted
    assert 'verify-x509-name "fw-main.xaac.net" name' in adapted
    assert "remote-cert-tls server" in adapted
    assert 'static-challenge "Enter OTP token:" 1' in adapted


def test_adapt_profile_requires_static_challenge(tmp_path: Path) -> None:
    module = load_runtime()
    source = tmp_path / "client.ovpn"
    source.write_text("client\nauth-user-pass\n", encoding="utf-8")

    with pytest.raises(module.VpnAdminError, match="static-challenge"):
        module._adapt_profile(
            source,
            tmp_path / "adapted.ovpn",
            tmp_path / "ca.pem",
            tmp_path / "client.crt",
            tmp_path / "client.key",
        )


def test_policy_update_preserves_other_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_runtime()
    config = tmp_path / "vpn-manager.toml"
    config.write_text(
        '[manager]\npolicy = "optional"\nprofile_name = "XAAC VPN"\n\n'
        '[openvpn3]\nprofile = "XAAC VPN"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)

    module._write_policy("required", config)

    text = config.read_text(encoding="utf-8")
    assert 'policy = "required"' in text
    assert 'profile_name = "XAAC VPN"' in text
    assert '[openvpn3]' in text
    assert module._read_policy(config) == "required"


def test_builder_installs_admin_tool_into_runtime() -> None:
    source = (
        ROOT / "src/xaac_thin_client_os/production_builder.py"
    ).read_text(encoding="utf-8")

    assert 'assets/runtime/xaac-vpn-admin' in source
    assert '/usr/local/sbin/xaac-vpn-admin' in source
    assert 'vpn_admin_target.chmod(0o755)' in source
    assert '"/usr/local/sbin/xaac-vpn-admin --help >/dev/null"' in source


def test_remove_command_disables_policy_by_design() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert '_write_policy("disabled")' in source
    assert "per evitar bloquejos" in source


def test_validate_profile_self_contained_rejects_runtime_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_runtime()

    class Result:
        stdout = f"ca {tmp_path}/ca.pem\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(module, "_run", lambda *_args, **_kwargs: Result())

    with pytest.raises(module.VpnAdminError, match="no és autocontingut"):
        module._validate_profile_self_contained("XAAC VPN CANDIDATE", tmp_path)


def test_swap_candidate_preserves_old_profile_until_candidate_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_runtime()
    calls: list[list[str]] = []

    def fake_paths(name: str) -> list[str]:
        if name == module.PROFILE_NAME:
            return ["/net/openvpn/v3/configuration/old"]
        if name.startswith("XAAC VPN BACKUP"):
            return ["/net/openvpn/v3/configuration/old"]
        return ["/net/openvpn/v3/configuration/candidate"]

    monkeypatch.setattr(module, "_profile_paths", fake_paths)
    monkeypatch.setattr(module, "_validate_imported_profile", lambda _name: None)
    monkeypatch.setattr(
        module,
        "_remove_profiles_named",
        lambda name: calls.append(["remove", name]) or 1,
    )
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, **_kwargs: calls.append(command)
        or type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    module._swap_candidate_profile("XAAC VPN CANDIDATE 1")

    assert any(
        command[:3] == [module.OPENVPN3, "config-manage", "--path"]
        and "--rename" in command
        for command in calls
        if command and command[0] != "remove"
    )
    assert any(
        command[:3] == [module.OPENVPN3, "config-manage", "--config"]
        and "XAAC VPN CANDIDATE 1" in command
        and module.PROFILE_NAME in command
        for command in calls
        if command and command[0] != "remove"
    )
    assert any(command[0] == "remove" and "BACKUP" in command[1] for command in calls)


def test_cli_parser_accepts_documented_admin_workflow() -> None:
    module = load_runtime()
    parser = module.build_parser()

    provision = parser.parse_args(["provision", "client.ovpn", "client.p12"])
    assert provision.command == "provision"
    assert provision.ovpn == Path("client.ovpn")
    assert provision.p12 == Path("client.p12")

    policy = parser.parse_args(["policy", "required"])
    assert policy.command == "policy"
    assert policy.value == "required"
