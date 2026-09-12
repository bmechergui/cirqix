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
    i_prot = code.find("_PISTES_A_PROTEGER = [base64.b64decode(meilleur.kicad_pcb_b64)]")
    i_palier = code.find("palier_courant, meilleur_du_palier = palier, 0")
    assert i_test != -1 and i_prot != -1 and i_palier != -1
    assert i_test < i_prot < i_palier, "la protection doit preceder l entree dans le nouveau palier"
    # UNE seule protection par changement de palier : la doubler double les
    # fils dans le DSN (mesure du 2026-09-11 : 88 % -> 79 %).
    assert code.count("_ajouter_aux_pistes_protegees(base64.b64decode(meilleur") == 0


def test_les_pistes_protegees_s_ajoutent_sans_effacer():
    memoire = R._PISTES_A_PROTEGER
    try:
        R._PISTES_A_PROTEGER = None
        R._ajouter_aux_pistes_protegees(b"a")
        R._ajouter_aux_pistes_protegees(b"b")
        assert list(R._PISTES_A_PROTEGER) == [b"a", b"b"]
    finally:
        R._PISTES_A_PROTEGER = memoire


def test_un_board_hors_de_portee_n_est_pas_protege():
    """55 % proteges a 4 couches -> 6 couches fige a 59 % (carte-08, 2026-09-11) :
    sous le seuil de re-tirage, le palier suivant repart de zero."""
    assert R._vaut_la_peine_de_proteger(R._SEUIL_REDRAW_PCT) is True
    assert R._vaut_la_peine_de_proteger(R._SEUIL_REDRAW_PCT - 1) is False
    assert R._vaut_la_peine_de_proteger(None) is False
    import inspect
    code = chr(10).join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
    i_v = code.find("_vaut_la_peine_de_proteger(meilleur.routed_percent)")
    i_p = code.find("_PISTES_A_PROTEGER = [base64.b64decode(meilleur.kicad_pcb_b64)]")
    assert i_v != -1 and i_p != -1 and i_v < i_p
