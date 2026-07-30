import json
from pathlib import Path
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.pxe_builder import PxeBuilder, PxeBuilderError, create_pxe_build_plan, load_pxe_builder

ROOT = Path(__file__).parents[1]


def copied(tmp_path, old, new):
    path = tmp_path / "pxe-builder.yaml"
    path.write_text((ROOT / "config/pxe-builder.yaml").read_text().replace(old, new))
    return path


def test_loads_pxe_policy():
    profile = load_pxe_builder(ROOT / "config/pxe-builder.yaml")
    assert profile["package"]["loader"] == "ipxe"
    assert profile["unattended_install"]["enabled"] is True


def test_manifest_is_stable():
    manifest = create_pxe_build_plan(ROOT, ROOT / "config/pxe-builder.yaml").manifest()
    assert manifest["format"] == "pxe-bundle"
    assert manifest["components"] == ["kernel", "initramfs", "rootfs", "ipxe", "unattended-config"]


def test_prepares_pxe_assets(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    cfg = project / "pxe.yaml"; cfg.write_text((ROOT / "config/pxe-builder.yaml").read_text())
    plan = create_pxe_build_plan(project, cfg)
    assert len(PxeBuilder().prepare(plan)) == 6
    assert json.loads(plan.output("manifest").read_text())["unattended_install"] is True
    assert "kernel ${base-url}/vmlinuz" in plan.output("ipxe_script").read_text()
    assert "confirmation-token" in plan.output("ipxe_script").read_text()
    unattended = json.loads(plan.output("unattended_config").read_text())
    assert unattended["target_disk"] == "auto-emmc" and unattended["wipe_target_disk"] is True
    script = plan.output("build_script").read_text()
    assert "rootfs.squashfs" in script and "sha256sum" in script
    assert plan.output("build_script").stat().st_mode & 0o777 == 0o750


def test_idempotent(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/pxe-builder.yaml").read_text())
    plan = create_pxe_build_plan(project, cfg); builder = PxeBuilder(); builder.prepare(plan)
    before = [plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes()]
    builder.prepare(plan)
    assert before == [plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes()]


def test_dry_run(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/pxe-builder.yaml").read_text())
    paths = PxeBuilder().prepare(create_pxe_build_plan(project, cfg), dry_run=True)
    assert len(paths) == 6 and not any(path.exists() for path in paths)


def test_rejects_disabled_unattended(tmp_path):
    with pytest.raises(PxeBuilderError, match="desatesa"):
        load_pxe_builder(copied(tmp_path, "enabled: true", "enabled: false"))


def test_rejects_missing_token(tmp_path):
    with pytest.raises(PxeBuilderError, match="token"):
        load_pxe_builder(copied(tmp_path, "require_confirmation_token: true", "require_confirmation_token: false"))


def test_rejects_no_disk_wipe(tmp_path):
    with pytest.raises(PxeBuilderError, match="esborrat"):
        load_pxe_builder(copied(tmp_path, "wipe_target_disk: true", "wipe_target_disk: false"))


def test_rejects_wrong_profile(tmp_path):
    with pytest.raises(PxeBuilderError, match="Perfil PXE"):
        load_pxe_builder(copied(tmp_path, "hardware_profile: wyse3040", "hardware_profile: generic"))


def test_rejects_unsafe_output(tmp_path):
    with pytest.raises(PxeBuilderError, match="Ruta"):
        load_pxe_builder(copied(tmp_path, ".build/pxe/manifest.json", "../manifest.json"))


def test_rejects_symlink(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/pxe-builder.yaml").read_text())
    target = project / ".build/pxe/manifest.json"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(PxeBuilderError, match="enllaç"):
        PxeBuilder().prepare(create_pxe_build_plan(project, cfg))


def test_cli(tmp_path):
    assert build_parser().parse_args(["build-pxe", "--dry-run"]).command == "build-pxe"
    (tmp_path / "config").mkdir(); (tmp_path / "config/pxe-builder.yaml").write_text((ROOT / "config/pxe-builder.yaml").read_text())
    assert main(["--root", str(tmp_path), "build-pxe", "--dry-run"]) == 0
