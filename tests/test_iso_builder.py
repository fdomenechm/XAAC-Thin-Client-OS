import json
from pathlib import Path
import pytest

from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.iso_builder import IsoBuilder, IsoBuilderError, create_iso_build_plan, load_iso_builder

ROOT = Path(__file__).parents[1]


def copied_config(tmp_path, old, new):
    path = tmp_path / "iso-builder.yaml"
    path.write_text((ROOT / "config/iso-builder.yaml").read_text().replace(old, new))
    return path


def test_loads_hybrid_iso_policy():
    profile = load_iso_builder(ROOT / "config/iso-builder.yaml")
    assert profile["image"]["uefi"] is True
    assert profile["image"]["bios_compatibility"] is True


def test_manifest_is_stable():
    manifest = create_iso_build_plan(ROOT, ROOT / "config/iso-builder.yaml").manifest()
    assert manifest == {"schema_version": 1, "image_id": "xaac-production-iso-1", "format": "iso-hybrid", "architecture": "amd64", "hardware_profile": "wyse3040", "uefi": True, "installer": True, "diagnostics_live": True, "hash_algorithm": "sha256", "signature_required": True}


def test_prepares_iso_assets(tmp_path):
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    config = project / "config/iso-builder.yaml"
    config.write_text((ROOT / "config/iso-builder.yaml").read_text())
    plan = create_iso_build_plan(project, config)
    paths = IsoBuilder().prepare(plan)
    grub = project / ".build/iso/staging/boot/grub/grub.cfg"
    assert "Install XAAC Thin Client OS" in grub.read_text()
    assert "diagnostics (read-only)" in grub.read_text()
    assert json.loads(plan.output("manifest").read_text())["uefi"] is True
    script = plan.output("build_script").read_text()
    assert "grub-mkrescue" in script and "xorriso" in script
    assert "sha256sum" in script and "gpg --batch" in script
    assert plan.output("build_script").stat().st_mode & 0o777 == 0o750
    assert len(paths) == 6


def test_idempotent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    config = project / "iso.yaml"
    config.write_text((ROOT / "config/iso-builder.yaml").read_text())
    plan = create_iso_build_plan(project, config)
    builder = IsoBuilder()
    builder.prepare(plan)
    before = [plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes()]
    builder.prepare(plan)
    assert before == [plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes()]


def test_dry_run_does_not_write(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    config = project / "iso.yaml"
    config.write_text((ROOT / "config/iso-builder.yaml").read_text())
    paths = IsoBuilder().prepare(create_iso_build_plan(project, config), dry_run=True)
    assert len(paths) == 6 and not any(path.exists() for path in paths)


def test_rejects_iso_without_uefi(tmp_path):
    with pytest.raises(IsoBuilderError, match="UEFI"):
        load_iso_builder(copied_config(tmp_path, "uefi: true", "uefi: false"))


def test_rejects_unsigned_iso(tmp_path):
    with pytest.raises(IsoBuilderError, match="signada"):
        load_iso_builder(copied_config(tmp_path, "require_signature: true", "require_signature: false"))


def test_rejects_writable_live_mode(tmp_path):
    with pytest.raises(IsoBuilderError, match="persistir"):
        load_iso_builder(copied_config(tmp_path, "persistent_changes: false", "persistent_changes: true"))


def test_rejects_unsafe_output(tmp_path):
    with pytest.raises(IsoBuilderError, match="Ruta"):
        load_iso_builder(copied_config(tmp_path, ".build/iso/staging", "../outside"))


def test_rejects_symlink_staging(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    config = project / "iso.yaml"
    config.write_text((ROOT / "config/iso-builder.yaml").read_text())
    staging = project / ".build/iso/staging"
    staging.parent.mkdir(parents=True)
    staging.symlink_to(tmp_path / "outside")
    with pytest.raises(IsoBuilderError, match="enllaç simbòlic"):
        IsoBuilder().prepare(create_iso_build_plan(project, config))


def test_checksum(tmp_path):
    artifact = tmp_path / "artifact.iso"
    artifact.write_bytes(b"xaac")
    assert IsoBuilder.checksum(artifact) == "14d2368e939f2aa2514ace5f6b0b67fb209d09855d72997d3e687fd19a2aaa26"


def test_cli(tmp_path):
    assert build_parser().parse_args(["build-iso", "--dry-run"]).command == "build-iso"
    (tmp_path / "config").mkdir()
    (tmp_path / "config/iso-builder.yaml").write_text((ROOT / "config/iso-builder.yaml").read_text())
    assert main(["--root", str(tmp_path), "build-iso", "--dry-run"]) == 0
