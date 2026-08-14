# Bloc 7.7 — Release canònica i ISO consolidada

La fase 7.7 tanca la integració de XAAC Thin Client Agent. No introdueix noves responsabilitats funcionals: converteix els contracts validats en 7.1–7.6 en un procés de release que no es pot completar amb un artefacte de prova.

## Paquet Agent canònic

XAAC Agent `1.0.0-7` ha de construir-se amb `dpkg-buildpackage -us -uc -b`. La construcció Debian usa `/usr/bin/python3.13` i `python3-pytest` de `Build-Depends`; no usa `.venv`, `pip` ni PyPI. El constructor de l'Agent emet el `.deb` i una provenança `xaac-block7-release-provenance/v1` amb versió, arquitectura, SHA-256, `SOURCE_DATE_EPOCH` i hash de `debian/release.json`.

## Gate de producció

`./scripts/validate-block7-release.sh` comprova que l'artefacte integrat i la seua provenança coincideixen amb `config/xaac-agent-package.yaml` i exigeix explícitament `build_method=dpkg-buildpackage` i `build_command=dpkg-buildpackage -us -uc -b`.

Aquest gate s'executa tant des de `build-production-iso.sh` com des del `production_builder`. Per tant, un `.deb` reconstruït amb `dpkg-deb` per facilitar proves locals no pot arribar a una ISO de producció.

## Flux únic de tancament

En un host Debian 13 amb accés als repositoris:

```sh
cd xaac-thin-client-os
./scripts/create-venv.sh
./scripts/install-build-dependencies.sh
./scripts/finalize-block7-release.sh /ruta/al/xaac-agent
```

`finalize-block7-release.sh`:

1. construeix canònicament XAAC Agent des d'una còpia de font neta;
2. copia només el `.deb` final i la provenança al directori `packages/`;
3. actualitza la versió/artefacte/SHA-256 del perfil;
4. executa els gates de release i integració Bloc 7;
5. executa les suites completes de l'Agent i de l'OS;
6. llança exactament una construcció `build-production-iso.sh --clean`.

La prova final sobre Dell Wyse 3040 continua sent una prova de maquinari i, per tant, no pot substituir-se per tests de contenidor o CI.
