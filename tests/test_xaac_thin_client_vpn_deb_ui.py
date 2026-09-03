from pathlib import Path
import subprocess
import tempfile
import yaml


def test_embedded_vpn_deb_contains_password_peek_control(project_root: Path) -> None:
    profile = yaml.safe_load(
        (project_root / "config/xaac-thin-client-vpn-package.yaml").read_text(encoding="utf-8")
    )
    artifact = project_root / profile["package"]["artifact"]

    with tempfile.TemporaryDirectory() as temp_dir:
        subprocess.run(["dpkg-deb", "-x", str(artifact), temp_dir], check=True)
        main_window = (
            Path(temp_dir)
            / "usr/lib/python3/dist-packages/xaac_thin_client_vpn/ui/main_window.py"
        )
        source = main_window.read_text(encoding="utf-8")

    assert "Gtk.PasswordEntry()" in source
    assert "set_show_peek_icon(True)" in source
    assert 'set_property("placeholder-text", placeholder)' in source
