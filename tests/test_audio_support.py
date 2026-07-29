from __future__ import annotations
import json
from pathlib import Path
import pytest
from xaac_thin_client_os.audio_support import (
    AudioConfigurator, AudioDetector, AudioDevice, AudioInventory, AudioSupportError,
    compare_audio, create_audio_configuration_plan, load_audio_profile, write_audio_report,
)

def write(root: Path, rel: str, value: str) -> None:
    path=root/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(value,encoding="utf-8")

def inventory(**changes: object) -> AudioInventory:
    values={"alsa_available":True,"loaded_modules":("snd_hda_intel",),"devices":(AudioDevice(0,"HDMI","HDA Intel HDMI",("hdmi",),()),AudioDevice(1,"PCH","HDA Intel PCH",("analog",),("microphone",))),"pipewire_available":True}
    values.update(changes); return AudioInventory(**values)  # type: ignore[arg-type]

def test_detector_reads_cards_and_modules(tmp_path: Path) -> None:
    write(tmp_path,"proc/asound/cards"," 0 [HDMI ]: HDA-Intel - HDA Intel HDMI\n 1 [PCH ]: HDA-Intel - HDA Intel PCH\n")
    write(tmp_path,"proc/modules","snd_hda_intel 1 0 - Live 0x0\n")
    write(tmp_path,"usr/bin/pipewire","")
    result=AudioDetector(root=tmp_path).detect(); assert result.alsa_available; assert len(result.devices)==2; assert "hdmi" in result.devices[0].outputs; assert result.pipewire_available

def test_detector_missing_files_is_safe(tmp_path: Path) -> None:
    result=AudioDetector(root=tmp_path).detect(); assert not result.alsa_available; assert result.devices==()

def test_profile_loads(project_root: Path) -> None:
    assert load_audio_profile(project_root/"config/audio.yaml")["profile"]=="wyse3040"

@pytest.mark.parametrize("content",["[]\n","schema_version: 2\n","schema_version: 1\nprofile: x\n"])
def test_invalid_profile_rejected(tmp_path: Path, content: str) -> None:
    path=tmp_path/"audio.yaml"; path.write_text(content,encoding="utf-8")
    with pytest.raises(AudioSupportError): load_audio_profile(path)

def test_compatible_audio_passes(project_root: Path) -> None:
    report=compare_audio(inventory(),load_audio_profile(project_root/"config/audio.yaml")); assert report.compatible

def test_missing_alsa_fails(project_root: Path) -> None:
    assert not compare_audio(inventory(alsa_available=False,loaded_modules=(),devices=()),load_audio_profile(project_root/"config/audio.yaml")).compatible

def test_missing_hdmi_fails(project_root: Path) -> None:
    assert not compare_audio(inventory(devices=(AudioDevice(0,"PCH","Analog",("analog",),("microphone",)),)),load_audio_profile(project_root/"config/audio.yaml")).compatible

def test_optional_analog_and_microphone_warn(project_root: Path) -> None:
    report=compare_audio(inventory(devices=(AudioDevice(0,"HDMI","HDMI",("hdmi",),()),)),load_audio_profile(project_root/"config/audio.yaml")); assert report.compatible; assert any(c.status=="warning" for c in report.checks)

def test_missing_pipewire_warns(project_root: Path) -> None:
    report=compare_audio(inventory(pipewire_available=False),load_audio_profile(project_root/"config/audio.yaml")); assert report.compatible; assert next(c for c in report.checks if c.name=="pipewire").status=="warning"

def test_plan_and_execution(tmp_path: Path, project_root: Path) -> None:
    plan=create_audio_configuration_plan(tmp_path/"build/rootfs",project_root/"config/audio.yaml"); assert "pipewire" in plan.packages; assert AudioConfigurator().execute(plan,dry_run=True)==()
    written=AudioConfigurator().execute(plan); assert len(written)==3; assert "snd_hda_intel" in written[0].read_text()

def test_unsafe_rootfs_rejected(project_root: Path) -> None:
    with pytest.raises(AudioSupportError,match="Rootfs insegur"): create_audio_configuration_plan(Path("/"),project_root/"config/audio.yaml")

def test_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    plan=create_audio_configuration_plan(tmp_path/"build/rootfs",project_root/"config/audio.yaml"); target=plan.rootfs/"etc/xaac/audio.conf"; target.parent.mkdir(parents=True); target.symlink_to(tmp_path/"other")
    with pytest.raises(AudioSupportError,match="enllaç simbòlic"): AudioConfigurator().execute(plan)

def test_report_written_atomically(tmp_path: Path, project_root: Path) -> None:
    report=compare_audio(inventory(),load_audio_profile(project_root/"config/audio.yaml")); dest=tmp_path/"audio.json"; write_audio_report(report,dest); assert json.loads(dest.read_text())["compatible"] is True; assert not dest.with_suffix(".json.tmp").exists()

def test_report_symlink_rejected(tmp_path: Path, project_root: Path) -> None:
    report=compare_audio(inventory(),load_audio_profile(project_root/"config/audio.yaml")); dest=tmp_path/"audio.json"; dest.symlink_to(tmp_path/"other")
    with pytest.raises(AudioSupportError): write_audio_report(report,dest)

def test_cli_parser_accepts_audio_commands(project_root: Path) -> None:
    from xaac_thin_client_os.cli import build_parser
    assert build_parser().parse_args(["--root",str(project_root),"configure-audio","--dry-run"]).command=="configure-audio"

def test_cli_inspect_audio_json(monkeypatch: pytest.MonkeyPatch, project_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from xaac_thin_client_os.cli import main
    monkeypatch.setattr("xaac_thin_client_os.cli.AudioDetector.detect",lambda self:inventory())
    assert main(["--root",str(project_root),"--json","inspect-audio"])==0
    assert json.loads(capsys.readouterr().out)["compatible"] is True
