"""Un placement CONDAMNE ne paie ni derniere chance ni repli GND.

Mesure du 2026-09-10 sur carte-05, essai 1 : tirages figes a 62/23/0 %, puis
derniere chance 10 min et repli GND 8 min pour un board a 0 % — quand le
placement suivant a route a 100 % en 30 s. Decision D-2026-09-10-d.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestSeuil:
    def test_sous_le_seuil_le_placement_est_condamne(self):
        assert R._placement_condamne(0) and R._placement_condamne(R._CONDAMNE_PCT - 1)

    def test_au_seuil_ou_au_dessus_la_derniere_chance_reste(self):
        """nucleo-f401 : tirages figes a 43-79 %, la derniere chance a rendu un board."""
        assert not R._placement_condamne(R._CONDAMNE_PCT)
        assert not R._placement_condamne(79)

    def test_le_seuil_reste_entre_les_deux_mesures(self):
        """carte-05 condamnee : tirages figes a 62/23/0 % ; nucleo sauvee par la
        derniere chance : 43-79 %. Le seuil vit entre les deux, et une
        valeur hors de cette fenetre contredirait l une des deux mesures."""
        assert 30 <= R._CONDAMNE_PCT <= 70

    def test_le_reglage_est_lu(self):
        from tools import reglages_banc
        original = reglages_banc.reglage
        try:
            reglages_banc.reglage = lambda nom, defaut=None: 90 if nom == "condamne_pct" else defaut
            assert R._placement_condamne(85)
        finally:
            reglages_banc.reglage = original


class TestCablage:
    def test_la_porte_de_la_derniere_chance_lit_le_verdict(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        i_cond = code.find("_placement_condamne(fige_max)")
        i_dc = code.find("derniere_chance_donnee = True")
        assert i_cond != -1 and i_dc != -1 and i_cond < i_dc, (
            "le verdict doit etre rendu AVANT d accorder la derniere chance")

    def test_le_meilleur_tirage_fige_est_memorise(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        assert "fige_max = max(fige_max" in code
