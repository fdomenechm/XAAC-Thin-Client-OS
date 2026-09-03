import json
from pathlib import Path

import pytest

from xaac_thin_client_os.terminal_lockdown import (
    TerminalLockdownConfigurator,
    TerminalLockdownError,
    create_terminal_lockdown_plan,
    load_terminal_lockdown_profile,
)


def test_profile_covers_all_phase_5_3_controls(project_root: Path) -> None:
    profile = load_terminal_lockdown_profile(project_root / "config/terminal-lockdown.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["policy"]["enforcement_mode"] == "enforce"
    assert "xterm" in profile["terminal_emulators"]["forbidden_packages"]
    assert "/bin/sh" in profile["command_execution"]["forbidden_shells"]
    assert "file" in profile["uri"]["forbidden_schemes"]
    assert profile["path"]["value"] == "/usr/local/libexec/xaac:/usr/libexec/xaac"


def test_plan_generates_restricted_environment_uri_policy_and_manifest(tmp_path: Path, project_root: Path) -> None:
    plan = create_terminal_lockdown_plan(tmp_path / "build/rootfs", project_root / "config/terminal-lockdown.yaml")
    contents = {str(path): content for path, content, _ in plan.files}
    environment = contents["/etc/xaac/kiosk/environment.d/20-terminal-lockdown.conf"]
    assert "PATH=/usr/local/libexec/xaac:/usr/libexec/xaac" in environment
    assert "TERMINAL=/usr/bin/false" in environment
    assert "/usr/bin:" not in environment
    mimeapps = contents["/etc/xaac/kiosk/mimeapps.list"]
    assert "x-scheme-handler/file=xaac-disabled.desktop;" in mimeapps
    policy = json.loads(contents["/etc/xaac/kiosk/terminal-lockdown.json"])
    assert policy["command_execution"]["forbid_user_desktop_files"] is True
    assert "xterm" in plan.to_manifest()["forbidden_executables"]


def test_execute_is_atomic_idempotent_and_secure(tmp_path: Path, project_root: Path) -> None:
    plan = create_terminal_lockdown_plan(tmp_path / "build/rootfs", project_root / "config/terminal-lockdown.yaml")
    configurator = TerminalLockdownConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    before = [path.read_bytes() for path in first]
    second = configurator.execute(plan)
    assert [path.read_bytes() for path in second] == before
    assert all((path.stat().st_mode & 0o777) == 0o640 for path in first)
    assert not list(plan.rootfs.rglob("*.tmp"))


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/terminal-lockdown.yaml"
    with pytest.raises(TerminalLockdownError, match="Rootfs insegur"):
        create_terminal_lockdown_plan(Path("/"), profile)
    plan = create_terminal_lockdown_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/kiosk/terminal-lockdown.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(TerminalLockdownError, match="enllaç simbòlic"):
        TerminalLockdownConfigurator().execute(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("default_decision: deny", "default_decision: allow", "denegar"),
        ("enforcement_mode: enforce", "enforcement_mode: staged", "aplicable"),
        ("forbid_user_desktop_files: true", "forbid_user_desktop_files: false", "llançadors"),
        ("    - xaac", "    - http", "permés i prohibit"),
        ("disable_generic_openers: true", "disable_generic_openers: false", "genèrics"),
        ("value: /usr/local/libexec/xaac:/usr/libexec/xaac", "value: /usr/bin:/usr/libexec/xaac", "ruta prohibida"),
        ("policy: /etc/xaac/kiosk/terminal-lockdown.json", "policy: ../outside", "Ruta insegura"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str, message: str) -> None:
    source = (project_root / "config/terminal-lockdown.yaml").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / "policy.yaml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(TerminalLockdownError, match=message):
        load_terminal_lockdown_profile(path)


def test_terminal_packages_are_absent_or_explicitly_excluded(project_root: Path) -> None:
    import yaml
    packages = yaml.safe_load((project_root / "config/packages.yaml").read_text(encoding="utf-8"))
    selected = set(packages["base"] + packages["graphical"] + packages["xaac"] + packages["optional"])
    forbidden = set(load_terminal_lockdown_profile(project_root / "config/terminal-lockdown.yaml")["terminal_emulators"]["forbidden_packages"])
    assert selected.isdisjoint(forbidden)
    assert forbidden.issubset(set(packages["exclude"]))


def test_cli_exposes_terminal_lockdown_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-terminal-lockdown", "--dry-run"])
    assert args.command == "configure-terminal-lockdown"
    assert args.dry_run
