#!/bin/sh
# Depose, pour CHAQUE carte, le board a chaque etape de la chaine de routage —
# plan coule, GND lie, routage, repose des vias, plans recoules, couture.
#
# Demande de l utilisateur le 2026-09-01 : pouvoir OUVRIR chaque etape dans
# KiCad et juger sur piece.
#
#   docker exec cirqix-banc sh /app/scripts/etapes_par_carte.sh [carte...]
#
# Les boards atterrissent dans /tmp/ex/<carte>/output/etapes/.
set -e
CARTES="${*:-nucleo-f401 stm32-30 stm32-60 stm32-100}"
cp /app/scripts/banc_exemples.py /tmp/banc.py
for c in $CARTES; do
    [ -d "/tmp/ex/$c" ] || { echo "(carte inconnue : $c)"; continue; }
    rm -rf /tmp/une && mkdir -p /tmp/une && cp -r "/tmp/ex/$c" /tmp/une/
    D="/tmp/ex/$c/output/etapes"
    rm -rf "$D" && mkdir -p "$D"
    echo "=== $c — etapes dans $D"
    cd /app && CIRQIX_DUMP_ETAPES="$D" python3 -u /tmp/banc.py /tmp/une \
        --placement-fige > "/tmp/etapes_$c.log" 2>&1 || true
    cp "/tmp/une/$c/output/final.kicad_pcb" "$D/99_final.kicad_pcb" 2>/dev/null || true
    ls -1 "$D" | sed 's/^/    /'
done
