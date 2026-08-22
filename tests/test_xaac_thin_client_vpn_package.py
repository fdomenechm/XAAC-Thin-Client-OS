from pathlib import Path
import hashlib
import subprocess
import yaml

def test_vpn_deb_profile_matches_artifact(project_root: Path) -> None:
    profile=yaml.safe_load((project_root/"config/xaac-thin-client-vpn-package.yaml").read_text())
    artifact=project_root/profile["package"]["artifact"]
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==profile["package"]["sha256"]
    out=subprocess.run(["dpkg-deb","-f",str(artifact),"Package","Version","Architecture"],check=True,capture_output=True,text=True).stdout
    assert "xaac-thin-client-vpn" in out
    assert "1.0.0" in out
    assert "all" in out

def test_os_does_not_vendor_vpn_python_sources(project_root: Path) -> None:
    assert not (project_root/"vendor/xaac-thin-client-vpn").exists()
    assert not (project_root/"src/xaac_thin_client_vpn").exists()

def test_session_supervisor_starts_vpn_gate(project_root: Path) -> None:
    assert "client_command: /usr/local/libexec/xaac-vpn-session-gate" in (project_root/"config/session-supervisor.yaml").read_text()

def test_production_builder_verifies_debian_package(project_root: Path) -> None:
    text=(project_root/"src/xaac_thin_client_os/production_builder.py").read_text()
    assert "xaac-thin-client-vpn" in text
    assert "configure-enable-xaac-vpn" in text

def test_vpn_gate_is_posix(project_root: Path) -> None:
    subprocess.run(["/bin/sh","-n",str(project_root/"assets/runtime/xaac-vpn-session-gate")],check=True)
