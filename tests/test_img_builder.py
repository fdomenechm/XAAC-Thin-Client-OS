import json
from pathlib import Path
import pytest
from xaac_thin_client_os.cli import build_parser, main
from xaac_thin_client_os.img_builder import ImgBuilder, ImgBuilderError, create_img_build_plan, load_img_builder

ROOT = Path(__file__).parents[1]

def copied(tmp_path, old, new):
    p = tmp_path / "img.yaml"
    p.write_text((ROOT / "config/img-builder.yaml").read_text().replace(old, new))
    return p

def test_loads_raw_img_policy():
    p = load_img_builder(ROOT / "config/img-builder.yaml")
    assert p["image"]["partition_table"] == "gpt"
    assert [x["id"] for x in p["partitions"]] == ["efi", "root", "data", "recovery"]

def test_manifest_is_stable():
    m = create_img_build_plan(ROOT, ROOT / "config/img-builder.yaml").manifest()
    assert m["format"] == "raw-img" and m["clone_ready"] is True
    assert m["expand_on_first_boot"] is True

def test_prepare_assets(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    cfg = project / "img.yaml"; cfg.write_text((ROOT / "config/img-builder.yaml").read_text())
    plan = create_img_build_plan(project, cfg)
    assert len(ImgBuilder().prepare(plan)) == 6
    assert json.loads(plan.output("manifest").read_text())["partition_table"] == "gpt"
    script = plan.output("build_script").read_text()
    assert "sgdisk" in script and "losetup --find --show --partscan" in script
    assert "xz -T0 -9" in script and "sha256sum" in script
    first = plan.output("first_boot_script").read_text()
    assert "growpart" in first and "resize2fs" in first
    assert "systemd-machine-id-setup" in first and "ssh-keygen -A" in first
    assert plan.output("build_script").stat().st_mode & 0o777 == 0o750

def test_idempotent(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/img-builder.yaml").read_text())
    plan = create_img_build_plan(project, cfg); b = ImgBuilder(); b.prepare(plan)
    before = (plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes())
    b.prepare(plan); assert before == (plan.output("manifest").read_bytes(), plan.output("build_script").read_bytes())

def test_dry_run(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/img-builder.yaml").read_text())
    paths = ImgBuilder().prepare(create_img_build_plan(project, cfg), dry_run=True)
    assert len(paths) == 6 and not any(p.exists() for p in paths)

def test_rejects_small_image(tmp_path):
    with pytest.raises(ImgBuilderError, match="Mida"):
        load_img_builder(copied(tmp_path, "size_mib: 7680", "size_mib: 2048"))

def test_rejects_non_gpt(tmp_path):
    with pytest.raises(ImgBuilderError, match="GPT"):
        load_img_builder(copied(tmp_path, "partition_table: gpt", "partition_table: mbr"))

def test_rejects_no_expansion(tmp_path):
    with pytest.raises(ImgBuilderError, match="expandir"):
        load_img_builder(copied(tmp_path, "expand_on_first_boot: true", "expand_on_first_boot: false"))

def test_rejects_identity_retention(tmp_path):
    with pytest.raises(ImgBuilderError, match="identitat"):
        load_img_builder(copied(tmp_path, "remove_identity_before_publish: true", "remove_identity_before_publish: false"))

def test_rejects_unsafe_output(tmp_path):
    with pytest.raises(ImgBuilderError, match="Ruta"):
        load_img_builder(copied(tmp_path, ".build/img/manifest.json", "../manifest.json"))

def test_rejects_symlink(tmp_path):
    project = tmp_path / "p"; project.mkdir(); cfg = project / "c"; cfg.write_text((ROOT / "config/img-builder.yaml").read_text())
    target = project / ".build/img/manifest.json"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path / "outside")
    with pytest.raises(ImgBuilderError, match="enllaç"):
        ImgBuilder().prepare(create_img_build_plan(project, cfg))

def test_cli(tmp_path):
    assert build_parser().parse_args(["build-img", "--dry-run"]).command == "build-img"
    (tmp_path / "config").mkdir(); (tmp_path / "config/img-builder.yaml").write_text((ROOT / "config/img-builder.yaml").read_text())
    assert main(["--root", str(tmp_path), "build-img", "--dry-run"]) == 0
