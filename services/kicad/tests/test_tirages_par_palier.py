"""Plusieurs tirages de routage A CHAQUE palier de couches.

Methode demandee par l utilisateur le 2026-08-28 :

    2 couches : tirer, re-tirer, re-tirer...   si insuffisant ->
    4 couches : tirer, re-tirer, re-tirer...   si insuffisant ->
    6 couches : ...

en gardant TOUJOURS le meilleur routage, jusqu a 100 % routable et fabricable.

⚠️ L escalade ne faisait qu UN SEUL tirage par palier. Or Freerouting est
stochastique : sur le meme board place de la Nucleo, trois executions ont donne
65 %, 77 % et 91 %. Un palier juge insuffisant l etait peut-etre seulement ce
tirage-la — et on montait d une couche pour rien, ce qui coute plus cher qu un
re-tirage (une carte 4 couches coute plus qu une carte 2 couches).

⚠️ Un tirage de routage coute 30 a 60 s quand tout va bien, contre 4 a 5 min
pour un tirage de PLACEMENT : c est le levier le moins cher de la chaine.

⚠️ On ne restructure PAS la boucle, chemin critique de plus de cent lignes : on
repete le palier dans l echelle. Le corps existant garde deja le meilleur sur le
couple (pourcentage, erreurs) et sort des qu il tient 100 % sans erreur — donc
les tirages surnumeraires ne sont jamais payes quand le premier suffit.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestEchelle:
    def test_chaque_palier_est_repete(self):
        assert R._paliers_avec_tirages([2, 4], 3) == [2, 2, 2, 4, 4, 4]

    def test_l_ordre_des_paliers_est_conserve(self):
        # On epuise 2 couches AVANT de payer 4 : une carte a moins de couches
        # coute moins cher a fabriquer.
        sortie = R._paliers_avec_tirages([2, 4, 6], 2)
        assert sortie == [2, 2, 4, 4, 6, 6]

    def test_un_seul_tirage_rend_l_echelle_inchangee(self):
        assert R._paliers_avec_tirages([2, 4, 6], 1) == [2, 4, 6]

    def test_zero_tirage_est_refuse(self):
        # Ne router aucun palier rendrait `route_auto` incapable de rien livrer.
        assert R._paliers_avec_tirages([2, 4], 0) == [2, 4]


class TestTolerance:
    def test_l_arret_tolere_au_moins_un_palier_entier_a_plat(self):
        # Sinon deux tirages malchanceux au meme palier couperaient l escalade
        # avant meme d avoir essaye le palier suivant.
        assert R._TOLERANCE_SANS_GAIN >= R._TIRAGES_ROUTAGE_PAR_PALIER

    def test_l_arret_finit_par_se_declencher(self):
        assert R._escalade_epuisee(R._TOLERANCE_SANS_GAIN + 1) is True
        assert R._escalade_epuisee(R._TOLERANCE_SANS_GAIN) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_parcourt_l_echelle_avec_tirages(self):
        # ⚠️ On ancre sur la boucle REELLE : `for palier in ` apparait d abord
        # dans la comprehension de `_paliers_avec_tirages` elle-meme.
        assert "essais = _paliers_avec_tirages(" in self.SOURCE
        # ⚠️ DECISION UTILISATEUR (2026-08-29) : l echelle demarre TOUJOURS a
        # 2 couches. Le plancher d echappement reste calcule et journalise,
        # mais ne commande plus le depart — on ne facture pas 4 couches sur une
        # prevision, on escalade sur preuve.
        assert "_layer_ladder(req.layers)" in self.SOURCE

    def test_la_sortie_anticipee_survit(self):
        # 100 % ET zero erreur doit toujours rendre la main immediatement :
        # sans quoi les tirages surnumeraires seraient payes pour rien.
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        corps = self.SOURCE[i:]
        assert "res.routed_percent >= 100 and not res.skipped and erreurs == 0" in corps
