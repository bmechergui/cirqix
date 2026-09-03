"""Escalader depend de QUEL net manque, pas seulement de combien.

Regle demandee par l utilisateur le 2026-08-31, et elle est mieux fondee que
celle que j avais codee le matin meme :

    il manque du GND      -> le plan ne l atteint pas    -> PAS d escalade,
                                                            fanout + via
    il manque du signal   -> le routeur manque de place  -> escalade, routage
                                                            conserve

⚠️ Ma version precedente ne regardait que « le moteur annonce-t-il 100 % ».
Elle laissait donc escalader une carte a 98 % dont le seul net manquant est
GND — exactement le cas de `stm32-60` et `stm32-30` au banc du 2026-08-31.

La preuve que l escalade n y peut rien, mesuree sur `arduino-uno` le meme
jour : 93 % a 2 couches, 93 % a 4, 93 % a 6, moteur a 100 % a chaque palier,
un seul net incomplet — GND. Six tirages, trois empilages, douze minutes, zero
gain. Un net confie au PLAN n est pas route par des pistes : il est COULE. Du
cuivre supplementaire ne l atteint pas davantage.

⚠️ Le critere reste « ce qui manque », jamais « combien il en manque ». Un
seul net de SIGNAL manquant justifie l escalade ; dix nets de plan ne la
justifient pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestRegle:
    def test_seul_GND_manque_on_n_escalade_PAS(self):
        # LE CAS MESURE : stm32-60 a 98 %, un net incomplet, GND.
        assert R._escalade_peut_aider(98, erreurs=0, manquants={"GND"}) is False

    def test_un_net_de_SIGNAL_manque_on_escalade(self):
        # Le routeur manque de place : c est la raison d etre de l escalade.
        assert R._escalade_peut_aider(98, erreurs=0, manquants={"GPIO23"}) is True

    def test_GND_ET_un_signal_on_escalade(self):
        """⚠️ Un seul signal suffit. Deux cartes du banc etaient dans ce cas :
        « net(s) : GND, GPIO23 » et « net(s) : GND, GPIO19 »."""
        assert R._escalade_peut_aider(
            97, erreurs=0, manquants={"GND", "GPIO23"}) is True

    def test_plusieurs_nets_CONFIES_AU_PLAN_ne_justifient_rien(self, monkeypatch):
        """⚠️ Le critere est « confie au PLAN dans CE run », pas « porte un nom
        de masse ».

        Premiere version de ce test : `{GND, AGND, DGND}` devait empecher
        l escalade. C etait faux. `_NETS_CONFIES_AU_PLAN` vaut `('GND',)` : AGND
        et DGND sont ROUTES PAR DES PISTES, donc du cuivre supplementaire peut
        les aider. Le code avait raison, mon test confondait le nom et le role.
        """
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ("GND", "AGND", "DGND"))
        assert R._escalade_peut_aider(
            90, erreurs=0, manquants={"GND", "AGND", "DGND"}) is False

    def test_un_net_de_masse_NON_confie_au_plan_fait_escalader(self):
        # AGND route par des pistes : c est un signal comme un autre.
        assert R._escalade_peut_aider(90, erreurs=0, manquants={"AGND"}) is True

    def test_des_erreurs_DRC_font_toujours_escalader(self):
        """Une violation de fabricabilite peut se resoudre avec plus d espace,
        contrairement a une pastille de plan orpheline."""
        assert R._escalade_peut_aider(98, erreurs=2, manquants={"GND"}) is True

    def test_sans_liste_on_retombe_sur_l_ancienne_regle(self):
        # Compatibilite : les appelants qui n ont pas la liste gardent le
        # comportement precedent, jamais un refus d escalade infonde.
        assert R._escalade_peut_aider(98, erreurs=0) is True
        assert R._escalade_peut_aider(100, erreurs=0) is False


class TestNetsIncomplets:
    def test_une_pastille_orpheline_nomme_son_net(self):
        # ⚠️ Forme REELLE du rapport : `_PAD_ISOLEE_RE` exige du texte apres la
        # reference. Ma premiere fixture s arretait a « of U1 » et ne matchait
        # rien — une fixture inventee ne prouve rien.
        rapport = {"unconnected_items": [{"items": [
            {"description": "Pad 12 [GND] of U1 on F.Cu"}]}]}
        assert "GND" in R._nets_incomplets(rapport)

    def test_une_paire_de_ZONES_nomme_son_net(self):
        """⚠️ `Zone [GND] <-> Zone [GND]` est un PLAN COUPE EN ILOTS. Ne
        chercher que des pastilles le rendait invisible (mesure 2026-08-26)."""
        rapport = {"unconnected_items": [{"items": [
            {"description": "Zone [GND] on F.Cu, priority 0"}]}]}
        assert "GND" in R._nets_incomplets(rapport)

    def test_un_rapport_vide_ne_rend_rien(self):
        assert R._nets_incomplets({}) == set()


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_liste_est_PASSEE_a_la_decision(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("_escalade_peut_aider(")
        assert "manquants" in corps[i:i + 200], (
            "la decision ignore QUELS nets manquent")

    def test_percent_verifie_reutilise_le_meme_extracteur(self):
        """Deux extractions divergeraient : le message nommerait des nets que
        la decision ne verrait pas."""
        i = self.SOURCE.index("def _percent_verifie")
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        assert "_nets_incomplets(" in self.SOURCE[i:j]
