# Fase 9.5 — Hardening del kernel

Aquesta fase aplica una política declarativa de seguretat al kernel de Debian 13.

## Controls

- ASLR amb `kernel.randomize_va_space=2`.
- `ptrace` restringit amb Yama.
- Core dumps deshabilitats per `sysctl` i PAM limits.
- Magic SysRq deshabilitat.
- Restricció de punters, `dmesg`, BPF i `perf`.
- Protecció d'enllaços, FIFO i fitxers regulars.
- Enduriment IPv4 i IPv6.
- Bloqueig de mòduls no necessaris mitjançant `modprobe.d`.

## Artefactes generats

- `/etc/sysctl.d/90-xaac-hardening.conf`
- `/etc/modprobe.d/xaac-hardening.conf`
- `/etc/security/limits.d/90-xaac-core-dumps.conf`
- `/usr/share/xaac/security/kernel-hardening.json`
- `/var/lib/xaac-agent/security/kernel-hardening-state.json`
