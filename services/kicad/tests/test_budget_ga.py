"""Budget du GA reduit + best-of-2 : le prix mesure est la VARIANCE.

Mesure du 2026-08-29, board STM32 17 composants, QUATRE tirages de chaque,
placement complet (Architecte, Geometre, Inspecteur, halo, snap) :

                 temps                       fil (hors GND)
    actuel   266  311  399  392       365  390  407  386     342 s / 387 mm
    reduit   101   91  172  128       359  441  372  565     123 s / 434 mm

⚠️ LE COUT N EST PAS DANS LA MOYENNE, IL EST DANS LA DISPERSION. L etendue
passe de 42 mm a 206 mm, avec un tirage a 565 mm — +46 %. La moyenne ne bouge
que de 12 % et elle MENT : ce n est pas « un peu plus de fil partout », c est
« parfois un placement absurde ».

J ai annonce « aucun cout de qualite » apres UN tirage, puis « qualite
identique » apres trois. Les deux etaient faux.

Le remede n est pas de remonter le budget — trois tirages reduits sur quatre
atteignent la bonne region, donc le budget SUFFIT ; c est le depart qui varie.
Le remede est le FILTRE : deux tirages reduits coutent moins qu un complet
(246 s contre 342) et on garde le meilleur.

⚠️ Encore faut-il pouvoir departager : les huit placements ont 0 conflit
ERROR. Un critere fonde sur les seuls conflits ne tranche rien et garderait le
565 mm par ordre d arrivee. D ou le second critere, la longueur de fil.
"""
from __future__ import annotations

from tools.placement import (_WF_GENERATIONS, _WF_POPULATION, _WF_ITERATIONS,
                             _TIRAGES_MINIMUM, _placement_meilleur)


class TestBudget:
    def test_le_budget_est_reduit(self):
        assert _WF_GENERATIONS <= 40
        assert _WF_POPULATION <= 30
        assert _WF_ITERATIONS <= 400

    def test_le_budget_reste_suffisant_pour_atteindre_la_bonne_region(self):
        """3 tirages reduits sur 4 sont a 359-441 mm, comme le complet.

        Descendre trop bas deplacerait TOUTE la serie vers le haut, ce qui
        serait de la sous-convergence — un autre defaut, qu aucun filtre ne
        repare.
        """
        assert _WF_GENERATIONS >= 20
        assert _WF_POPULATION >= 20


class TestTiragesMinimum:
    def test_au_moins_deux_tirages(self):
        """Le filtre anti-aberration EST la raison d etre du budget reduit."""
        assert _TIRAGES_MINIMUM >= 2

    def test_pas_plus_de_deux_par_defaut(self):
        """Best-of-3 reduit (369 s) ne bat plus un complet (342 s)."""
        assert _TIRAGES_MINIMUM <= 2


class TestChoixDuMeilleur:
    def test_moins_de_conflits_gagne_toujours(self):
        a = {"conflits_restants": 0, "fil_mm": 999.0}
        b = {"conflits_restants": 3, "fil_mm": 1.0}
        assert _placement_meilleur(a, b) is True
        assert _placement_meilleur(b, a) is False

    def test_a_egalite_le_fil_departage(self):
        a = {"conflits_restants": 0, "fil_mm": 372.0}
        b = {"conflits_restants": 0, "fil_mm": 565.0}
        assert _placement_meilleur(a, b) is True
        assert _placement_meilleur(b, a) is False

    def test_un_fil_inconnu_ne_gagne_pas_par_defaut(self):
        """Sans mesure, on ne prefere pas : le premier arrive reste."""
        a = {"conflits_restants": 0}
        b = {"conflits_restants": 0, "fil_mm": 400.0}
        assert _placement_meilleur(a, b) is False

    def test_le_premier_candidat_est_toujours_retenu(self):
        assert _placement_meilleur({"conflits_restants": 5}, None) is True
