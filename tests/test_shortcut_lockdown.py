import json
from pathlib import Path

import pytest

from xaac_thin_client_os.compositor import REMOTE_BOTTOM_CLEARANCE_PIXELS
from xaac_thin_client_os.shortcut_lockdown import (
    ShortcutLockdownConfigurator,
    ShortcutLockdownError,
    create_shortcut_lockdown_plan,
    load_shortcut_lockdown_profile,
)


def test_profile_covers_all_phase_5_2_categories(project_root: Path) -> None:
    profile = load_shortcut_lockdown_profile(project_root / "config/shortcut-lockdown.yaml")
    assert set(profile["categories"]) == {
        "application_switching", "window_closing", "compositor_menu",
        "command_execution", "screenshots", "system",
    }
    assert profile["policy"]["enforcement_mode"] == "enforce"
    assert profile["backends"]["wayland"]["disable_default_keybindings"] is True
    assert "Alt+Tab" in profile["categories"]["application_switching"]
    assert "Print" in profile["categories"]["screenshots"]


def test_plan_disables_compositor_defaults_and_exports_policy(tmp_path: Path, project_root: Path) -> None:
    plan = create_shortcut_lockdown_plan(tmp_path / "build/rootfs", project_root / "config/shortcut-lockdown.yaml")
    contents = {str(path): content for path, content, _ in plan.files}
    assert '<keybind key="A-F4" />' in contents["/etc/xaac/labwc/rc.xml"]
    assert "<default" not in contents["/etc/xaac/labwc/rc.xml"]
    assert 'button="Right" action="Press"' in contents["/etc/xaac/labwc/rc.xml"]
    assert "ShowMenu" not in contents["/etc/xaac/labwc/rc.xml"]
    assert "Reconfigure" not in contents["/etc/xaac/labwc/rc.xml"]
    assert "Exit" not in contents["/etc/xaac/labwc/rc.xml"]
    assert "<decoration>server</decoration>" in contents["/etc/xaac/labwc/rc.xml"]
    assert "<layout>:</layout>" in contents["/etc/xaac/labwc/rc.xml"]
    assert 'serverDecoration="yes"' in contents["/etc/xaac/labwc/rc.xml"]
    assert '<margin bottom=' not in contents["/etc/xaac/labwc/rc.xml"]
    assert 'identifier="org.xaac.thinclient"' in contents["/etc/xaac/labwc/rc.xml"]
    assert '<context name="Client">' in contents["/etc/xaac/labwc/rc.xml"]
    assert '<action name="Focus" />' in contents["/etc/xaac/labwc/rc.xml"]
    assert '<action name="Raise" />' in contents["/etc/xaac/labwc/rc.xml"]
    assert f'name="MoveRelative" x="0" y="-{REMOTE_BOTTOM_CLEARANCE_PIXELS}"' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'name="Maximize" direction="both"' not in contents["/etc/xaac/labwc/rc.xml"]
    assert 'name="AutoPlace" policy="center"' in contents["/etc/xaac/labwc/rc.xml"]
    assert '<windowRule identifier="*xfreerdp*" serverDecoration="no" />' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'identifier="org.xaac.ThinClientDock"' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'fixedPosition="yes"' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'ignoreFocusRequest="yes"' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'name="MoveToEdge" direction="down" snapWindows="no"' in contents["/etc/xaac/labwc/rc.xml"]
    assert 'name="ToggleAlwaysOnTop"' not in contents["/etc/xaac/labwc/rc.xml"]
    openbox = contents["/etc/xaac/openbox/rc.xml"]
    assert "<keyboard />" in openbox
    assert '<fullscreen>yes</fullscreen>' not in openbox
    assert 'class="org.xaac.thinclient"' in openbox
    assert f'<y>-{REMOTE_BOTTOM_CLEARANCE_PIXELS}</y>' in openbox
    assert 'class="org.xaac.ThinClientDock"' in openbox
    assert '<y>-0</y>' in openbox
    assert '<context name="Client">' in openbox
    policy = json.loads(contents["/etc/xaac/kiosk/shortcut-policy.json"])
    assert policy["policy"]["default_decision"] == "deny"
    assert plan.to_manifest()["blocked_count"] >= 15


def test_execute_is_atomic_idempotent_and_secure(tmp_path: Path, project_root: Path) -> None:
    plan = create_shortcut_lockdown_plan(tmp_path / "build/rootfs", project_root / "config/shortcut-lockdown.yaml")
    configurator = ShortcutLockdownConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    before = [path.read_bytes() for path in first]
    second = configurator.execute(plan)
    assert [path.read_bytes() for path in second] == before
    assert (first[-1].stat().st_mode & 0o777) == 0o640
    assert not list(plan.rootfs.rglob("*.tmp"))


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/shortcut-lockdown.yaml"
    with pytest.raises(ShortcutLockdownError, match="Rootfs insegur"):
        create_shortcut_lockdown_plan(Path("/"), profile)
    plan = create_shortcut_lockdown_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/kiosk/shortcut-policy.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(ShortcutLockdownError, match="enllaç simbòlic"):
        ShortcutLockdownConfigurator().execute(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("default_decision: deny", "default_decision: allow", "denegar-se"),
        ("enforcement_mode: enforce", "enforcement_mode: staged", "aplicable"),
        ("disable_default_keybindings: true", "disable_default_keybindings: false", "insegur"),
        ("    - Alt+Tab", "    - Print", "més d'una categoria"),
        ("  - Ctrl+Alt+F12", "  - Alt+Tab", "reservada"),
        ("  policy: /etc/xaac/kiosk/shortcut-policy.json", "  policy: ../outside", "Ruta insegura"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, project_root: Path, old: str, new: str, message: str) -> None:
    source = (project_root / "config/shortcut-lockdown.yaml").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / "policy.yaml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ShortcutLockdownError, match=message):
        load_shortcut_lockdown_profile(path)


def test_cli_exposes_shortcut_command() -> None:
    from xaac_thin_client_os.cli import build_parser
    args = build_parser().parse_args(["configure-shortcut-lockdown", "--dry-run"])
    assert args.command == "configure-shortcut-lockdown"
    assert args.dry_run


def test_kiosk_titlebar_uses_roboto(project_root, tmp_path):
    from xaac_thin_client_os.shortcut_lockdown import create_shortcut_lockdown_plan
    plan = create_shortcut_lockdown_plan(tmp_path / "rootfs", project_root / "config/shortcut-lockdown.yaml")
    rc = next(content for path, content, _mode in plan.files if str(path).endswith("labwc/rc.xml"))
    assert rc.count("<name>Roboto</name>") >= 2
    assert 'place="ActiveWindow"' in rc
    assert 'place="InactiveWindow"' in rc
