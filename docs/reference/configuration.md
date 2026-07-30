# Referència de configuració

## Ubicacions

- `config/*.yaml`: polítiques i constructors.
- `config/systemd/`, `config/network/`, `config/ssh/`, `config/nftables/`: recursos específics.
- `profiles/common/` i `profiles/wyse3040/`: valors heretables per maquinari.
- `templates/`: fitxers renderitzats dins del rootfs.
- `hooks/`: extensions opcionals en punts controlats del procés.

## Regles

1. Les rutes han de romandre dins del projecte o del rootfs autoritzat.
2. Els camps obligatoris es validen abans de modificar el sistema.
3. Les llistes ordenades i els manifests han de ser deterministes.
4. Els secrets no formen part de YAML versionat.
5. Els canvis de l'esquema exigeixen proves i actualització documental.
