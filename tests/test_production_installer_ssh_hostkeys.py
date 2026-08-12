from pathlib import Path


def _production_builder_source() -> str:
    return Path("src/xaac_thin_client_os/production_builder.py").read_text(encoding="utf-8")


def test_installer_regenerates_ssh_host_keys_after_identity_sanitisation():
    source = _production_builder_source()
    remove = source.index(
        'rm -f "$mount_root/var/lib/dbus/machine-id" "$mount_root"/etc/ssh/ssh_host_*'
    )
    generate = source.index('chroot "$mount_root" ssh-keygen -A', remove)
    marker = source.index('touch "$mount_root/var/lib/xaac/first-boot.pending"', generate)
    assert remove < generate < marker


def test_installer_validates_generated_openssh_host_keys():
    source = _production_builder_source()
    generate = source.index('chroot "$mount_root" ssh-keygen -A')
    tail = source[generate:generate + 1800]
    assert 'ssh_host_ed25519_key' in tail
    assert 'ssh_host_ed25519_key.pub' in tail
    assert 'chroot "$mount_root" /usr/sbin/sshd -t' in tail


def test_installer_enables_ssh_only_after_keys_exist():
    source = _production_builder_source()
    generate = source.index('chroot "$mount_root" ssh-keygen -A')
    enable = source.index('chroot "$mount_root" systemctl enable ssh.service', generate)
    assert generate < enable
