"""Escalader les couches quand cela n apporte rien coute des minutes pour rien.

⚠️ Mesure du 2026-08-27, ESP32 du banc, meme board place :

    palier 2 couches    89 s   ->  80 %
    palier 4 couches    72 s   ->  80 %
    palier 6 couches   421 s   ->  40 %     <- le plus de temps, le pire score
    palier 8 couches   126 s   ->  73 %

Douze minutes de routage pour finir sur le resultat du palier 2, que l on
avait deja apres 89 secondes.

⚠️ On avait d abord cru a un palier AFFAME : `_remaining_budget_s` rend le temps
RESTANT, donc les paliers tardifs recoivent moins. La structure le dit, mais les
durees mesurees le refutent — le palier 6 a recu cinq fois le temps du palier 2.
Ajouter des couches rend la recherche de Freerouting plus DURE, pas plus facile.
Lire le code ne suffisait pas ; il fallait lire l horloge.

⚠️ On garde toujours le MEILLEUR palier, jamais le dernier : l arret anticipe
ne change que le nombre d essais, pas le resultat rendu.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestRegle:
    def test_un_tirage_sans_gain_est_tolere(self):
        # Un tirage plat peut preceder un tirage utile : on ne coupe pas au
        # premier essai infructueux.
        assert R._escalade_epuisee(1) is False

    def test_l_escalade_finit_par_s_arreter(self):
        assert R._escalade_epuisee(R._TOLERANCE_SANS_GAIN + 1) is True

    def test_un_palier_qui_ameliore_remet_le_compteur_a_zero(self):
        assert R._escalade_epuisee(0) is False

    def test_la_tolerance_est_nommee_et_bornee(self):
        """⚠️ Ce test exigeait `1 <= tolerance <= 2`.

        Il datait d avant les TIRAGES PAR PALIER (2026-08-28) : le compteur ne
        comptait alors que des paliers, un par palier. Il compte desormais des
        TIRAGES, et deux tirages malchanceux au meme palier couperaient
        l escalade avant d avoir essaye le palier suivant.

        La borne suit donc le nombre de tirages — deux paliers entiers a plat —
        et reste bornee : chaque tirage inutile coute de une a quinze minutes.
        """
        assert R._TOLERANCE_SANS_GAIN == 2 * R._TIRAGES_ROUTAGE_PAR_PALIER
        assert R._TOLERANCE_SANS_GAIN <= 12


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_consulte_la_regle(self):
        corps = self.SOURCE[self.SOURCE.index("essais = _paliers_avec_tirages("):]
        # ⚠️ Fenetre supprimee : la boucle des paliers s est allongee (bonus a
        # portee, derniere chance, protection des pistes, regle par net). Une
        # garde calee sur une longueur mesure la mise en page, pas le cablage.
        assert "_escalade_epuisee(" in corps

    def test_le_meilleur_reste_rendu(self):
        # L arret anticipe ne doit pas transformer « on garde le meilleur » en
        # « on garde le dernier ».
        corps = self.SOURCE[self.SOURCE.index("essais = _paliers_avec_tirages("):]
        assert "return meilleur" in corps
