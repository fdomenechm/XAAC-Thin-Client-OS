# Bloc 7.7 — Release canònica i ISO consolidada

La fase 7.7 tanca la integració de XAAC Thin Client Agent sense acoblar els dos projectes. XAAC Agent produeix el seu paquet Debian; XAAC Thin Client OS consumeix eixe artefacte i, una vegada incorporat, pot construir-se sense conéixer ni necessitar la ruta del codi font de l'Agent.

## Paquet Agent canònic

XAAC Agent `1.0.0-7` ha de construir-se amb `dpkg-buildpackage -us -uc -b`. La construcció Debian usa `/usr/bin/python3.13` i `python3-pytest` de `Build-Depends`; no usa `.venv`, `pip` ni PyPI. El constructor de l'Agent emet el `.deb` i una provenança `xaac-block7-release-provenance/v1` amb versió, arquitectura, SHA-256, `SOURCE_DATE_EPOCH` i hash de `debian/release.json`.

En el projecte Agent:

```sh
./scripts/install-build-dependencies.sh
./scripts/build-debian-release.sh ../artifacts
```

## Importació a XAAC Thin Client OS

L'OS no construeix XAAC Agent. Rep el `.deb` canònic com qualsevol altre artefacte versionat:

```sh
./scripts/create-venv.sh
./scripts/import-xaac-agent-package.sh ../artifacts/xaac-agent_1.0.0-7_amd64.deb
```

`import-xaac-agent-package.sh`:

1. rep la ruta del `.deb`, **no** la ruta del codi font de l'Agent;
2. exigeix al costat `xaac-agent_...deb.provenance.json`;
3. valida `Package`, versió, arquitectura, SHA-256 i provenança canònica;
4. rebutja `dpkg-deb-fallback` i qualsevol artefacte no canònic;
5. substitueix transaccionalment l'artefacte anterior;
6. actualitza `config/xaac-agent-package.yaml` amb versió, ruta i SHA-256;
7. executa de nou els gates de release i integració.

Si qualsevol comprovació falla, restaura el paquet i el perfil anteriors.

## Gate de producció

`./scripts/validate-block7-release.sh` comprova que l'artefacte ja integrat i la seua provenança coincideixen amb `config/xaac-agent-package.yaml` i exigeix explícitament `build_method=dpkg-buildpackage` i `build_command=dpkg-buildpackage -us -uc -b`.

Aquest gate s'executa tant des de `build-production-iso.sh` com des del `production_builder`. Per tant, un `.deb` reconstruït amb `dpkg-deb` per facilitar proves locals no pot arribar a una ISO de producció.

## Construcció habitual de l'OS

Una vegada incorporat un `.deb` canònic, XAAC Thin Client OS és autocontingut:

```sh
sudo ./scripts/install-build-dependencies.sh
./scripts/build-production-iso.sh --clean
```

No s'ha de passar cap ruta del projecte Agent i la construcció de la ISO no reconstrueix l'Agent. Una nova versió/revisió de l'Agent només requereix repetir el procés separat de build + importació.

La prova final sobre Dell Wyse 3040 continua sent una prova de maquinari i, per tant, no pot substituir-se per tests de contenidor o CI.
