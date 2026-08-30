"""Un palier a 99 % n est pas un palier qui a echoue.

⚠️ Mesure du 2026-08-30, `stm32-100` (100 composants, 208 x 156 mm). Deux runs
sur le MEME board place, meme code, seule la chance de Freerouting differe :

    run gagnant   2 couches : fige, 99 %, puis 100 %              1810 s
    run perdant   2 couches : fige, 96 %, 99 %
                  puis 4 couches : 87 %, puis 0 %, budget mort    4290 s

Le run gagnant a gagne au TROISIEME tirage du MEME palier. Le run perdant avait
le meme 99 % en main, a quitte le palier, est redescendu a 87 % en payant une
couche de plus, puis a tue son budget.

    monter d une couche a coute 2400 s pour DEGRADER de 12 points
    un tirage de plus au meme palier coutait 600 s et a produit le seul 100 %

C est le symetrique exact de `_SEUIL_REDRAW_PCT` (80), qui refuse de RE-TIRER
un palier hors d atteinte. Il manquait son jumeau : refuser de QUITTER un
palier a portee.

⚠️ Le seuil ne doit pas etre choisi au doigt. La preuve porte sur 99 % ; on
l etend a 97 %, soit deux nets sur les 79 de cette carte. Rien de mesure ne
soutient plus bas — entre 80 et 97 le comportement reste celui d avant :
on finit les tirages du palier, puis on escalade.

⚠️ Une couche de plus n est pas neutre : une carte 4 couches coute plus cher a
fabriquer qu une carte 2 couches. On ne la vend que sur preuve.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestSeuil:
    def test_un_palier_a_99_pourcent_est_a_portee(self):
        # Le cas mesure : 99 % -> 100 % au tirage suivant, meme palier.
        assert R._tirages_bonus(99) > 0

    def test_un_palier_a_100_pourcent_ne_demande_rien(self):
        # ⚠️ 100 % sans erreur sort AVANT par la sortie anticipee ; s il arrive
        # ici c est qu il restait des erreurs DRC, et un tirage de plus est
        # exactement le levier. Ne pas le priver du bonus.
        assert R._tirages_bonus(100) > 0

    def test_un_palier_moyen_ne_recoit_aucun_bonus(self):
        # Entre 80 et 97 : comportement d avant, on finit puis on escalade.
        assert R._tirages_bonus(90) == 0
        assert R._tirages_bonus(96) == 0

    def test_un_palier_hors_d_atteinte_ne_recoit_aucun_bonus(self):
        # Il est deja abandonne par `_tirages_epuises_au_palier`.
        assert R._tirages_bonus(70) == 0
        assert R._tirages_bonus(48) == 0

    def test_un_zero_ne_recoit_aucun_bonus(self):
        # « 0 % (aucun moteur) » est une PANNE, pas un verdict de routage.
        assert R._tirages_bonus(0) == 0

    def test_le_seuil_est_au_dessus_du_seuil_d_abandon(self):
        # Les deux regles doivent etre disjointes : un palier ne peut pas etre
        # a la fois hors d atteinte et a portee.
        assert R._SEUIL_PALIER_A_PORTEE > R._SEUIL_REDRAW_PCT

    def test_le_bonus_reste_borne(self):
        # Sans borne, une carte qui plafonne a 99 % re-tirerait sans fin et ne
        # verrait jamais 4 couches — on recreerait le defaut du 2026-08-29,
        # a l autre extremite.
        assert 0 < R._TIRAGES_BONUS_A_PORTEE <= R._TIRAGES_ROUTAGE_PAR_PALIER


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
        encoding="utf-8")

    def _boucle(self) -> str:
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        return self.SOURCE[i:i + 4000]

    def test_le_bonus_est_APPELE_dans_la_boucle(self):
        """⚠️ Une regle juste jamais invoquee est indistinguable d une regle
        absente. C est ce qui a masque des semaines que le Geometre ne tournait
        jamais en production."""
        assert "_tirages_bonus(" in self._boucle()

    def test_le_bonus_s_applique_au_CHANGEMENT_de_palier(self):
        # Le bonus n a de sens qu au moment ou l on s appreterait a quitter le
        # palier : ailleurs il ne ferait qu allonger la file.
        corps = self._boucle()
        assert corps.index("palier != palier_courant") < corps.index(
            "_tirages_bonus(")

    def test_la_sortie_anticipee_survit(self):
        # 100 % ET zero erreur doit toujours rendre la main immediatement.
        assert ("res.routed_percent >= 100 and not res.skipped and erreurs == 0"
                in self.SOURCE)
