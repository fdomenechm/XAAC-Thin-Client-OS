# Release XAAC Thin Client OS 1.0.0

## Estat

La versió del projecte està fixada en **1.0.0**. El codi inclou constructors per
preparar la release candidate i la release estable, però la publicació oficial
requereix executar-los en l'entorn de producció.

## Artefactes previstos

- ISO híbrida d'instal·lació
- IMG comprimida per a escriptura directa
- imatge de recuperació
- paquet PXE
- repositori de paquets Debian
- documentació i manifests
- fitxer global `SHA256SUMS` i signatures separades

## Procés de publicació

1. Congelar la release candidate.
2. Completar proves de codi, imatge, maquinari, rendiment i documentació.
3. Registrar les aprovacions exigides.
4. Construir els artefactes finals en un entorn net.
5. Calcular hashes i signar amb la clau privada autoritzada.
6. Executar la verificació independent dels artefactes.
7. Publicar notes, artefactes i repositori APT.

## Política de versions

- `1.0.x`: correccions compatibles i de seguretat.
- `1.x.0`: funcionalitats compatibles que no trenquen el desplegament existent.
- `2.0.0`: canvis incompatibles d'arquitectura, configuració o operació.

## Suport

La documentació del repositori no fixa una duració contractual de suport. Qualsevol
política temporal o SLA ha de definir-se en el desplegament o contracte corresponent.
