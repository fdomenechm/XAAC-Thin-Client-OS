# Fase 8.3 — Configuració centralitzada de RustDesk

Aquesta fase incorpora una configuració declarativa i transaccional per a **XAAC Remote Support**.

## Abast

`config/rustdesk-central.yaml` defineix:

- servidor ID i servidor relay;
- API de suport exclusivament HTTPS;
- clau pública i requisit de xifratge;
- proxy de sistema, deshabilitat o manual;
- excepcions de proxy;
- polítiques gestionades;
- canal d'actualització controlat per XAAC;
- rutes d'estat actiu, staging i backup.

Els dominis `.invalid` i la clau de substitució del perfil distribuït són valors deliberadament no operatius. Una imatge real ha de proporcionar endpoints i clau pública corporatius abans de desplegar-se.

## Aplicació

```bash
xaac-os-build configure-rustdesk-central
```

Per validar sense modificar el rootfs:

```bash
xaac-os-build configure-rustdesk-central --dry-run
```

Per restaurar l'última configuració anterior:

```bash
xaac-os-build rollback-rustdesk-central
```

L'aplicació escriu primer en staging, conserva la configuració activa anterior i reemplaça el fitxer actiu de forma atòmica. Els fitxers sensibles utilitzen permisos `0640` i es rebutgen objectius que siguen enllaços simbòlics.

## Límits de la fase

Aquesta fase no crea ni activa cap servei systemd. L'usuari, el servei, les dependències, el reinici, el sandboxing i l'estat corresponen a la fase 8.4.
