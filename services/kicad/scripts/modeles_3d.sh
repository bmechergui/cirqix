#!/bin/sh
# Remplit le volume Docker `cirqix-3dmodels` avec les bibliothèques de modèles
# 3D de KiCad dont nos empreintes ont besoin (STEP, ~1,3 Go), depuis le dépôt
# officiel kicad-packages3D, en clone partiel (sparse) — le dépôt entier pèse
# plusieurs Go et le PPA 10.0 ne fournit pas `kicad-packages3d`.
#
# Le volume est monté dans le service sur /usr/share/kicad/3dmodels
# (KICAD10_3DMODEL_DIR) : `kicad-cli pcb export glb` y trouve alors les
# composants, et le viewer 3D les affiche. Sans lui, la carte sort nue.
#
# Usage (WSL) :  sh services/kicad/scripts/modeles_3d.sh
# Rejouable : le contenu précédent est remplacé.
set -eu

VOLUME="${CIRQIX_3D_VOLUME:-cirqix-3dmodels}"
LIBS="Capacitor_SMD Resistor_SMD LED_SMD Connector_PinHeader_2.54mm Package_TO_SOT_SMD \
Package_QFP Package_SO Package_LGA Capacitor_THT Resistor_THT LED_THT Diode_SMD Diode_THT \
Package_DIP Package_DFN_QFN Package_TO_SOT_THT Crystal Inductor_SMD Button_Switch_SMD \
Button_Switch_THT Connector_USB Connector_JST Connector_PinSocket_2.54mm Potentiometer_THT Package_BGA"

DIRS=""
for l in $LIBS; do DIRS="$DIRS $l.3dshapes"; done

docker volume create "$VOLUME" >/dev/null
# ⚠️ Pas `alpine/git` : son git ne connait pas `sparse-checkout` (< 2.25) —
# mesure le 2026-09-14, « The most similar commands are show, push ». L image
# du service (Ubuntu noble, git 2.43) convient.
docker run --rm -u root -v "$VOLUME:/models" --entrypoint sh cirqix-kicad:latest -c "
  set -e
  cd /models && rm -rf src ./*.3dshapes
  git clone --depth 1 --filter=blob:none --sparse https://gitlab.com/kicad/libraries/kicad-packages3D.git /models/src
  cd /models/src && git sparse-checkout set $DIRS
  mv /models/src/*.3dshapes /models/ && rm -rf /models/src
  echo \"bibliotheques : \$(ls /models | wc -l)\" ; du -sh /models
"
echo "volume $VOLUME pret — recreer le conteneur cirqix-kicad avec -v $VOLUME:/usr/share/kicad/3dmodels:ro"
