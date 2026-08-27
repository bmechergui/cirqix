"""On ne route pas un board dont le placement est deja casse.

Mesure du 2026-08-27, ESP32 du banc. `auto_place` rend un placement
STOCHASTIQUE — `OptimizationWorkflow` n a pas de seed fixe. Sur des tirages
successifs du meme board, sans qu une ligne change :

    tirage A : 0 conflit    tirage B : 13 conflits

Le second part quand meme au routage, qui coute 25 minutes, pour produire un
board que le DRC refusera de toute facon.

L asymetrie de cout tranche : le placement coute 2 a 4 minutes, le routage 25.
Re-tirer un placement casse est dix fois moins cher que router un board perdu.

⚠️ Le nombre de tirages est BORNE. Une carte reellement impossible a placer ne
doit pas boucler indefiniment — on livre alors le meilleur obtenu, et
`conflits_restants` le dit.

⚠️ On garde le MEILLEUR, pas le dernier : un tirage tardif peut etre pire que
son predecesseur.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


class TestContrat:
    def test_le_nombre_de_tirages_est_borne(self):
        assert 1 < P._MAX_TIRAGES_PLACEMENT <= 6, (
            "trop peu ne corrige rien, trop bloque le pipeline")


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_auto_place_retire_tant_qu_il_reste_des_conflits(self):
        assert "_MAX_TIRAGES_PLACEMENT" in self.SOURCE
        corps = self.SOURCE[self.SOURCE.index("def auto_place(") :]
        assert "conflits_restants" in corps

    def test_le_meilleur_est_garde_pas_le_dernier(self):
        # Un tirage tardif peut etre pire que son predecesseur.
        corps = self.SOURCE[self.SOURCE.index("def auto_place(") :]
        assert "meilleur" in corps

    def test_un_placement_propre_ne_declenche_aucun_re_tirage(self):
        # Re-tirer sans raison couterait 2 a 4 minutes pour rien.
        corps = self.SOURCE[self.SOURCE.index("def auto_place(") :]
        i = corps.index("_MAX_TIRAGES_PLACEMENT")
        assert "break" in corps[i:i + 2000], "il faut sortir des que c est propre"
