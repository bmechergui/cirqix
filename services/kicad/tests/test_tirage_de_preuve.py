"""Sous le plancher d echappement, UN seul tirage de preuve par palier
(D-2026-09-11-a, validee par l utilisateur le 2026-09-11).

carte-08 : trois tirages a 2 couches brulaient les 1800 s et le palier 4
(plancher calcule) rendait « 0 % (aucun moteur) », deux essais de suite.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def test_sans_plancher_rien_ne_change():
    assert R._paliers_avec_tirages([2, 4], 3) == [2, 2, 2, 4, 4, 4]
    assert R._paliers_avec_tirages([2, 4], 3, plancher=2) == [2, 2, 2, 4, 4, 4]


def test_sous_le_plancher_un_seul_tirage_de_preuve():
    assert R._paliers_avec_tirages([2, 4], 3, plancher=4) == [2, 4, 4, 4]
    assert R._paliers_avec_tirages([2, 4, 6], 3, plancher=6) == [2, 4, 6, 6, 6]


def test_le_palier_du_plancher_garde_ses_tirages():
    assert R._paliers_avec_tirages([2, 4, 6], 3, plancher=4) == [2, 4, 4, 4, 6, 6, 6]


def test_le_reglage_desarme():
    from tools import reglages_banc
    original = reglages_banc.reglage
    try:
        reglages_banc.reglage = lambda nom, defaut=None: False if nom == "tirage_de_preuve" else defaut
        assert R._tirage_de_preuve() is False
    finally:
        reglages_banc.reglage = original
    assert R._tirage_de_preuve() is True


def test_route_auto_passe_le_plancher_a_l_echelle():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
    i_plancher = code.find("plancher = _couches_pour_echapper(")
    i_essais = code.find("plancher=plancher if _tirage_de_preuve() else 0")
    assert i_plancher != -1 and i_essais != -1 and i_plancher < i_essais, (
        "le plancher doit etre calcule avant de construire l echelle des tirages")
