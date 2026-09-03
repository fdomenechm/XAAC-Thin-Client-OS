import json
from pathlib import Path

import pytest

from xaac_thin_client_os.kiosk_restrictions import (
    KioskRestrictionConfigurator,
    KioskRestrictionError,
    create_kiosk_restriction_plan,
    load_kiosk_restriction_profile,
)


def test_profile_defines_all_phase_5_1_surfaces(project_root: Path) -> None:
    profile = load_kiosk_restriction_profile(project_root / "config/kiosk-restrictions.yaml")
    assert profile["policy"]["default_decision"] == "deny"
    assert profile["policy"]["enforcement_mode"] == "staged"
    assert {item for threat in profile["threats"] for item in threat["mitigations"]} == {
        "actions", "shortcuts", "processes", "devices", "sessions"
    }
    assert profile["devices"]["classes"]["storage"] == "deny"
    assert profile["sessions"]["graphical"]["allowed"] == ["xaac-kiosk-wayland"]


def test_plan_separates_effective_policy_and_threat_model(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_restriction_plan(
        tmp_path / "build/rootfs", project_root / "config/kiosk-restrictions.yaml"
    )
    contents = {str(path): json.loads(content) for path, content, _ in plan.files}
    assert "threats" not in contents["/etc/xaac/kiosk/restrictions.json"]
    assert len(contents["/usr/share/doc/xaac-thin-client-os/kiosk-threat-model.json"]["threats"]) == 5
    assert plan.to_manifest()["enforcement"] == "staged"


def test_execute_is_atomic_idempotent_and_preserves_modes(tmp_path: Path, project_root: Path) -> None:
    plan = create_kiosk_restriction_plan(
        tmp_path / "build/rootfs", project_root / "config/kiosk-restrictions.yaml"
    )
    configurator = KioskRestrictionConfigurator()
    assert configurator.execute(plan, dry_run=True) == ()
    first = configurator.execute(plan)
    before = [path.read_bytes() for path in first]
    second = configurator.execute(plan)
    assert [path.read_bytes() for path in second] == before
    assert (first[0].stat().st_mode & 0o777) == 0o640
    assert (first[1].stat().st_mode & 0o777) == 0o644
    assert not list(plan.rootfs.rglob("*.tmp"))


def test_unsafe_root_and_symlink_are_rejected(tmp_path: Path, project_root: Path) -> None:
    profile = project_root / "config/kiosk-restrictions.yaml"
    with pytest.raises(KioskRestrictionError, match="Rootfs insegur"):
        create_kiosk_restriction_plan(Path("/"), profile)
    plan = create_kiosk_restriction_plan(tmp_path / "build/rootfs", profile)
    target = plan.rootfs / "etc/xaac/kiosk/restrictions.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(KioskRestrictionError, match="enllaç simbòlic"):
        KioskRestrictionConfigurator().execute(plan)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("default_decision: deny", "default_decision: allow", "decisió per defecte"),
        ("enforcement_mode: staged", "enforcement_mode: enforce", "staged"),
        ("kiosk_user: xaac-kiosk", "kiosk_user: root", "xaac-kiosk"),
        ("severity: critical", "severity: urgent", "Severitat"),
        ("mitigations: [shortcuts, processes, sessions]", "mitigations: [unknown]", "Mitigació"),
        ("  allowed: []", "  allowed: [Alt+F4]", "simultàniament"),
        ("  maximum_user_processes: 64", "  maximum_user_processes: 2", "processos"),
        ("    storage: deny", "    storage: allow", "emmagatzematge"),
        ("  automount: false", "  automount: true", "automuntatge"),
        ("    switching: false", "    switching: true", "canvi"),
        ("    kiosk_access: false", "    kiosk_access: true", "TTY"),
        ("    kiosk_ssh: false", "    kiosk_ssh: true", "remotes"),
        ("  policy: /etc/xaac/kiosk/restrictions.json", "  policy: ../outside", "Ruta insegura"),
    ],
)
def test_invalid_profiles_are_rejected(
    tmp_path: Path, project_root: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "policy.yaml"
    source = (project_root / "config/kiosk-restrictions.yaml").read_text(encoding="utf-8")
    assert old in source
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(KioskRestrictionError, match=message):
        load_kiosk_restriction_profile(path)


def test_cli_exposes_command() -> None:
    from xaac_thin_client_os.cli import build_parser

    args = build_parser().parse_args(["configure-kiosk-restrictions", "--dry-run"])
    assert args.command == "configure-kiosk-restrictions"
    assert args.dry_run
