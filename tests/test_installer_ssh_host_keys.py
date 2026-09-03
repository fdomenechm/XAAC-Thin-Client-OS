from pathlib import Path


def test_installer_generates_unique_ssh_host_keys_on_target():
    source = Path("src/xaac_thin_client_os/installer_builder.py").read_text(encoding="utf-8")
    section = source[source.index("rm -f \"$WORK/root/etc/ssh/ssh_host_\"*"):
                     source.index('mkdir -p "$WORK/root/etc/xaac"')]
    assert 'chroot "$WORK/root" ssh-keygen -A' in section
    assert 'ssh_host_ed25519_key' in section
    assert 'chroot "$WORK/root" /usr/sbin/sshd -t' in section
    assert 'chroot "$WORK/root" systemctl enable ssh.service' in section


def test_installer_removes_inherited_host_keys_before_generation():
    source = Path("src/xaac_thin_client_os/installer_builder.py").read_text(encoding="utf-8")
    remove = source.index('rm -f "$WORK/root/etc/ssh/ssh_host_"*')
    generate = source.index('chroot "$WORK/root" ssh-keygen -A')
    assert remove < generate
