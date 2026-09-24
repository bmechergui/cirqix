"""Toute connexion manquante fait monter d'un palier — masse comprise.

D-2026-09-24-e, consigne de l'utilisateur : « si tu n'atteins pas 100 %
routage tu dois escalader le numéro de couche ». Et sa question : « si par
exemple 98 %, il manque 2 %, j'escalade le numéro de couche ? » — oui.

⚠️ La règle du 2026-08-31 refusait d'escalader quand seul un net confié au
PLAN manquait (GND), sur la foi d'`arduino-uno` : 93 % à 2, 4 et 6 couches.
Ce jour-là, les paliers supérieurs repartaient du routage précédent, pistes
protégées ; depuis le 2026-09-24 ils routent LIBREMENT (D-2026-09-24-a). La
prémisse ne tient plus, et la mesure du même jour la contredit :

    carte-08   98 % à 2 couches (GND seul)  ->  100 % à 4 couches
    carte-07   97 % à 2 couches (GND seul) ; 100 % à 4 couches, tirage libre

À 2 couches, B.Cu porte le plan ET des signaux : les pistes découpent le plan
et enferment une broche de masse. À 4 couches les signaux ont deux couches de
plus, le plan est moins découpé — du cuivre en plus RELIE la masse.

L'arrêt reste borné par `_escalade_epuisee` (un palier sans gain toléré), et
le plafond du plan n'est jamais dépassé.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestRegle:
    def test_seule_la_masse_manque_on_escalade(self, monkeypatch):
        """LE CAS DE carte-07 et carte-08 : 97-98 %, un seul net incomplet, GND,
        confié au plan."""
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ("GND",))
        assert R._escalade_peut_aider(98, erreurs=0, manquants={"GND"}) is True

    def test_un_signal_manque_on_escalade(self):
        assert R._escalade_peut_aider(98, erreurs=0, manquants={"GPIO23"}) is True

    def test_des_erreurs_font_escalader(self):
        assert R._escalade_peut_aider(100, erreurs=2, manquants=set()) is True

    def test_un_pourcentage_incomplet_fait_escalader_meme_sans_nom(self):
        """Le DRC n'a pas su nommer le net : le board n'est pas complet pour
        autant."""
        assert R._escalade_peut_aider(97, erreurs=0, manquants=set()) is True

    def test_un_board_complet_et_propre_n_escalade_pas(self):
        assert R._escalade_peut_aider(100, erreurs=0, manquants=set()) is False


class TestPourcentageJamaisArrondiA100:
    """⚠️ `_percent_verifie` ARRONDISSAIT : 1 net manquant sur 250 donnait
    round(99,6) = 100. La chaîne rendait alors « 100 %, 0 erreur » — c'est-à-
    dire son cas de SUCCÈS — sur une carte incomplète, et `route_auto` s'arrêtait
    là. Même famille que « un échec rend la même valeur que le cas normal »."""

    def _rapport(self, nets):
        return {"unconnected_items": [
            {"items": [{"description": "Pad 1 [%s] of U1 on F.Cu" % n},
                       {"description": "Pad 2 [%s] of C1 on F.Cu" % n}]}
            for n in nets]}

    def test_un_net_manquant_sur_250_n_est_pas_100(self, monkeypatch):
        monkeypatch.setattr(R, "_rapport_drc", lambda _b: self._rapport(["GND"]))
        assert R._percent_verifie(b"x", 100, 250) < 100

    def test_un_net_manquant_sur_20_donne_95(self, monkeypatch):
        monkeypatch.setattr(R, "_rapport_drc", lambda _b: self._rapport(["GND"]))
        assert R._percent_verifie(b"x", 100, 20) == 95

    def test_sans_manque_le_moteur_fait_foi(self, monkeypatch):
        monkeypatch.setattr(R, "_rapport_drc", lambda _b: {})
        assert R._percent_verifie(b"x", 100, 250) == 100


class TestCablage:
    SOURCE = inspect.getsource(R.route_auto)

    def test_la_decision_lit_le_pourcentage_LIVRE(self):
        """Le pourcentage du MOTEUR ignore les nets confiés au plan : c'est ce
        qui laissait une masse orpheline passer pour « le routeur a fini »."""
        i = self.SOURCE.index("_escalade_peut_aider(")
        assert "res.routed_percent" in self.SOURCE[i:i + 120]

    def test_plus_aucune_exception_pour_les_nets_du_plan(self):
        i = self.SOURCE.index("_escalade_peut_aider(")
        appel = self.SOURCE[i:self.SOURCE.index(")", self.SOURCE.index("manquants", i)) + 1]
        assert "orpheline" not in appel

    def test_le_succes_exige_aucune_connexion_manquante(self):
        """Un palier ne s'arrête sur un succès que si le DRC ne nomme AUCUN net
        incomplet — pas seulement si le pourcentage arrondi vaut 100."""
        i = self.SOURCE.index("res.routed_percent >= 100 and not res.skipped and erreurs == 0")
        assert "manquants_du_palier" in self.SOURCE[i:i + 160]


class TestErreursNommees:
    """Un palier refusé pour des erreurs DRC doit DIRE lesquelles.

    Mesure du 2026-09-24, carte-07 : deux tirages à 100 % en 2 couches ont été
    écartés pour des erreurs que le journal ne nommait pas. Si elles viennent
    d'un défaut réparable, la carte pourrait sortir en 2 couches — moins chère.
    """

    def test_seules_les_bloquantes_sont_comptees_par_type(self):
        rapport = {"violations": [
            {"type": "clearance", "severity": "error"},
            {"type": "clearance", "severity": "error"},
            {"type": "hole_to_hole", "severity": "warning"},
            {"type": "silk_overlap", "severity": "warning"},
        ]}
        assert R._types_bloquants(rapport) == {"clearance": 2, "hole_to_hole": 1}

    def test_un_rapport_vide_ne_nomme_rien(self):
        assert R._types_bloquants({}) == {}

    def test_route_auto_les_journalise(self):
        assert "_types_bloquants(" in inspect.getsource(R.route_auto)
