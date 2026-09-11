"""D-2026-09-11-b : une carte routee a son plafond de couches sans 100 % /
0 erreur est AGRANDIE de 20 % pour l essai suivant (au plus deux fois), et le
service rend le contour a la taille demandee.

Mesure carte-08 : 98 % a 2, 4 et 6 couches pendant 24 h ; +20 % de contour ->
100 % / 0 erreur a 2 couches au premier tirage.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

_spec = importlib.util.spec_from_file_location(
    "run_pipeline_cirqix", _SERVICE / "examples" / "led-blinker-full-pipeline" / "run_pipeline.py")
RP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RP)

from tools import placement as P  # noqa: E402


class TestTailleSuivante:
    def test_au_plafond_sans_100_on_agrandit_de_20_pct(self):
        assert RP.taille_suivante(125, 95, 98, 2, couches=6, plafond=6, agrandissements=0) == (150.0, 114.0, 1)

    def test_a_100_et_0_erreur_rien_ne_change(self):
        assert RP.taille_suivante(125, 95, 100, 0, couches=2, plafond=6, agrandissements=0) == (125, 95, 0)

    def test_sous_le_plafond_on_laisse_l_escalade_faire(self):
        assert RP.taille_suivante(125, 95, 96, 4, couches=4, plafond=6, agrandissements=0) == (125, 95, 0)

    def test_au_plus_deux_agrandissements(self):
        assert RP.taille_suivante(180, 137, 97, 3, couches=6, plafond=6, agrandissements=2) == (180, 137, 2)

    def test_un_plafond_de_2_couches_agrandit_des_2(self):
        assert RP.taille_suivante(70, 50, 92, 8, couches=2, plafond=2, agrandissements=0)[2] == 1

    def test_la_boucle_de_la_chaine_l_appelle(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(RP.main).splitlines())
        assert "taille_suivante(" in code and "board_w, board_h, agrandissements = " in code


class TestContour:
    def test_taille_d_un_gr_rect(self):
        t = '(gr_rect (start 0 0) (end 125 95) (layer "Edge.Cuts") (width 0.1))'
        assert P._taille_contour(t) == (125.0, 95.0)

    def test_taille_de_quatre_gr_line(self):
        t = "".join('(gr_line (start %s) (end %s) (layer "Edge.Cuts"))' % (a, b) for a, b in
                    (("0 0", "100 0"), ("100 0", "100 60"), ("100 60", "0 60"), ("0 60", "0 0")))
        assert P._taille_contour(t) == (100.0, 60.0)

    def test_sans_contour_rend_none(self):
        assert P._taille_contour("(kicad_pcb)") is None

    def test_auto_place_redimensionne_quand_la_demande_depasse_le_contour(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(P._auto_place_une_fois).splitlines())
        i_c = code.find("_taille_contour(")
        i_r = code.find("_redimensionner_contour(src, nl, nh)")
        assert i_c != -1 and i_r != -1 and i_c < i_r
        assert "nl > contour[0]" in code
