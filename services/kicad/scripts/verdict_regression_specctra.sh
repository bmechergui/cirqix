#!/bin/sh
# Verdict sur la regression du 2026-09-01 : segfault pcbnew (exit -11) a
# l import de session Specctra, apparu quand l etape ③ a rendu non vide la
# liste des pistes du board remis a `_specctra_roundtrip`.
#
# A tirer DANS le conteneur, des que Docker repond :
#     docker exec cirqix-banc sh /app/scripts/verdict_regression_specctra.sh
#
# Rejoue la SEULE carte qui plante — moins d une minute — et imprime six
# compteurs. Il repond CONTRE les correctifs aussi bien que pour eux :
#   - segfault a 0            -> la regression a disparu
#   - garde integrite a 1+    -> elle NOMME la cause (board ampute par pcbnew)
#   - segfault encore > 0     -> les trois correctifs n etaient que de la
#                                solidite ; chercher dans ImportSpecctraSES
set -e
cp /app/scripts/banc_exemples.py /tmp/banc.py
rm -rf /tmp/une && mkdir -p /tmp/une && cp -r /tmp/ex/esp32-baseline /tmp/une/
cd /app && python3 -u /tmp/banc.py /tmp/une --placement-fige > /tmp/verdict.log 2>&1 || true
echo "=================== VERDICT ==================="
printf 'segfault pcbnew      : '; grep -c 'child exit -11'                /tmp/verdict.log || true
printf 'GND perdu (kct)      : '; grep -c "Net 'GND' not found"           /tmp/verdict.log || true
printf 'garde integrite      : '; grep -c 'a PERDU'                       /tmp/verdict.log || true
printf 'doublons ecartes     : '; grep -c 'doublon(s) de pastille'        /tmp/verdict.log || true
printf 'vias non resolubles  : '; grep -c "n est pas declare dans le DSN" /tmp/verdict.log || true
printf 'sorties rejouees     : '; grep -c 'reprise'                       /tmp/verdict.log || true
echo "--- resultat de la carte (temoin : 100 %, 0 manquant, 0 erreur, 41 s) ---"
grep -E '^esp32|ECHEC' /tmp/verdict.log || echo '(aucune ligne de resultat)'
