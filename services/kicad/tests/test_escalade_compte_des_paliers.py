"""L'escalade s'arrête après deux PALIERS sans gain — pas après N tirages.

⚠️ Mesuré sur `nucleo-f401`, campagne de production du 2026-09-23 :

    palier 2 : 96 %                                  gain (premier board)
    palier 4 : 98 %  98 %  figé  figé  96 %          GAIN  (96 -> 98)
    palier 6 : 96 %  figé  96 %                      pas de gain
    « escalade arrêtée avant 8 couches — 7 palier(s) consécutif(s) sans gain »

Le journal dit « 7 paliers » : c'étaient 7 TIRAGES. La règle écrite est « arrêt
après deux paliers entiers sans gain » ; le code comptait les tirages, avec une
tolérance de `2 × 3 = 6`. Le palier 4 avait PROGRESSÉ — mais ses deux tirages
bonus (accordés parce que 98 % est « à portée de 100 % ») et ses deux tirages
figés ont rempli le compteur. Un seul palier plat, et **8 couches n'ont jamais
été essayées**.

Les tirages bonus, faits pour AIDER, consommaient donc le budget d'arrêt et
fermaient la porte au palier suivant. C'est l'inverse de la règle de
l'utilisateur (2026-09-24) : « si tu n'atteins pas 100 %, tu dois escalader le
nombre de couches ».

## Pourquoi on comptait des tirages

La garde précédente l'explique : un compteur naïf, incrémenté à CHAQUE tirage
d'un palier, coupait l'escalade après deux tirages malchanceux au même palier.
On avait donc multiplié la tolérance par le nombre de tirages — ce qui ne
tenait plus dès que les bonus et les tirages figés ont allongé les paliers.

Compter les PALIERS règle les deux : un palier n'est « sans gain » que si AUCUN
de ses tirages n'a amélioré le meilleur board. Des tirages malchanceux au sein
d'un palier ne comptent pas un par un.

⚠️ Le résultat rendu ne change jamais : `route_auto` garde le MEILLEUR board,
jamais le dernier. Seul le nombre de paliers essayés peut augmenter — et le
plafond de couches du plan, comme le budget de temps, restent maîtres.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _code_de(fonction) -> str:
    """Source sans commentaires : une garde ne s'ancre jamais sur sa propre
    documentation (piège inscrit le 2026-09-08)."""
    return "\n".join(l.split("#")[0] for l in inspect.getsource(fonction).splitlines())


def _rejouer(paliers: list) -> tuple:
    """Rejoue une suite de paliers — chacun = liste de « le tirage a-t-il
    amélioré le meilleur ? » — avec la règle de production.

    Rend (paliers effectivement essayés, raison de l'arrêt)."""
    sans_gain, essayes = 0, []
    for i, tirages in enumerate(paliers):
        if i > 0 and R._escalade_epuisee(sans_gain):
            return essayes, "arret"
        essayes.append(i)
        sans_gain = R._paliers_sans_gain_apres(sans_gain, any(tirages))
    return essayes, "epuise"


class TestLaRegle:
    def test_un_palier_sans_gain_ne_suffit_pas_a_arreter(self):
        assert R._escalade_epuisee(1) is False

    def test_deux_paliers_sans_gain_arretent(self):
        assert R._escalade_epuisee(2) is True

    def test_un_palier_qui_progresse_remet_le_compte_a_zero(self):
        assert R._paliers_sans_gain_apres(1, True) == 0
        assert R._paliers_sans_gain_apres(0, True) == 0

    def test_un_palier_plat_incremente_d_UN_quel_que_soit_son_nombre_de_tirages(self):
        """Le cœur du correctif : un palier compte UNE fois."""
        assert R._paliers_sans_gain_apres(0, False) == 1
        assert R._paliers_sans_gain_apres(1, False) == 2


class TestLeCasNucleo:
    """La séquence réelle de `nucleo-f401` du 2026-09-23."""

    SEQUENCE = [
        [True],                                 # palier 2 : premier board, 96 %
        [True, False, False, False, False],     # palier 4 : 98 %, puis 4 tirages plats
        [False, False, False],                  # palier 6 : rien
        [False, False, False],                  # palier 8 : ce qu'on n'essayait jamais
    ]

    def test_le_palier_8_est_desormais_essaye(self):
        essayes, _ = _rejouer(self.SEQUENCE)
        assert 3 in essayes, (
            "le palier 4 a PROGRESSE (96 -> 98) : un seul palier plat ensuite, "
            "l escalade doit aller jusqu au palier 8"
        )

    def test_les_tirages_bonus_ne_ferment_plus_la_porte(self):
        """Un palier qui progresse, même suivi de nombreux tirages plats, ne
        compte pas comme un palier sans gain."""
        essayes, _ = _rejouer([[True], [True] + [False] * 20, [False], [False]])
        assert essayes == [0, 1, 2, 3]


class TestLaProtectionContreLEscaladeInutile:
    """⚠️ La raison pour laquelle l'arrêt existe : sur l'ESP32 du banc
    (2026-08-27), 2 -> 80 %, 4 -> 80 %, 6 -> 40 %, 8 -> 73 %. Douze minutes
    pour finir sur le résultat du palier 2. L'arrêt doit continuer à jouer."""

    def test_deux_paliers_plats_arretent_encore(self):
        essayes, raison = _rejouer([[True], [False, False, False], [False, False, False], [True]])
        assert raison == "arret"
        assert essayes == [0, 1, 2]


class TestLeCABLAGE:
    def test_route_auto_compte_les_paliers(self):
        code = _code_de(R.route_auto)
        assert "_paliers_sans_gain_apres(" in code, (
            "le compteur doit etre mis a jour PAR PALIER, via la regle nommee")

    def test_le_compte_est_mis_a_jour_a_la_sortie_du_palier(self):
        """Avant de fixer le nouveau palier courant — sinon on compterait le
        palier qu'on vient d'ouvrir, pas celui qu'on quitte."""
        code = _code_de(R.route_auto)
        i_maj = code.find("_paliers_sans_gain_apres(")
        i_entree = code.find("palier_courant, meilleur_du_palier = palier, 0")
        assert i_maj != -1 and i_entree != -1
        assert i_maj < i_entree

    def test_une_amelioration_marque_le_palier(self):
        code = _code_de(R.route_auto)
        assert "gain_au_palier = True" in code
