"""D-2026-09-14-b (validee par l utilisateur le 2026-09-14, « ok ») : quand la
broche GND orpheline est NOMMEE et que son repli cible vient d echouer au
palier courant, l escalade continue d UN palier — deux couches internes sont
un chemin pour une piste de masse courte — et le repli y est rejoue. Si lui
aussi echoue, la regle « un net confie au plan ne se relie pas avec du cuivre
en plus » s applique comme avant.

Mesure carte-10, placement gele : repli cible U1-8 refuse a 2 couches (une
seule face de signal entre les sorties du LQFP), palier 4 jamais tente,
98 % en 192 s.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestPredicat:
    def test_sans_orpheline_nommee_la_regle_historique_tient(self, monkeypatch):
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ["GND"])
        assert not R._escalade_peut_aider(100, 0, manquants={"GND"})

    def test_une_orpheline_nommee_dont_le_repli_a_echoue_fait_escalader_une_fois(self, monkeypatch):
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ["GND"])
        assert R._escalade_peut_aider(100, 0, manquants={"GND"}, orpheline_sans_issue=True)

    def test_un_signal_manquant_escalade_toujours(self, monkeypatch):
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ["GND"])
        assert R._escalade_peut_aider(90, 0, manquants={"SIG"})
        assert R._escalade_peut_aider(90, 0, manquants={"SIG"}, orpheline_sans_issue=True)

    def test_un_routeur_a_100_sans_manque_ni_orpheline_n_escalade_pas(self, monkeypatch):
        monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ["GND"])
        assert not R._escalade_peut_aider(100, 0, manquants=set())


class TestCablage:
    SOURCE = inspect.getsource(R.route_auto)

    def test_route_auto_transmet_l_orpheline_sans_issue(self):
        assert "orpheline_sans_issue=" in self.SOURCE

    def test_le_palier_supplementaire_n_est_accorde_qu_une_fois(self):
        # Un drapeau posé quand le palier est accordé, relu avant d'en accorder un autre.
        assert "palier_orpheline_accorde" in self.SOURCE
        assert self.SOURCE.count("palier_orpheline_accorde = True") == 1

    def test_l_orpheline_compte_seulement_si_son_repli_a_echoue_a_ce_palier(self):
        assert "_repli_deja_tente(orphelines, couches=couches_final)" in self.SOURCE
