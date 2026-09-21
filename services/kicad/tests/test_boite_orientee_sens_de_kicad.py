"""La boite d un footprint TOURNE avec lui, dans le sens de KiCad.

⚠️ Mesure du 2026-09-21. `_repair_off_board` cherchait une case libre avec des
boites NON tournees : un SOT-223 a 90 degres (courtyard 8,8 x 7,2) etait teste
couche, la case « libre » tombait dans son vrai courtyard, et carte-05 comme
carte-09 sortaient a une erreur `courtyards_overlap`.

Le SENS compte des que la boite est decentree (connecteur, module). Verite
lue dans pcbnew, connecteur 1x04 de boite locale (-1,77 -1,77 1,77 9,39) :

    a 90 degres, KiCad   : (-1,81 -1,81  9,44  1,81)
    convention y-haut    : (-9,39 -1,77  1,77  1,77)   <- le courtyard A L OPPOSE

`placement_bypass._boite_absolue` portait la seconde. Une regle, un endroit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402
from tools import placement_bypass as B  # noqa: E402


def _fp(rot, boite=(-1.77, -1.77, 1.77, 9.39), pos=(0.0, 0.0)):
    x0, y0, x1, y1 = boite
    g = SimpleNamespace(layer="F.CrtYd", start=(x0, y0), end=(x1, y1))
    return SimpleNamespace(graphics=[g], pads=[], rotation=rot, position=pos, reference="J1")


class TestSensDeKicad:
    def test_sans_rotation_la_boite_est_la_locale(self):
        assert P._boite_orientee_fp(_fp(0)) == pytest.approx((-1.77, -1.77, 1.77, 9.39))

    def test_a_90_le_corps_part_vers_les_x_positifs(self):
        assert P._boite_orientee_fp(_fp(90)) == pytest.approx((-1.77, -1.77, 9.39, 1.77))

    def test_a_270_vers_les_x_negatifs(self):
        assert P._boite_orientee_fp(_fp(270)) == pytest.approx((-9.39, -1.77, 1.77, 1.77))

    def test_un_boitier_centre_echange_ses_cotes(self):
        b = P._boite_orientee_fp(_fp(90, boite=(-4.4, -3.6, 4.4, 3.6)))
        assert b == pytest.approx((-3.6, -4.4, 3.6, 4.4))


class TestUneSeuleRegle:
    def test_le_snap_lit_la_meme_boite(self):
        fp = _fp(90, pos=(10.0, 20.0))
        assert B._boite_absolue(fp) == pytest.approx((8.23, 18.23, 19.39, 21.77))

    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def _corps(self, nom):
        debut = self.SOURCE.index(f"def {nom}(")
        return self.SOURCE[debut:self.SOURCE.index("\ndef ", debut + 1)]

    @pytest.mark.parametrize("nom", ["_repair_off_board", "_refs_trop_pres_du_bord",
                                     "_reparer_chevauchements_du_drc"])
    def test_les_reparations_lisent_la_boite_orientee(self, nom):
        corps = self._corps(nom)
        assert "_boite_orientee_fp(" in corps
        assert "_boite_locale_fp(" not in corps


class TestLaBrocheViseeParLeDecouplage:
    """⚠️ Meme sens faux dans `_pastille_partagee` : sur les boards du banc, 312
    pastilles de boitiers tournes etaient calculees a 7,1 mm en moyenne de leur
    vraie place (0,08 mm dans le sens de KiCad). La capa visait une broche qui
    n etait pas la."""

    def test_la_pastille_d_un_ci_tourne_est_la_ou_kicad_la_met(self):
        pad = SimpleNamespace(net_name="+3V3", position=(3.0, 1.0))
        ci = SimpleNamespace(pads=[pad], rotation=90.0, position=(10.0, 10.0))
        capa = SimpleNamespace(pads=[SimpleNamespace(net_name="+3V3", position=(0.5, 0.0))],
                               rotation=0.0, position=(0.0, 0.0))
        assert B._pastille_partagee(ci, capa) == pytest.approx((11.0, 7.0))
