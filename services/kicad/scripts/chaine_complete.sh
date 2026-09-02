#!/bin/sh
# Chaîne COMPLÈTE sur chaque carte : placement NEUF (code corrigé) puis routage.
#
# Contrairement à `etapes_par_carte.sh`, le placement figé est VOLONTAIREMENT
# écarté : on veut mesurer la chaîne telle qu'un utilisateur la reçoit, depuis
# la description du circuit jusqu'au board routé.
#
#   docker exec cirqix-banc sh /app/scripts/chaine_complete.sh [carte...]
#
# ⚠️ Le placement validé est protégé dans Git — `expected/2_placement_valide.kicad_pcb`
# sur chaque carte. Ce script écrase `output/2_placement.kicad_pcb`, ce qui est
# sans danger tant que cette copie existe. Restauration :
#   cp examples/<carte>/expected/2_placement_valide.kicad_pcb \
#      examples/<carte>/output/2_placement.kicad_pcb
set -e
CARTES="${*:-nucleo-f401 stm32-30 stm32-60 stm32-100}"
cp /app/scripts/banc_exemples.py /tmp/banc.py
for c in $CARTES; do
    [ -d "/tmp/ex/$c" ] || { echo "(carte inconnue : $c)"; continue; }
    rm -rf /tmp/une && mkdir -p /tmp/une && cp -r "/tmp/ex/$c" /tmp/une/
    # Retirer le placement conservé FORCE son recalcul par le code corrigé.
    rm -f "/tmp/une/$c/output/2_placement.kicad_pcb"
    D="/tmp/ex/$c/output/etapes"
    rm -rf "$D" && mkdir -p "$D"
    echo "=== $c — placement NEUF + routage"
    cd /app && CIRQIX_DUMP_ETAPES="$D" python3 -u /tmp/banc.py /tmp/une \
        > "/tmp/complet_$c.log" 2>&1 || true
    cp "/tmp/une/$c/output/2_placement.kicad_pcb" "$D/00_placement.kicad_pcb" 2>/dev/null || true
    cp "/tmp/une/$c/output/final.kicad_pcb" "$D/99_final.kicad_pcb" 2>/dev/null || true
    tail -2 "/tmp/complet_$c.log" | sed 's/^/    /'
done
