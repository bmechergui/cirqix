"""Le board livré ne porte ni piste ni via pendant.

Mesure du 2026-10-01 sur les boards livrés du banc (`kicad-cli pcb drc`) :
0 erreur et 0 connexion manquante, mais des avertissements `track_dangling`
(carte-08, carte-09 : 4) et `via_dangling` (carte-09) — du cuivre qui ne
relie rien. kicad-tools les classe « non réparables » ; ils le sont pourtant
simplement : le DRC donne leur `uuid`, on retire ce bloc, et on garde le
board seulement si le DRC ne s'aggrave pas (ni erreur, ni connexion manquante).
"""
from __future__ import annotations

import base64
import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402

BOARD = (
    '(kicad_pcb\n'
    '\t(net 1 "Net-(U1-Pad3)")\n'
    '\t(segment\n\t\t(start 1 1)\n\t\t(end 2 2)\n\t\t(net "Net-(U1-Pad3)")\n'
    '\t\t(uuid "aaaa")\n\t)\n'
    '\t(segment\n\t\t(start 2 2)\n\t\t(end 3 3)\n\t\t(net "GND")\n'
    '\t\t(uuid "bbbb")\n\t)\n'
    '\t(via\n\t\t(at 5 5)\n\t\t(net "GND")\n\t\t(uuid "cccc")\n\t)\n'
    ')\n'
)


def test_retire_seulement_les_blocs_vises():
    sortie = R._supprimer_cuivre_par_uuid(BOARD.encode(), {"aaaa", "cccc"}).decode()
    assert '"aaaa"' not in sortie and '"cccc"' not in sortie
    assert '"bbbb"' in sortie
    assert sortie.count("(") == sortie.count(")")
    assert '(net 1 "Net-(U1-Pad3)")' in sortie


def test_un_uuid_hors_cuivre_n_est_jamais_retire():
    texte = BOARD.replace('(uuid "bbbb")', '(uuid "bbbb")').replace(
        "(kicad_pcb\n", '(kicad_pcb\n\t(footprint "R"\n\t\t(uuid "pppp")\n\t)\n')
    sortie = R._supprimer_cuivre_par_uuid(texte.encode(), {"pppp"}).decode()
    assert '"pppp"' in sortie


def _rapport(pendants, manquantes=0, erreurs=0):
    return {"violations": [{"type": t, "severity": "warning", "items": [{"uuid": u}]}
                           for t, u in pendants]
            + [{"type": "clearance", "severity": "error", "items": []}] * erreurs,
            "unconnected_items": [{}] * manquantes}


def test_retire_les_pendants_et_s_arrete(monkeypatch):
    rapports = iter([_rapport([("track_dangling", "aaaa"), ("via_dangling", "cccc")]),
                     _rapport([])])
    monkeypatch.setattr(R, "_rapport_drc", lambda b: next(rapports))
    sortie = R._retirer_pendants(BOARD.encode()).decode()
    assert '"aaaa"' not in sortie and '"cccc"' not in sortie and '"bbbb"' in sortie


def test_jamais_pire_une_connexion_perdue_annule(monkeypatch):
    rapports = iter([_rapport([("track_dangling", "bbbb")]),
                     _rapport([], manquantes=1)])
    monkeypatch.setattr(R, "_rapport_drc", lambda b: next(rapports))
    assert R._retirer_pendants(BOARD.encode()) == BOARD.encode()


def test_sans_verdict_on_ne_touche_a_rien(monkeypatch):
    monkeypatch.setattr(R, "_rapport_drc", lambda b: {"_sans_verdict": True})
    assert R._retirer_pendants(BOARD.encode()) == BOARD.encode()


def test_les_deux_sorties_de_route_auto_nettoient_le_board_livre():
    src = inspect.getsource(R.route_auto)
    assert src.count("_livrer_sans_pendants(") >= 2


def test_livrer_sans_pendants_rend_une_copie(monkeypatch):
    monkeypatch.setattr(R, "_retirer_pendants", lambda b: b.replace(b"X", b"Y"))
    res = R.RouteAutoResponse(kicad_pcb_b64=base64.b64encode(b"(kicad_pcb X)").decode(),
                              routed_percent=100, layers=2)
    neuf = R._livrer_sans_pendants(res)
    assert base64.b64decode(neuf.kicad_pcb_b64) == b"(kicad_pcb Y)"
    assert base64.b64decode(res.kicad_pcb_b64) == b"(kicad_pcb X)"
