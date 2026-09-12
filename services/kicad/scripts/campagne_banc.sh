#!/usr/bin/env bash
# Rejoue les cartes du banc — LA FILE ENTIERE VIT DANS LE CONTENEUR.
#
# ## Pourquoi ce script existe à côté de `regenerer_le_banc.py`
#
# `regenerer_le_banc.py` compare et ne garde que le meilleur — c'est lui qui
# porte la règle. Mais il PILOTE depuis l'hôte, et sur cette machine le système
# tue le processus pilote dès que le conteneur consomme la mémoire :
#
#     2026-09-08   cinq exécutions perdues, quatre pipelines ORPHELINS accumulés
#     2026-09-09   un tirage expiré à 66 minutes, verdict jamais rendu
#
# ⚠️ Et une mise à mort côté Windows ne tue PAS le pipeline côté conteneur : les
# orphelins se disputaient la mémoire et faisaient tuer la suivante — une
# spirale que chaque relance alimentait.
#
# Ici : on COPIE tout d'abord, puis un SEUL processus détaché déroule la file.
# Rien côté hôte n'a besoin de survivre. La comparaison et la livraison se font
# après coup, à froid, par `livrer_campagne.py`.
#
# ## Ce qu'il ne fait PAS
#
# ⚠️ Il n'écrit RIEN dans `examples/`. Un pipeline brut ne compare pas, et
# livrer sans comparer remplacerait un bon board par un moins bon — mesuré le
# 2026-09-08, cinq cartes « dégradées » qui étaient en fait des routages
# tronqués par le temps.
#
# Usage :
#     bash scripts/campagne_banc.sh 2 carte-01-diviseur carte-02-alimentation …
#          ^ nombre de tirages par carte
set -eu

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$RACINE/examples" ] || RACINE=/mnt/c/Users/Mechegui/Desktop/dev/cirqix/services/kicad
TIRAGES="${1:?nombre de tirages attendu}"
shift
CARTES="$*"
: "${CARTES:?cartes attendues}"

FILE=/tmp/campagne-$(date +%s)
LOCAL=$(mktemp -d)

for C in $CARTES; do
  for T in $(seq 1 "$TIRAGES"); do
    mkdir -p "$LOCAL/$C-t$T/input"
    cp "$RACINE/examples/$C/input/schema.json" "$LOCAL/$C-t$T/input/schema.json"
    cp "$RACINE/examples/led-blinker-full-pipeline/run_pipeline.py" "$LOCAL/$C-t$T/"
  done
done

cat > "$LOCAL/derouler.sh" <<'PILOTE'
#!/bin/sh
F="$1"; T="$2"; shift 2
echo "$(date +%H:%M:%S)  campagne : $T tirage(s) x $# carte(s)" >> "$F/campagne.txt"
for C in "$@"; do
  N=1
  while [ "$N" -le "$T" ]; do
    D="$F/$C-t$N"
    echo "$(date +%H:%M:%S)  $C tirage $N  demarre" >> "$F/campagne.txt"
    cd /app && python3 "$D/run_pipeline.py" "$D/output" > "$D/journal.txt" 2>&1
    S=$(grep -a SUMMARY "$D/journal.txt" | tail -1)
    echo "$(date +%H:%M:%S)  $C tirage $N  ${S:-AUCUN SUMMARY}" >> "$F/campagne.txt"
    N=$((N + 1))
  done
done
echo "$(date +%H:%M:%S)  CAMPAGNE TERMINEE" >> "$F/campagne.txt"
PILOTE
chmod +x "$LOCAL/derouler.sh"

docker cp "$LOCAL" "cirqix-kicad:$FILE" >/dev/null
docker exec -u root cirqix-kicad chmod -R 777 "$FILE"

# ⚠️ Partir propre. Un orphelin d'une campagne precedente ferait tuer celle-ci.
docker exec -u root cirqix-kicad sh -c 'pkill -f run_pipeline.py; pkill -f derouler.sh; rm -f /tmp/cirqix-reglages.json' 2>/dev/null || true
sleep 3

docker exec -d cirqix-kicad sh "$FILE/derouler.sh" "$FILE" "$TIRAGES" $CARTES

echo "$FILE"
echo "suivre  : docker exec cirqix-kicad cat $FILE/campagne.txt"
echo "livrer  : python scripts/livrer_campagne.py $FILE"
