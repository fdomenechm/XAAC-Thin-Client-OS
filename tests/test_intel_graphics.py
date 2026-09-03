from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.intel_graphics import (Connector, GraphicsInventory, IntelGraphicsConfigurator, IntelGraphicsDetector, IntelGraphicsError, compare_graphics, create_graphics_configuration_plan, load_graphics_profile, write_graphics_report)

def write(root: Path, rel: str, value: str) -> None:
    path=root/rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value, encoding="utf-8")

def inventory(**changes: object) -> GraphicsInventory:
    values={"modules":("i915",),"pci_vendors":("8086",),"connectors":(Connector("card0-DP-1","connected",("1920x1080",),True),Connector("card0-DP-2","disconnected",(),False)),"kernel_command_line":("quiet",)}; values.update(changes); return GraphicsInventory(**values)  # type: ignore[arg-type]

def test_detects_i915_intel_gpu_and_connectors(tmp_path: Path) -> None:
    write(tmp_path,"proc/modules","i915 1 0 - Live 0x0\n"); write(tmp_path,"proc/cmdline","quiet splash\n")
    write(tmp_path,"sys/bus/pci/devices/0000:00:02.0/vendor","0x8086\n"); write(tmp_path,"sys/bus/pci/devices/0000:00:02.0/class","0x030000\n")
    write(tmp_path,"sys/class/drm/card0-DP-1/status","connected\n"); write(tmp_path,"sys/class/drm/card0-DP-1/modes","1920x1080\n1280x720\n"); write(tmp_path,"sys/class/drm/card0-DP-1/enabled","enabled\n")
    result=IntelGraphicsDetector(root=tmp_path).detect(); assert result.modules==("i915",); assert result.pci_vendors==("8086",); assert result.connectors[0].enabled

def test_missing_sysfs_is_safe(tmp_path: Path) -> None:
    assert IntelGraphicsDetector(root=tmp_path).detect()==GraphicsInventory((),(),(),())

def test_profile_loads(project_root: Path) -> None:
    assert load_graphics_profile(project_root/"config/graphics.yaml")["profile"]=="wyse3040"

@pytest.mark.parametrize("content",["[]\n","schema_version: 99\n","schema_version: 1\nprofile: x\n"])
def test_invalid_profile_rejected(tmp_path: Path, content: str) -> None:
    path=tmp_path/"graphics.yaml"; path.write_text(content,encoding="utf-8")
    with pytest.raises(IntelGraphicsError): load_graphics_profile(path)

def test_compatible_graphics_passes(project_root: Path) -> None:
    report=compare_graphics(inventory(),load_graphics_profile(project_root/"config/graphics.yaml")); assert report.compatible; assert all(c.status=="pass" for c in report.checks)

@pytest.mark.parametrize("changed,failed",[(dict(modules=()),"driver"),(dict(pci_vendors=()),"intel-gpu"),(dict(kernel_command_line=("nomodeset",)),"kernel-parameters"),(dict(connectors=()),"connectors"),(dict(connectors=(Connector("card0-DP-1","connected",("800x600",),True),Connector("card0-DP-2","disconnected",(),False))),"display-mode")])
def test_incompatible_conditions(project_root: Path, changed: dict[str,object], failed: str) -> None:
    report=compare_graphics(inventory(**changed),load_graphics_profile(project_root/"config/graphics.yaml")); assert not report.compatible; assert next(c for c in report.checks if c.name==failed).status=="fail"

def test_headless_boot_is_accepted(project_root: Path) -> None:
    report=compare_graphics(inventory(connectors=(Connector("card0-DP-1","disconnected",(),False),Connector("card0-DP-2","disconnected",(),False))),load_graphics_profile(project_root/"config/graphics.yaml")); assert report.compatible

def test_configuration_plan_and_execution(tmp_path: Path, project_root: Path) -> None:
    plan=create_graphics_configuration_plan(tmp_path/"build/rootfs",project_root/"config/graphics.yaml"); assert plan.firmware_packages==("firmware-intel-graphics",)
    assert IntelGraphicsConfigurator().execute(plan,dry_run=True)==(); written=IntelGraphicsConfigurator().execute(plan); assert len(written)==2; assert "i915" in written[0].read_text(encoding="utf-8")

def test_unsafe_rootfs_rejected(project_root: Path) -> None:
    with pytest.raises(IntelGraphicsError,match="Rootfs insegur"): create_graphics_configuration_plan(Path("/"),project_root/"config/graphics.yaml")

def test_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    plan=create_graphics_configuration_plan(tmp_path/"build/rootfs",project_root/"config/graphics.yaml"); target=plan.rootfs/"etc/modules-load.d/xaac-intel-graphics.conf"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/"other")
    with pytest.raises(IntelGraphicsError,match="enllaç simbòlic"): IntelGraphicsConfigurator().execute(plan)

def test_report_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report=compare_graphics(inventory(),load_graphics_profile(project_root/"config/graphics.yaml")); destination=tmp_path/"reports/graphics.json"; write_graphics_report(report,destination); assert json.loads(destination.read_text())["compatible"] is True; assert not destination.with_suffix(".json.tmp").exists()
