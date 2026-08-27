"""Re-tirer un genetique ne repare pas un echec STRUCTUREL.

⚠️ Chronologie mesuree le 2026-08-27 sur `arduino-uno` (35 composants) :

    19:27:11  tirage 1 demarre
    19:27:33  tirage 1 fini            22 s de travail journalise
    19:37:15  tirage 2 demarre         9 min 42 de SILENCE entre les deux

Le silence est `OptimizationWorkflow`, qui ne journalise qu a la fin. Son
budget est FIXE — 100 generations x 50 individus, plus 1000 iterations de
raffinement — et ne diminue pas pour une carte simple. Dix minutes par tirage.

Or les tirages 1 et 2 finissent tous deux a UN conflit, et sur l ESP32 les
quatre tirages donnent 17, 16, 16 et 22. Quand un boitier domine la carte,
l echec ne varie pas : le genetique optimise une longueur de fil que ce boitier
ecrase, et les passifs sont du bruit dans sa fonction de cout. Re-tirer coute
trente minutes et ne change rien — c est la couronne deterministe qui finit par
etre retenue, en 0,1 s.

⚠️ Sans boitier dominant, le re-tirage garde toute sa valeur : la variance est
alors reelle et le genetique est le bon outil. On ne reduit les tirages que la
ou l on a mesure qu ils n apportent rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


class TestNombreDeTirages:
    def test_un_boitier_dominant_ne_vaut_qu_un_seul_tirage(self):
        assert P._tirages_utiles(dominants=["U1"]) == 1, (
            "re-tirer sur un echec structurel coute 10 min et ne change rien")

    def test_sans_dominant_on_garde_la_pleine_serie(self):
        assert P._tirages_utiles(dominants=[]) == P._MAX_TIRAGES_PLACEMENT, (
            "la variance du genetique est reelle quand aucun boitier n ecrase "
            "la fonction de cout")


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_auto_place_consulte_le_nombre_de_tirages(self):
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):]
        corps = corps[:corps.index("def _couronne_de_secours")]
        assert "_tirages_utiles(" in corps

    def test_la_couronne_reste_le_dernier_mot(self):
        # Reduire les tirages ne doit pas retirer le repli deterministe : c est
        # lui qui rend le board propre sur ces cartes-la.
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):]
        corps = corps[:corps.index("def _couronne_de_secours")]
        assert "_couronne_de_secours(" in corps
