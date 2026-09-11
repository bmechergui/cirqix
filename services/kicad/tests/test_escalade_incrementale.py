"""L escalade de couches est INCREMENTALE : le palier suivant recoit les
pistes du meilleur board du palier quitte, protegees, et ne route que ce qui
manque. D-2026-09-10-b, validee par l utilisateur le 2026-09-11.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def test_active_par_defaut_et_desarmable():
    assert R._escalade_incrementale() is True
    from tools import reglages_banc
    original = reglages_banc.reglage
    try:
        reglages_banc.reglage = lambda nom, defaut=None: False if nom == "escalade_incrementale" else defaut
        assert R._escalade_incrementale() is False
    finally:
        reglages_banc.reglage = original


def test_le_changement_de_palier_protege_le_meilleur_board():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
    i_test = code.find("_escalade_incrementale()")
    i_prot = code.find("_ajouter_aux_pistes_protegees(base64.b64decode(meilleur.kicad_pcb_b64))")
    i_palier = code.find("palier_courant, meilleur_du_palier = palier, 0")
    assert i_test != -1 and i_prot != -1 and i_palier != -1
    assert i_test < i_prot < i_palier, "la protection doit preceder l entree dans le nouveau palier"


def test_les_pistes_protegees_s_ajoutent_sans_effacer():
    memoire = R._PISTES_A_PROTEGER
    try:
        R._PISTES_A_PROTEGER = None
        R._ajouter_aux_pistes_protegees(b"a")
        R._ajouter_aux_pistes_protegees(b"b")
        assert list(R._PISTES_A_PROTEGER) == [b"a", b"b"]
    finally:
        R._PISTES_A_PROTEGER = memoire
